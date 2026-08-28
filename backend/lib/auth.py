"""RBAC for a single shared warehouse: roles only — no tenancy, no per-record ownership.

One decision function (`authorize`) drives every route via the `enforce` dependency that is
attached to `api_router`, so an un-annotated path is denied by default (fail-closed).
"""
import hashlib
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from fastapi import Cookie, HTTPException, Request

from lib.db import db
from models.auth import Role, User, UserPublic

SESSION_COOKIE = "gp_session"
GOOGLE_COOKIE = "session_token"     # Emergent-managed Google Auth session cookie
SESSION_DAYS = 7
OWNER_EMAIL = "gsuntertimur1@gmail.com"   # pemilik aplikasi → selalu administrator

# --- password hashing (stdlib pbkdf2; no extra dependency) ---
_ITERATIONS = 200_000


def hash_password(password: str, salt: Optional[str] = None) -> Tuple[str, str]:
    use_salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), use_salt.encode(), _ITERATIONS)
    return digest.hex(), use_salt


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    candidate, _ = hash_password(password, salt)
    return secrets.compare_digest(candidate, password_hash)


# --- permissions: what each role may do ---
# admin      : everything
# penjualan  : outbound only (barang keluar / surat jalan)
# pengadaan  : procurement only (PO, stok masuk, produk & supplier)
# viewer     : read-only on remaining stock + sales
PERMISSIONS: Dict[Role, List[str]] = {
    "admin": [
        "stock:read", "sales:read", "sales:write", "procurement:read", "procurement:write",
        "inventory:read", "reports:read", "settings:write", "users:manage", "data:reset",
    ],
    "penjualan": ["stock:read", "sales:read", "sales:write", "inventory:read", "reports:read"],
    "pengadaan": [
        "stock:read", "procurement:read", "procurement:write", "inventory:read", "reports:read",
    ],
    "viewer": ["stock:read", "sales:read"],
}

ROLE_LABELS: Dict[str, str] = {
    "admin": "Administrator",
    "penjualan": "Penjualan (barang keluar)",
    "pengadaan": "Pengadaan (barang masuk)",
    "viewer": "Pemantau (lihat stok & penjualan)",
}

# --- route -> required action table (method, path regex) ---
# Anything not matched here is denied, so a new endpoint fails closed until listed.
_RULES: List[Tuple[str, str, Optional[str]]] = [
    # public
    ("POST", r"^/api/auth/login$", None),
    ("POST", r"^/api/auth/google/session$", None),
    ("POST", r"^/api/auth/logout$", None),
    ("GET", r"^/api/auth/me$", None),
    ("GET", r"^/api/$", None),
    # user administration
    ("*", r"^/api/auth/users(/.*)?$", "users:manage"),
    # stock visibility (every role, viewer included)
    ("GET", r"^/api/products$", "stock:read"),
    ("GET", r"^/api/products/[^/]+$", "stock:read"),
    ("GET", r"^/api/stats$", "stock:read"),
    # lokasi & tumpukan stok
    ("GET", r"^/api/locations(/.*)?$", "stock:read"),
    ("GET", r"^/api/placements(/.*)?$", "stock:read"),
    ("*", r"^/api/locations(/.*)?$", "procurement:write"),
    ("*", r"^/api/placements(/.*)?$", "procurement:write"),
    # sales / outbound
    ("GET", r"^/api/shipments(/.*)?$", "sales:read"),
    ("*", r"^/api/shipments(/.*)?$", "sales:write"),
    # procurement / inbound
    ("GET", r"^/api/suppliers$", "procurement:read"),
    ("GET", r"^/api/purchase-orders(/.*)?$", "procurement:read"),
    ("*", r"^/api/suppliers(/.*)?$", "procurement:write"),
    ("*", r"^/api/purchase-orders(/.*)?$", "procurement:write"),
    ("POST", r"^/api/products/import$", "procurement:write"),
    ("*", r"^/api/products(/.*)?$", "procurement:write"),
    ("POST", r"^/api/transactions$", "procurement:write"),
    # shared reads
    ("GET", r"^/api/transactions(/.*)?$", "inventory:read"),
    ("GET", r"^/api/settings$", "stock:read"),
    ("GET", r"^/api/reports/.*$", "reports:read"),
    # admin only
    ("POST", r"^/api/seed$", "data:reset"),
    ("PUT", r"^/api/settings$", "settings:write"),
]


