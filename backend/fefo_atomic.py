from __future__ import annotations

from backend.server import db, new_id, now_iso
from backend.stack_lots import EPS, _n
from backend.fefo_conservative import _active_lots


async def consume_tracked_fefo_atomic(load: dict, group: dict, qty: float) -> tuple[float, float]:
    """Consume tracked lots with compensation if the audit movement cannot be recorded.

    The lot balance and its movement row form one logical mutation. Mongo transactions are
    not assumed to be available in every Railway deployment, so a failed movement insert
    restores the lot quantity before the exception is propagated.
    """
    needed = max(_n(qty), 0.0)
    if needed <= EPS:
        return 0.0, 0.0

    product_id = str(group.get("productId") or "")
    stack_code = str(group.get("stackCode") or "").strip().upper()
    if not product_id or not stack_code:
        return 0.0, needed

    tracked = 0.0
    lots = await _active_lots(product_id, stack_code)
    for lot in lots:
        if needed <= EPS:
            break
        available = _n(lot.get("remainingQty"))
        if available <= EPS:
            continue

        take = min(available, needed)
        previous_status = str(lot.get("status") or "AKTIF")
        mutation_time = now_iso()
        result = await db.stack_lots.update_one(
            {"id": lot.get("id"), "remainingQty": {"$gte": take - EPS}},
            {"$inc": {"remainingQty": -take}, "$set": {"updatedAt": mutation_time}},
        )
        if result.matched_count == 0:
            continue

        movement = {
            "id": new_id(),
            "time": mutation_time,
            "loadId": str(load.get("id") or ""),
            "lotId": lot.get("id", ""),
            "lotCode": lot.get("lotCode", ""),
            "movementType": "OUTBOUND_FEFO",
            "productId": product_id,
            "sku": group.get("sku", ""),
            "product": group.get("product", ""),
            "stackCode": stack_code,
            "sourceDocument": str(group.get("sourceDocument") or ""),
            "qty": -take,
            "unit": group.get("unit", ""),
            "exp": lot.get("exp", ""),
            "note": "FEFO diterapkan setelah saldo legacy/untracked pada tumpukan dianggap habis.",
        }

        try:
            await db.stack_lot_movements.insert_one(movement)
        except Exception:
            # Compensate immediately so a retry cannot consume this lot twice.
            await db.stack_lots.update_one(
                {"id": lot.get("id")},
                {"$inc": {"remainingQty": take}, "$set": {"status": previous_status, "updatedAt": now_iso()}},
            )
            raise

        after = max(available - take, 0.0)
        if after <= EPS:
            await db.stack_lots.update_one(
                {"id": lot.get("id")},
                {"$set": {"remainingQty": 0.0, "status": "HABIS", "updatedAt": now_iso()}},
            )

        tracked += take
        needed -= take

    return tracked, max(needed, 0.0)
