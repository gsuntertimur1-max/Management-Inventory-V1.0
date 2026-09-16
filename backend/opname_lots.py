from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from backend.server import db, new_id, now_iso
from backend.operational_guards import operation_guard, product_lock_keys
from backend.stack_lots import EPS, _n, lot_sort_key
from backend.stock_opname import (
    OpnameDecisionInput,
    approve_stock_opname as base_approve_stock_opname,
    require_opname_approval,
)

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)


async def _movement_total(opname_id: str, product_id: str, stack_code: str, positive: bool) -> float:
    rows = await db.stack_lot_movements.find(
        {
            "opnameId": opname_id,
            "productId": product_id,
            "stackCode": stack_code,
            "movementType": {"$in": ["OPNAME_LOT_ADJUSTMENT", "OPNAME_UNTRACKED_ADJUSTMENT"]},
        },
        {"_id": 0, "qty": 1},
    ).to_list(10000)
    values = [_n(row.get("qty")) for row in rows]
    return sum(value for value in values if value > EPS) if positive else sum(abs(value) for value in values if value < -EPS)


async def _record_untracked(opname: dict, txn: dict, qty: float, note: str) -> None:
    if abs(qty) <= EPS:
        return
    await db.stack_lot_movements.insert_one({
        "id": new_id(), "time": now_iso(), "loadId": "", "opnameId": opname.get("id", ""),
        "lotId": "", "lotCode": "", "movementType": "OPNAME_UNTRACKED_ADJUSTMENT",
        "productId": txn.get("product_id", ""), "sku": txn.get("sku", ""), "product": txn.get("product", ""),
        "stackCode": str(txn.get("stackCode") or "").upper(), "sourceDocument": opname.get("no", ""),
        "qty": qty, "unit": txn.get("unit", ""), "note": note,
    })


async def _reduce_single_lot(opname: dict, txn: dict, lot: dict, qty: float) -> float:
    if qty <= EPS:
        return 0.0
    available = _n(lot.get("remainingQty"))
    take = min(available, qty)
    if take <= EPS:
        return 0.0
    result = await db.stack_lots.update_one(
        {"id": lot.get("id"), "remainingQty": {"$gte": take - EPS}},
        {"$inc": {"remainingQty": -take}, "$set": {"updatedAt": now_iso()}},
    )
    if result.matched_count == 0:
        return 0.0
    after = max(available - take, 0.0)
    if after <= EPS:
        await db.stack_lots.update_one(
            {"id": lot.get("id")},
            {"$set": {"remainingQty": 0.0, "status": "HABIS", "updatedAt": now_iso()}},
        )
    await db.stack_lot_movements.insert_one({
        "id": new_id(), "time": now_iso(), "loadId": "", "opnameId": opname.get("id", ""),
        "lotId": lot.get("id", ""), "lotCode": lot.get("lotCode", ""), "movementType": "OPNAME_LOT_ADJUSTMENT",
        "productId": txn.get("product_id", ""), "sku": txn.get("sku", ""), "product": txn.get("product", ""),
        "stackCode": str(txn.get("stackCode") or "").upper(), "sourceDocument": opname.get("no", ""),
        "qty": -take, "unit": txn.get("unit", ""), "exp": lot.get("exp", ""),
        "note": "Selisih kurang stock opname; satu-satunya lot terlacak pada tumpukan disesuaikan.",
    })
    return take


