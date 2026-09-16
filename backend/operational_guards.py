from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Iterable

from fastapi import APIRouter, Depends, HTTPException
from pymongo.errors import DuplicateKeyError, OperationFailure

from backend.server import db, new_id, require_admin, require_master_write, require_write
from backend.inventory_flow import (
    DamageDiscoveryInput,
    PurchaseOrderCancelInput,
    ReceiptInput,
    SupplierReplacementInput,
    SupplierReturnInput,
    cancel_purchase_order,
    create_supplier_return,
    receive_stock,
    receive_supplier_replacement,
    record_stock_damage_discovery,
)
from backend.outbound_flow import (
    ConsignmentReturnInput,
    DocumentCancelInput,
    OutboundCreateInput,
    OutboundEditInput,
    SalesReturnInput,
    cancel_outbound_load,
    complete_outbound_load,
    create_consignment_return,
    create_outbound_load,
    create_sales_return,
    edit_outbound_load,
)

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)
_LOCK_TTL_MINUTES = 5


def lock_keys(*groups: Iterable[str]) -> list[str]:
    values = {
        str(value or "").strip()
        for group in groups
        for value in group
        if str(value or "").strip()
    }
    return sorted(values)


def product_lock_keys(product_ids: Iterable[str]) -> list[str]:
    return lock_keys((f"product:{str(product_id).strip()}" for product_id in product_ids if str(product_id or "").strip()),)


def document_lock_keys(document_numbers: Iterable[str]) -> list[str]:
    return lock_keys((f"document:{str(number).strip().upper()}" for number in document_numbers if str(number or "").strip()),)


async def ensure_operational_guard_indexes() -> None:
    """Indexes supporting cross-worker locks and document uniqueness."""
    await db.operation_locks.create_index("expiresAt", expireAfterSeconds=0, name="operation_lock_ttl")
    for collection, keys, name in (
        (db.supplier_returns, [("return_no", 1)], "supplier_return_no_unique"),
        (db.outbound_loads, [("bon_no", 1)], "bon_no_unique"),
        (db.outbound_loads, [("operational_date", 1), ("antrian", 1)], "queue_daily_unique"),
    ):
        try:
            await collection.create_index(keys, unique=True, sparse=True, name=name)
        except OperationFailure as exc:
            logger.warning("Index unik %s belum dapat dibuat; periksa duplikasi historis: %s", name, exc)


@asynccontextmanager
async def operation_guard(keys: Iterable[str]):
    ordered = lock_keys(keys)
    if not ordered:
        yield
        return

    token = new_id()
    acquired: list[str] = []
    now = datetime.now(timezone.utc)
    await db.operation_locks.delete_many({"expiresAt": {"$lt": now}})
    try:
        for key in ordered:
            try:
                await db.operation_locks.insert_one({
                    "_id": key,
                    "token": token,
                    "createdAt": now,
                    "expiresAt": now + timedelta(minutes=_LOCK_TTL_MINUTES),
                })
                acquired.append(key)
            except DuplicateKeyError as exc:
                raise HTTPException(
                    status_code=409,
                    detail="Data yang sama sedang diproses operator lain. Muat ulang lalu coba kembali.",
                ) from exc
        yield
    finally:
        if acquired:
            await db.operation_locks.delete_many({"_id": {"$in": acquired}, "token": token})


async def _load_product_ids(load_id: str) -> tuple[dict, list[str]]:
    load = await db.outbound_loads.find_one({"id": load_id}, {"_id": 0})
    if not load:
        raise HTTPException(status_code=404, detail="Data pemuatan tidak ditemukan")
    product_ids = [item.get("productId", "") for item in load.get("items", [])]
    return load, [value for value in product_ids if value]


async def _bind_supplier_return(body: SupplierReturnInput) -> None:
    product = await db.products.find_one({"id": body.productId}, {"_id": 0})
    if not product:
        raise HTTPException(status_code=404, detail="Produk tidak ditemukan")

    source = None
    if body.sourceDamageOperationId:
        source = await db.transactions.find_one(
            {
                "operation_id": body.sourceDamageOperationId,
                "product": product.get("name", ""),
                "kondisi": "RUSAK",
            },
            {"_id": 0},
        )
        if not source:
            raise HTTPException(status_code=400, detail="Sumber barang rusak tidak ditemukan")
        if source.get("channel"):
            body.channel = str(source.get("channel") or "")
        if source.get("po_no"):
            if body.poNo.strip() and body.poNo.strip() != str(source.get("po_no")):
                raise HTTPException(status_code=400, detail="Nomor PO tidak sesuai sumber barang rusak")
            body.poNo = str(source.get("po_no") or "")

    po = None
    if body.poNo.strip():
        po = await db.purchase_orders.find_one({"no": body.poNo.strip()}, {"_id": 0})
        if not po:
            raise HTTPException(status_code=404, detail="PO sumber retur tidak ditemukan")
        if not any(item.get("productId") == body.productId for item in po.get("items", [])):
            raise HTTPException(status_code=400, detail="Produk retur tidak terdapat pada PO sumber")

    supplier = (
        body.supplier.strip()
        or str((po or {}).get("supplier") or "").strip()
        or str((source or {}).get("penerima") or "").strip()
        or str(product.get("supplier") or "").strip()
    )
    if not supplier:
        raise HTTPException(status_code=400, detail="Supplier retur wajib dipilih")
    if po and supplier != str(po.get("supplier") or "").strip():
        raise HTTPException(status_code=400, detail="Supplier retur tidak sesuai dengan PO sumber")
    if not await db.suppliers.find_one({"name": supplier}, {"_id": 1}):
        raise HTTPException(status_code=404, detail="Supplier retur tidak terdaftar pada master supplier")
    body.supplier = supplier


