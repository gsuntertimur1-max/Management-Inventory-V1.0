import os
import uuid
from typing import List, Optional

import httpx
from fastapi import APIRouter, Cookie, Header, HTTPException, Request, Response

from lib.auth import (
    GOOGLE_COOKIE,
    OWNER_EMAIL,
    SESSION_COOKIE,
    SESSION_DAYS,
    create_session,
    current_user,
    destroy_session,
    hash_password,
    principal,
    to_public,
    token_from_request,
    verify_password,
)
from lib.db import db
from models.auth import GoogleSessionRequest, LoginRequest, User, UserCreate, UserPublic, UserUpdate

router = APIRouter(prefix="/auth")

IS_HTTPS = os.environ.get("APP_URL", "").startswith("https")
EMERGENT_SESSION_DATA_URL = (
    "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data"
)


@router.post("/login", response_model=UserPublic)
async def login(payload: LoginRequest, request: Request, response: Response):
    doc = await db.users.find_one({"username": payload.username.strip().lower()})
    if not doc:
        raise HTTPException(status_code=401, detail="Username atau password salah")
    doc.pop("_id", None)
    user = User(**doc)
    if not verify_password(payload.password, user.password_hash, user.salt):
        raise HTTPException(status_code=401, detail="Username atau password salah")

    token = await create_session(user.id)
    # Derive Secure from the ACTUAL request scheme: a Secure cookie is silently dropped when the
    # app is opened over plain http, which would bounce the user straight back to /login.
    forwarded = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
    is_https = (forwarded or request.url.scheme) == "https"
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=is_https,
        max_age=SESSION_DAYS * 24 * 3600,
        path="/",
    )
    return to_public(user)


@router.post("/google/session", response_model=UserPublic)
async def google_session(
    request: Request,
    response: Response,
    payload: Optional[GoogleSessionRequest] = None,
    x_session_id: Optional[str] = Header(default=None),
):
    """Tukar session_id Emergent Google Auth menjadi sesi aplikasi (peran RBAC tetap berlaku)."""
    session_id = (payload.session_id if payload else None) or x_session_id
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id tidak ditemukan")

    async with httpx.AsyncClient(timeout=20) as client:
        try:
            res = await client.get(EMERGENT_SESSION_DATA_URL, headers={"X-Session-ID": session_id})
        except httpx.HTTPError:
            raise HTTPException(status_code=502, detail="Gagal menghubungi layanan autentikasi")
    if res.status_code != 200:
        raise HTTPException(status_code=401, detail="Sesi Google tidak valid atau kedaluwarsa")

    data = res.json()
    email = str(data.get("email", "")).strip().lower()
    session_token = data.get("session_token")
    if not email or not session_token:
        raise HTTPException(status_code=502, detail="Data sesi Google tidak lengkap")

    name = str(data.get("name") or email.split("@")[0])
    picture = str(data.get("picture") or "")

    existing = await db.users.find_one({"email": email}, {"_id": 0})
    if existing:
        await db.users.update_one(
            {"id": existing["id"]},
            {"$set": {
                "full_name": existing.get("full_name") or name,
                "picture": picture,
                "auth_provider": "google",
                **({"role": "admin"} if email == OWNER_EMAIL else {}),
            }},
        )
        user = User(**{**existing, "full_name": existing.get("full_name") or name,
                       "picture": picture, "auth_provider": "google",
                       "role": "admin" if email == OWNER_EMAIL else existing.get("role", "viewer")})
    else:
        base = email.split("@")[0][:30] or "google"
        username = base
        while await db.users.find_one({"username": username}):
            username = f"{base}-{uuid.uuid4().hex[:4]}"
        user = User(
            username=username,
            full_name=name,
            # Pemilik aplikasi langsung administrator; akun Google lain mulai sebagai pemantau
            # dan bisa dinaikkan perannya oleh admin di halaman Pengguna.
            role="admin" if email == OWNER_EMAIL else "viewer",
            email=email,
            picture=picture,
            auth_provider="google",
        )
        await db.users.insert_one(user.model_dump())

    await create_session(user.id, token=session_token)

    forwarded = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
    is_https = (forwarded or request.url.scheme) == "https"
    for cookie_name in (GOOGLE_COOKIE, SESSION_COOKIE):
        response.set_cookie(
            cookie_name,
            session_token,
            httponly=True,
            samesite="none" if is_https else "lax",
            secure=is_https,
            max_age=SESSION_DAYS * 24 * 3600,
            path="/",
        )
    return to_public(user)


