from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlparse, parse_qsl, urlunparse

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from backend.server import JWT_SECRET, db, get_current_user, new_id, now_iso
from backend.role_four_config import has_role_permission
from backend.marketplace_integration import _log, _provider_key

router = APIRouter(prefix="/api")
AUTH_SESSION_MINUTES = 15


def _ensure_settings(user: dict) -> None:
    if not has_role_permission(user.get("role"), "settings"):
        raise HTTPException(status_code=403, detail="Hanya Superadmin yang dapat mengatur koneksi marketplace")


def _credential_key(provider: str) -> str:
    key = _provider_key(provider)
    if key in {"TOKOPEDIA_SHOP", "TIKTOK_SHOP"}:
        return "TIKTOK_SHOP"
    return key


def _env(provider: str, *names: str) -> str:
    key = _credential_key(provider)
    for name in names:
        value = os.getenv(f"MARKETPLACE_{key}_{name}", "").strip()
        if value:
            return value
    return ""


def _encryption_key() -> bytes:
    configured = os.getenv("MARKETPLACE_TOKEN_ENCRYPTION_KEY", "").strip()
    if configured:
        try:
            raw = configured.encode("utf-8")
            Fernet(raw)
            return raw
        except Exception as exc:
            raise RuntimeError("MARKETPLACE_TOKEN_ENCRYPTION_KEY bukan Fernet key yang valid") from exc
    # Backward-compatible secure fallback: derive a dedicated Fernet key from the app JWT secret.
    return base64.urlsafe_b64encode(hashlib.sha256((JWT_SECRET + "|marketplace-token-v1").encode("utf-8")).digest())


