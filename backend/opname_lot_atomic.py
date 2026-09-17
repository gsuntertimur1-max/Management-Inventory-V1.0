from __future__ import annotations

import logging

from backend.server import db, new_id, now_iso
from backend.stack_lots import EPS, _n
import backend.opname_lots as opname_lots
import backend.opname_lots_conservative as opname_lots_conservative

logger = logging.getLogger(__name__)


async def reduce_single_lot_atomic(opname: dict, txn: dict, lot: dict, qty: float) -> float:
    """Reduce one identified lot and compensate the mutation if its audit movement cannot be stored."""
    if qty <= EPS:
        return 0.0
    snapshot = dict(lot)
    available = _n(snapshot.get("remainingQty"))
    take = min(available, qty)
    if take <= EPS:
        return 0.0

    timestamp = now_iso()
    result = await db.stack_lots.update_one(
        {"id": snapshot.get("id"), "remainingQty": {"$gte": take - EPS}},
        {"$inc": {"remainingQty": -take}, "$set": {"updatedAt": timestamp}},
    )
    if result.matched_count == 0:
        return 0.0

    try:
        after = max(available - take, 0.0)
        if after <= EPS:
            await db.stack_lots.update_one(
                {"id": snapshot.get("id")},
                {"$set": {"remainingQty": 0.0, "status": "HABIS", "updatedAt": timestamp}},
            )

        movement_id = new_id()
        await db.stack_lot_movements.insert_one({
            "id": movement_id,
            "time": timestamp,
            "loadId": "",
            "opnameId": opname.get("id", ""),
            "lotId": snapshot.get("id", ""),
            "lotCode": snapshot.get("lotCode", ""),
            "movementType": "OPNAME_LOT_ADJUSTMENT",
            "productId": txn.get("product_id", ""),
            "sku": txn.get("sku", ""),
            "product": txn.get("product", ""),
            "stackCode": str(txn.get("stackCode") or "").upper(),
            "sourceDocument": opname.get("no", ""),
            "qty": -take,
            "unit": txn.get("unit", ""),
            "exp": snapshot.get("exp", ""),
            "note": "Selisih kurang stock opname; satu-satunya lot terlacak pada tumpukan disesuaikan.",
        })
        return take
    except Exception:
        try:
            await db.stack_lots.replace_one({"id": snapshot.get("id")}, snapshot, upsert=True)
        except Exception:
            logger.exception(
                "CRITICAL: gagal mengembalikan lot %s setelah audit movement opname gagal",
                snapshot.get("id", ""),
            )
        raise


# Patch both legacy and conservative opname engines. They resolve this global at runtime,
# so all registered routes use the compensated implementation without duplicating endpoints.
opname_lots._reduce_single_lot = reduce_single_lot_atomic
opname_lots_conservative._reduce_single_lot = reduce_single_lot_atomic
