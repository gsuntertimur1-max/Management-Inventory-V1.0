from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.server import db, ensure_channel_stock, normalize_channel, require_write
from backend.inventory_flow import (
    DamageDiscoveryInput,
    SupplierReturnInput,
    create_supplier_return,
    record_stock_damage_discovery,
)
from backend.operational_guards import _bind_supplier_return, idempotent_operation, product_lock_keys
from backend.outbound_flow import _reserved_qty
from backend.stack_reservations import reserved_stack_qty

router = APIRouter(prefix="/api")
EPS = 1e-9


async def _validate_good_stock_reduction(product: dict, product_id: str, channel: str, stack_code: str, qty: float) -> None:
    await ensure_channel_stock(product)
    product = await db.products.find_one({"id": product_id}, {"_id": 0}) or product

    master_physical = float(product.get("stock", 0) or 0)
    master_reserved = await _reserved_qty(product_id, "BAIK")
    if master_physical - qty + EPS < master_reserved:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Perubahan ditolak karena stok Baik sudah direservasi outbound. "
                f"Fisik {master_physical:g}, reservasi {master_reserved:g}, pengurangan diminta {qty:g}."
            ),
        )

    bucket = (product.get("channelStock") or {}).get(channel, {})
    channel_physical = float(bucket.get("stock", 0) or 0)
    channel_reserved = await _reserved_qty(product_id, "BAIK", channel=channel)
    if channel_physical - qty + EPS < channel_reserved:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Perubahan ditolak karena stok Baik {channel} sudah direservasi outbound. "
                f"Fisik {channel_physical:g}, reservasi {channel_reserved:g}, pengurangan diminta {qty:g}."
            ),
        )

    allocation = await db.stack_allocations.find_one(
        {"productId": product_id, "stackCode": stack_code},
        {"_id": 0, "primaryQty": 1},
    )
    stack_physical = float((allocation or {}).get("primaryQty", 0) or 0)
    stack_reserved = await reserved_stack_qty(product_id, stack_code)
    if stack_physical - qty + EPS < stack_reserved:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Perubahan ditolak karena tumpukan {stack_code} sudah direservasi outbound. "
                f"Fisik {stack_physical:g}, reservasi {stack_reserved:g}, pengurangan diminta {qty:g}."
            ),
        )


async def _validate_damaged_stock_reduction(product: dict, product_id: str, channel: str, qty: float) -> None:
    await ensure_channel_stock(product)
    product = await db.products.find_one({"id": product_id}, {"_id": 0}) or product

    master_physical = float(product.get("damaged", 0) or 0)
    master_reserved = await _reserved_qty(product_id, "RUSAK")
    if master_physical - qty + EPS < master_reserved:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Retur ditolak karena stok Rusak sudah direservasi outbound. "
                f"Fisik {master_physical:g}, reservasi {master_reserved:g}, pengurangan diminta {qty:g}."
            ),
        )

    bucket = (product.get("channelStock") or {}).get(channel, {})
    channel_physical = float(bucket.get("damaged", 0) or 0)
    channel_reserved = await _reserved_qty(product_id, "RUSAK", channel=channel)
    if channel_physical - qty + EPS < channel_reserved:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Retur ditolak karena stok Rusak {channel} sudah direservasi outbound. "
                f"Fisik {channel_physical:g}, reservasi {channel_reserved:g}, pengurangan diminta {qty:g}."
            ),
        )


@router.post("/stock-damage-discoveries")
async def guarded_stock_damage_with_reservations(
    body: DamageDiscoveryInput,
    request: Request,
    user: dict = Depends(require_write),
):
    async def action():
        product = await db.products.find_one({"id": body.productId}, {"_id": 0})
        if not product:
            raise HTTPException(status_code=404, detail="Produk tidak ditemukan")
        channel = normalize_channel(body.channel, normalize_channel(product.get("channel")))
        stack_code = body.stackCode.strip().upper()
        await _validate_good_stock_reduction(product, body.productId, channel, stack_code, float(body.qty))
        result = await record_stock_damage_discovery(body, user)
        transaction = result.get("transaction") or {}
        if transaction.get("id"):
            await db.transactions.update_one({"id": transaction["id"]}, {"$set": {"product_id": body.productId}})
            transaction["product_id"] = body.productId
        return result

    return await idempotent_operation(
        request,
        user,
        "damage-discovery",
        product_lock_keys([body.productId]),
        action,
    )


@router.post("/supplier-returns")
async def guarded_supplier_return_with_reservations(
    body: SupplierReturnInput,
    request: Request,
    user: dict = Depends(require_write),
):
    async def action():
        await _bind_supplier_return(body)
        product = await db.products.find_one({"id": body.productId}, {"_id": 0})
        if not product:
            raise HTTPException(status_code=404, detail="Produk tidak ditemukan")
        channel = normalize_channel(body.channel, normalize_channel(product.get("channel")))
        await _validate_damaged_stock_reduction(product, body.productId, channel, float(body.qty))
        result = await create_supplier_return(body, user)
        if result.get("id"):
            await db.transactions.update_many(
                {"operation_id": result["id"]},
                {"$set": {"product_id": body.productId}},
            )
        return result

    return await idempotent_operation(
        request,
        user,
        "supplier-return",
        product_lock_keys([body.productId]),
        action,
    )
