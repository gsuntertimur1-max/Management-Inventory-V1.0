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
    data["systemIssues"] = issues

    summary = dict(data.get("summary") or {})
    summary["lotOvertrackedProducts"] = len(overtracked)
    summary["lotLegacyProducts"] = len(legacy)
    summary["ok"] = sum(1 for row in rows if row.get("severity") == "OK")
    summary["warnings"] = sum(1 for row in rows if row.get("severity") == "WARNING")
    summary["errors"] = sum(1 for row in rows if row.get("severity") == "ERROR")
    data["summary"] = summary
    return data
