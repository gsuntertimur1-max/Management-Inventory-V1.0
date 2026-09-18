from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.server import db, get_current_user
from backend.operational_guards import idempotent_operation, lock_keys
from backend.consignment_operations import (
    BAZAR, ECOM, BazarTripCreate, BazarTripClose, EcomOrderCreate, EcomStatusBody, EcomReturnBody,
    create_bazar_trip, close_bazar_trip, create_ecom_order, update_ecom_status, receive_ecom_return,
)
from backend.bazar_packages import (
    PackageAssembleInput, PackageUnpackInput, PackageLoadCreate, PackageLoadClose,
    assemble_package, unpack_package, create_package_load, close_package_load,
)

router = APIRouter(prefix="/api")


def product_keys(destination: str, product_ids) -> list[str]:
    return lock_keys((f"consignment:{destination}:{str(pid).strip()}" for pid in product_ids if str(pid or "").strip()),)


@router.post("/bazar/trips")
async def guarded_create_bazar_trip(body: BazarTripCreate, request: Request, user: dict = Depends(get_current_user)):
    return await idempotent_operation(request, user, "bazar-trip-create", product_keys(BAZAR, [x.productId for x in body.items]), lambda: create_bazar_trip(body, user))


@router.post("/bazar/trips/{trip_id}/close")
async def guarded_close_bazar_trip(trip_id: str, body: BazarTripClose, request: Request, user: dict = Depends(get_current_user)):
    trip = await db.bazar_trips.find_one({"id": trip_id}, {"_id": 0})
    if not trip:
        raise HTTPException(status_code=404, detail="Perjalanan Bazar tidak ditemukan")
    keys = product_keys(BAZAR, [x.get("productId") for x in trip.get("items", [])]) + [f"bazar-trip:{trip_id}"]
    return await idempotent_operation(request, user, f"bazar-trip-close:{trip_id}", keys, lambda: close_bazar_trip(trip_id, body, user))


@router.post("/ecom/orders")
async def guarded_create_ecom_order(body: EcomOrderCreate, request: Request, user: dict = Depends(get_current_user)):
    keys = product_keys(ECOM, [x.productId for x in body.items]) + [f"ecom-order:{body.marketplace.strip().upper()}:{body.orderNo.strip().upper()}"]
    return await idempotent_operation(request, user, "ecom-order-create", keys, lambda: create_ecom_order(body, user))


async def ecom_keys(order_id: str) -> list[str]:
    order = await db.ecom_orders.find_one({"id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Pesanan E-commerce tidak ditemukan")
    return product_keys(ECOM, [x.get("productId") for x in order.get("items", [])]) + [f"ecom-order-id:{order_id}"]


@router.post("/ecom/orders/{order_id}/status")
async def guarded_update_ecom_status(order_id: str, body: EcomStatusBody, request: Request, user: dict = Depends(get_current_user)):
    return await idempotent_operation(request, user, f"ecom-status:{order_id}:{body.status}", await ecom_keys(order_id), lambda: update_ecom_status(order_id, body, user))


@router.post("/ecom/orders/{order_id}/return")
async def guarded_receive_ecom_return(order_id: str, body: EcomReturnBody, request: Request, user: dict = Depends(get_current_user)):
    return await idempotent_operation(request, user, f"ecom-return:{order_id}", await ecom_keys(order_id), lambda: receive_ecom_return(order_id, body, user))


async def template_products(template_id: str) -> list[str]:
    template = await db.bazar_package_templates.find_one({"id": template_id}, {"_id": 0, "components": 1})
    if not template:
        raise HTTPException(status_code=404, detail="Master paket tidak ditemukan")
    return [x.get("productId") for x in template.get("components", []) if x.get("productId")]


@router.post("/bazar/packages/assemble")
async def guarded_assemble_package(body: PackageAssembleInput, request: Request, user: dict = Depends(get_current_user)):
    keys = product_keys(BAZAR, await template_products(body.templateId)) + [f"bazar-package-template:{body.templateId}"]
    return await idempotent_operation(request, user, "bazar-package-assemble", keys, lambda: assemble_package(body, user))


@router.post("/bazar/package-batches/{batch_id}/unpack")
async def guarded_unpack_package(batch_id: str, body: PackageUnpackInput, request: Request, user: dict = Depends(get_current_user)):
    batch = await db.bazar_package_batches.find_one({"id": batch_id}, {"_id": 0, "templateId": 1})
    if not batch:
        raise HTTPException(status_code=404, detail="Batch paket tidak ditemukan")
    keys = [f"bazar-package-template:{batch.get('templateId', '')}", f"bazar-package-batch:{batch_id}"]
    return await idempotent_operation(request, user, f"bazar-package-unpack:{batch_id}", keys, lambda: unpack_package(batch_id, body, user))


@router.post("/bazar/package-loads")
async def guarded_create_package_load(body: PackageLoadCreate, request: Request, user: dict = Depends(get_current_user)):
    keys = lock_keys((f"bazar-package-template:{x.templateId}" for x in body.items))
    return await idempotent_operation(request, user, "bazar-package-load-create", keys, lambda: create_package_load(body, user))


@router.post("/bazar/package-loads/{load_id}/close")
async def guarded_close_package_load(load_id: str, body: PackageLoadClose, request: Request, user: dict = Depends(get_current_user)):
    load = await db.bazar_package_loads.find_one({"id": load_id}, {"_id": 0})
    if not load:
        raise HTTPException(status_code=404, detail="Pemuatan paket tidak ditemukan")
    product_ids, template_ids = [], []
    for item in load.get("items", []):
        template_ids.append(item.get("templateId", ""))
        product_ids.extend([x.get("productId") for x in item.get("components", []) if x.get("productId")])
    keys = lock_keys(product_keys(BAZAR, product_ids), (f"bazar-package-template:{x}" for x in template_ids if x), [f"bazar-package-load:{load_id}"])
    return await idempotent_operation(request, user, f"bazar-package-close:{load_id}", keys, lambda: close_package_load(load_id, body, user))
