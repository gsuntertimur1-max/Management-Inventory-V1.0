from __future__ import annotations

import os
import re
from collections import defaultdict
from typing import List, Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from backend.server import db, get_current_user, new_id, normalize_channel, now_iso
from backend.role_four_config import has_role_permission, role_destination
import backend.consignment_operations as operations

router = APIRouter(prefix="/api")
ECOM = operations.ECOM
EPS = operations.EPS
SUPPORTED_PROVIDERS = {"Shopee", "Tokopedia & Shop", "TikTok Shop", "Other"}


def _n(value) -> float:
    return operations._n(value)


def _ensure_ecom_access(user: dict, write: bool = False) -> None:
    scoped = role_destination(user.get("role"))
    if scoped and scoped != ECOM:
        raise HTTPException(status_code=403, detail=f"Akun ini hanya memiliki akses ke {scoped}")
    permission = "ecomOps" if write else "ecomView"
    if not has_role_permission(user.get("role"), permission):
        raise HTTPException(status_code=403, detail="Tidak memiliki akses Marketplace E-commerce")


def _provider_key(provider: str) -> str:
    normalized = re.sub(r"[^A-Z0-9]+", "_", str(provider or "").upper()).strip("_")
    return normalized or "OTHER"


def _webhook_secret(provider: str) -> str:
    provider_key = _provider_key(provider)
    return os.getenv(f"MARKETPLACE_WEBHOOK_KEY_{provider_key}", "") or os.getenv("MARKETPLACE_WEBHOOK_KEY", "")


async def _log(
    *,
    level: str,
    event_type: str,
    provider: str = "",
    account_id: str = "",
    reference: str = "",
    message: str = "",
    payload: dict | None = None,
) -> None:
    await db.marketplace_sync_logs.insert_one({
        "id": new_id(),
        "time": now_iso(),
        "level": level,
        "eventType": event_type,
        "provider": provider,
        "accountId": account_id,
        "reference": reference,
        "message": message,
        "payload": payload or {},
    })


class MarketplaceAccountBody(BaseModel):
    provider: Literal["Shopee", "Tokopedia & Shop", "TikTok Shop", "Other"]
    shopName: str
    shopId: str = ""
    connectionMode: Literal["API", "Middleware", "Manual"] = "API"
    active: bool = True
    note: str = ""


class MarketplaceAccountUpdate(BaseModel):
    shopName: str | None = None
    shopId: str | None = None
    connectionMode: Literal["API", "Middleware", "Manual"] | None = None
    active: bool | None = None
    note: str | None = None


class SkuMappingBody(BaseModel):
    accountId: str
    productId: str
    marketplaceSku: str
    listingId: str = ""
    active: bool = True


class NormalizedMarketplaceItem(BaseModel):
    marketplaceSku: str
    qty: float = Field(gt=0)


class NormalizedMarketplaceEvent(BaseModel):
    eventId: str
    eventType: Literal["ORDER_CREATED", "ORDER_CANCELLED", "ORDER_PACKING", "ORDER_SHIPPED"]
    accountId: str
    orderNo: str
    buyer: str = ""
    trackingNo: str = ""
    items: List[NormalizedMarketplaceItem] = Field(default_factory=list)
    occurredAt: str = ""
    raw: dict = Field(default_factory=dict)


@router.get("/marketplace/accounts")
async def list_marketplace_accounts(user: dict = Depends(get_current_user)):
    _ensure_ecom_access(user, write=False)
    rows = await db.marketplace_accounts.find({}, {"_id": 0}).sort([("provider", 1), ("shopName", 1)]).to_list(5000)
    return [{**row, "gatewayConfigured": bool(_webhook_secret(row.get("provider", "")))} for row in rows]


@router.get("/marketplace/products")
async def marketplace_products(user: dict = Depends(get_current_user)):
    _ensure_ecom_access(user, write=False)
    rows = await db.products.find({}, {"_id": 0, "id": 1, "sku": 1, "name": 1, "unit": 1, "channel": 1}).sort("name", 1).to_list(20000)
    return rows


