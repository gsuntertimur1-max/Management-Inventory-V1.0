from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.server import db, new_id, now_iso, require_admin
from backend.operational_guards import operation_guard, product_lock_keys

router = APIRouter(prefix="/api")
EPS = 1e-9


def _n(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


class ReturnLotReconcileInput(BaseModel):
    qty: float = Field(gt=0)
    lotCode: str = Field(min_length=1, max_length=120)
    exp: str = ""
    note: str = Field(default="", max_length=500)


def _validate_exp(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Tanggal expired harus YYYY-MM-DD") from exc
    return text


async def _resolved_qty(source_movement_id: str) -> float:
    rows = await db.stack_lot_movements.find(
        {"movementType": "RETURN_RECONCILED", "sourceReturnMovementId": source_movement_id},
        {"_id": 0, "qty": 1},
    ).to_list(10000)
    return sum(abs(_n(row.get("qty"))) for row in rows)


@router.get("/return-lot-reconciliations/pending")
async def list_pending_return_lot_reconciliations(user: dict = Depends(require_admin)):
    rows = await db.stack_lot_movements.find(
        {"movementType": "RETURN_UNTRACKED", "qty": {"$gt": EPS}},
        {"_id": 0},
    ).sort("time", -1).to_list(20000)
    result = []
    for row in rows:
        source_id = str(row.get("id") or "")
        qty = _n(row.get("qty"))
        resolved = await _resolved_qty(source_id)
        remaining = max(qty - resolved, 0.0)
        if remaining <= EPS:
            continue
        result.append({
            **row,
            "originalQty": qty,
            "reconciledQty": resolved,
            "remainingQty": remaining,
        })
    return result


@router.post("/return-lot-reconciliations/{movement_id}")
async def reconcile_return_lot(
    movement_id: str,
    body: ReturnLotReconcileInput,
    user: dict = Depends(require_admin),
):
    source = await db.stack_lot_movements.find_one(
        {"id": movement_id, "movementType": "RETURN_UNTRACKED"},
        {"_id": 0},
    )
    if not source:
        raise HTTPException(status_code=404, detail="Movement retur legacy tidak ditemukan")

    product_id = str(source.get("productId") or "")
    stack_code = str(source.get("stackCode") or "").strip().upper()
    if not product_id or not stack_code:
        raise HTTPException(status_code=400, detail="Movement retur tidak memiliki produk/tumpukan yang dapat direkonsiliasi")

    lot_code = body.lotCode.strip()
    exp = _validate_exp(body.exp)
    qty = float(body.qty)

    async with operation_guard(product_lock_keys([product_id]) + [f"return-lot:{movement_id}"]):
        source = await db.stack_lot_movements.find_one(
            {"id": movement_id, "movementType": "RETURN_UNTRACKED"},
            {"_id": 0},
        )
        if not source:
            raise HTTPException(status_code=404, detail="Movement retur legacy tidak ditemukan")

        original_qty = _n(source.get("qty"))
        resolved_qty = await _resolved_qty(movement_id)
        remaining = max(original_qty - resolved_qty, 0.0)
        if qty > remaining + EPS:
            raise HTTPException(
                status_code=409,
                detail=f"Kuantum rekonsiliasi melebihi sisa retur legacy. Sisa {remaining:g} {source.get('unit', '')}",
            )

        allocation = await db.stack_allocations.find_one(
            {"productId": product_id, "stackCode": stack_code},
            {"_id": 0, "primaryQty": 1},
        )
        physical = _n((allocation or {}).get("primaryQty"))
        tracked_rows = await db.stack_lots.find(
            {"productId": product_id, "stackCode": stack_code, "remainingQty": {"$gt": EPS}, "status": {"$nin": ["DIBATALKAN"]}},
            {"_id": 0, "remainingQty": 1},
        ).to_list(10000)
        tracked = sum(_n(row.get("remainingQty")) for row in tracked_rows)
        untracked_capacity = max(physical - tracked, 0.0)
        if qty > untracked_capacity + EPS:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Rekonsiliasi ditolak karena saldo untracked tumpukan tidak cukup. "
                    f"Fisik {physical:g}, lot terlacak {tracked:g}, tersedia untuk rekonsiliasi {untracked_capacity:g}."
                ),
            )

        existing = await db.stack_lots.find_one(
            {"productId": product_id, "stackCode": stack_code, "lotCode": lot_code, "exp": exp, "status": {"$ne": "DIBATALKAN"}},
            {"_id": 0},
        )
        now = now_iso()
        if existing:
            lot_id = existing["id"]
            await db.stack_lots.update_one(
                {"id": lot_id},
                {"$inc": {"originalQty": qty, "remainingQty": qty}, "$set": {"status": "AKTIF", "updatedAt": now}},
            )
        else:
            lot_id = new_id()
            await db.stack_lots.insert_one({
                "id": lot_id,
                "lotCode": lot_code,
                "productId": product_id,
                "sku": source.get("sku", ""),
                "product": source.get("product", ""),
                "stackCode": stack_code,
                "channel": source.get("channel", ""),
                "sourceTransactionId": "",
                "operationId": "",
                "sourceRef": source.get("returnDocument", "") or source.get("sourceDocument", ""),
                "poNo": "",
                "receivedAt": source.get("time") or now,
                "exp": exp,
                "originalQty": qty,
                "remainingQty": qty,
                "unit": source.get("unit", ""),
                "status": "AKTIF",
                "createdAt": now,
                "reconciledFromReturn": True,
            })

        movement = {
            "id": new_id(),
            "time": now,
            "loadId": source.get("loadId", ""),
            "lotId": lot_id,
            "lotCode": lot_code,
            "movementType": "RETURN_RECONCILED",
            "sourceReturnMovementId": movement_id,
            "productId": product_id,
            "sku": source.get("sku", ""),
            "product": source.get("product", ""),
            "stackCode": stack_code,
            "sourceDocument": source.get("sourceDocument", ""),
            "returnDocument": source.get("returnDocument", ""),
            "qty": qty,
            "unit": source.get("unit", ""),
            "exp": exp,
            "operator": user.get("name", ""),
            "note": body.note.strip() or "Rekonsiliasi stok retur legacy ke lot terverifikasi; tidak mengubah stok fisik.",
        }
        try:
            await db.stack_lot_movements.insert_one(movement)
        except Exception:
            await db.stack_lots.update_one(
                {"id": lot_id},
                {"$inc": {"originalQty": -qty, "remainingQty": -qty}, "$set": {"updatedAt": now}},
            )
            lot_after = await db.stack_lots.find_one({"id": lot_id}, {"_id": 0, "originalQty": 1, "remainingQty": 1})
            if lot_after and _n(lot_after.get("originalQty")) <= EPS and _n(lot_after.get("remainingQty")) <= EPS:
                await db.stack_lots.delete_one({"id": lot_id})
            raise

        return {
            "sourceMovementId": movement_id,
            "lotId": lot_id,
            "lotCode": lot_code,
            "exp": exp,
            "qty": qty,
            "remainingUntrackedQty": max(remaining - qty, 0.0),
            "stockPhysicalChanged": False,
        }