def _encrypt_token_bundle(bundle: dict) -> str:
    raw = json.dumps(bundle, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return Fernet(_encryption_key()).encrypt(raw).decode("utf-8")


def _decrypt_token_bundle(ciphertext: str) -> dict:
    try:
        raw = Fernet(_encryption_key()).decrypt(str(ciphertext or "").encode("utf-8"))
        return json.loads(raw.decode("utf-8"))
    except (InvalidToken, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="Token marketplace tidak dapat didekripsi. Periksa encryption key.") from exc


def _iso_after(seconds: int | float | str | None) -> str:
    try:
        sec = max(int(float(seconds or 0)), 0)
    except (TypeError, ValueError):
        sec = 0
    if sec <= 0:
        return ""
    return (datetime.now(timezone.utc) + timedelta(seconds=sec)).isoformat()


async def _save_tokens(account: dict, bundle: dict) -> None:
    account_id = account["id"]
    access_token = str(bundle.get("access_token") or "")
    refresh_token = str(bundle.get("refresh_token") or "")
    if not access_token:
        raise HTTPException(status_code=502, detail="Marketplace tidak mengembalikan access_token")

    metadata = {
        "accountId": account_id,
        "provider": account.get("provider", ""),
        "ciphertext": _encrypt_token_bundle(bundle),
        "expiresAt": _iso_after(bundle.get("access_token_expire_in") or bundle.get("expire_in") or bundle.get("expires_in")),
        "refreshExpiresAt": _iso_after(bundle.get("refresh_token_expire_in") or bundle.get("refresh_expires_in")),
        "hasRefreshToken": bool(refresh_token),
        "openId": str(bundle.get("open_id") or ""),
        "sellerName": str(bundle.get("seller_name") or ""),
        "grantedScopes": bundle.get("granted_scopes") or bundle.get("scope") or [],
        "updatedAt": now_iso(),
    }
    await db.marketplace_tokens.update_one({"accountId": account_id}, {"$set": metadata}, upsert=True)
    await db.marketplace_accounts.update_one(
        {"id": account_id},
        {"$set": {
            "connectionStatus": "CONNECTED",
            "connectedAt": now_iso(),
            "tokenStored": True,
            "tokenExpiresAt": metadata["expiresAt"],
            "refreshTokenStored": bool(refresh_token),
            "grantedScopes": metadata["grantedScopes"],
            "updatedAt": now_iso(),
        }},
    )


def _append_query(url: str, values: dict) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    for key, value in values.items():
        if value not in (None, ""):
            query[key] = str(value)
    return urlunparse(parsed._replace(query=urlencode(query)))


def _base_url(request: Request) -> str:
    configured = os.getenv("MARKETPLACE_PUBLIC_BASE_URL", "").strip().rstrip("/")
    if configured:
        return configured
    return str(request.base_url).rstrip("/")


def _callback_url(request: Request, provider: str) -> str:
    return f"{_base_url(request)}/api/marketplace/oauth/callback/{_provider_key(provider).lower()}"


def _frontend_result_url(request: Request, status: str, account_id: str, message: str = "") -> str:
    base = f"{_base_url(request)}/pengaturan/marketplace"
    return _append_query(base, {
        "marketplaceConnection": status,
        "accountId": account_id,
        "message": message[:240],
    })


async def _create_auth_session(account: dict, callback_url: str) -> str:
    state = secrets.token_urlsafe(32)
    digest = hashlib.sha256(state.encode("utf-8")).hexdigest()
    await db.marketplace_auth_sessions.insert_one({
        "id": new_id(),
        "stateHash": digest,
        "accountId": account["id"],
        "provider": account.get("provider", ""),
        "callbackUrl": callback_url,
        "createdAt": now_iso(),
        "expiresAt": (datetime.now(timezone.utc) + timedelta(minutes=AUTH_SESSION_MINUTES)).isoformat(),
        "used": False,
    })
    return state


async def _consume_auth_session(state: str, provider_slug: str) -> dict:
    if not state:
        raise HTTPException(status_code=400, detail="OAuth state tidak tersedia")
    digest = hashlib.sha256(state.encode("utf-8")).hexdigest()
    session = await db.marketplace_auth_sessions.find_one({"stateHash": digest}, {"_id": 0})
    if not session:
        raise HTTPException(status_code=400, detail="OAuth state tidak valid")
    if session.get("used"):
        raise HTTPException(status_code=409, detail="OAuth state sudah digunakan")
    expires_at = datetime.fromisoformat(session["expiresAt"])
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="Sesi otorisasi sudah kedaluwarsa")
    if _provider_key(session.get("provider", "")).lower() != provider_slug.lower():
        # Tokopedia & Shop intentionally shares TikTok Shop credential family but keeps its own provider slug.
        expected = _provider_key(session.get("provider", "")).lower()
        if not ({expected, provider_slug.lower()} <= {"tokopedia_shop", "tiktok_shop"}):
            raise HTTPException(status_code=400, detail="Provider callback tidak sesuai sesi otorisasi")
    await db.marketplace_auth_sessions.update_one({"stateHash": digest}, {"$set": {"used": True, "usedAt": now_iso()}})
    return session


def _shopee_signature(partner_id: str, partner_key: str, path: str, timestamp: int) -> str:
    message = f"{partner_id}{path}{timestamp}".encode("utf-8")
    return hmac.new(partner_key.encode("utf-8"), message, hashlib.sha256).hexdigest()


def _shopee_auth_url(provider: str, callback_url: str, state: str) -> str:
    partner_id = _env(provider, "PARTNER_ID", "APP_ID", "CLIENT_ID")
    partner_key = _env(provider, "PARTNER_KEY", "APP_SECRET", "CLIENT_SECRET")
    template = _env(provider, "AUTH_URL_TEMPLATE")
    if template:
        return (template
                .replace("{redirect_url}", callback_url)
                .replace("{callback_url}", callback_url)
                .replace("{state}", state)
                .replace("{partner_id}", partner_id))

    if not partner_id or not partner_key:
        raise HTTPException(status_code=409, detail="Shopee Partner ID dan Partner Key belum tersedia di Railway Variables")
    host = _env(provider, "API_HOST") or "https://partner.shopeemobile.com"
    path = _env(provider, "AUTH_PATH") or "/api/v2/shop/auth_partner"
    timestamp = int(time.time())
    sign = _shopee_signature(partner_id, partner_key, path, timestamp)
    return _append_query(host.rstrip("/") + path, {
        "partner_id": partner_id,
        "timestamp": timestamp,
        "sign": sign,
        "redirect": callback_url,
        "state": state,
    })


