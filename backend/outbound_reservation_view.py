from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from backend.integrity_control import ACTIVE_OUTBOUND_STATUSES, build_stack_reservation_integrity
from backend.server import db, get_current_user

router = APIRouter(prefix="/api")


@router.get("/outbound-reservations")
async def outbound_reservations(user: dict = Depends(get_current_user)):
    """Return the authoritative per-stack reservation picture used by outbound UI.

    The endpoint deliberately returns negative available quantities when a stack is
    over-reserved so operators can see the integrity problem instead of masking it.
    """
    products = await db.products.find(
        {}, {"_id": 0, "id": 1, "sku": 1, "name": 1, "unit": 1}
    ).to_list(20000)
    allocations = await db.stack_allocations.find(
        {}, {"_id": 0, "productId": 1, "stackCode": 1, "primaryQty": 1}
    ).to_list(50000)
    active_loads = await db.outbound_loads.find(
        {"status": {"$in": list(ACTIVE_OUTBOUND_STATUSES)}},
        {"_id": 0, "id": 1, "antrian": 1, "ref": 1, "status": 1, "kondisi": 1, "items": 1},
    ).to_list(10000)

    rows, unassigned = build_stack_reservation_integrity(allocations, active_loads, products)
    over_reserved = [row for row in rows if row.get("overReserved")]
    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "activeLoads": len(active_loads),
            "reservedStacks": len(rows),
            "overReservedStacks": len(over_reserved),
            "unassignedReservations": len(unassigned),
        },
        "rows": rows,
        "unassigned": unassigned[:500],
    }
