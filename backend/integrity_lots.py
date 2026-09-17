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
    data["systemIssues"] = issues
    data["completedOutboundMissingSuratJalan"] = missing_sj[:500]
    data["orphanSuratJalan"] = orphan_sj[:500]

    summary = dict(data.get("summary") or {})
    summary["lotOvertrackedProducts"] = len(overtracked)
    summary["lotLegacyProducts"] = len(legacy)
    summary["completedOutboundMissingSuratJalan"] = len(missing_sj)
    summary["orphanSuratJalan"] = len(orphan_sj)
    summary["ok"] = sum(1 for row in rows if row.get("severity") == "OK")
    summary["warnings"] = sum(1 for row in rows if row.get("severity") == "WARNING")
    summary["errors"] = sum(1 for row in rows if row.get("severity") == "ERROR")
    data["summary"] = summary
    return data