async def sync_opname_lots(opname: dict) -> dict:
    if str(opname.get("status") or "") != "APPROVED":
        raise HTTPException(status_code=400, detail="Lot hanya dapat disinkronkan setelah stock opname disetujui")
    if str(opname.get("lotSyncStatus") or "") == "SYNCED":
        return opname

    operation_id = str(opname.get("adjustmentOperationId") or "")
    if not operation_id:
        await db.stock_opnames.update_one(
            {"id": opname.get("id")},
            {"$set": {"lotSyncStatus": "SYNCED", "lotSyncNote": "Tidak ada adjustment stok", "lotSyncedAt": now_iso()}},
        )
        return await db.stock_opnames.find_one({"id": opname.get("id")}, {"_id": 0})

    txns = await db.transactions.find(
        {"operation_id": operation_id, "document_type": "OPNAME", "type": "PENYESUAIAN"},
        {"_id": 0},
    ).to_list(5000)
    product_ids = [str(txn.get("product_id") or "") for txn in txns if txn.get("product_id")]
    reconciliation_required = []
    tracked_adjusted = untracked_adjusted = 0.0

    async with operation_guard(product_lock_keys(product_ids)):
        for txn in txns:
            qty = _n(txn.get("change"))
            if abs(qty) <= EPS:
                continue
            product_id = str(txn.get("product_id") or "")
            stack_code = str(txn.get("stackCode") or "").strip().upper()
            if not product_id or not stack_code:
                continue

            if qty > EPS:
                processed = await _movement_total(opname["id"], product_id, stack_code, True)
                remaining = max(qty - processed, 0.0)
                if remaining > EPS:
                    await _record_untracked(opname, txn, remaining, "Selisih lebih stock opname belum memiliki identitas batch/expired; dicatat sebagai stok untracked.")
                    untracked_adjusted += remaining
                continue

            needed_total = abs(qty)
            processed = await _movement_total(opname["id"], product_id, stack_code, False)
            needed = max(needed_total - processed, 0.0)
            if needed <= EPS:
                continue

            lots = await db.stack_lots.find(
                {"productId": product_id, "stackCode": stack_code, "remainingQty": {"$gt": EPS}, "status": {"$nin": ["DIBATALKAN"]}},
                {"_id": 0},
            ).to_list(10000)
            lots.sort(key=lot_sort_key)

            if len(lots) == 1:
                taken = await _reduce_single_lot(opname, txn, lots[0], needed)
                tracked_adjusted += taken
                needed -= taken
                if needed > EPS:
                    await _record_untracked(opname, txn, -needed, "Sisa selisih kurang berasal dari stok legacy/untracked.")
                    untracked_adjusted += needed
            elif len(lots) == 0:
                await _record_untracked(opname, txn, -needed, "Selisih kurang berasal dari stok legacy tanpa lot terlacak.")
                untracked_adjusted += needed
            else:
                reconciliation_required.append({
                    "productId": product_id, "sku": txn.get("sku", ""), "product": txn.get("product", ""),
                    "stackCode": stack_code, "qty": needed, "unit": txn.get("unit", ""), "activeLots": len(lots),
                })

        status = "RECONCILIATION_REQUIRED" if reconciliation_required else "SYNCED"
        note = (
            "Ada selisih kurang pada tumpukan multi-lot. Sistem tidak menebak batch yang hilang; lakukan rekonsiliasi lot."
            if reconciliation_required
            else "Subledger lot telah diselaraskan sebatas batch yang dapat ditentukan secara aman."
        )
        await db.stock_opnames.update_one(
            {"id": opname.get("id")},
            {"$set": {
                "lotSyncStatus": status, "lotSyncNote": note, "lotReconciliation": reconciliation_required,
                "lotTrackedAdjustmentQty": tracked_adjusted, "lotUntrackedAdjustmentQty": untracked_adjusted,
                "lotSyncedAt": now_iso(),
            }},
        )

    return await db.stock_opnames.find_one({"id": opname.get("id")}, {"_id": 0})


@router.post("/stock-opnames/{opname_id}/approve")
async def approve_stock_opname(opname_id: str, body: OpnameDecisionInput, user: dict = Depends(require_opname_approval)):
    result = await base_approve_stock_opname(opname_id, body, user)
    try:
        return await sync_opname_lots(result)
    except Exception as exc:
        logger.exception("Stock opname %s disetujui tetapi sinkronisasi lot gagal", opname_id)
        await db.stock_opnames.update_one(
            {"id": opname_id},
            {"$set": {"lotSyncStatus": "ERROR", "lotSyncNote": str(exc), "lotSyncedAt": now_iso()}},
        )
        return await db.stock_opnames.find_one({"id": opname_id}, {"_id": 0}) or result


@router.post("/stock-opnames/{opname_id}/sync-lots")
async def repair_stock_opname_lots(opname_id: str, user: dict = Depends(require_opname_approval)):
    opname = await db.stock_opnames.find_one({"id": opname_id}, {"_id": 0})
    if not opname:
        raise HTTPException(status_code=404, detail="Stock opname tidak ditemukan")
    return await sync_opname_lots(opname)
