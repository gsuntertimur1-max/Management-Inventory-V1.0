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
import backend.consignment as consignment_module
from backend.operational_guards import operation_guard, lock_keys

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


def _credential_env_key(provider: str) -> str:
    key = _provider_key(provider)
    if key in {"TOKOPEDIA_SHOP", "TIKTOK_SHOP"}:
        return "TIKTOK_SHOP"
    return key


def _provider_env(provider: str, *names: str) -> str:
    prefix = f"MARKETPLACE_{_credential_env_key(provider)}"
    for name in names:
        value = os.getenv(f"{prefix}_{name}", "").strip()
        if value:
            return value
    return ""


def _connection_env_status(provider: str) -> dict:
    client_id = _provider_env(provider, "APP_KEY", "APP_ID", "CLIENT_ID", "PARTNER_ID")
    client_secret = _provider_env(provider, "APP_SECRET", "CLIENT_SECRET", "PARTNER_KEY")
    access_token = _provider_env(provider, "ACCESS_TOKEN")
    refresh_token = _provider_env(provider, "REFRESH_TOKEN")
    auth_url = _provider_env(provider, "AUTH_URL", "AUTH_URL_TEMPLATE")
    return {
        "clientConfigured": bool(client_id),
        "secretConfigured": bool(client_secret),
        "tokenConfigured": bool(access_token),
        "refreshTokenConfigured": bool(refresh_token),
        "authUrlConfigured": bool(auth_url),
        "gatewayConfigured": bool(_webhook_secret(provider)),
        "readyForAuthorization": bool(client_id and client_secret),
    }


def _ensure_marketplace_settings(user: dict) -> None:
    if not has_role_permission(user.get("role"), "settings"):
        raise HTTPException(status_code=403, detail="Hanya Superadmin yang dapat mengubah Integrasi Marketplace")


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
    _ensure_marketplace_settings(user)
    rows = await db.marketplace_accounts.find({}, {"_id": 0}).sort([("provider", 1), ("shopName", 1)]).to_list(5000)
    token_docs = await db.marketplace_tokens.find({}, {
        "_id": 0, "accountId": 1, "expiresAt": 1, "hasRefreshToken": 1,
        "grantedScopes": 1, "updatedAt": 1
    }).to_list(5000)
    token_map = {row.get("accountId"): row for row in token_docs}
    result = []
    for row in rows:
        token = token_map.get(row.get("id"), {})
        env_status = _connection_env_status(row.get("provider", ""))
        result.append({
            **row,
            **env_status,
            "tokenConfigured": bool(token) or env_status["tokenConfigured"],
            "storedToken": bool(token),
            "storedRefreshToken": bool(token.get("hasRefreshToken")),
            "tokenExpiresAt": token.get("expiresAt", row.get("tokenExpiresAt", "")),
            "grantedScopes": token.get("grantedScopes", row.get("grantedScopes", [])),
            "credentialFamily": _credential_env_key(row.get("provider", "")),
        })
    return result


@router.get("/marketplace/products")
async def marketplace_products(user: dict = Depends(get_current_user)):
    _ensure_marketplace_settings(user)
    rows = await db.products.find({}, {"_id": 0, "id": 1, "sku": 1, "name": 1, "unit": 1, "channel": 1}).sort("name", 1).to_list(20000)
    return rows


@router.post("/marketplace/accounts")
async def create_marketplace_account(body: MarketplaceAccountBody, user: dict = Depends(get_current_user)):
    _ensure_marketplace_settings(user)
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
        "credentialEnvPrefix": f"MARKETPLACE_{_credential_env_key(provider)}",
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
    _ensure_marketplace_settings(user)
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