def _tiktok_auth_url(provider: str, callback_url: str, state: str) -> str:
    base = _env(provider, "AUTH_URL", "AUTH_URL_TEMPLATE")
    if not base:
        raise HTTPException(
            status_code=409,
            detail="Authorization Link TikTok Shop belum tersedia. Salin Authorization Link dari Partner Center ke MARKETPLACE_TIKTOK_SHOP_AUTH_URL.",
        )
    # Partner Center owns the Redirect URL; state is appended here for CSRF protection.
    return _append_query(
        base.replace("{redirect_url}", callback_url).replace("{callback_url}", callback_url),
        {"state": state},
    )


@router.post("/marketplace/accounts/{account_id}/authorize")
async def authorize_marketplace(account_id: str, request: Request, user: dict = Depends(get_current_user)):
    _ensure_settings(user)
    account = await db.marketplace_accounts.find_one({"id": account_id}, {"_id": 0})
    if not account:
        raise HTTPException(status_code=404, detail="Akun marketplace tidak ditemukan")
    if not account.get("active", True):
        raise HTTPException(status_code=409, detail="Aktifkan akun marketplace terlebih dahulu")
    if account.get("connectionMode") == "Manual":
        raise HTTPException(status_code=409, detail="Ubah mode koneksi menjadi API untuk memakai authorization")

    provider = account.get("provider", "")
    callback_url = _callback_url(request, provider)
    state = await _create_auth_session(account, callback_url)

    if _credential_key(provider) == "TIKTOK_SHOP":
        authorization_url = _tiktok_auth_url(provider, callback_url, state)
    elif _credential_key(provider) == "SHOPEE":
        authorization_url = _shopee_auth_url(provider, callback_url, state)
    else:
        template = _env(provider, "AUTH_URL_TEMPLATE")
        if not template:
            raise HTTPException(status_code=409, detail="AUTH_URL_TEMPLATE provider ini belum diatur di Railway")
        authorization_url = (template
                             .replace("{redirect_url}", callback_url)
                             .replace("{callback_url}", callback_url)
                             .replace("{state}", state))

    await db.marketplace_accounts.update_one(
        {"id": account_id},
        {"$set": {
            "connectionStatus": "AUTHORIZATION_PENDING",
            "authorizationStartedAt": now_iso(),
            "callbackUrl": callback_url,
            "updatedBy": user.get("name", ""),
            "updatedAt": now_iso(),
        }},
    )
    await _log(
        level="INFO",
        event_type="AUTHORIZATION_STARTED",
        provider=provider,
        account_id=account_id,
        reference=account.get("shopName", ""),
        message="Authorization marketplace dimulai.",
    )
    return {"status": "AUTHORIZATION_PENDING", "authorizationUrl": authorization_url, "callbackUrl": callback_url}