@router.post("/marketplace/accounts")
async def create_marketplace_account(body: MarketplaceAccountBody, user: dict = Depends(get_current_user)):
    _ensure_ecom_access(user, write=True)
    shop_name = body.shopName.strip()
    if not shop_name:
        raise HTTPException(status_code=400, detail="Nama toko wajib diisi")
    provider = body.provider
    duplicate = await db.marketplace_accounts.find_one(
        {"provider": provider, "shopId": body.shopId.strip(), "shopName": shop_name},
        {"_id": 0},
    )
    if duplicate:
        return duplicate

    doc = {
        "id": new_id(),
        "provider": provider,
        "shopName": shop_name,
        "shopId": body.shopId.strip(),
        "connectionMode": body.connectionMode,
        "connectionStatus": "NOT_CONNECTED",
        "active": body.active,
        "note": body.note.strip(),
        "credentialSource": "RAILWAY_ENV",
        "credentialEnvPrefix": f"MARKETPLACE_{_provider_key(provider)}",
        "lastSyncAt": "",
        "lastSyncStatus": "NEVER",
        "createdAt": now_iso(),
        "createdBy": user.get("name", ""),
    }
    await db.marketplace_accounts.insert_one(dict(doc))
    await _log(
        level="INFO",
        event_type="ACCOUNT_CREATED",
        provider=provider,
        account_id=doc["id"],
        reference=shop_name,
        message="Akun marketplace dibuat. Kredensial API belum terhubung dan harus disimpan di environment Railway.",
    )
    return doc


@router.patch("/marketplace/accounts/{account_id}")
async def update_marketplace_account(account_id: str, body: MarketplaceAccountUpdate, user: dict = Depends(get_current_user)):
    _ensure_ecom_access(user, write=True)
    current = await db.marketplace_accounts.find_one({"id": account_id}, {"_id": 0})
    if not current:
        raise HTTPException(status_code=404, detail="Akun marketplace tidak ditemukan")
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if "shopName" in patch:
        patch["shopName"] = str(patch["shopName"]).strip()
        if not patch["shopName"]:
            raise HTTPException(status_code=400, detail="Nama toko tidak boleh kosong")
    if "shopId" in patch:
        patch["shopId"] = str(patch["shopId"]).strip()
    if "note" in patch:
        patch["note"] = str(patch["note"]).strip()
    patch["updatedAt"] = now_iso()
    patch["updatedBy"] = user.get("name", "")
    await db.marketplace_accounts.update_one({"id": account_id}, {"$set": patch})
    return await db.marketplace_accounts.find_one({"id": account_id}, {"_id": 0})


@router.get("/marketplace/sku-mappings")
async def list_sku_mappings(accountId: str = "", user: dict = Depends(get_current_user)):
    _ensure_ecom_access(user, write=False)
    query = {"accountId": accountId} if accountId else {}
    return await db.marketplace_sku_mappings.find(query, {"_id": 0}).sort([("accountId", 1), ("marketplaceSku", 1)]).to_list(20000)


@router.post("/marketplace/sku-mappings")
async def upsert_sku_mapping(body: SkuMappingBody, user: dict = Depends(get_current_user)):
    _ensure_ecom_access(user, write=True)
    account = await db.marketplace_accounts.find_one({"id": body.accountId}, {"_id": 0})
    if not account:
        raise HTTPException(status_code=404, detail="Akun marketplace tidak ditemukan")
    product = await db.products.find_one({"id": body.productId}, {"_id": 0})
    if not product:
        raise HTTPException(status_code=404, detail="Produk internal tidak ditemukan")
    marketplace_sku = body.marketplaceSku.strip()
    if not marketplace_sku:
        raise HTTPException(status_code=400, detail="SKU marketplace wajib diisi")

    now = now_iso()
    existing = await db.marketplace_sku_mappings.find_one(
        {"accountId": body.accountId, "marketplaceSku": marketplace_sku},
        {"_id": 0},
    )
    mapping_id = (existing or {}).get("id") or new_id()
    doc = {
        "id": mapping_id,
        "accountId": body.accountId,
        "provider": account.get("provider", ""),
        "shopName": account.get("shopName", ""),
        "productId": body.productId,
        "internalSku": product.get("sku", ""),
        "productName": product.get("name", ""),
        "unit": product.get("unit", ""),
        "marketplaceSku": marketplace_sku,
        "listingId": body.listingId.strip(),
        "active": body.active,
        "updatedAt": now,
        "updatedBy": user.get("name", ""),
    }
    if not existing:
        doc["createdAt"] = now
    await db.marketplace_sku_mappings.update_one(
        {"accountId": body.accountId, "marketplaceSku": marketplace_sku},
        {"$set": doc},
        upsert=True,
    )
    await _log(
        level="INFO",
        event_type="SKU_MAPPING_UPDATED",
        provider=account.get("provider", ""),
        account_id=body.accountId,
        reference=marketplace_sku,
        message=f"{marketplace_sku} → {product.get('sku', '')} {product.get('name', '')}",
    )
    return await db.marketplace_sku_mappings.find_one({"id": mapping_id}, {"_id": 0})


