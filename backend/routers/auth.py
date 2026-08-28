import os
from typing import List, Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response

from lib.auth import (
    SESSION_COOKIE,
    SESSION_DAYS,
    create_session,
    current_user,
    destroy_session,
    hash_password,
    principal,
    to_public,
    verify_password,
)
from lib.db import db
from models.auth import LoginRequest, User, UserCreate, UserPublic, UserUpdate

router = APIRouter(prefix="/auth")

IS_HTTPS = os.environ.get("APP_URL", "").startswith("https")


@router.post("/login", response_model=UserPublic)
async def login(payload: LoginRequest, response: Response):
    doc = await db.users.find_one({"username": payload.username.strip().lower()})
    if not doc:
        raise HTTPException(status_code=401, detail="Username atau password salah")
    doc.pop("_id", None)
    user = User(**doc)
    if not verify_password(payload.password, user.password_hash, user.salt):
        raise HTTPException(status_code=401, detail="Username atau password salah")

    token = await create_session(user.id)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=IS_HTTPS,
        max_age=SESSION_DAYS * 24 * 3600,
        path="/",
    )
    return to_public(user)


@router.post("/logout")
async def logout(response: Response, gp_session: Optional[str] = Cookie(default=None)):
    await destroy_session(gp_session)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/me", response_model=Optional[UserPublic])
async def me(gp_session: Optional[str] = Cookie(default=None)):
    user = await current_user(gp_session)
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