@router.post("/marketplace/accounts/{account_id}/connect")
async def connect_marketplace_account(account_id: str, user: dict = Depends(get_current_user)):
    _ensure_marketplace_settings(user)
    account = await db.marketplace_accounts.find_one({"id": account_id}, {"_id": 0})
    if not account:
        raise HTTPException(status_code=404, detail="Akun marketplace tidak ditemukan")
    if not account.get("active", True):
        raise HTTPException(status_code=409, detail="Aktifkan akun marketplace terlebih dahulu")

    provider = account.get("provider", "")
    env_status = _connection_env_status(provider)
    now = now_iso()

    if account.get("connectionMode") == "Manual":
        await db.marketplace_accounts.update_one(
            {"id": account_id},
            {"$set": {"connectionStatus": "CONNECTED_MANUAL", "connectedAt": now, "updatedAt": now, "updatedBy": user.get("name", "")}},
        )
        await _log(level="INFO", event_type="ACCOUNT_CONNECTED_MANUAL", provider=provider, account_id=account_id,
                   reference=account.get("shopName", ""), message="Akun ditandai terhubung dalam mode Manual.")
        return {"status": "CONNECTED_MANUAL", "authorizationUrl": "", "env": env_status}

    if not env_status["readyForAuthorization"]:
        raise HTTPException(
            status_code=409,
            detail=f"Kredensial {provider} belum lengkap di Railway Variables. App/Client/Partner ID dan Secret/Key wajib tersedia.",
        )

    if env_status["tokenConfigured"]:
        await db.marketplace_accounts.update_one(
            {"id": account_id},
            {"$set": {"connectionStatus": "CONNECTED", "connectedAt": now, "updatedAt": now, "updatedBy": user.get("name", "")}},
        )
        await _log(level="INFO", event_type="ACCOUNT_CONNECTED", provider=provider, account_id=account_id,
                   reference=account.get("shopName", ""), message="Token marketplace terdeteksi dari Railway environment.")
        return {"status": "CONNECTED", "authorizationUrl": "", "env": env_status}

    auth_template = _provider_env(provider, "AUTH_URL_TEMPLATE", "AUTH_URL")
    if auth_template:
        authorization_url = auth_template.replace("{account_id}", account_id).replace("{shop_id}", str(account.get("shopId", "")))
        await db.marketplace_accounts.update_one(
            {"id": account_id},
            {"$set": {"connectionStatus": "AUTHORIZATION_REQUIRED", "updatedAt": now, "updatedBy": user.get("name", "")}},
        )
        await _log(level="INFO", event_type="AUTHORIZATION_STARTED", provider=provider, account_id=account_id,
                   reference=account.get("shopName", ""), message="Authorization URL disiapkan dari Railway environment.")
        return {"status": "AUTHORIZATION_REQUIRED", "authorizationUrl": authorization_url, "env": env_status}

    await db.marketplace_accounts.update_one(
        {"id": account_id},
        {"$set": {"connectionStatus": "CREDENTIALS_READY", "updatedAt": now, "updatedBy": user.get("name", "")}},
    )
    return {
        "status": "CREDENTIALS_READY",
        "authorizationUrl": "",
        "env": env_status,
        "message": "Kredensial dasar sudah tersedia. Tambahkan AUTH_URL_TEMPLATE atau ACCESS_TOKEN pada Railway untuk menyelesaikan koneksi.",
    }


@router.post("/marketplace/accounts/{account_id}/disconnect")
async def disconnect_marketplace_account(account_id: str, user: dict = Depends(get_current_user)):
    _ensure_marketplace_settings(user)
    account = await db.marketplace_accounts.find_one({"id": account_id}, {"_id": 0})
    if not account:
        raise HTTPException(status_code=404, detail="Akun marketplace tidak ditemukan")
    now = now_iso()
    await db.marketplace_tokens.delete_many({"accountId": account_id})
    await db.marketplace_auth_sessions.delete_many({"accountId": account_id})
    await db.marketplace_accounts.update_one(
        {"id": account_id},
        {"$set": {
            "connectionStatus": "NOT_CONNECTED", "disconnectedAt": now, "updatedAt": now,
            "updatedBy": user.get("name", ""), "tokenStored": False,
            "refreshTokenStored": False, "tokenExpiresAt": "",
        }},
    )
    await _log(level="INFO", event_type="ACCOUNT_DISCONNECTED", provider=account.get("provider", ""), account_id=account_id,
               reference=account.get("shopName", ""), message="Koneksi marketplace dinonaktifkan di Inventory. Secret Railway tidak dihapus.")
    return {"status": "NOT_CONNECTED"}


@router.get("/marketplace/sku-mappings")
async def list_sku_mappings(accountId: str = "", user: dict = Depends(get_current_user)):
    _ensure_marketplace_settings(user)
    query = {"accountId": accountId} if accountId else {}
    return await db.marketplace_sku_mappings.find(query, {"_id": 0}).sort([("accountId", 1), ("marketplaceSku", 1)]).to_list(20000)