@router.get("/marketplace/stock-preview")
async def marketplace_stock_preview(accountId: str = "", user: dict = Depends(get_current_user)):
    _ensure_ecom_access(user, write=False)
    query = {"active": True}
    if accountId:
        query["accountId"] = accountId
    mappings = await db.marketplace_sku_mappings.find(query, {"_id": 0}).to_list(20000)
    result = []
    for mapping in mappings:
        physical, reserved, available = await operations._available(ECOM, mapping["productId"])
        result.append({
            **mapping,
            "physicalQty": physical,
            "reservedQty": reserved,
            "availableQty": available,
            "recommendedMarketplaceQty": available,
        })
    return result


@router.post("/marketplace/accounts/{account_id}/sync-preview")
async def create_sync_preview(account_id: str, user: dict = Depends(get_current_user)):
    _ensure_ecom_access(user, write=True)
    account = await db.marketplace_accounts.find_one({"id": account_id}, {"_id": 0})
    if not account:
        raise HTTPException(status_code=404, detail="Akun marketplace tidak ditemukan")
    mappings = await db.marketplace_sku_mappings.find({"accountId": account_id, "active": True}, {"_id": 0}).to_list(20000)
    rows = []
    for mapping in mappings:
        physical, reserved, available = await operations._available(ECOM, mapping["productId"])
        rows.append({
            "marketplaceSku": mapping.get("marketplaceSku", ""),
            "internalSku": mapping.get("internalSku", ""),
            "productName": mapping.get("productName", ""),
            "physicalQty": physical,
            "reservedQty": reserved,
            "availableQty": available,
            "wouldPushQty": available,
        })
    await db.marketplace_accounts.update_one(
        {"id": account_id},
        {"$set": {
            "lastSyncAt": now_iso(),
            "lastSyncStatus": "PREVIEW_ONLY",
            "connectionStatus": "NOT_CONNECTED",
        }},
    )
    await _log(
        level="INFO",
        event_type="STOCK_SYNC_PREVIEW",
        provider=account.get("provider", ""),
        account_id=account_id,
        reference=account.get("shopName", ""),
        message=f"Preview sinkron stok dibuat untuk {len(rows)} SKU. Tidak ada data yang dikirim ke marketplace.",
        payload={"rows": rows},
    )
    return {"account": account, "rows": rows, "mode": "PREVIEW_ONLY"}


@router.get("/marketplace/sync-logs")
async def list_sync_logs(accountId: str = "", limit: int = 500, user: dict = Depends(get_current_user)):
    _ensure_ecom_access(user, write=False)
    query = {"accountId": accountId} if accountId else {}
    safe_limit = min(max(int(limit or 500), 1), 5000)
    return await db.marketplace_sync_logs.find(query, {"_id": 0}).sort("time", -1).to_list(safe_limit)


async def _mapping_for_event(account_id: str, marketplace_sku: str) -> dict:
    mapping = await db.marketplace_sku_mappings.find_one(
        {"accountId": account_id, "marketplaceSku": marketplace_sku, "active": True},
        {"_id": 0},
    )
    if not mapping:
        raise HTTPException(status_code=409, detail=f"SKU marketplace belum dipetakan: {marketplace_sku}")
    return mapping


async def _normalized_items(account_id: str, items: list[NormalizedMarketplaceItem]) -> list[dict]:
    grouped = defaultdict(float)
    for item in items:
        mapping = await _mapping_for_event(account_id, item.marketplaceSku)
        grouped[mapping["productId"]] += float(item.qty)

    result = []
    for product_id, qty in grouped.items():
        identity = await operations._identity(ECOM, product_id)
        result.append({
            "productId": product_id,
            "sku": identity.get("sku", ""),
            "name": identity.get("name", ""),
            "unit": identity.get("unit", ""),
            "channel": normalize_channel(identity.get("channel"), "KOM"),
            "qty": qty,
        })
    return result


