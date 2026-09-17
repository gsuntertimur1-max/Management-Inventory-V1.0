from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.server import db, get_current_user, require_admin, require_write
from backend.outbound_flow import OutboundCreateInput, OutboundEditInput
from backend.operational_guards import guarded_create_outbound, guarded_edit_outbound

router = APIRouter(prefix="/api")
EPS = 1e-9
ACTIVE_STATUSES = ["Menunggu", "Sedang Dimuat"]


def _item_value(item, key: str, default=None):
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def aggregate_stack_demand(items) -> dict[tuple[str, str], float]:
    demand: dict[tuple[str, str], float] = defaultdict(float)
    for item in items:
        product_id = str(_item_value(item, "productId", "") or "").strip()
        stack_code = str(_item_value(item, "stackCode", "") or "").strip().upper()
        qty = float(_item_value(item, "qty", 0) or 0)
        if product_id and stack_code and qty > 0:
            demand[(product_id, stack_code)] += qty
    return dict(demand)


async def active_stack_reservations(exclude_load_id: str = "") -> dict[tuple[str, str], float]:
    query = {"status": {"$in": ACTIVE_STATUSES}, "kondisi": "BAIK"}
    if exclude_load_id:
        query["id"] = {"$ne": exclude_load_id}
    loads = await db.outbound_loads.find(query, {"_id": 0, "items": 1}).to_list(5000)
    reserved: dict[tuple[str, str], float] = defaultdict(float)
    for load in loads:
        for item in load.get("items", []):
            product_id = str(item.get("productId") or "").strip()
            stack_code = str(item.get("stackCode") or "").strip().upper()
            qty = float(item.get("qty", 0) or 0)
            if product_id and stack_code and qty > 0:
                reserved[(product_id, stack_code)] += qty
    return dict(reserved)


async def validate_stack_reservations(items, exclude_load_id: str = "") -> None:
    demand = aggregate_stack_demand(items)
    if not demand:
        return
    reserved = await active_stack_reservations(exclude_load_id)
    for (product_id, stack_code), requested_qty in demand.items():
        allocation = await db.stack_allocations.find_one(
            {"productId": product_id, "stackCode": stack_code},
            {"_id": 0, "primaryQty": 1, "productName": 1, "unit": 1},
        )
        physical = float((allocation or {}).get("primaryQty", 0) or 0)
        held = float(reserved.get((product_id, stack_code), 0) or 0)
        available = max(physical - held, 0.0)
        if requested_qty > available + EPS:
            name = str((allocation or {}).get("productName") or product_id)
            unit = str((allocation or {}).get("unit") or "")
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Stok tumpukan {stack_code} untuk {name} sudah terreservasi antrean lain. "
                    f"Fisik {physical:g}, terreservasi {held:g}, tersedia {available:g} {unit}."
                ).strip(),
            )


@router.get("/stack-reservations")
async def list_stack_reservations(user: dict = Depends(get_current_user)):
    reserved = await active_stack_reservations()
    rows = []
    for (product_id, stack_code), qty in sorted(reserved.items(), key=lambda value: (value[0][1], value[0][0])):
        allocation = await db.stack_allocations.find_one(
            {"productId": product_id, "stackCode": stack_code},
            {"_id": 0, "primaryQty": 1, "productName": 1, "sku": 1, "unit": 1},
        ) or {}
        physical = float(allocation.get("primaryQty", 0) or 0)
        rows.append({
            "productId": product_id,
            "product": allocation.get("productName", ""),
            "sku": allocation.get("sku", ""),
            "stackCode": stack_code,
            "unit": allocation.get("unit", ""),
            "physicalQty": physical,
            "reservedQty": qty,
            "availableQty": max(physical - qty, 0.0),
            "overReserved": qty > physical + EPS,
        })
    return rows


@router.post("/outbound-loads")
async def stack_reserved_create_outbound(body: OutboundCreateInput, request: Request, user: dict = Depends(require_write)):
    if body.kondisi == "BAIK":
        await validate_stack_reservations(body.items)
    return await guarded_create_outbound(body, request, user)


@router.put("/outbound-loads/{load_id}/edit")
async def stack_reserved_edit_outbound(load_id: str, body: OutboundEditInput, request: Request, user: dict = Depends(require_admin)):
    load = await db.outbound_loads.find_one({"id": load_id}, {"_id": 0, "kondisi": 1})
    if not load:
        raise HTTPException(status_code=404, detail="Data pemuatan tidak ditemukan")
    if load.get("kondisi", "BAIK") == "BAIK":
        await validate_stack_reservations(body.items, exclude_load_id=load_id)
    return await guarded_edit_outbound(load_id, body, request, user)
