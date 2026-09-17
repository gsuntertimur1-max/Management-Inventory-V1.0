from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException

from backend.operational_guards import operation_guard, product_lock_keys
from backend.outbound_flow import start_outbound_load
from backend.server import db, require_write
from backend.stack_reservations import available_stack_qty

router = APIRouter(prefix="/api")
EPS = 1e-9


async def _validate_start_reservations(load: dict) -> None:
    """Revalidate master and stack availability immediately before loading starts.

    The current load is excluded from the reservation calculation because its own
    quantity is the reservation being validated. Other active queues remain reserved.
    """
    if str(load.get("kondisi") or "BAIK").upper() != "BAIK":
        return

    requested_by_product: dict[str, float] = defaultdict(float)
    requested_by_stack: dict[tuple[str, str], float] = defaultdict(float)
    for item in load.get("items", []):
        product_id = str(item.get("productId") or "")
        qty = float(item.get("qty", 0) or 0)
        stack_code = str(item.get("stackCode") or "").strip().upper()
        if not product_id or qty <= EPS:
            continue
        if not stack_code:
            raise HTTPException(
                status_code=409,
                detail=f"Antrean {load.get('antrian', '')} memiliki barang tanpa tumpukan sumber. Koreksi pengeluaran sebelum mulai pemuatan.",
            )
        requested_by_product[product_id] += qty
        requested_by_stack[(product_id, stack_code)] += qty

    products: dict[str, dict] = {}
    for product_id, qty in requested_by_product.items():
        product = await db.products.find_one({"id": product_id}, {"_id": 0})
        if not product:
            raise HTTPException(status_code=404, detail="Produk pengeluaran tidak ditemukan")
        products[product_id] = product
        physical = float(product.get("stock", 0) or 0)
        # Sum reservations in all other active loads for this product.
        other_loads = await db.outbound_loads.find(
            {
                "id": {"$ne": load.get("id")},
                "status": {"$in": ["Menunggu", "Sedang Dimuat"]},
                "kondisi": "BAIK",
                "items.productId": product_id,
            },
            {"_id": 0, "items": 1},
        ).to_list(5000)
        other_reserved = sum(
            float(item.get("qty", 0) or 0)
            for other in other_loads
            for item in other.get("items", [])
            if str(item.get("productId") or "") == product_id
        )
        available = physical - other_reserved
        if qty > available + EPS:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Reservasi {product.get('name', 'produk')} tidak lagi valid. "
                    f"Fisik {physical:g}, reservasi antrean lain {other_reserved:g}, tersedia {available:g}, kebutuhan antrean ini {qty:g}."
                ),
            )

    for (product_id, stack_code), qty in requested_by_stack.items():
        allocation = await db.stack_allocations.find_one(
            {"productId": product_id, "stackCode": stack_code},
            {"_id": 0, "primaryQty": 1},
        )
        physical = float((allocation or {}).get("primaryQty", 0) or 0)
        reserved, available = await available_stack_qty(
            product_id, stack_code, physical, exclude_load_id=str(load.get("id") or "")
        )
        if not allocation or qty > available + EPS:
            product = products.get(product_id) or {}
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Tumpukan {stack_code} untuk {product.get('name', 'produk')} tidak lagi aman dimuat. "
                    f"Fisik {physical:g}, reservasi antrean lain {reserved:g}, tersedia {available:g}, kebutuhan antrean ini {qty:g}."
                ),
            )


@router.post("/outbound-loads/{load_id}/start")
async def guarded_start_outbound(load_id: str, user: dict = Depends(require_write)):
    load = await db.outbound_loads.find_one({"id": load_id}, {"_id": 0})
    if not load:
        raise HTTPException(status_code=404, detail="Data pemuatan tidak ditemukan")
    if load.get("status") == "Sedang Dimuat":
        return load
    if load.get("status") != "Menunggu":
        return await start_outbound_load(load_id, user)

    product_ids = [str(item.get("productId") or "") for item in load.get("items", []) if item.get("productId")]
    async with operation_guard(product_lock_keys(product_ids)):
        current = await db.outbound_loads.find_one({"id": load_id}, {"_id": 0})
        if not current:
            raise HTTPException(status_code=404, detail="Data pemuatan tidak ditemukan")
        if current.get("status") == "Sedang Dimuat":
            return current
        if current.get("status") != "Menunggu":
            return await start_outbound_load(load_id, user)
        await _validate_start_reservations(current)
        return await start_outbound_load(load_id, user)