async def _apply_order_created(account: dict, body: NormalizedMarketplaceEvent) -> dict:
    existing = await db.ecom_orders.find_one(
        {"marketplaceAccountId": body.accountId, "orderNo": body.orderNo},
        {"_id": 0},
    )
    if existing:
        return existing

    items = await _normalized_items(body.accountId, body.items)
    if not items:
        raise HTTPException(status_code=400, detail="Order tidak memiliki item")

    for item in items:
        _, _, available = await operations._available(ECOM, item["productId"])
        if item["qty"] > available + EPS:
            raise HTTPException(
                status_code=409,
                detail=f"Stok E-commerce {item.get('name', '')} tersedia hanya {available:g} {item.get('unit', '')}",
            )

    now = now_iso()
    order = {
        "id": new_id(),
        "marketplace": (account.get("provider", "") + " / " + account.get("shopName", "")).strip(" /"),
        "marketplaceAccountId": body.accountId,
        "shopName": account.get("shopName", ""),
        "orderNo": body.orderNo.strip(),
        "buyer": body.buyer.strip(),
        "items": items,
        "status": "RESERVED",
        "trackingNo": body.trackingNo.strip(),
        "note": "Dibuat otomatis dari Marketplace Gateway",
        "source": "MARKETPLACE_GATEWAY",
        "externalEventId": body.eventId,
        "createdAt": now,
        "createdBy": "Marketplace Gateway",
    }
    await db.ecom_orders.insert_one(dict(order))
    await operations._history(
        ECOM,
        "ECOM_RESERVED",
        order["id"],
        f"{account.get('provider', '')} / {account.get('shopName', '')}/{body.orderNo}",
        "Marketplace Gateway",
        items,
        "Order otomatis dari marketplace",
        {"marketplace": account.get("provider", ""), "accountId": body.accountId},
    )
    return order


