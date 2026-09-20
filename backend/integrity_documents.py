from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends

from backend.server import db, require_master_write
from backend.integrity_postcommit import integrity_control as base_integrity_control
from backend.integrity_consignment import analyze_consignment_integrity

router = APIRouter(prefix="/api")
EPS = 1e-9


def _n(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


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
            continue
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
        {"_id": 0, "id": 1, "status": 1, "bon_no": 1, "antrian": 1, "surat_jalan_id": 1, "surat_jalan_no": 1, "items": 1},
    ).to_list(30000)
    surat_jalan = await db.surat_jalan.find(
        {},
        {"_id": 0, "id": 1, "load_id": 1, "no": 1, "bon_no": 1, "antrian": 1},
    ).to_list(30000)
    transactions = await db.transactions.find(
        {"type": "KELUAR"},
        {"_id": 0, "id": 1, "load_id": 1, "product_id": 1, "stackCode": 1, "change": 1, "bon_no": 1, "antrian": 1},
    ).to_list(100000)

    document_issues = analyze_outbound_document_integrity(loads, surat_jalan, transactions)
    errors = sum(1 for row in document_issues if row.get("severity") == "ERROR")
    warnings = sum(1 for row in document_issues if row.get("severity") == "WARNING")

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
    summary["outboundDocumentIntegrityIssues"] = len(document_issues)
    summary["outboundDocumentIntegrityErrors"] = errors
    summary["outboundDocumentIntegrityWarnings"] = warnings
    summary["systemErrors"] = sum(1 for issue in system_issues if str(issue.get("severity") or "") == "ERROR")
    summary["systemWarnings"] = sum(1 for issue in system_issues if str(issue.get("severity") or "") == "WARNING")
    data["summary"] = summary
    return data