@router.post("/marketplace/sku-mappings")
async def upsert_sku_mapping(body: SkuMappingBody, user: dict = Depends(get_current_user)):
    _ensure_marketplace_settings(user)
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
    _ensure_marketplace_settings(user)
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
    _ensure_marketplace_settings(user)
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
    _ensure_marketplace_settings(user)
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


async def _apply_order_created(account: dict, body: NormalizedMarketplaceEvent, normalized_items: list[dict] | None = None) -> dict:
    existing = await db.ecom_orders.find_one(
        {"marketplaceAccountId": body.accountId, "orderNo": body.orderNo},
        {"_id": 0},
    )
    if existing:
        return existing

    items = normalized_items if normalized_items is not None else await _normalized_items(body.accountId, body.items)
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
    movement_keys: list[str] = []
    synced_products: set[str] = set()
    operation_id = f"marketplace-event:{body.accountId}:{body.eventId}"
    order_updated = False
    history_saved = False

    try:
        if target == "SHIPPED":
            # Marketplace shipment must mutate the same physical E-commerce
            # subledger used by manual orders. First repair any legacy location,
            # then write the movement and reconcile the physical layouts to it.
            for item in order.get("items", []):
                product_id = str(item.get("productId") or "")
                if not product_id:
                    continue
                await consignment_module.sync_consignment_layout_balance(
                    ECOM,
                    product_id,
                    operator="Marketplace Gateway",
                    operation_key=f"{operation_id}:pre:{product_id}",
                    note="Validasi lokasi fisik sebelum order marketplace dikirim.",
                )

                event_key = f"ecom-ship:{order['id']}:{product_id}"
                movement = {
                    "id": new_id(),
                    "eventKey": event_key,
                    "operationId": operation_id,
                    "time": now,
                    "destination": ECOM,
                    "movementType": "ECOM_DIKIRIM",
                    "referenceId": order["id"],
                    "referenceNo": order.get("orderNo", ""),
                    "productId": product_id,
                    "sku": item.get("sku", ""),
                    "name": item.get("name", ""),
                    "unit": item.get("unit", ""),
                    "channel": item.get("channel", "KOM"),
                    "delta": -_n(item.get("qty")),
                    "operator": "Marketplace Gateway",
                    "source": "MARKETPLACE_GATEWAY",
                    "marketplaceAccountId": body.accountId,
                    "externalEventId": body.eventId,
                }
                existing_movement = await db.consignment_movements.find_one({"eventKey": event_key}, {"_id": 0})
                if existing_movement:
                    # A completed order would already have returned above. Finding
                    # a movement here means an earlier attempt was interrupted.
                    raise HTTPException(
                        status_code=409,
                        detail="Pengiriman marketplace memiliki movement tertinggal. Jalankan Kontrol Integritas sebelum retry.",
                    )
                await db.consignment_movements.insert_one(dict(movement))
                movement_keys.append(event_key)
                synced_products.add(product_id)

            for product_id in sorted(synced_products):
                await consignment_module.sync_consignment_layout_balance(
                    ECOM,
                    product_id,
                    operator="Marketplace Gateway",
                    operation_key=f"{operation_id}:ship:{product_id}",
                    note=f"Pengurangan lokasi fisik untuk order marketplace {order.get('orderNo', '')}.",
                )

        patch = {
            "status": target,
            "updatedAt": now,
            "updatedBy": "Marketplace Gateway",
            "lastMarketplaceEventId": body.eventId,
        }
        if body.trackingNo.strip():
            patch["trackingNo"] = body.trackingNo.strip()
        if target == "SHIPPED":
            patch["shippedAt"] = now
        if target == "CANCELLED":
            patch["cancelledAt"] = now

        result = await db.ecom_orders.update_one(
            {"id": order["id"], "status": current},
            {"$set": patch},
        )
        if result.matched_count == 0:
            raise HTTPException(status_code=409, detail="Status order berubah saat event marketplace diproses")
        order_updated = True

        await operations._history(
            ECOM,
            f"ECOM_{target}",
            order["id"],
            f"{account.get('provider', '')}/{body.orderNo}",
            "Marketplace Gateway",
            order.get("items", []),
            "Status otomatis dari marketplace",
            {
                "fromStatus": current,
                "toStatus": target,
                "accountId": body.accountId,
                "externalEventId": body.eventId,
                "operationId": operation_id,
            },
        )
        history_saved = True
        return await db.ecom_orders.find_one({"id": order["id"]}, {"_id": 0})

    except Exception:
        if history_saved:
            await db.consignment_operation_history.delete_many({"operationId": operation_id})
        if order_updated:
            await db.ecom_orders.replace_one({"id": order["id"]}, dict(order), upsert=False)
        if movement_keys:
            await db.consignment_movements.delete_many({"eventKey": {"$in": movement_keys}})
        for product_id in sorted(synced_products):
            try:
                await consignment_module.sync_consignment_layout_balance(
                    ECOM,
                    product_id,
                    operator="Sistem (rollback marketplace)",
                    operation_key=f"{operation_id}:rollback:{product_id}",
                    note="Rollback event marketplace yang tidak selesai.",
                )
            except Exception:
                pass
        raise


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
    order_lock = f"marketplace-order:{body.accountId}:{body.orderNo.strip().upper()}"
    normalized_items = None
    product_ids: list[str] = []

    concrete_order_lock = ""
    if body.eventType == "ORDER_CREATED":
        normalized_items = await _normalized_items(body.accountId, body.items)
        product_ids = sorted({
            str(item.get("productId") or "")
            for item in normalized_items
            if str(item.get("productId") or "")
        })
    else:
        existing_order = await db.ecom_orders.find_one(
            {"marketplaceAccountId": body.accountId, "orderNo": body.orderNo},
            {"_id": 0, "id": 1, "items": 1},
        )
        if existing_order:
            concrete_order_lock = f"ecom-order:{existing_order.get('id', '')}"
            product_ids = sorted({
                str(item.get("productId") or "")
                for item in existing_order.get("items", [])
                if str(item.get("productId") or "")
            })

    keys = lock_keys(
        [f"marketplace-event:{event_key}", order_lock, concrete_order_lock],
        (f"consignment:{ECOM}:{product_id}" for product_id in product_ids),
    )

    async with operation_guard(keys):
        existing = await db.marketplace_webhook_events.find_one({"eventKey": event_key}, {"_id": 0})
        if existing and existing.get("status") == "PROCESSED":
            return {"ok": True, "duplicate": True, "eventId": body.eventId}

        now = now_iso()
        event_doc = {
            "id": (existing or {}).get("id") or new_id(),
            "eventKey": event_key,
            "provider": provider,
            "accountId": body.accountId,
            "eventId": body.eventId,
            "eventType": body.eventType,
            "orderNo": body.orderNo,
            "receivedAt": (existing or {}).get("receivedAt") or now,
            "lastAttemptAt": now,
            "attemptCount": int((existing or {}).get("attemptCount", 0) or 0) + 1,
            "status": "RECEIVED",
            "payload": body.model_dump(),
        }
        await db.marketplace_webhook_events.update_one(
            {"eventKey": event_key},
            {"$set": event_doc, "$unset": {"failedAt": "", "error": ""}},
            upsert=True,
        )

        try:
            if body.eventType == "ORDER_CREATED":
                result = await _apply_order_created(account, body, normalized_items=normalized_items)
            else:
                result = await _apply_status_event(account, body)

            await db.marketplace_webhook_events.update_one(
                {"eventKey": event_key},
                {"$set": {
                    "status": "PROCESSED",
                    "processedAt": now_iso(),
                    "resultId": result.get("id", ""),
                }},
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
        except Exception as exc:
            await db.marketplace_webhook_events.update_one(
                {"eventKey": event_key},
                {"$set": {"status": "FAILED", "failedAt": now_iso(), "error": str(exc)[:1000]}},
            )
            await _log(
                level="ERROR",
                event_type=f"WEBHOOK_{body.eventType}_FAILED",
                provider=provider,
                account_id=body.accountId,
                reference=body.orderNo,
                message="Event marketplace gagal diproses karena error internal.",
                payload={"eventId": body.eventId, "error": str(exc)[:1000]},
            )
            raise


@router.get("/marketplace/webhook-events")
async def list_webhook_events(accountId: str = "", status: str = "", user: dict = Depends(get_current_user)):
    _ensure_marketplace_settings(user)
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
    await db.ecom_orders.create_index(
        [("marketplaceAccountId", 1), ("orderNo", 1)],
        unique=True,
        name="ecom_marketplace_order_unique",
        partialFilterExpression={"marketplaceAccountId": {"$type": "string"}},
    )