async def _apply_status_event(account: dict, body: NormalizedMarketplaceEvent) -> dict:
    order = await db.ecom_orders.find_one(
        {"marketplaceAccountId": body.accountId, "orderNo": body.orderNo},
        {"_id": 0},
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order marketplace belum ada di Inventory")

    target = {
        "ORDER_PACKING": "PACKING",
        "ORDER_CANCELLED": "CANCELLED",
        "ORDER_SHIPPED": "SHIPPED",
    }[body.eventType]
    current = order.get("status", "RESERVED")
    if current == target:
        return order
    allowed = {"RESERVED": {"PACKING", "CANCELLED", "SHIPPED"}, "PACKING": {"SHIPPED", "CANCELLED"}}
    if target not in allowed.get(current, set()):
        raise HTTPException(status_code=409, detail=f"Status order {current} tidak dapat diubah menjadi {target}")

    now = now_iso()
    if target == "SHIPPED":
        for item in order.get("items", []):
            event_key = f"marketplace-ship:{order['id']}:{item['productId']}"
            movement = {
                "id": new_id(),
                "eventKey": event_key,
                "time": now,
                "destination": ECOM,
                "movementType": "ECOM_DIKIRIM",
                "referenceId": order["id"],
                "referenceNo": order.get("orderNo", ""),
                "productId": item["productId"],
                "sku": item.get("sku", ""),
                "name": item.get("name", ""),
                "unit": item.get("unit", ""),
                "channel": item.get("channel", "KOM"),
                "delta": -_n(item.get("qty")),
                "operator": "Marketplace Gateway",
            }
            await db.consignment_movements.update_one({"eventKey": event_key}, {"$setOnInsert": movement}, upsert=True)

    patch = {
        "status": target,
        "updatedAt": now,
        "updatedBy": "Marketplace Gateway",
    }
    if body.trackingNo.strip():
        patch["trackingNo"] = body.trackingNo.strip()
    if target == "SHIPPED":
        patch["shippedAt"] = now
    if target == "CANCELLED":
        patch["cancelledAt"] = now
    await db.ecom_orders.update_one({"id": order["id"]}, {"$set": patch})
    updated = await db.ecom_orders.find_one({"id": order["id"]}, {"_id": 0})
    await operations._history(
        ECOM,
        f"ECOM_{target}",
        order["id"],
        f"{account.get('provider', '')}/{body.orderNo}",
        "Marketplace Gateway",
        order.get("items", []),
        "Status otomatis dari marketplace",
        {"fromStatus": current, "toStatus": target, "accountId": body.accountId},
    )
    return updated


@router.post("/marketplace/gateway/{provider}/events")
async def marketplace_gateway_event(
    provider: str,
    body: NormalizedMarketplaceEvent,
    x_marketplace_webhook_key: str = Header(default="", alias="X-Marketplace-Webhook-Key"),
):
    account = await db.marketplace_accounts.find_one({"id": body.accountId}, {"_id": 0})
    if not account:
        raise HTTPException(status_code=404, detail="Akun marketplace tidak ditemukan")
    if _provider_key(account.get("provider", "")) != _provider_key(provider):
        raise HTTPException(status_code=400, detail="Provider event tidak sesuai akun marketplace")
    if not account.get("active", True):
        raise HTTPException(status_code=409, detail="Akun marketplace sedang nonaktif")

    expected = _webhook_secret(provider)
    if not expected:
        raise HTTPException(status_code=503, detail="Marketplace Gateway belum diaktifkan di environment Railway")
    if not x_marketplace_webhook_key or x_marketplace_webhook_key != expected:
        raise HTTPException(status_code=401, detail="Signature/key Marketplace Gateway tidak valid")

    event_key = f"{provider}:{body.accountId}:{body.eventId}"
    existing = await db.marketplace_webhook_events.find_one({"eventKey": event_key}, {"_id": 0})
    if existing and existing.get("status") == "PROCESSED":
        return {"ok": True, "duplicate": True, "eventId": body.eventId}

    event_doc = {
        "id": (existing or {}).get("id") or new_id(),
        "eventKey": event_key,
        "provider": provider,
        "accountId": body.accountId,
        "eventId": body.eventId,
        "eventType": body.eventType,
        "orderNo": body.orderNo,
        "receivedAt": now_iso(),
        "status": "RECEIVED",
        "payload": body.model_dump(),
    }
    await db.marketplace_webhook_events.update_one({"eventKey": event_key}, {"$set": event_doc}, upsert=True)

    try:
        if body.eventType == "ORDER_CREATED":
            result = await _apply_order_created(account, body)
        else:
            result = await _apply_status_event(account, body)

        await db.marketplace_webhook_events.update_one(
            {"eventKey": event_key},
            {"$set": {"status": "PROCESSED", "processedAt": now_iso(), "resultId": result.get("id", "")}},
        )
        await _log(
            level="INFO",
            event_type=f"WEBHOOK_{body.eventType}",
            provider=provider,
            account_id=body.accountId,
            reference=body.orderNo,
            message="Event marketplace diproses oleh gateway.",
            payload={"eventId": body.eventId, "orderId": result.get("id", "")},
        )
        return {"ok": True, "duplicate": False, "eventId": body.eventId, "order": result}
    except HTTPException as exc:
        await db.marketplace_webhook_events.update_one(
            {"eventKey": event_key},
            {"$set": {"status": "FAILED", "failedAt": now_iso(), "error": str(exc.detail)}},
        )
        await _log(
            level="ERROR",
            event_type=f"WEBHOOK_{body.eventType}_FAILED",
            provider=provider,
            account_id=body.accountId,
            reference=body.orderNo,
            message=str(exc.detail),
            payload={"eventId": body.eventId},
        )
        raise


@router.get("/marketplace/webhook-events")
async def list_webhook_events(accountId: str = "", status: str = "", user: dict = Depends(get_current_user)):
    _ensure_ecom_access(user, write=False)
    query = {}
    if accountId:
        query["accountId"] = accountId
    if status:
        query["status"] = status
    return await db.marketplace_webhook_events.find(query, {"_id": 0, "payload.raw": 0}).sort("receivedAt", -1).to_list(5000)


async def ensure_marketplace_indexes() -> None:
    await db.marketplace_accounts.create_index([("provider", 1), ("shopId", 1), ("shopName", 1)], name="marketplace_account_identity")
    await db.marketplace_sku_mappings.create_index([("accountId", 1), ("marketplaceSku", 1)], unique=True, name="marketplace_sku_unique")
    await db.marketplace_sku_mappings.create_index([("accountId", 1), ("productId", 1)], name="marketplace_product_lookup")
    await db.marketplace_sync_logs.create_index([("accountId", 1), ("time", -1)], name="marketplace_sync_log")
    await db.marketplace_webhook_events.create_index("eventKey", unique=True, name="marketplace_webhook_event_unique")
    await db.marketplace_webhook_events.create_index([("accountId", 1), ("receivedAt", -1)], name="marketplace_webhook_account")
