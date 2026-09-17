from __future__ import annotations

from backend.server import db

EPS = 1e-9
ACTIVE_STATUSES = ["Menunggu", "Sedang Dimuat"]


async def reserved_stack_qty(product_id: str, stack_code: str, exclude_load_id: str = "") -> float:
    code = str(stack_code or "").strip().upper()
    if not product_id or not code:
        return 0.0
    query = {"status": {"$in": ACTIVE_STATUSES}, "kondisi": "BAIK"}
    if exclude_load_id:
        query["id"] = {"$ne": exclude_load_id}
    loads = await db.outbound_loads.find(query, {"_id": 0, "items": 1}).to_list(5000)
    total = 0.0
    for load in loads:
        for item in load.get("items", []):
            if item.get("productId") == product_id and str(item.get("stackCode") or "").strip().upper() == code:
                total += float(item.get("qty", 0) or 0)
    return total


async def available_stack_qty(product_id: str, stack_code: str, physical_qty: float, exclude_load_id: str = "") -> tuple[float, float]:
    reserved = await reserved_stack_qty(product_id, stack_code, exclude_load_id)
    return reserved, max(float(physical_qty or 0) - reserved, 0.0)
