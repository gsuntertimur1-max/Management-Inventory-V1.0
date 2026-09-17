from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends

from backend.server import db, require_master_write
from backend.integrity_control import integrity_control as base_integrity_control

router = APIRouter(prefix="/api")
EPS = 1e-9


def _n(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def apply_lot_integrity(row: dict, tracked_qty: float) -> dict:
    result = dict(row)
    stack_qty = _n(result.get("stackGood"))
    tracked = _n(tracked_qty)
    untracked = max(stack_qty - tracked, 0.0)
    result["lotTracked"] = tracked
    result["lotUntracked"] = untracked
    result["lotDifference"] = stack_qty - tracked
    result["lotCoveragePct"] = (tracked / stack_qty * 100.0) if stack_qty > EPS else (100.0 if tracked <= EPS else 0.0)
    issues = list(result.get("issues") or [])
    severity = str(result.get("severity") or "OK")

    if tracked - stack_qty > EPS:
        issues.append("Total lot terlacak lebih besar daripada stok tumpukan; lakukan rekonsiliasi lot")
        severity = "ERROR"
    elif stack_qty - tracked > EPS:
        issues.append(f"Coverage lot belum 100%: {untracked:g} {result.get('unit', '')} masih legacy/untracked")
        if severity == "OK":
            severity = "WARNING"

    result["issues"] = issues
    result["severity"] = severity
    return result


async def _document_integrity() -> tuple[list[dict], list[dict]]:
    all_loads = await db.outbound_loads.find(
        {},
        {"_id": 0, "id": 1, "status": 1, "bon_no": 1, "antrian": 1, "ref": 1, "surat_jalan_id": 1, "surat_jalan_no": 1},
    ).to_list(30000)
    completed = [row for row in all_loads if row.get("status") == "Selesai"]
    surat_jalan = await db.surat_jalan.find(
        {},
        {"_id": 0, "id": 1, "load_id": 1, "no": 1, "bon_no": 1, "antrian": 1},
    ).to_list(30000)

    all_load_ids = {str(row.get("id") or "") for row in all_loads if row.get("id")}
    sj_by_id = {str(row.get("id") or ""): row for row in surat_jalan if row.get("id")}
    sj_by_load = defaultdict(list)
    for row in surat_jalan:
        load_id = str(row.get("load_id") or "")
        if load_id:
            sj_by_load[load_id].append(row)

    missing = []
    for load in completed:
        load_id = str(load.get("id") or "")
        sj_id = str(load.get("surat_jalan_id") or "")
        linked = sj_by_id.get(sj_id) if sj_id else None
        if not linked and load_id:
            linked_rows = sj_by_load.get(load_id, [])
            linked = linked_rows[0] if linked_rows else None
        if linked:
            continue
        missing.append({
            "loadId": load_id,
            "bonNo": load.get("bon_no", ""),
            "queue": load.get("antrian", ""),
            "ref": load.get("ref", ""),
            "suratJalanId": sj_id,
            "suratJalanNo": load.get("surat_jalan_no", ""),
            "issue": "Pengeluaran Selesai belum memiliki Surat Jalan yang dapat ditemukan",
        })

    orphan = []
    for sj in surat_jalan:
        load_id = str(sj.get("load_id") or "")
        if not load_id or load_id in all_load_ids:
            continue
        orphan.append({
            "suratJalanId": sj.get("id", ""),
            "suratJalanNo": sj.get("no", ""),
            "loadId": load_id,
            "bonNo": sj.get("bon_no", ""),
            "queue": sj.get("antrian", ""),
            "issue": "Surat Jalan tidak memiliki data pemuatan sumber",
        })
    return missing, orphan


async def _settlement_integrity() -> tuple[list[dict], list[dict]]:
    loads = await db.outbound_loads.find(
        {},
        {"_id": 0, "id": 1, "ref": 1, "documents": 1, "document_type": 1, "items": 1, "document_links": 1, "bon_no": 1, "antrian": 1},
    ).to_list(30000)

    document_owners: dict[str, set[tuple[str, str]]] = defaultdict(set)
    settlement_issues: list[dict] = []

    for load in loads:
        load_id = str(load.get("id") or "")
        for number in load.get("documents") or [load.get("ref", "")]:
            doc_no = str(number or "").strip().upper()
            if doc_no:
                document_owners[doc_no].add((load_id, "SOURCE"))
        for link in load.get("document_links") or []:
            doc_no = str(link.get("no") or "").strip().upper()
            if doc_no:
                document_owners[doc_no].add((load_id, "LINK"))

        if str(load.get("document_type") or "") not in {"CT", "MEMO", "ND"}:
            continue

        original: dict[tuple[str, str], float] = defaultdict(float)
        for item in load.get("items") or []:
            source = str(item.get("documentNo") or load.get("ref") or "").strip()
            product_id = str(item.get("productId") or "")
            if source and product_id:
                original[(source, product_id)] += _n(item.get("qty"))

        settled: dict[tuple[str, str], float] = defaultdict(float)
        for link in load.get("document_links") or []:
            link_type = str(link.get("type") or "")
            if link_type not in {"CR", "RETUR", "SO"}:
                continue
            source = str(link.get("sourceDocumentNo") or load.get("ref") or "").strip()
            for item in link.get("items") or []:
                product_id = str(item.get("productId") or "")
                if not source or not product_id:
                    settlement_issues.append({
                        "severity": "ERROR",
                        "code": "SETTLEMENT_LINK_INCOMPLETE",
                        "loadId": load_id,
                        "bonNo": load.get("bon_no", ""),
                        "queue": load.get("antrian", ""),
                        "documentNo": link.get("no", ""),
                        "sourceDocumentNo": source,
                        "issue": "Dokumen turunan tidak memiliki dokumen sumber atau productId yang lengkap",
                    })
                    continue
                qty = _n(item.get("qty")) if link_type == "SO" else _n(item.get("goodQty")) + _n(item.get("damagedQty"))
                key = (source, product_id)
                settled[key] += qty
                if key not in original:
                    settlement_issues.append({
                        "severity": "ERROR",
                        "code": "SETTLEMENT_ORPHAN_PRODUCT",
                        "loadId": load_id,
                        "bonNo": load.get("bon_no", ""),
                        "queue": load.get("antrian", ""),
                        "documentNo": link.get("no", ""),
                        "sourceDocumentNo": source,
                        "productId": product_id,
                        "qty": qty,
                        "issue": "Dokumen turunan menunjuk produk/dokumen sumber yang tidak terdapat pada pengeluaran asal",
                    })

        for key, qty in settled.items():
            source, product_id = key
            source_qty = original.get(key, 0.0)
            if source_qty > 0 and qty - source_qty > EPS:
                settlement_issues.append({
                    "severity": "ERROR",
                    "code": "SETTLEMENT_OVER_QTY",
                    "loadId": load_id,
                    "bonNo": load.get("bon_no", ""),
                    "queue": load.get("antrian", ""),
                    "sourceDocumentNo": source,
                    "productId": product_id,
                    "sourceQty": source_qty,
                    "settledQty": qty,
                    "overBy": qty - source_qty,
                    "issue": "Total SO/CR/Retur melebihi kuantum dokumen sumber",
                })

    duplicates = []
    for document_no, owners in document_owners.items():
        if len(owners) <= 1:
            continue
        duplicates.append({
            "documentNo": document_no,
            "occurrences": [{"loadId": load_id, "role": role} for load_id, role in sorted(owners)],
            "issue": "Nomor dokumen digunakan lebih dari satu kali pada pengeluaran/dokumen turunan",
        })

    return duplicates, settlement_issues


async def _pending_return_lot_reconciliations() -> list[dict]:
    sources = await db.stack_lot_movements.find(
        {"movementType": "RETURN_UNTRACKED", "qty": {"$gt": EPS}},
        {"_id": 0},
    ).to_list(20000)
    source_ids = [str(row.get("id") or "") for row in sources if row.get("id")]
    resolved: dict[str, float] = defaultdict(float)
    if source_ids:
        rows = await db.stack_lot_movements.find(
            {"movementType": "RETURN_RECONCILED", "sourceReturnMovementId": {"$in": source_ids}},
            {"_id": 0, "sourceReturnMovementId": 1, "qty": 1},
        ).to_list(50000)
        for row in rows:
            resolved[str(row.get("sourceReturnMovementId") or "")] += abs(_n(row.get("qty")))

    pending = []
    for source in sources:
        source_id = str(source.get("id") or "")
        original = _n(source.get("qty"))
        reconciled = resolved.get(source_id, 0.0)
        remaining = max(original - reconciled, 0.0)
        if remaining <= EPS:
            continue
        pending.append({
            "movementId": source_id,
            "loadId": source.get("loadId", ""),
            "returnDocument": source.get("returnDocument", ""),
            "sourceDocument": source.get("sourceDocument", ""),
            "productId": source.get("productId", ""),
            "sku": source.get("sku", ""),
            "product": source.get("product", ""),
            "stackCode": source.get("stackCode", ""),
            "unit": source.get("unit", ""),
            "originalQty": original,
            "reconciledQty": reconciled,
            "remainingQty": remaining,
            "issue": "Retur Baik masih legacy/untracked dan belum seluruhnya direkonsiliasi ke lot/batch terverifikasi",
        })
    return pending


@router.get("/integrity-control")
async def integrity_control(user: dict = Depends(require_master_write)):
    data = await base_integrity_control(user)

    lot_totals: dict[str, float] = defaultdict(float)
    lots = await db.stack_lots.find(
        {"remainingQty": {"$gt": EPS}, "status": {"$nin": ["DIBATALKAN"]}},
        {"_id": 0, "productId": 1, "remainingQty": 1},
    ).to_list(50000)
    for lot in lots:
        product_id = str(lot.get("productId") or "")
        if product_id:
            lot_totals[product_id] += _n(lot.get("remainingQty"))

    rows = [apply_lot_integrity(row, lot_totals.get(str(row.get("productId") or ""), 0.0)) for row in data.get("products", [])]
    data["products"] = rows

    overtracked = [row for row in rows if _n(row.get("lotTracked")) - _n(row.get("stackGood")) > EPS]
    legacy = [row for row in rows if _n(row.get("stackGood")) - _n(row.get("lotTracked")) > EPS]
    missing_sj, orphan_sj = await _document_integrity()
    duplicate_documents, settlement_issues = await _settlement_integrity()
    pending_return_lots = await _pending_return_lot_reconciliations()

    issues = list(data.get("systemIssues") or [])
    if overtracked:
        issues.append({
            "severity": "ERROR",
            "code": "LOT_OVERTRACKED",
            "message": f"Ada {len(overtracked)} produk dengan saldo lot lebih besar daripada stok tumpukan.",
        })
    if legacy:
        issues.append({
            "severity": "WARNING",
            "code": "LOT_LEGACY_UNTRACKED",
            "message": f"Ada {len(legacy)} produk yang belum 100% tercakup subledger lot/FEFO. Stok legacy tetap dipertahankan tanpa mengarang tanggal expired.",
        })
    if pending_return_lots:
        total_pending = sum(_n(row.get("remainingQty")) for row in pending_return_lots)
        issues.append({
            "severity": "WARNING",
            "code": "RETURN_LOT_RECONCILIATION_PENDING",
            "message": f"Ada {len(pending_return_lots)} retur Baik dengan total {total_pending:g} unit yang masih menunggu rekonsiliasi batch/expired.",
        })
    if missing_sj:
        issues.append({
            "severity": "ERROR",
            "code": "COMPLETED_OUTBOUND_MISSING_SJ",
            "message": f"Ada {len(missing_sj)} pengeluaran Selesai tanpa Surat Jalan yang dapat ditemukan.",
        })
    if orphan_sj:
        issues.append({
            "severity": "WARNING",
            "code": "ORPHAN_SURAT_JALAN",
            "message": f"Ada {len(orphan_sj)} Surat Jalan tanpa data pemuatan sumber.",
        })
    if duplicate_documents:
        issues.append({
            "severity": "ERROR",
            "code": "DUPLICATE_OUTBOUND_DOCUMENT",
            "message": f"Ada {len(duplicate_documents)} nomor dokumen yang digunakan lebih dari satu kali.",
        })
    if settlement_issues:
        issues.append({
            "severity": "ERROR",
            "code": "SETTLEMENT_INTEGRITY",
            "message": f"Ada {len(settlement_issues)} masalah kuantum/relasi pada SO, CR, atau Retur lanjutan.",
        })

    data["systemIssues"] = issues
    data["completedOutboundMissingSuratJalan"] = missing_sj[:500]
    data["orphanSuratJalan"] = orphan_sj[:500]
    data["duplicateOutboundDocuments"] = duplicate_documents[:500]
    data["documentSettlementIssues"] = settlement_issues[:500]
    data["pendingReturnLotReconciliations"] = pending_return_lots[:500]

    summary = dict(data.get("summary") or {})
    summary["lotOvertrackedProducts"] = len(overtracked)
    summary["lotLegacyProducts"] = len(legacy)
    summary["pendingReturnLotReconciliations"] = len(pending_return_lots)
    summary["pendingReturnLotQty"] = sum(_n(row.get("remainingQty")) for row in pending_return_lots)
    summary["completedOutboundMissingSuratJalan"] = len(missing_sj)
    summary["orphanSuratJalan"] = len(orphan_sj)
    summary["duplicateOutboundDocuments"] = len(duplicate_documents)
    summary["documentSettlementIssues"] = len(settlement_issues)
    summary["ok"] = sum(1 for row in rows if row.get("severity") == "OK")
    summary["warnings"] = sum(1 for row in rows if row.get("severity") == "WARNING")
    summary["errors"] = sum(1 for row in rows if row.get("severity") == "ERROR")
    data["summary"] = summary
    return data