@router.post("/logout")
async def logout(request: Request, response: Response, gp_session: Optional[str] = Cookie(default=None)):
    await destroy_session(token_from_request(request, gp_session))
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(GOOGLE_COOKIE, path="/")
    return {"ok": True}


@router.get("/me", response_model=Optional[UserPublic])
async def me(request: Request, gp_session: Optional[str] = Cookie(default=None)):
    user = await current_user(token_from_request(request, gp_session))
    return to_public(user) if user else None


# ---------- user administration (admin only, gated by the router-wide enforce) ----------
@router.get("/users", response_model=List[UserPublic])
async def list_users():
    docs = await db.users.find().sort("username", 1).to_list(200)
    out: List[UserPublic] = []
    for d in docs:
        d.pop("_id", None)
        out.append(to_public(User(**d)))
    return out


@router.post("/users", response_model=UserPublic)
async def create_user(payload: UserCreate):
    username = payload.username.strip().lower()
    if await db.users.find_one({"username": username}):
        raise HTTPException(status_code=409, detail="Username sudah digunakan")
    password_hash, salt = hash_password(payload.password)
    user = User(
        username=username,
        full_name=payload.full_name.strip(),
        role=payload.role,
        password_hash=password_hash,
        salt=salt,
    )
    await db.users.insert_one(user.model_dump())
    return to_public(user)


@router.patch("/users/{user_id}", response_model=UserPublic)
async def update_user(user_id: str, payload: UserUpdate, request: Request):
    doc = await db.users.find_one({"id": user_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Pengguna tidak ditemukan")
    doc.pop("_id", None)
    user = User(**doc)

    caller = await principal(request)
    update: dict = {}
    if payload.full_name is not None:
        update["full_name"] = payload.full_name.strip()
    if payload.role is not None:
        # Never let an admin demote themselves and lock the app out of administration.
        if caller and caller.id == user_id and payload.role != "admin":
            raise HTTPException(status_code=400, detail="Tidak dapat menurunkan peran akun sendiri")
        if user.role == "admin" and payload.role != "admin":
            admins = await db.users.count_documents({"role": "admin"})
            if admins <= 1:
                raise HTTPException(status_code=400, detail="Minimal satu administrator harus tersisa")
        update["role"] = payload.role
    if payload.password:
        password_hash, salt = hash_password(payload.password)
        update["password_hash"] = password_hash
        update["salt"] = salt
        await db.sessions.delete_many({"user_id": user_id})

    if update:
        await db.users.update_one({"id": user_id}, {"$set": update})
    merged = {**user.model_dump(), **update}
    return to_public(User(**merged))


@router.delete("/users/{user_id}")
async def delete_user(user_id: str, request: Request):
    doc = await db.users.find_one({"id": user_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Pengguna tidak ditemukan")
    caller = await principal(request)
    if caller and caller.id == user_id:
        raise HTTPException(status_code=400, detail="Tidak dapat menghapus akun sendiri")
    if doc.get("role") == "admin" and await db.users.count_documents({"role": "admin"}) <= 1:
        raise HTTPException(status_code=400, detail="Minimal satu administrator harus tersisa")
    await db.users.delete_one({"id": user_id})
    await db.sessions.delete_many({"user_id": user_id})
    return {"ok": True}