def action_for(method: str, path: str) -> Tuple[bool, Optional[str]]:
    """Return (matched, action). action None on a matched public route."""
    for rule_method, pattern, action in _RULES:
        if (rule_method == "*" or rule_method == method) and re.match(pattern, path):
            return True, action
    return False, None


def authorize(role: Optional[Role], action: str) -> bool:
    if role is None:
        return False
    return action in PERMISSIONS.get(role, [])


# --- sessions ---
async def create_session(user_id: str, token: Optional[str] = None) -> str:
    session_token = token or secrets.token_urlsafe(32)
    await db.sessions.insert_one({
        "token": session_token,
        "user_id": user_id,
        "expires_at": datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS),
    })
    return session_token


async def destroy_session(token: Optional[str]) -> None:
    if token:
        await db.sessions.delete_one({"token": token})


async def current_user(token: Optional[str]) -> Optional[User]:
    """Role is re-read from the users collection on every request, never from the cookie."""
    if not token:
        return None
    session = await db.sessions.find_one({"token": token})
    if not session:
        return None
    expires = session.get("expires_at")
    if isinstance(expires, datetime):
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires < datetime.now(timezone.utc):
            await db.sessions.delete_one({"token": token})
            return None
    doc = await db.users.find_one({"id": session["user_id"]})
    if not doc:
        return None
    doc.pop("_id", None)
    return User(**doc)


def token_from_request(request: Request, gp_session: Optional[str] = None) -> Optional[str]:
    """Both auth paths share one sessions collection: app cookie, Google cookie, then Bearer."""
    if gp_session:
        return gp_session
    cookie = request.cookies.get(SESSION_COOKIE) or request.cookies.get(GOOGLE_COOKIE)
    if cookie:
        return cookie
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header.split(" ", 1)[1].strip() or None
    return None


async def enforce(request: Request, gp_session: Optional[str] = Cookie(default=None)) -> None:
    """Router-wide gate: deny-by-default on both authentication and authorization."""
    if request.method == "OPTIONS":
        return

    matched, action = action_for(request.method, request.url.path)
    if not matched:
        raise HTTPException(status_code=403, detail="Endpoint tidak diizinkan")
    if action is None:
        return

    user = await current_user(token_from_request(request, gp_session))
    if not user:
        raise HTTPException(status_code=401, detail="Silakan login terlebih dahulu")
    if not authorize(user.role, action):
        raise HTTPException(
            status_code=403,
            detail=f"Peran {ROLE_LABELS.get(user.role, user.role)} tidak berhak melakukan aksi ini",
        )
    request.state.user = user


async def principal(request: Request) -> Optional[User]:
    """Handler-side access to the caller resolved by `enforce` (used for field masking)."""
    return getattr(request.state, "user", None)


def to_public(user: User) -> UserPublic:
    return UserPublic(
        id=user.id,
        username=user.username,
        full_name=user.full_name,
        role=user.role,
        email=user.email,
        picture=user.picture,
        auth_provider=user.auth_provider,
        created_at=user.created_at,
    )


async def ensure_default_admin() -> None:
    """Guarantee the documented default admin exists, so the app can never lock you out.

    Checks for the account by USERNAME (not "are there any users at all"): once other accounts
    exist — or the default admin was deleted — the old emptiness check silently stopped
    recreating it, leaving no working way in.
    """
    username = os.environ.get("DEFAULT_ADMIN_USER", "admin").strip().lower()
    existing = await db.users.find_one({"username": username})
    if existing:
        # Never silently reset a password, but do keep the recovery account privileged.
        if existing.get("role") != "admin":
            await db.users.update_one({"id": existing["id"]}, {"$set": {"role": "admin"}})
        return

    password = os.environ.get("DEFAULT_ADMIN_PASSWORD", "admin123")
    password_hash, salt = hash_password(password)
    await db.users.insert_one(User(
        username=username, full_name="Administrator Gudang", role="admin",
        password_hash=password_hash, salt=salt,
    ).model_dump())


async def migrate_legacy_roles() -> None:
    """The old 'operator' role was split into 'penjualan' + 'pengadaan'; keep old accounts usable."""
    await db.users.update_many({"role": "operator"}, {"$set": {"role": "penjualan"}})