async def _exchange_tiktok(provider: str, auth_code: str) -> dict:
    app_key = _env(provider, "APP_KEY", "APP_ID", "CLIENT_ID")
    app_secret = _env(provider, "APP_SECRET", "CLIENT_SECRET")
    if not app_key or not app_secret:
        raise HTTPException(status_code=409, detail="TikTok Shop App Key/App Secret belum lengkap di Railway")
    url = _env(provider, "TOKEN_URL") or "https://auth.tiktok-shops.com/api/v2/token/get"
    params = {
        "app_key": app_key,
        "app_secret": app_secret,
        "auth_code": auth_code,
        "grant_type": "authorized_code",
    }
    async with httpx.AsyncClient(timeout=25.0) as client:
        response = await client.get(url, params=params)
    try:
        data = response.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Respons token TikTok Shop tidak valid") from exc
    if response.status_code >= 400 or int(data.get("code", -1)) != 0:
        raise HTTPException(status_code=502, detail=f"Token TikTok Shop gagal: {data.get('message') or response.status_code}")
    token_data = data.get("data") or {}
    if int(token_data.get("user_type", 0) or 0) not in (0,):
        raise HTTPException(status_code=409, detail="Authorization bukan seller token TikTok Shop")
    return token_data


async def _exchange_shopee(provider: str, auth_code: str, shop_id: str) -> dict:
    partner_id = _env(provider, "PARTNER_ID", "APP_ID", "CLIENT_ID")
    partner_key = _env(provider, "PARTNER_KEY", "APP_SECRET", "CLIENT_SECRET")
    if not partner_id or not partner_key:
        raise HTTPException(status_code=409, detail="Shopee Partner ID/Partner Key belum lengkap di Railway")
    if not shop_id:
        raise HTTPException(status_code=400, detail="Shopee callback tidak membawa shop_id")

    host = _env(provider, "API_HOST") or "https://partner.shopeemobile.com"
    path = _env(provider, "TOKEN_PATH") or "/api/v2/auth/token/get"
    timestamp = int(time.time())
    sign = _shopee_signature(partner_id, partner_key, path, timestamp)
    url = _append_query(host.rstrip("/") + path, {
        "partner_id": partner_id,
        "timestamp": timestamp,
        "sign": sign,
    })
    payload = {"code": auth_code, "shop_id": int(shop_id), "partner_id": int(partner_id)}
    async with httpx.AsyncClient(timeout=25.0) as client:
        response = await client.post(url, json=payload)
    try:
        data = response.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Respons token Shopee tidak valid") from exc
    if response.status_code >= 400 or data.get("error"):
        raise HTTPException(status_code=502, detail=f"Token Shopee gagal: {data.get('message') or data.get('error') or response.status_code}")
    data["shop_id"] = str(shop_id)
    return data


@router.get("/marketplace/oauth/callback/{provider_slug}")
async def marketplace_oauth_callback(
    provider_slug: str,
    request: Request,
    code: str = "",
    auth_code: str = "",
    state: str = "",
    shop_id: str = "",
    error: str = "",
    error_description: str = "",
):
    session = await _consume_auth_session(state, provider_slug)
    account_id = session["accountId"]
    account = await db.marketplace_accounts.find_one({"id": account_id}, {"_id": 0})
    if not account:
        raise HTTPException(status_code=404, detail="Akun marketplace tidak ditemukan")
    provider = account.get("provider", "")

    if error:
        await db.marketplace_accounts.update_one(
            {"id": account_id},
            {"$set": {"connectionStatus": "AUTHORIZATION_FAILED", "lastConnectionError": error_description or error, "updatedAt": now_iso()}},
        )
        await _log(level="ERROR", event_type="AUTHORIZATION_FAILED", provider=provider, account_id=account_id,
                   reference=account.get("shopName", ""), message=error_description or error)
        return RedirectResponse(_frontend_result_url(request, "failed", account_id, error_description or error), status_code=302)

    authorization_code = auth_code or code
    if not authorization_code:
        return RedirectResponse(_frontend_result_url(request, "failed", account_id, "Authorization code tidak tersedia"), status_code=302)

    try:
        if _credential_key(provider) == "TIKTOK_SHOP":
            bundle = await _exchange_tiktok(provider, authorization_code)
        elif _credential_key(provider) == "SHOPEE":
            bundle = await _exchange_shopee(provider, authorization_code, shop_id or account.get("shopId", ""))
        else:
            raise HTTPException(status_code=501, detail="Token adapter provider ini belum tersedia")

        await _save_tokens(account, bundle)
        patch = {"lastConnectionError": "", "updatedAt": now_iso()}
        resolved_shop = str(bundle.get("shop_id") or shop_id or account.get("shopId", ""))
        if resolved_shop:
            patch["shopId"] = resolved_shop
        await db.marketplace_accounts.update_one({"id": account_id}, {"$set": patch})
        await _log(level="INFO", event_type="AUTHORIZATION_CONNECTED", provider=provider, account_id=account_id,
                   reference=account.get("shopName", ""), message="Authorization selesai dan token disimpan terenkripsi.")
        return RedirectResponse(_frontend_result_url(request, "success", account_id, "Marketplace berhasil terhubung"), status_code=302)
    except HTTPException as exc:
        await db.marketplace_accounts.update_one(
            {"id": account_id},
            {"$set": {"connectionStatus": "AUTHORIZATION_FAILED", "lastConnectionError": str(exc.detail), "updatedAt": now_iso()}},
        )
        await _log(level="ERROR", event_type="AUTHORIZATION_FAILED", provider=provider, account_id=account_id,
                   reference=account.get("shopName", ""), message=str(exc.detail))
        return RedirectResponse(_frontend_result_url(request, "failed", account_id, str(exc.detail)), status_code=302)


