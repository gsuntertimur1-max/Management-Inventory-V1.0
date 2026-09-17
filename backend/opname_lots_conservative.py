from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from backend.server import db, now_iso
from backend.operational_guards import operation_guard, product_lock_keys
from backend.stack_lots import EPS, _n, lot_sort_key
from backend.opname_lots import _movement_total, _record_untracked, _reduce_single_lot
from backend.stock_opname import (
    OpnameDecisionInput,
    approve_stock_opname as base_approve_stock_opname,
    require_opname_approval,
)

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)


def conservative_shortage_split(current_stack_qty: float, tracked_qty: float, needed: float) -> tuple[float, float]:
    """Split an opname shortage without guessing identified lots.

    Unknown/legacy stock absorbs the shortage first. Tracked lots are reduced
    only when tracked quantity would otherwise exceed the physical stack after
    the approved opname adjustment.
    """
    shortage = max(_n(needed), 0.0)
    tracked_excess = min(shortage, max(_n(tracked_qty) - _n(current_stack_qty), 0.0))
    untracked = max(shortage - tracked_excess, 0.0)
    return untracked, tracked_excess


async def _stack_qty(product_id: str, stack_code: str) -> float:
    rows = await db.stack_allocations.find(
        {"productId": product_id, "stackCode": stack_code},
        {"_id": 0, "primaryQty": 1},
    ).to_list(10000)
    return sum(_n(row.get("primaryQty")) for row in rows)


async def sync_opname_lots_conservative(opname: dict) -> dict:
    if str(opname.get("status") or "") != "APPROVED":
        raise HTTPException(status_code=400, detail="Lot hanya dapat disinkronkan setelah stock opname disetujui")
    if str(opname.get("lotSyncStatus") or "") == "SYNCED":
        return opname

    operation_id = str(opname.get("adjustmentOperationId") or "")
    if not operation_id:
        await db.stock_opnames.update_one(
            {"id": opname.get("id")},
            {"$set": {
                "lotSyncStatus": "SYNCED",
                "lotSyncNote": "Tidak ada adjustment stok",
                "lotSyncedAt": now_iso(),
                "lotPolicy": "CONSERVATIVE_LEGACY_FIRST",
            }},
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
                    await _record_untracked(
                        opname,
                        txn,
                        remaining,
                        "Selisih lebih stock opname belum memiliki identitas batch/expired; dicatat sebagai stok legacy/untracked.",
                    )
                    untracked_adjusted += remaining
                continue

            needed_total = abs(qty)
            processed = await _movement_total(opname["id"], product_id, stack_code, False)
            needed = max(needed_total - processed, 0.0)
            if needed <= EPS:
                continue

            lots = await db.stack_lots.find(
                {
                    "productId": product_id,
                    "stackCode": stack_code,
                    "remainingQty": {"$gt": EPS},
                    "status": {"$nin": ["DIBATALKAN"]},
                },
                {"_id": 0},
            ).to_list(10000)
            lots.sort(key=lot_sort_key)
            tracked_qty = sum(_n(lot.get("remainingQty")) for lot in lots)
            current_stack_qty = await _stack_qty(product_id, stack_code)
            untracked_needed, tracked_needed = conservative_shortage_split(current_stack_qty, tracked_qty, needed)

            if untracked_needed > EPS:
                await _record_untracked(
                    opname,
                    txn,
                    -untracked_needed,
                    "Selisih kurang lebih dulu dibebankan ke stok legacy/untracked agar sistem tidak menebak lot yang hilang.",
                )
                untracked_adjusted += untracked_needed

            if tracked_needed <= EPS:
                continue

            if len(lots) == 1:
                taken = await _reduce_single_lot(opname, txn, lots[0], tracked_needed)
                tracked_adjusted += taken
                residual = max(tracked_needed - taken, 0.0)
                if residual > EPS:
                    reconciliation_required.append({
                        "productId": product_id,
                        "sku": txn.get("sku", ""),
                        "product": txn.get("product", ""),
                        "stackCode": stack_code,
                        "qty": residual,
                        "unit": txn.get("unit", ""),
                        "activeLots": len(lots),
                    })
            elif len(lots) == 0:
                await _record_untracked(
                    opname,
                    txn,
                    -tracked_needed,
                    "Subledger tidak memiliki lot aktif; bagian selisih dicatat sebagai legacy/untracked.",
                )
                untracked_adjusted += tracked_needed
            else:
                reconciliation_required.append({
                    "productId": product_id,
                    "sku": txn.get("sku", ""),
                    "product": txn.get("product", ""),
                    "stackCode": stack_code,
                    "qty": tracked_needed,
                    "unit": txn.get("unit", ""),
                    "activeLots": len(lots),
                })

        status = "RECONCILIATION_REQUIRED" if reconciliation_required else "SYNCED"
        note = (
            "Ada bagian selisih yang wajib mengenai lot terlacak dan terdapat lebih dari satu kandidat lot. Pilih lot secara manual."
            if reconciliation_required
            else "Subledger lot telah diselaraskan secara konservatif; stok legacy/untracked diprioritaskan sebelum lot bernama dikurangi."
        )
        await db.stock_opnames.update_one(
            {"id": opname.get("id")},
            {"$set": {
                "lotSyncStatus": status,
                "lotSyncNote": note,
                "lotReconciliation": reconciliation_required,
                "lotTrackedAdjustmentQty": tracked_adjusted,
                "lotUntrackedAdjustmentQty": untracked_adjusted,
                "lotSyncedAt": now_iso(),
                "lotPolicy": "CONSERVATIVE_LEGACY_FIRST",
            }},
        )

    return await db.stock_opnames.find_one({"id": opname.get("id")}, {"_id": 0})


@router.post("/stock-opnames/{opname_id}/approve")
async def approve_stock_opname_conservative(
    opname_id: str,
    body: OpnameDecisionInput,
    user: dict = Depends(require_opname_approval),
):
    result = await base_approve_stock_opname(opname_id, body, user)
    try:
        return await sync_opname_lots_conservative(result)
    except Exception as exc:
        logger.exception("Stock opname %s disetujui tetapi sinkronisasi lot konservatif gagal", opname_id)
        await db.stock_opnames.update_one(
            {"id": opname_id},
            {"$set": {
                "lotSyncStatus": "ERROR",
                "lotSyncNote": str(exc),
                "lotSyncedAt": now_iso(),
                "lotPolicy": "CONSERVATIVE_LEGACY_FIRST",
            }},
        )
        return await db.stock_opnames.find_one({"id": opname_id}, {"_id": 0}) or result


@router.post("/stock-opnames/{opname_id}/sync-lots")
async def repair_stock_opname_lots_conservative(
    opname_id: str,
    user: dict = Depends(require_opname_approval),
):
    opname = await db.stock_opnames.find_one({"id": opname_id}, {"_id": 0})
    if not opname:
        raise HTTPException(status_code=404, detail="Stock opname tidak ditemukan")
    return await sync_opname_lots_conservative(opname)
