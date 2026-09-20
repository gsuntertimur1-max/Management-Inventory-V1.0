from __future__ import annotations

from collections import defaultdict
import re

from fastapi import APIRouter, Depends

from backend.server import db, require_master_write
from backend.integrity_postcommit import integrity_control as base_integrity_control
from backend.integrity_consignment import analyze_consignment_integrity
from backend.so_monitoring import build_so_monitoring, fulfillment_integrity_issues
from backend.cost_integrity import analyze_handling_cost_integrity

router = APIRouter(prefix="/api")
EPS = 1e-9


def _n(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


BON_PATTERN = re.compile(r"^BM-(\d{8})-(\d{3})$")
SJ_PATTERN = re.compile(r"^SJ/09100-09200/(\d{6})/(\d{4})$")


def _doc_set(values) -> set[str]:
    return {str(value or "").strip().upper() for value in (values or []) if str(value or "").strip()}


def _print_item_key(item: dict, fallback_document: str = "") -> tuple[str, str, str]:
    document = str(item.get("documentNo") or fallback_document or "").strip().upper()
    product = str(item.get("productId") or item.get("sku") or item.get("name") or "").strip().upper()
    stack = str(item.get("stackCode") or item.get("location") or "").strip().upper()
    return document, product, stack


def _print_item_totals(items: list[dict], fallback_document: str = "") -> dict[tuple[str, str, str], dict]:
    totals: dict[tuple[str, str, str], dict] = {}
    for item in items or []:
        key = _print_item_key(item, fallback_document)
        row = totals.setdefault(key, {
            "qty": 0.0,
            "berat": 0.0,
            "secondaryQty": _n(item.get("secondaryQty")),
            "secondary": str(item.get("secondary") or ""),
            "unit": str(item.get("unit") or ""),
            "measureUnit": str(item.get("measureUnit") or "kg").lower(),
        })
        row["qty"] += _n(item.get("qty"))
        row["berat"] += _n(item.get("berat"))
    return totals


def analyze_stack_card_integrity(allocations: list[dict], settings: dict) -> list[dict]:
    issues: list[dict] = []
    if not str(settings.get("warehouseHead") or "").strip():
        issues.append({
            "severity": "ERROR",
            "code": "STACK_CARD_WAREHOUSE_HEAD_MISSING",
            "issue": "Master Kepala Gudang belum diisi sehingga tanda tangan Kartu Tumpukan tidak memiliki nama pejabat yang sah.",
        })

    for item in allocations:
        stack_code = str(item.get("stackCode") or "").strip().upper()
        primary = _n(item.get("primaryQty"))
        if primary <= EPS:
            continue
        if not str(item.get("sku") or "").strip() or not str(item.get("productName") or "").strip():
            issues.append({
                "severity": "ERROR",
                "code": "STACK_CARD_PRODUCT_IDENTITY_MISSING",
                "stackCode": stack_code,
                "productId": item.get("productId", ""),
                "issue": "Kartu Tumpukan memiliki saldo tetapi SKU/nama produk tidak lengkap.",
            })
        measure = str(item.get("measureUnit") or "kg").strip().lower()
        if measure not in {"kg", "liter", "pcs"}:
            issues.append({
                "severity": "WARNING",
                "code": "STACK_CARD_MEASURE_UNIT_INVALID",
                "stackCode": stack_code,
                "sku": item.get("sku", ""),
                "measureUnit": measure,
                "issue": "Satuan kuantum Kartu Tumpukan bukan kg/liter/pcs.",
            })
        if _n(item.get("weight")) <= EPS:
            issues.append({
                "severity": "WARNING",
                "code": "STACK_CARD_UNIT_QUANTUM_MISSING",
                "stackCode": stack_code,
                "sku": item.get("sku", ""),
                "issue": "Kuantum per unit belum diisi; kuantum fisik pada Kartu Tumpukan tidak dapat dihitung dengan benar.",
            })

        if item.get("arrangementAdjusted"):
            issues.append({
                "severity": "WARNING",
                "code": "STACK_CARD_ARRANGEMENT_PENDING",
                "stackCode": stack_code,
                "sku": item.get("sku", ""),
                "name": item.get("productName", ""),
                "primaryQty": primary,
                "issue": "Susunan fisik berubah setelah pengeluaran. PDF akan menandai perkalian perlu dihitung ulang.",
            })
            continue

        secondary_qty = _n(item.get("secondaryQty"))
        if secondary_qty <= EPS:
            continue
        blocks = item.get("arrangements") or [{
            "hamparan": item.get("length", 0),
            "kaki": item.get("width", 0),
            "height": item.get("height", 0),
        }]
        secondary_count = sum(
            _n(block.get("hamparan")) * _n(block.get("kaki")) * _n(block.get("height"))
            for block in blocks
        ) + _n(item.get("extraSecondary"))
        calculated = secondary_count * secondary_qty + _n(item.get("extraPrimary"))
        if abs(calculated - primary) > EPS:
            issues.append({
                "severity": "ERROR",
                "code": "STACK_CARD_ARRANGEMENT_QTY_MISMATCH",
                "stackCode": stack_code,
                "sku": item.get("sku", ""),
                "primaryQty": primary,
                "calculatedQty": calculated,
                "difference": calculated - primary,
                "issue": "Perkalian Kartu Tumpukan tidak sama dengan saldo primer tumpukan.",
            })
    return issues


def analyze_outbound_document_integrity(loads: list[dict], surat_jalan: list[dict], transactions: list[dict]) -> list[dict]:
    issues: list[dict] = []
    loads_by_id = {str(row.get("id") or ""): row for row in loads if row.get("id")}
    sj_by_id = {str(row.get("id") or ""): row for row in surat_jalan if row.get("id")}
    sj_by_load: dict[str, list[dict]] = defaultdict(list)
    tx_by_load: dict[str, list[dict]] = defaultdict(list)
    bon_owners: dict[str, set[str]] = defaultdict(set)

    for load in loads:
        load_id = str(load.get("id") or "")
        bon_no = str(load.get("bon_no") or "").strip()
        if load_id and bon_no and str(load.get("status") or "") != "Dibatalkan":
            bon_owners[bon_no].add(load_id)
            match = BON_PATTERN.match(bon_no)
            if not match:
                issues.append({
                    "severity": "ERROR",
                    "code": "BON_MUAT_NUMBER_FORMAT",
                    "loadId": load_id,
                    "bonNo": bon_no,
                    "issue": "Nomor Bon Muat tidak mengikuti format BM-YYYYMMDD-nnn.",
                })
            else:
                operational_date = str(load.get("operational_date") or "").replace("-", "")
                if operational_date and match.group(1) != operational_date:
                    issues.append({
                        "severity": "ERROR",
                        "code": "BON_MUAT_DATE_MISMATCH",
                        "loadId": load_id,
                        "bonNo": bon_no,
                        "operationalDate": load.get("operational_date", ""),
                        "issue": "Tanggal pada nomor Bon Muat berbeda dari tanggal operasional pemuatan.",
                    })

    for sj in surat_jalan:
        load_id = str(sj.get("load_id") or "")
        if load_id:
            sj_by_load[load_id].append(sj)

    for txn in transactions:
        if str(txn.get("type") or "") != "KELUAR":
            continue
        load_id = str(txn.get("load_id") or "")
        if load_id:
            tx_by_load[load_id].append(txn)

    for load_id, rows in sj_by_load.items():
        if len(rows) > 1:
            issues.append({
                "severity": "ERROR",
                "code": "DUPLICATE_SURAT_JALAN_PER_LOAD",
                "loadId": load_id,
                "suratJalan": [str(row.get("no") or row.get("id") or "") for row in rows],
                "issue": "Satu pemuatan memiliki lebih dari satu Surat Jalan.",
            })

    for sj in surat_jalan:
        load_id = str(sj.get("load_id") or "")
        load = loads_by_id.get(load_id)
        if not load:
            issues.append({
                "severity": "ERROR",
                "code": "SURAT_JALAN_ORPHAN",
                "suratJalanId": sj.get("id", ""),
                "suratJalanNo": sj.get("no", ""),
                "loadId": load_id,
                "issue": "Surat Jalan tidak memiliki pemuatan induk yang valid.",
            })
            continue

        sj_no = str(sj.get("no") or "").strip()
        if sj_no.startswith("SJ/"):
            match = SJ_PATTERN.match(sj_no)
            if not match:
                issues.append({
                    "severity": "ERROR",
                    "code": "SURAT_JALAN_NUMBER_FORMAT",
                    "loadId": load_id,
                    "suratJalanNo": sj_no,
                    "issue": "Nomor Surat Jalan baru tidak mengikuti format SJ/09100-09200/YYYYMM/nnnn.",
                })
            else:
                op_month = str(sj.get("operational_date") or load.get("operational_date") or "").replace("-", "")[:6]
                if op_month and match.group(1) != op_month:
                    issues.append({
                        "severity": "ERROR",
                        "code": "SURAT_JALAN_MONTH_MISMATCH",
                        "loadId": load_id,
                        "suratJalanNo": sj_no,
                        "operationalDate": sj.get("operational_date") or load.get("operational_date", ""),
                        "issue": "Bulan pada nomor Surat Jalan berbeda dari bulan operasional.",
                    })
        elif sj_no and not sj_no.startswith("SJ-"):
            issues.append({
                "severity": "WARNING",
                "code": "SURAT_JALAN_LEGACY_NUMBER_UNKNOWN",
                "loadId": load_id,
                "suratJalanNo": sj_no,
                "issue": "Nomor Surat Jalan tidak dikenali sebagai format baru maupun arsip legacy SJ-YYYYMM-nnn.",
            })
        if str(load.get("status") or "") != "Selesai":
            issues.append({
                "severity": "ERROR",
                "code": "SURAT_JALAN_LOAD_NOT_COMPLETED",
                "loadId": load_id,
                "suratJalanId": sj.get("id", ""),
                "suratJalanNo": sj.get("no", ""),
                "loadStatus": load.get("status", ""),
                "issue": "Surat Jalan sudah ada tetapi pemuatan belum berstatus Selesai.",
            })

        load_bon = str(load.get("bon_no") or "").strip()
        sj_bon = str(sj.get("bon_no") or "").strip()
        if load_bon and sj_bon and load_bon != sj_bon:
            issues.append({
                "severity": "ERROR",
                "code": "BON_MUAT_SURAT_JALAN_MISMATCH",
                "loadId": load_id,
                "bonNo": load_bon,
                "suratJalanBonNo": sj_bon,
                "suratJalanNo": sj.get("no", ""),
                "issue": "Nomor Bon Muat pada pemuatan dan Surat Jalan tidak sama.",
            })

        load_queue = str(load.get("antrian") or "").strip()
        sj_queue = str(sj.get("antrian") or "").strip()
        if load_queue and sj_queue and load_queue != sj_queue:
            issues.append({
                "severity": "WARNING",
                "code": "QUEUE_SURAT_JALAN_MISMATCH",
                "loadId": load_id,
                "queue": load_queue,
                "suratJalanQueue": sj_queue,
                "suratJalanNo": sj.get("no", ""),
                "issue": "Nomor antrean pada pemuatan dan Surat Jalan tidak sama.",
            })

        load_docs = _doc_set(load.get("documents") or [load.get("ref", "")])
        sj_docs = _doc_set(sj.get("documents") or [sj.get("ref", "")])
        if load_docs != sj_docs:
            issues.append({
                "severity": "ERROR",
                "code": "SURAT_JALAN_SOURCE_DOCUMENT_MISMATCH",
                "loadId": load_id,
                "suratJalanNo": sj.get("no", ""),
                "loadDocuments": sorted(load_docs),
                "suratJalanDocuments": sorted(sj_docs),
                "issue": "Daftar dokumen sumber pada Surat Jalan berbeda dari pemuatan.",
            })

        load_items = _print_item_totals(load.get("items") or [], load.get("ref", ""))
        sj_items = _print_item_totals(sj.get("items") or [], sj.get("ref", ""))
        for key in set(load_items) | set(sj_items):
            expected_row = load_items.get(key, {})
            printed_row = sj_items.get(key, {})
            if abs(_n(expected_row.get("qty")) - _n(printed_row.get("qty"))) > EPS or abs(_n(expected_row.get("berat")) - _n(printed_row.get("berat"))) > EPS:
                issues.append({
                    "severity": "ERROR",
                    "code": "SURAT_JALAN_ITEM_SNAPSHOT_MISMATCH",
                    "loadId": load_id,
                    "suratJalanNo": sj.get("no", ""),
                    "documentNo": key[0],
                    "productKey": key[1],
                    "stackCode": key[2],
                    "loadQty": _n(expected_row.get("qty")),
                    "suratJalanQty": _n(printed_row.get("qty")),
                    "loadQuantum": _n(expected_row.get("berat")),
                    "suratJalanQuantum": _n(printed_row.get("berat")),
                    "issue": "Kuantitas/kuantum snapshot Surat Jalan berbeda dari data pemuatan.",
                })
                continue
            if expected_row and printed_row:
                for field in ("secondaryQty", "secondary", "unit", "measureUnit"):
                    if str(expected_row.get(field, "")) != str(printed_row.get(field, "")):
                        issues.append({
                            "severity": "WARNING",
                            "code": "SURAT_JALAN_PACKAGING_METADATA_MISMATCH",
                            "loadId": load_id,
                            "suratJalanNo": sj.get("no", ""),
                            "documentNo": key[0],
                            "productKey": key[1],
                            "field": field,
                            "loadValue": expected_row.get(field, ""),
                            "suratJalanValue": printed_row.get(field, ""),
                            "issue": "Metadata kemasan/satuan Surat Jalan berbeda dari snapshot pemuatan.",
                        })

    for load in loads:
        load_id = str(load.get("id") or "")
        if not load_id:
            continue
        sj_id = str(load.get("surat_jalan_id") or "")
        if sj_id:
            linked = sj_by_id.get(sj_id)
            if linked and str(linked.get("load_id") or "") != load_id:
                issues.append({
                    "severity": "ERROR",
                    "code": "SURAT_JALAN_WRONG_LOAD_LINK",
                    "loadId": load_id,
                    "suratJalanId": sj_id,
                    "actualSuratJalanLoadId": linked.get("load_id", ""),
                    "issue": "surat_jalan_id pada pemuatan menunjuk Surat Jalan milik pemuatan lain.",
                })

        if str(load.get("status") or "") != "Selesai":
            continue

        linked_sj_rows = sj_by_load.get(load_id, [])
        if not linked_sj_rows:
            issues.append({
                "severity": "ERROR",
                "code": "COMPLETED_OUTBOUND_MISSING_SURAT_JALAN",
                "loadId": load_id,
                "bonNo": load.get("bon_no", ""),
                "issue": "Pemuatan Selesai tidak memiliki Surat Jalan.",
            })
        elif len(linked_sj_rows) == 1:
            actual_sj = linked_sj_rows[0]
            if str(load.get("surat_jalan_id") or "") != str(actual_sj.get("id") or "") or str(load.get("surat_jalan_no") or "") != str(actual_sj.get("no") or ""):
                issues.append({
                    "severity": "ERROR",
                    "code": "SURAT_JALAN_LOAD_LINK_METADATA_MISMATCH",
                    "loadId": load_id,
                    "loadSuratJalanId": load.get("surat_jalan_id", ""),
                    "loadSuratJalanNo": load.get("surat_jalan_no", ""),
                    "actualSuratJalanId": actual_sj.get("id", ""),
                    "actualSuratJalanNo": actual_sj.get("no", ""),
                    "issue": "Metadata Surat Jalan pada pemuatan tidak sama dengan record Surat Jalan sebenarnya.",
                })

        tx_rows = tx_by_load.get(load_id, [])
        if not tx_rows:
            issues.append({
                "severity": "ERROR",
                "code": "COMPLETED_OUTBOUND_MISSING_TRANSACTION",
                "loadId": load_id,
                "bonNo": load.get("bon_no", ""),
                "queue": load.get("antrian", ""),
                "issue": "Pemuatan Selesai tidak memiliki transaksi KELUAR.",
            })
            continue

        expected: dict[tuple[str, str], float] = defaultdict(float)
        actual: dict[tuple[str, str], float] = defaultdict(float)
        for item in load.get("items") or []:
            product_id = str(item.get("productId") or "")
            stack_code = str(item.get("stackCode") or "").strip().upper()
            if product_id:
                expected[(product_id, stack_code)] += _n(item.get("qty"))
        for txn in tx_rows:
            product_id = str(txn.get("product_id") or "")
            stack_code = str(txn.get("stackCode") or "").strip().upper()
            if product_id:
                actual[(product_id, stack_code)] += abs(_n(txn.get("change")))

        keys = set(expected) | set(actual)
        for key in keys:
            expected_qty = expected.get(key, 0.0)
            actual_qty = actual.get(key, 0.0)
            if abs(expected_qty - actual_qty) <= EPS:
                continue
            issues.append({
                "severity": "ERROR",
                "code": "OUTBOUND_TRANSACTION_QTY_MISMATCH",
                "loadId": load_id,
                "productId": key[0],
                "stackCode": key[1],
                "expectedQty": expected_qty,
                "transactionQty": actual_qty,
                "difference": actual_qty - expected_qty,
                "issue": "Kuantum transaksi KELUAR tidak sama dengan kuantum pemuatan Selesai.",
            })

        load_bon = str(load.get("bon_no") or "").strip()
        mismatched_tx_bon = sorted({str(txn.get("bon_no") or "").strip() for txn in tx_rows if str(txn.get("bon_no") or "").strip() and str(txn.get("bon_no") or "").strip() != load_bon})
        if load_bon and mismatched_tx_bon:
            issues.append({
                "severity": "ERROR",
                "code": "BON_MUAT_TRANSACTION_MISMATCH",
                "loadId": load_id,
                "bonNo": load_bon,
                "transactionBonNo": mismatched_tx_bon,
                "issue": "Nomor Bon Muat pada transaksi KELUAR berbeda dari data pemuatan.",
            })

    for bon_no, owners in bon_owners.items():
        if len(owners) > 1:
            issues.append({
                "severity": "ERROR",
                "code": "DUPLICATE_BON_MUAT",
                "bonNo": bon_no,
                "loadIds": sorted(owners),
                "issue": "Nomor Bon Muat digunakan oleh lebih dari satu pemuatan aktif/selesai.",
            })

    return issues


@router.get("/integrity-control")
async def integrity_control(user: dict = Depends(require_master_write)):
    data = await base_integrity_control(user)
    loads = await db.outbound_loads.find(
        {},
        {"_id": 0, "id": 1, "status": 1, "bon_no": 1, "bon_format_version": 1, "antrian": 1, "operational_date": 1, "ref": 1, "documents": 1, "document_type": 1, "surat_jalan_id": 1, "surat_jalan_no": 1, "items": 1},
    ).to_list(30000)
    surat_jalan = await db.surat_jalan.find(
        {},
        {"_id": 0, "id": 1, "load_id": 1, "no": 1, "format_version": 1, "bon_no": 1, "antrian": 1, "operational_date": 1, "time": 1, "ref": 1, "documents": 1, "items": 1},
    ).to_list(30000)
    transactions = await db.transactions.find(
        {"type": "KELUAR"},
        {"_id": 0, "id": 1, "load_id": 1, "product_id": 1, "stackCode": 1, "change": 1, "bon_no": 1, "antrian": 1},
    ).to_list(100000)
    stack_allocations = await db.stack_allocations.find({}, {"_id": 0}).to_list(50000)
    settings = await db.settings.find_one({"_id": "app"}, {"_id": 0}) or {}

    document_issues = analyze_outbound_document_integrity(loads, surat_jalan, transactions)
    stack_card_issues = analyze_stack_card_integrity(stack_allocations, settings)
    so_monitoring = await build_so_monitoring()
    so_issues = fulfillment_integrity_issues(so_monitoring)
    errors = sum(1 for row in document_issues if row.get("severity") == "ERROR")
    warnings = sum(1 for row in document_issues if row.get("severity") == "WARNING")
    stack_card_errors = sum(1 for row in stack_card_issues if row.get("severity") == "ERROR")
    stack_card_warnings = sum(1 for row in stack_card_issues if row.get("severity") == "WARNING")
    so_errors = sum(1 for row in so_issues if row.get("severity") == "ERROR")
    so_warnings = sum(1 for row in so_issues if row.get("severity") == "WARNING")

    system_issues = list(data.get("systemIssues") or [])
    if errors:
        system_issues.append({
            "severity": "ERROR",
            "code": "OUTBOUND_DOCUMENT_INTEGRITY",
            "message": f"Ada {errors} masalah integritas pada Bon Muat, Surat Jalan, atau transaksi pengeluaran.",
        })
    if warnings:
        system_issues.append({
            "severity": "WARNING",
            "code": "OUTBOUND_DOCUMENT_INTEGRITY_WARNING",
            "message": f"Ada {warnings} peringatan relasi dokumen/antrian pengeluaran.",
        })
    if stack_card_errors:
        system_issues.append({
            "severity": "ERROR",
            "code": "STACK_CARD_PRINT_INTEGRITY",
            "message": f"Ada {stack_card_errors} masalah data cetak Kartu Tumpukan.",
        })
    if stack_card_warnings:
        system_issues.append({
            "severity": "WARNING",
            "code": "STACK_CARD_PRINT_WARNING",
            "message": f"Ada {stack_card_warnings} Kartu Tumpukan yang membutuhkan pembaruan susunan/metadata.",
        })
    if so_errors:
        system_issues.append({
            "severity": "ERROR",
            "code": "SO_FULFILLMENT_INTEGRITY",
            "message": f"Ada {so_errors} masalah integritas pada pemenuhan SO bertahap.",
        })
    if so_warnings:
        system_issues.append({
            "severity": "WARNING",
            "code": "SO_FULFILLMENT_WARNING",
            "message": f"Ada {so_warnings} peringatan pada monitoring SO bertahap.",
        })

    handling_cost = await analyze_handling_cost_integrity()
    handling_cost_summary = dict(handling_cost.get("summary") or {})
    cost_errors = int(handling_cost_summary.get("handlingCostIntegrityErrors", 0) or 0)
    cost_warnings = int(handling_cost_summary.get("handlingCostIntegrityWarnings", 0) or 0)
    if cost_errors:
        system_issues.append({
            "severity": "ERROR",
            "code": "HANDLING_COST_INTEGRITY",
            "message": f"Ada {cost_errors} masalah integritas pada biaya muat/bongkar atau pembayaran.",
        })
    if cost_warnings:
        system_issues.append({
            "severity": "WARNING",
            "code": "HANDLING_COST_INTEGRITY_WARNING",
            "message": f"Ada {cost_warnings} peringatan pada biaya muat/bongkar.",
        })

    consignment = await analyze_consignment_integrity()
    consignment_summary = dict(consignment.get("summary") or {})
    consignment_errors = int(consignment_summary.get("consignmentIntegrityErrors", 0) or 0)
    consignment_warnings = int(consignment_summary.get("consignmentIntegrityWarnings", 0) or 0)

    if consignment_errors:
        system_issues.append({
            "severity": "ERROR",
            "code": "CONSIGNMENT_INTEGRITY",
            "message": f"Ada {consignment_errors} masalah integritas pada Bazar/E-commerce/Paket/ND.",
        })
    if consignment_warnings:
        system_issues.append({
            "severity": "WARNING",
            "code": "CONSIGNMENT_INTEGRITY_WARNING",
            "message": f"Ada {consignment_warnings} kondisi konsinyasi yang masih membutuhkan perhatian.",
        })

    data["systemIssues"] = system_issues
    data["outboundDocumentIntegrityIssues"] = document_issues[:1000]
    data["stackCardIntegrityIssues"] = stack_card_issues[:1000]
    data["soFulfillmentIntegrityIssues"] = so_issues[:1000]
    data["handlingCostIntegrityIssues"] = handling_cost.get("handlingCostIntegrityIssues", [])[:1000]
    for key in (
        "consignmentStockIntegrity",
        "consignmentReservationIssues",
        "packageIntegrityIssues",
        "ecomOrderIntegrityIssues",
        "consignmentDamagedIntegrityIssues",
        "consignmentOpnamePending",
        "externalNDIntegrityIssues",
    ):
        data[key] = consignment.get(key, [])[:1000]

    summary = dict(data.get("summary") or {})
    summary.update(consignment_summary)
    summary.update(handling_cost_summary)
    summary["outboundDocumentIntegrityIssues"] = len(document_issues)
    summary["outboundDocumentIntegrityErrors"] = errors
    summary["outboundDocumentIntegrityWarnings"] = warnings
    summary["stackCardIntegrityIssues"] = len(stack_card_issues)
    summary["stackCardIntegrityErrors"] = stack_card_errors
    summary["stackCardIntegrityWarnings"] = stack_card_warnings
    summary["suratJalanLegacyCount"] = sum(1 for row in surat_jalan if str(row.get("no") or "").startswith("SJ-"))
    summary["suratJalanCurrentCount"] = sum(1 for row in surat_jalan if SJ_PATTERN.match(str(row.get("no") or "")))
    summary["soMonitoringTotal"] = int((so_monitoring.get("summary") or {}).get("total", 0) or 0)
    summary["soMonitoringOutstanding"] = int((so_monitoring.get("summary") or {}).get("outstanding", 0) or 0)
    summary["soMonitoringLegacy"] = int((so_monitoring.get("summary") or {}).get("legacy", 0) or 0)
    summary["soFulfillmentIntegrityIssues"] = len(so_issues)
    summary["soFulfillmentIntegrityErrors"] = so_errors
    summary["soFulfillmentIntegrityWarnings"] = so_warnings
    summary["systemErrors"] = sum(1 for issue in system_issues if str(issue.get("severity") or "") == "ERROR")
    summary["systemWarnings"] = sum(1 for issue in system_issues if str(issue.get("severity") or "") == "WARNING")
    data["summary"] = summary
    return data