def surat_jalan_with_exact_locations(load: dict, surat_jalan: dict | None) -> dict | None:
    if not surat_jalan:
        return surat_jalan
    result = dict(surat_jalan)
    sj_items = [dict(item) for item in result.get("items", [])]
    load_items = load.get("items", [])
    for index, row in enumerate(sj_items):
        if index >= len(load_items):
            continue
        source = load_items[index]
        stack_code = str(source.get("stackCode") or "").strip().upper()
        row["stackCode"] = stack_code
        row["location"] = stack_code or source.get("location", "") or row.get("location", "")
    result["items"] = sj_items
    result["unit_loading"] = load.get("unit_loading", result.get("unit_loading", ""))
    return result


@router.post("/receipts")
async def guarded_receive_stock(body: ReceiptInput, user: dict = Depends(require_write)):
    keys = product_lock_keys(item.productId for item in body.items)
    if body.poId:
        keys.append(f"po:{body.poId}")
    async with operation_guard(keys):
        return await receive_stock(body, user)


@router.post("/purchase-orders-v2/{po_id}/cancel")
async def guarded_cancel_purchase_order(po_id: str, body: PurchaseOrderCancelInput, user: dict = Depends(require_master_write)):
    async with operation_guard([f"po:{po_id}"]):
        return await cancel_purchase_order(po_id, body, user)


@router.post("/stock-damage-discoveries")
async def guarded_stock_damage(body: DamageDiscoveryInput, user: dict = Depends(require_write)):
    async with operation_guard(product_lock_keys([body.productId])):
        return await record_stock_damage_discovery(body, user)


@router.post("/supplier-returns")
async def guarded_supplier_return(body: SupplierReturnInput, user: dict = Depends(require_write)):
    async with operation_guard(product_lock_keys([body.productId])):
        await _bind_supplier_return(body)
        return await create_supplier_return(body, user)


@router.post("/supplier-returns/{return_id}/replacement")
async def guarded_supplier_replacement(return_id: str, body: SupplierReplacementInput, user: dict = Depends(require_write)):
    claim = await db.supplier_returns.find_one({"id": return_id}, {"_id": 0, "product_id": 1})
    if not claim:
        raise HTTPException(status_code=404, detail="Retur pemasok tidak ditemukan")
    async with operation_guard(product_lock_keys([claim.get("product_id", "")])):
        return await receive_supplier_replacement(return_id, body, user)


@router.post("/outbound-loads")
async def guarded_create_outbound(body: OutboundCreateInput, user: dict = Depends(require_write)):
    refs = [body.ref, *body.documents]
    keys = lock_keys(
        product_lock_keys(item.productId for item in body.items),
        document_lock_keys(refs),
    )
    async with operation_guard(keys):
        return await create_outbound_load(body, user)


@router.put("/outbound-loads/{load_id}/edit")
async def guarded_edit_outbound(load_id: str, body: OutboundEditInput, user: dict = Depends(require_admin)):
    load, previous_products = await _load_product_ids(load_id)
    refs = [*load.get("documents", []), *body.documents]
    keys = lock_keys(
        product_lock_keys([*previous_products, *(item.productId for item in body.items)]),
        document_lock_keys(refs),
    )
    async with operation_guard(keys):
        return await edit_outbound_load(load_id, body, user)


@router.post("/outbound-loads/{load_id}/cancel")
async def guarded_cancel_outbound(load_id: str, body: DocumentCancelInput, user: dict = Depends(require_write)):
    _, product_ids = await _load_product_ids(load_id)
    async with operation_guard(product_lock_keys(product_ids)):
        return await cancel_outbound_load(load_id, body, user)


@router.post("/outbound-loads/{load_id}/complete")
async def guarded_complete_outbound(load_id: str, user: dict = Depends(require_write)):
    _, product_ids = await _load_product_ids(load_id)
    async with operation_guard(product_lock_keys(product_ids)):
        result = await complete_outbound_load(load_id, user)
        load = result.get("load") or await db.outbound_loads.find_one({"id": load_id}, {"_id": 0}) or {}
        sj = surat_jalan_with_exact_locations(load, result.get("suratJalan"))
        if sj and sj.get("id"):
            await db.surat_jalan.update_one(
                {"id": sj["id"]},
                {"$set": {"items": sj.get("items", []), "unit_loading": sj.get("unit_loading", "")}},
            )
            result["suratJalan"] = sj
        return result


@router.post("/outbound-loads/{load_id}/return")
async def guarded_consignment_return(load_id: str, body: ConsignmentReturnInput, user: dict = Depends(require_write)):
    async with operation_guard(product_lock_keys(item.productId for item in body.items)):
        return await create_consignment_return(load_id, body, user)


@router.post("/outbound-loads/{load_id}/sales-return")
async def guarded_sales_return(load_id: str, body: SalesReturnInput, user: dict = Depends(require_write)):
    async with operation_guard(product_lock_keys(item.productId for item in body.items)):
        return await create_sales_return(load_id, body, user)