async def _token_bundle(account_id: str) -> dict:
    token_doc = await db.marketplace_tokens.find_one({"accountId": account_id}, {"_id": 0})
    if not token_doc:
        raise HTTPException(status_code=409, detail="Akun belum memiliki token marketplace")
    return _decrypt_token_bundle(token_doc.get("ciphertext", ""))


async def _refresh_tiktok(provider: str, refresh_token: str) -> dict:
    app_key = _env(provider, "APP_KEY", "APP_ID", "CLIENT_ID")
    app_secret = _env(provider, "APP_SECRET", "CLIENT_SECRET")
    url = _env(provider, "REFRESH_URL") or "https://auth.tiktok-shops.com/api/v2/token/refresh"
    params = {
        "app_key": app_key,
        "app_secret": app_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    async with httpx.AsyncClient(timeout=25.0) as client:
        response = await client.get(url, params=params)
    data = response.json()
    if response.status_code >= 400 or int(data.get("code", -1)) != 0:
        raise HTTPException(status_code=502, detail=f"Refresh token TikTok Shop gagal: {data.get('message') or response.status_code}")
    return data.get("data") or {}


async def _refresh_shopee(provider: str, refresh_token: str, shop_id: str) -> dict:
    partner_id = _env(provider, "PARTNER_ID", "APP_ID", "CLIENT_ID")
    partner_key = _env(provider, "PARTNER_KEY", "APP_SECRET", "CLIENT_SECRET")
    host = _env(provider, "API_HOST") or "https://partner.shopeemobile.com"
    path = _env(provider, "REFRESH_PATH") or "/api/v2/auth/access_token/get"
    timestamp = int(time.time())
    sign = _shopee_signature(partner_id, partner_key, path, timestamp)
    url = _append_query(host.rstrip("/") + path, {
        "partner_id": partner_id,
        "timestamp": timestamp,
        "sign": sign,
    })
    payload = {"refresh_token": refresh_token, "shop_id": int(shop_id), "partner_id": int(partner_id)}
    async with httpx.AsyncClient(timeout=25.0) as client:
        response = await client.post(url, json=payload)
    data = response.json()
    if response.status_code >= 400 or data.get("error"):
        raise HTTPException(status_code=502, detail=f"Refresh token Shopee gagal: {data.get('message') or data.get('error') or response.status_code}")
    data["shop_id"] = str(shop_id)
    return data


@router.post("/marketplace/accounts/{account_id}/refresh-token")
async def refresh_marketplace_token(account_id: str, user: dict = Depends(get_current_user)):
    _ensure_settings(user)
    account = await db.marketplace_accounts.find_one({"id": account_id}, {"_id": 0})
    if not account:
        raise HTTPException(status_code=404, detail="Akun marketplace tidak ditemukan")
    current = await _token_bundle(account_id)
    refresh_token = str(current.get("refresh_token") or "")
    if not refresh_token:
        raise HTTPException(status_code=409, detail="Refresh token tidak tersedia; lakukan Hubungkan ulang")

    provider = account.get("provider", "")
    if _credential_key(provider) == "TIKTOK_SHOP":
        bundle = await _refresh_tiktok(provider, refresh_token)
    elif _credential_key(provider) == "SHOPEE":
        bundle = await _refresh_shopee(provider, refresh_token, str(current.get("shop_id") or account.get("shopId", "")))
    else:
        raise HTTPException(status_code=501, detail="Refresh adapter provider ini belum tersedia")

    if not bundle.get("refresh_token"):
        bundle["refresh_token"] = refresh_token
    await _save_tokens(account, bundle)
    await _log(level="INFO", event_type="TOKEN_REFRESHED", provider=provider, account_id=account_id,
               reference=account.get("shopName", ""), message="Access token marketplace diperbarui.")
    return {"status": "CONNECTED", "tokenRefreshed": True}


@router.post("/marketplace/accounts/{account_id}/revoke-local")
async def revoke_local_marketplace_token(account_id: str, user: dict = Depends(get_current_user)):
    _ensure_settings(user)
    account = await db.marketplace_accounts.find_one({"id": account_id}, {"_id": 0})
    if not account:
        raise HTTPException(status_code=404, detail="Akun marketplace tidak ditemukan")
    await db.marketplace_tokens.delete_many({"accountId": account_id})
    await db.marketplace_accounts.update_one(
        {"id": account_id},
        {"$set": {
            "connectionStatus": "NOT_CONNECTED",
            "tokenStored": False,
            "refreshTokenStored": False,
            "tokenExpiresAt": "",
            "disconnectedAt": now_iso(),
            "updatedAt": now_iso(),
        }},
    )
    await _log(level="INFO", event_type="LOCAL_TOKEN_REVOKED", provider=account.get("provider", ""), account_id=account_id,
               reference=account.get("shopName", ""), message="Token lokal marketplace dihapus.")
    return {"status": "NOT_CONNECTED"}


@router.get("/marketplace/accounts/{account_id}/connection")
async def marketplace_connection_status(account_id: str, user: dict = Depends(get_current_user)):
    _ensure_settings(user)
    account = await db.marketplace_accounts.find_one({"id": account_id}, {"_id": 0})
    if not account:
        raise HTTPException(status_code=404, detail="Akun marketplace tidak ditemukan")
    token_doc = await db.marketplace_tokens.find_one({"accountId": account_id}, {
        "_id": 0, "ciphertext": 0
    })
    return {
        "accountId": account_id,
        "provider": account.get("provider", ""),
        "status": account.get("connectionStatus", "NOT_CONNECTED"),
        "tokenStored": bool(token_doc),
        "hasRefreshToken": bool((token_doc or {}).get("hasRefreshToken")),
        "tokenExpiresAt": (token_doc or {}).get("expiresAt", ""),
        "grantedScopes": (token_doc or {}).get("grantedScopes", []),
        "lastError": account.get("lastConnectionError", ""),
        "callbackUrl": account.get("callbackUrl", ""),
        "credentialFamily": _credential_key(account.get("provider", "")),
    }


async def ensure_marketplace_oauth_indexes() -> None:
    await db.marketplace_tokens.create_index("accountId", unique=True, name="marketplace_token_account_unique")
    await db.marketplace_auth_sessions.create_index("stateHash", unique=True, name="marketplace_oauth_state_unique")
    await db.marketplace_auth_sessions.create_index("expiresAt", name="marketplace_oauth_expiry")
