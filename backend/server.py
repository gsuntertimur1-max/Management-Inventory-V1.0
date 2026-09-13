from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

import os
import io
import csv
import uuid
import logging
import bcrypt
import jwt
import httpx
from collections import Counter
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from fastapi import FastAPI, APIRouter, HTTPException, Request, Response, Depends, UploadFile, File
from fastapi.responses import StreamingResponse
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ReturnDocument
from pymongo.errors import OperationFailure
from pydantic import BaseModel, Field
from typing import List, Literal, Optional
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment

REQUIRED_ENV = ("MONGO_URL", "DB_NAME", "JWT_SECRET")
missing_env = [name for name in REQUIRED_ENV if not os.environ.get(name)]
if missing_env:
    raise RuntimeError(f"Environment variable wajib belum diatur: {', '.join(missing_env)}")

mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

JWT_ALG = "HS256"
JWT_SECRET = os.environ["JWT_SECRET"]
JAKARTA_TZ = ZoneInfo("Asia/Jakarta")
GOOGLE_SESSION_URL = os.environ.get("GOOGLE_SESSION_URL", "").strip()

@asynccontextmanager
async def lifespan(app: FastAPI):
    await initialize_app()
    yield
    client.close()


app = FastAPI(lifespan=lifespan)
api_router = APIRouter(prefix="/api")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# ---------- helpers ----------
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def create_access_token(user_id: str) -> str:
    payload = {"sub": user_id, "type": "access", "exp": datetime.now(timezone.utc) + timedelta(days=7)}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def operational_now() -> datetime:
    """Waktu bisnis gudang (WIB), khusus tanggal dan nomor dokumen."""
    return datetime.now(JAKARTA_TZ)


def new_id() -> str:
    return uuid.uuid4().hex


async def max_suffix(collection, field: str, prefix: str, query: Optional[dict] = None) -> int:
    match = dict(query or {})
    match[field] = {"$regex": f"^{prefix}"}
    doc = await collection.find_one(match, {"_id": 0, field: 1}, sort=[(field, -1)])
    if not doc:
        return 0
    try:
        return int(str(doc[field]).rsplit("-", 1)[-1])
    except (KeyError, TypeError, ValueError):
        return 0


async def next_sequence(key: str, floor: int = 0) -> int:
    """Ambil nomor urut secara atomik agar dua operator tidak mendapat nomor sama."""
    doc = await db.counters.find_one_and_update(
        {"_id": key},
        [{"$set": {"value": {"$add": [{"$max": [{"$ifNull": ["$value", 0]}, floor]}, 1]}}}],
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return int(doc["value"])


def public_user(doc: dict) -> dict:
    result = {k: v for k, v in doc.items() if k not in ("_id", "password_hash")}
    if "role" in result:
        result["role_label"] = role_label(result.get("role"))
    return result


async def get_current_user(request: Request) -> dict:
    token = request.cookies.get("access_token") or request.cookies.get("session_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Belum masuk")
    # try JWT first
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
        if payload.get("type") == "access":
            user = await db.users.find_one({"id": payload["sub"]}, {"_id": 0, "password_hash": 0})
            if user:
                return user
    except jwt.InvalidTokenError:
        pass
    # fallback: google session token
    sess = await db.user_sessions.find_one({"session_token": token}, {"_id": 0})
    if sess:
        expires_at = sess["expires_at"]
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at)
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at >= datetime.now(timezone.utc):
            user = await db.users.find_one({"id": sess["user_id"]}, {"_id": 0, "password_hash": 0})
            if user:
                return user
    raise HTTPException(status_code=401, detail="Sesi tidak valid atau kedaluwarsa")


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if canonical_role(user.get("role")) != ROLE_SUPERADMIN:
        raise HTTPException(status_code=403, detail="Hanya Administrator yang diizinkan")
    return user


ROLE_SUPERADMIN = "Administrator"
ROLE_ADMIN = "Supervisor"
ROLE_OPERATOR = "Operator"
ROLE_QC = "QC"
ROLE_VIEWER = "Pemantau"

ROLE_ALIASES = {
    "Superadmin": ROLE_SUPERADMIN,
    "Admin": ROLE_ADMIN,
}

ROLE_LABELS = {
    ROLE_SUPERADMIN: "Superadmin",
    ROLE_ADMIN: "Admin",
    ROLE_OPERATOR: "Operator",
    ROLE_QC: "QC",
    ROLE_VIEWER: "Pemantau",
}


def canonical_role(role: Optional[str]) -> str:
    value = (role or ROLE_VIEWER).strip()
    return ROLE_ALIASES.get(value, value)


ROLE_PERMISSIONS = {
    ROLE_SUPERADMIN: {"masterWrite", "inbound", "outbound", "rebagging", "qc", "users", "settings"},
    ROLE_ADMIN: {"masterWrite", "inbound", "outbound", "rebagging"},
    ROLE_OPERATOR: {"rebagging"},
    ROLE_QC: {"qc"},
    ROLE_VIEWER: set(),
}


def has_role_permission(role: Optional[str], permission: str) -> bool:
    canonical = canonical_role(role)
    if permission == "currentWrite":
        return canonical in {ROLE_SUPERADMIN, ROLE_ADMIN}
    if permission == "operations":
        return canonical in {ROLE_SUPERADMIN, ROLE_ADMIN}
    return permission in ROLE_PERMISSIONS.get(canonical, set())


def role_label(role: Optional[str]) -> str:
    canonical = canonical_role(role)
    return ROLE_LABELS.get(canonical, canonical)


# The current Railway branch has no separate Rebagging/QC endpoints yet. The
# generic write dependency therefore covers only the currently exposed master,
# inbound, and outbound operations. Future modules should use the dedicated
# permission helpers above instead of widening this set.
WRITE_ROLES = {ROLE_SUPERADMIN, ROLE_ADMIN}


async def require_write(user: dict = Depends(get_current_user)) -> dict:
    if not has_role_permission(user.get("role"), "currentWrite"):
        raise HTTPException(
            status_code=403,
            detail=f"Peran {role_label(user.get('role'))} tidak memiliki hak untuk mengubah data pada modul ini",
        )
    return user


# ---------- CSV seed ----------
def parse_seed_rows(text: str) -> List[dict]:
    rows = []
    reader = csv.DictReader(io.StringIO(text), delimiter=';')
    for r in reader:
        sku = (r.get('sku') or '').strip().strip('[]')
        name = (r.get('nama') or '').strip()
        if not sku or not name:
            continue
        qty_raw = (r.get('jumlah') or '0').strip().replace('.', '').replace(',', '.')
        try:
            stock = int(float(qty_raw))
        except ValueError:
            stock = 0
        unit = (r.get('satuan') or 'Pcs').strip()
        try:
            cost = float((r.get('harga_beli') or '0').strip() or 0)
        except ValueError:
            cost = 0
        rows.append({
            'name': name, 'sku': sku, 'category': (r.get('kategori') or '').strip(),
            'stock': stock, 'damaged': 0, 'cost': cost, 'exp': '',
            'location': (r.get('lokasi') or '').strip(), 'supplier': (r.get('supplier') or '').strip(),
            'min': 0, 'unit': unit, 'weight': 1 if unit.lower() in ('kg', 'liter') else 0, 'secondary': '',
        })
    return rows


def suppliers_from_products(products: List[dict]) -> List[dict]:
    by_sup = {}
    for p in products:
        name = p.get('supplier')
        if not name:
            continue
        by_sup.setdefault(name, []).append(p.get('category', ''))
    result = []
    for name, cats in by_sup.items():
        top_cat = Counter([c for c in cats if c]).most_common(1)
        result.append({
            'id': new_id(), 'name': name, 'pic': '', 'phone': '', 'email': '', 'address': '',
            'category': top_cat[0][0] if top_cat else '',
        })
    return result


async def seed_master(force: bool = False):
    if force:
        # Reset penuh: semua master dan dokumen operasional dikosongkan agar SKU baru tidak bercampur.
        for collection in (
            db.stack_allocations, db.stack_history, db.stack_treatments, db.transactions,
            db.surat_jalan, db.purchase_orders, db.outbound_loads, db.products,
            db.suppliers, db.counters,
        ):
            await collection.delete_many({})
    text = (ROOT_DIR / 'seed_data.csv').read_text(encoding='utf-8')
    rows = parse_seed_rows(text)
    if await db.products.count_documents({}) == 0:
        for r in rows:
            r['id'] = new_id()
        if rows:
            await db.products.insert_many(rows)
    if await db.suppliers.count_documents({}) == 0:
        sups = suppliers_from_products(rows)
        if sups:
            await db.suppliers.insert_many(sups)


async def seed_admin():
    username = os.environ.get("ADMIN_USERNAME", "admin").strip().lower()
    existing = await db.users.find_one({"username": username})
    if existing:
        return
    password = os.environ.get("ADMIN_PASSWORD", "")
    if len(password) < 8:
        raise RuntimeError("ADMIN_PASSWORD minimal 8 karakter wajib diatur saat membuat administrator pertama")
    await db.users.insert_one({
        "id": new_id(), "name": "Administrator Gudang", "username": username,
        "email": os.environ.get("ADMIN_EMAIL", ""), "role": "Administrator", "active": True,
        "auth_provider": "local", "password_hash": hash_password(password),
        "created_at": now_iso(),
    })


async def create_unique_index_safely(collection, keys, **kwargs):
    try:
        await collection.create_index(keys, unique=True, **kwargs)
    except OperationFailure as exc:
        logger.error("Index unik gagal dibuat; periksa data ganda pada %s: %s", collection.name, exc)


async def initialize_app():
    await db.users.create_index("username", unique=True)
    await db.user_sessions.create_index("session_token")
    await db.products.create_index("sku")
    await db.stack_allocations.create_index([("productId", 1), ("stackCode", 1)], unique=True)
    await create_unique_index_safely(db.consignment_layouts, [("destination", 1), ("productId", 1)])
    await db.consignment_layout_history.create_index([("destination", 1), ("time", -1)])
    await db.consignment_opnames.create_index([("destination", 1), ("time", -1)])
    await db.login_attempts.create_index("identifier")
    await create_unique_index_safely(db.surat_jalan, "no", sparse=True)
    await create_unique_index_safely(db.purchase_orders, "no", sparse=True)
    await create_unique_index_safely(db.surat_jalan, [("operational_date", 1), ("antrian", 1)], sparse=True)
    await seed_admin()
    await seed_master()


# ---------- models ----------
class LoginBody(BaseModel):
    username: str
    password: str


class SessionBody(BaseModel):
    session_id: str


class UserCreate(BaseModel):
    name: str
    username: str
    email: str = ''
    role: Literal['Administrator', 'Supervisor', 'Operator', 'QC', 'Pemantau', 'Superadmin', 'Admin'] = 'Operator'
    password: str


class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    role: Optional[Literal['Administrator', 'Supervisor', 'Operator', 'QC', 'Pemantau', 'Superadmin', 'Admin']] = None
    active: Optional[bool] = None


class PasswordBody(BaseModel):
    password: str


class ProductBody(BaseModel):
    name: str
    sku: str
    category: str = ''
    stock: float = Field(default=0, ge=0)
    damaged: float = Field(default=0, ge=0)
    cost: float = Field(default=0, ge=0)
    exp: str = ''
    location: str = ''
    supplier: str = ''
    min: float = Field(default=0, ge=0)
    unit: str = 'Pcs'
    weight: float = Field(default=0, ge=0)
    secondary: str = ''
    secondaryQty: float = Field(default=0, ge=0)


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    sku: Optional[str] = None
    category: Optional[str] = None
    stock: Optional[float] = Field(default=None, ge=0)
    damaged: Optional[float] = Field(default=None, ge=0)
    cost: Optional[float] = Field(default=None, ge=0)
    exp: Optional[str] = None
    location: Optional[str] = None
    supplier: Optional[str] = None
    min: Optional[float] = Field(default=None, ge=0)
    unit: Optional[str] = None
    weight: Optional[float] = Field(default=None, ge=0)
    secondary: Optional[str] = None
    secondaryQty: Optional[float] = Field(default=None, ge=0)


class SupplierBody(BaseModel):
    name: str
    pic: str = ''
    phone: str = ''
    email: str = ''
    address: str = ''
    category: str = ''


class TxnItem(BaseModel):
    productId: str
    qty: float = Field(gt=0)


class TxnBody(BaseModel):
    type: str
    items: List[TxnItem]
    party: str = ''
    ref: str = ''
    polisi: str = ''
    kondisi: str = 'BAIK'
    keterangan: str = ''


class SJStatusBody(BaseModel):
    status: str


class POItem(BaseModel):
    name: str
    qty: float = Field(gt=0)
    cost: float = Field(ge=0)


class POBody(BaseModel):
    supplier: str
    items: List[POItem] = Field(min_length=1)
    total: float = Field(ge=0)
    status: str = 'Draft'
    date: str = ''


DEFAULT_CATEGORY_ITEMS = [
    {"name": "Beras", "color": "#f59e0b", "active": True},
    {"name": "Minyak", "color": "#eab308", "active": True},
    {"name": "Gula", "color": "#ec4899", "active": True},
    {"name": "Tepung", "color": "#a855f7", "active": True},
    {"name": "Sarden", "color": "#3b82f6", "active": True},
    {"name": "Teh", "color": "#22c55e", "active": True},
    {"name": "Margarin", "color": "#f97316", "active": True},
    {"name": "Kecap", "color": "#8b5cf6", "active": True},
    {"name": "Kopi", "color": "#b45309", "active": True},
    {"name": "Susu", "color": "#22d3ee", "active": True},
]


class CategorySetting(BaseModel):
    name: str
    color: str = '#64748b'
    active: bool = True


class SettingsBody(BaseModel):
    warehouse: str = 'Gudang Sunter Timur I & II'
    address: str = 'Jl. Sunter Agung, Jakarta Utara'
    warehouseHead: str = 'Irsa Maulian Nugraha'
    categories: List[CategorySetting] = Field(default_factory=lambda: [CategorySetting(**item) for item in DEFAULT_CATEGORY_ITEMS])
    lowAlert: bool = True
    expAlert: bool = True
    autoQueue: bool = True


DEFAULT_SETTINGS = SettingsBody().model_dump()


def build_xlsx(headers: list[str], rows: list[list], sheet_name: str) -> io.BytesIO:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name[:31]

    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal='center')

    for row in rows:
        ws.append(row)

    for column in ws.columns:
        max_len = 0
        letter = column[0].column_letter
        for cell in column:
            value = '' if cell.value is None else str(cell.value)
            max_len = max(max_len, len(value))
        ws.column_dimensions[letter].width = min(max(max_len + 2, 10), 42)

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output


# ---------- auth ----------
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


@api_router.post("/auth/login")
async def login(body: LoginBody, request: Request, response: Response):
    username = body.username.strip().lower()
    identifier = username
    attempt = await db.login_attempts.find_one({"identifier": identifier}, {"_id": 0})
    if attempt and attempt.get("count", 0) >= MAX_LOGIN_ATTEMPTS:
        locked_until = datetime.fromisoformat(attempt["last_attempt"]) + timedelta(minutes=LOCKOUT_MINUTES)
        if datetime.now(timezone.utc) < locked_until:
            raise HTTPException(status_code=429, detail=f"Terlalu banyak percobaan gagal. Coba lagi dalam {LOCKOUT_MINUTES} menit.")
        await db.login_attempts.delete_one({"identifier": identifier})
    user = await db.users.find_one({"username": username})
    if not user or not user.get("password_hash") or not verify_password(body.password, user["password_hash"]):
        await db.login_attempts.update_one(
            {"identifier": identifier},
            {"$inc": {"count": 1}, "$set": {"last_attempt": now_iso()}},
            upsert=True,
        )
        raise HTTPException(status_code=401, detail="Username atau password salah")
    if not user.get("active", True):
        raise HTTPException(status_code=403, detail="Akun dinonaktifkan. Hubungi administrator.")
    await db.login_attempts.delete_one({"identifier": identifier})
    token = create_access_token(user["id"])
    response.set_cookie("access_token", token, httponly=True, secure=True, samesite="none", max_age=604800, path="/")
    return {"user": public_user(user), "token": token}


@api_router.post("/auth/session")
async def google_session(body: SessionBody, response: Response):
    if not GOOGLE_SESSION_URL:
        raise HTTPException(status_code=503, detail="Login Google belum dikonfigurasi")
    try:
        async with httpx.AsyncClient() as hc:
            resp = await hc.get(
                GOOGLE_SESSION_URL,
                headers={"X-Session-ID": body.session_id},
                timeout=15.0,
            )
    except httpx.RequestError as exc:
        logger.warning("Layanan login Google tidak dapat dihubungi: %s", exc)
        raise HTTPException(status_code=502, detail="Layanan login Google tidak dapat dihubungi") from exc
    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Session ID tidak valid")
    data = resp.json()
    email = data.get("email", "").lower()
    user = await db.users.find_one({"email": email})
    if not user:
        user = {
            "id": new_id(), "name": data.get("name") or email, "username": email,
            "email": email, "role": "Pemantau", "active": True,
            "auth_provider": "google", "picture": data.get("picture", ""),
            "created_at": now_iso(),
        }
        await db.users.insert_one(dict(user))
    if not user.get("active", True):
        raise HTTPException(status_code=403, detail="Akun dinonaktifkan. Hubungi administrator.")
    session_token = data["session_token"]
    await db.user_sessions.insert_one({
        "user_id": user["id"], "session_token": session_token,
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
        "created_at": now_iso(),
    })
    response.set_cookie("session_token", session_token, httponly=True, secure=True, samesite="none", max_age=604800, path="/")
    return {"user": public_user(user), "session_token": session_token}


@api_router.get("/auth/me")
async def me(user: dict = Depends(get_current_user)):
    return public_user(user)


@api_router.post("/auth/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get("session_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if token:
        await db.user_sessions.delete_many({"session_token": token})
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("session_token", path="/")
    return {"ok": True}


# ---------- settings ----------
@api_router.get("/settings")
async def get_settings(user: dict = Depends(get_current_user)):
    doc = await db.settings.find_one({"_id": "app"}, {"_id": 0})
    result = {**DEFAULT_SETTINGS, **(doc or {})}
    result["categories"] = [dict(item) for item in result.get("categories", [])]
    # Kategori lama yang telah terpakai tetap ditampilkan supaya tidak kehilangan konteks produk.
    names = {str(item.get("name", "")).strip().lower() for item in result.get("categories", [])}
    used_categories = await db.products.distinct("category", {"category": {"$ne": ""}})
    for name in used_categories:
        cleaned = str(name or "").strip()
        if cleaned and cleaned.lower() not in names:
            result["categories"].append({"name": cleaned, "color": "#64748b", "active": True})
            names.add(cleaned.lower())
    return result


@api_router.put("/settings")
async def update_settings(body: SettingsBody, admin: dict = Depends(require_admin)):
    payload = body.model_dump()
    normalized_categories = []
    names = set()
    for item in payload.get("categories", []):
        name = str(item.get("name", "")).strip()
        color = str(item.get("color", "#64748b")).strip()
        if not name:
            raise HTTPException(status_code=400, detail="Nama kategori wajib diisi")
        if name.lower() in names:
            raise HTTPException(status_code=400, detail=f"Kategori {name} tercatat lebih dari sekali")
        if not color.startswith("#") or len(color) not in (4, 7):
            raise HTTPException(status_code=400, detail=f"Warna kategori {name} tidak valid")
        names.add(name.lower())
        normalized_categories.append({"name": name, "color": color, "active": bool(item.get("active", True))})
    used_categories = {str(item).strip().lower() for item in await db.products.distinct("category", {"category": {"$ne": ""}}) if str(item).strip()}
    missing = used_categories - names
    if missing:
        raise HTTPException(status_code=400, detail=f"Kategori masih dipakai produk dan tidak dapat dihapus: {', '.join(sorted(missing))}")
    payload["categories"] = normalized_categories
    payload["updated_at"] = now_iso()
    payload["updated_by"] = admin["name"]
    await db.settings.update_one({"_id": "app"}, {"$set": payload}, upsert=True)
    return {**DEFAULT_SETTINGS, **payload}


# ---------- users (admin) ----------
@api_router.get("/users")
async def list_users(user: dict = Depends(require_admin)):
    users = await db.users.find({}, {"_id": 0, "password_hash": 0}).sort("created_at", 1).to_list(500)
    return [public_user(item) for item in users]


@api_router.post("/users")
async def create_user(body: UserCreate, admin: dict = Depends(require_admin)):
    username = body.username.strip().lower()
    if not username or not body.password:
        raise HTTPException(status_code=400, detail="Username & password wajib diisi")
    if len(body.password) < 6:
        raise HTTPException(status_code=400, detail="Password minimal 6 karakter")
    if await db.users.find_one({"username": username}):
        raise HTTPException(status_code=400, detail="Username sudah digunakan")
    doc = {
        "id": new_id(), "name": body.name.strip(), "username": username,
        "email": body.email.strip(), "role": canonical_role(body.role), "active": True,
        "auth_provider": "local", "password_hash": hash_password(body.password),
        "created_at": now_iso(),
    }
    await db.users.insert_one(dict(doc))
    return public_user(doc)


@api_router.put("/users/{user_id}")
async def update_user(user_id: str, body: UserUpdate, admin: dict = Depends(require_admin)):
    patch = body.model_dump(exclude_unset=True, exclude_none=True)
    target = await db.users.find_one({"id": user_id}, {"_id": 0})
    if not target:
        raise HTTPException(status_code=404, detail="Pengguna tidak ditemukan")
    if "role" in patch:
        patch["role"] = canonical_role(patch["role"])
    if target["id"] == admin["id"] and (patch.get("role") not in (None, "Administrator") or patch.get("active") is False):
        raise HTTPException(status_code=400, detail="Tidak dapat menurunkan/menonaktifkan akun sendiri")
    if patch:
        await db.users.update_one({"id": user_id}, {"$set": patch})
    updated = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})
    return public_user(updated)


@api_router.put("/users/{user_id}/password")
async def change_password(user_id: str, body: PasswordBody, user: dict = Depends(get_current_user)):
    if not has_role_permission(user.get("role"), "users") and user["id"] != user_id:
        raise HTTPException(status_code=403, detail="Tidak diizinkan mengubah password pengguna lain")
    if len(body.password) < 6:
        raise HTTPException(status_code=400, detail="Password minimal 6 karakter")
    target = await db.users.find_one({"id": user_id})
    if not target:
        raise HTTPException(status_code=404, detail="Pengguna tidak ditemukan")
    await db.users.update_one({"id": user_id}, {"$set": {"password_hash": hash_password(body.password)}})
    return {"ok": True}


@api_router.delete("/users/{user_id}")
async def delete_user(user_id: str, admin: dict = Depends(require_admin)):
    if user_id == admin["id"]:
        raise HTTPException(status_code=400, detail="Tidak dapat menghapus akun sendiri")
    target = await db.users.find_one({"id": user_id})
    if not target:
        raise HTTPException(status_code=404, detail="Pengguna tidak ditemukan")
    if canonical_role(target.get("role")) == ROLE_SUPERADMIN:
        admins = await db.users.count_documents({"role": "Administrator"})
        if admins <= 1:
            raise HTTPException(status_code=400, detail="Minimal harus ada satu Administrator")
    await db.users.delete_one({"id": user_id})
    await db.user_sessions.delete_many({"user_id": user_id})
    return {"ok": True}


# ---------- products ----------
@api_router.get("/products")
async def list_products(user: dict = Depends(get_current_user)):
    return await db.products.find({}, {"_id": 0}).sort("name", 1).to_list(2000)


@api_router.post("/products")
async def create_product(body: ProductBody, user: dict = Depends(require_write)):
    doc = body.model_dump()
    doc["sku"] = doc["sku"].strip()
    if not doc["sku"]:
        raise HTTPException(status_code=400, detail="SKU wajib diisi")
    if await db.products.find_one({"sku": doc["sku"]}):
        raise HTTPException(status_code=409, detail="SKU sudah digunakan")
    doc["id"] = new_id()
    await db.products.insert_one(dict(doc))
    return doc


@api_router.put("/products/{product_id}")
async def update_product(product_id: str, body: ProductUpdate, user: dict = Depends(require_write)):
    patch = body.model_dump(exclude_unset=True, exclude_none=True)
    if "sku" in patch:
        patch["sku"] = patch["sku"].strip()
        if not patch["sku"]:
            raise HTTPException(status_code=400, detail="SKU wajib diisi")
        duplicate = await db.products.find_one({"sku": patch["sku"], "id": {"$ne": product_id}})
        if duplicate:
            raise HTTPException(status_code=409, detail="SKU sudah digunakan")
    if patch:
        result = await db.products.update_one({"id": product_id}, {"$set": patch})
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Produk tidak ditemukan")
    return await db.products.find_one({"id": product_id}, {"_id": 0})


@api_router.delete("/products/{product_id}")
async def delete_product(product_id: str, user: dict = Depends(require_write)):
    result = await db.products.delete_one({"id": product_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Produk tidak ditemukan")
    return {"ok": True}


# ---------- suppliers ----------
@api_router.get("/suppliers")
async def list_suppliers(user: dict = Depends(get_current_user)):
    return await db.suppliers.find({}, {"_id": 0}).sort("name", 1).to_list(1000)


@api_router.post("/suppliers")
async def create_supplier(body: SupplierBody, user: dict = Depends(require_write)):
    doc = body.model_dump()
    doc["id"] = new_id()
    await db.suppliers.insert_one(dict(doc))
    return doc


@api_router.put("/suppliers/{supplier_id}")
async def update_supplier(supplier_id: str, body: SupplierBody, user: dict = Depends(require_write)):
    result = await db.suppliers.update_one({"id": supplier_id}, {"$set": body.model_dump()})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Supplier tidak ditemukan")
    return await db.suppliers.find_one({"id": supplier_id}, {"_id": 0})


@api_router.delete("/suppliers/{supplier_id}")
async def delete_supplier(supplier_id: str, user: dict = Depends(require_write)):
    result = await db.suppliers.delete_one({"id": supplier_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Supplier tidak ditemukan")
    return {"ok": True}


# ---------- transactions & surat jalan ----------
@api_router.get("/transactions")
async def list_transactions(user: dict = Depends(get_current_user)):
    return await db.transactions.find({}, {"_id": 0}).sort("time", -1).to_list(2000)


@api_router.post("/transactions")
async def create_transaction(body: TxnBody, user: dict = Depends(require_write)):
    if body.type not in ("MASUK", "KELUAR"):
        raise HTTPException(status_code=400, detail="Jenis transaksi tidak valid")
    if body.kondisi not in ("BAIK", "RUSAK"):
        raise HTTPException(status_code=400, detail="Kondisi stok tidak valid")
    if not body.items:
        raise HTTPException(status_code=400, detail="Pilih minimal satu produk")

    products = []
    for it in body.items:
        prod = await db.products.find_one({"id": it.productId}, {"_id": 0})
        if not prod:
            raise HTTPException(status_code=404, detail="Produk tidak ditemukan")
        if body.type == "KELUAR" and body.kondisi == "BAIK" and it.qty > prod.get("stock", 0):
            raise HTTPException(status_code=400, detail=f"Stok {prod['name']} tidak mencukupi (tersisa {prod.get('stock', 0)})")
        if body.type == "KELUAR" and body.kondisi == "RUSAK" and it.qty > prod.get("damaged", 0):
            raise HTTPException(status_code=400, detail=f"Stok rusak {prod['name']} tidak mencukupi (tersisa {prod.get('damaged', 0)})")
        products.append(prod)

    time = now_iso()
    op_now = operational_now()
    operation_id = new_id()
    transaction_ref = body.ref or f"{'IN' if body.type == 'MASUK' else 'OUT'}-{op_now.strftime('%Y%m%d%H%M%S%f')}"
    antrian = ""
    sj = None
    if body.type == "KELUAR":
        operational_date = op_now.strftime("%Y-%m-%d")
        settings = await db.settings.find_one({"_id": "app"}, {"_id": 0, "autoQueue": 1}) or {}
        if settings.get("autoQueue", True):
            day_start = op_now.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)
            day_query = {"time": {"$gte": day_start.astimezone(timezone.utc).isoformat(), "$lt": day_end.astimezone(timezone.utc).isoformat()}}
            queue_floor = await max_suffix(db.surat_jalan, "antrian", "A-", day_query)
            queue_number = await next_sequence(f"queue:{operational_date}", queue_floor)
            antrian = f"A-{queue_number:03d}"

        month_prefix = op_now.strftime("SJ-%Y%m")
        sj_floor = await max_suffix(db.surat_jalan, "no", f"{month_prefix}-")
        sj_number = await next_sequence(f"surat-jalan:{op_now.strftime('%Y%m')}", sj_floor)
        sj_items = []
        total_berat = 0.0
        total_unit = 0.0
        for it, prod in zip(body.items, products):
            berat = (prod.get("weight") or 0) * it.qty
            total_berat += berat
            total_unit += it.qty
            sj_items.append({"name": prod["name"], "qty": it.qty, "unit": prod.get("unit", ""), "berat": berat, "sec": ""})
        sj = {
            "id": new_id(), "operation_id": operation_id,
            "no": f"{month_prefix}-{sj_number:03d}", "antrian": antrian,
            "operational_date": operational_date,
            "time": time, "penerima": body.party or "-", "polisi": body.polisi, "operator": user["name"],
            "status": "Menunggu", "ref": body.ref, "items": sj_items, "berat": total_berat, "unit": total_unit,
        }

    txns = []
    stock_changes = []
    try:
        for it, prod in zip(body.items, products):
            field = "damaged" if body.kondisi == "RUSAK" else "stock"
            delta = it.qty if body.type == "MASUK" else -it.qty
            stock_query = {"id": prod["id"]}
            if body.type == "KELUAR":
                stock_query[field] = {"$gte": it.qty}
            result = await db.products.update_one(stock_query, {"$inc": {field: delta}})
            if result.matched_count == 0:
                raise HTTPException(status_code=409, detail=f"Stok {prod['name']} berubah atau tidak mencukupi. Muat ulang lalu coba kembali.")
            stock_changes.append((prod["id"], field, delta))
            txns.append({
                "id": new_id(), "operation_id": operation_id, "time": time,
                "ref": transaction_ref, "antrian": antrian, "type": body.type,
                "kondisi": body.kondisi, "product": prod["name"], "sku": prod.get("sku", ""),
                "change": delta, "penerima": body.party or "-", "polisi": body.polisi,
                "operator": user["name"], "keterangan": body.keterangan,
            })

        if sj:
            await db.surat_jalan.insert_one(dict(sj))
        if txns:
            await db.transactions.insert_many([dict(txn) for txn in txns])
    except Exception:
        await db.transactions.delete_many({"operation_id": operation_id})
        await db.surat_jalan.delete_many({"operation_id": operation_id})
        for product_id, field, delta in reversed(stock_changes):
            await db.products.update_one({"id": product_id}, {"$inc": {field: -delta}})
        raise

    return {"transactions": txns, "suratJalan": sj}


@api_router.get("/surat-jalan")
async def list_surat_jalan(user: dict = Depends(get_current_user)):
    return await db.surat_jalan.find({}, {"_id": 0}).sort("time", -1).to_list(1000)


@api_router.put("/surat-jalan/{sj_id}/status")
async def update_sj_status(sj_id: str, body: SJStatusBody, user: dict = Depends(require_write)):
    result = await db.surat_jalan.update_one({"id": sj_id}, {"$set": {"status": body.status}})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Surat jalan tidak ditemukan")
    return await db.surat_jalan.find_one({"id": sj_id}, {"_id": 0})


# ---------- purchase orders ----------
@api_router.get("/purchase-orders")
async def list_pos(user: dict = Depends(get_current_user)):
    return await db.purchase_orders.find({}, {"_id": 0}).sort("date", -1).to_list(1000)


@api_router.post("/purchase-orders")
async def create_po(body: POBody, user: dict = Depends(require_write)):
    year = operational_now().strftime("%Y")
    prefix = f"PO-{year}-"
    floor = await max_suffix(db.purchase_orders, "no", prefix)
    number = await next_sequence(f"purchase-order:{year}", floor)
    doc = {
        "id": new_id(), "no": f"{prefix}{number:03d}", "supplier": body.supplier,
        "date": body.date or now_iso(), "status": body.status,
        "items": [i.model_dump() for i in body.items],
        "total": sum(i.qty * i.cost for i in body.items),
    }
    await db.purchase_orders.insert_one(dict(doc))
    return doc


# ---------- exports ----------
@api_router.get("/export/products.xlsx")
async def export_products(user: dict = Depends(get_current_user)):
    products = await db.products.find({}, {"_id": 0}).sort("name", 1).to_list(5000)
    headers = [
        "Nama Produk", "SKU", "Kategori", "Stok Baik", "Stok Rusak", "Satuan",
        "Harga Modal", "Nilai Total", "Supplier", "Lokasi", "Stok Minimum",
        "Berat/Unit (kg)", "Kemasan Sekunder", "Isi/Kemasan Sekunder",
        "Berat/Kemasan Sekunder (kg)", "Kedaluwarsa"
    ]
    rows = [
        [
            p.get("name", ""), p.get("sku", ""), p.get("category", ""),
            p.get("stock", 0), p.get("damaged", 0), p.get("unit", ""),
            p.get("cost", 0), (p.get("stock", 0) or 0) * (p.get("cost", 0) or 0),
            p.get("supplier", ""), p.get("location", ""), p.get("min", 0),
            p.get("weight", 0), p.get("secondary", ""), p.get("secondaryQty", 0),
            (p.get("weight", 0) or 0) * (p.get("secondaryQty", 0) or 0), p.get("exp", "")
        ]
        for p in products
    ]
    output = build_xlsx(headers, rows, "Daftar Produk")
    filename = f"daftar_produk_{operational_now().strftime('%Y%m%d_%H%M')}.xlsx"
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@api_router.get("/export/transactions.xlsx")
async def export_transactions_current_month(user: dict = Depends(get_current_user)):
    now = operational_now()
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)

    transactions = await db.transactions.find(
        {
            "time": {
                "$gte": start.astimezone(timezone.utc).isoformat(),
                "$lt": end.astimezone(timezone.utc).isoformat(),
            }
        },
        {"_id": 0},
    ).sort("time", 1).to_list(10000)

    headers = [
        "Waktu", "No. Referensi", "Antrian", "Tipe", "Kondisi", "Produk", "SKU",
        "Perubahan", "Pihak Terkait", "No. Polisi", "Dicatat Oleh", "Keterangan"
    ]
    rows = [
        [
            t.get("time", ""), t.get("ref", ""), t.get("antrian", ""),
            t.get("type", ""), t.get("kondisi", ""), t.get("product", ""),
            t.get("sku", ""), t.get("change", 0), t.get("penerima", ""),
            t.get("polisi", ""), t.get("operator", ""), t.get("keterangan", "")
        ]
        for t in transactions
    ]
    output = build_xlsx(headers, rows, "Riwayat Transaksi")
    filename = f"riwayat_transaksi_{start.strftime('%Y_%m')}.xlsx"
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------- import & admin ----------
@api_router.post("/import/csv")
async def import_csv(file: UploadFile = File(...), user: dict = Depends(require_write)):
    content = (await file.read()).decode("utf-8-sig", errors="replace")
    rows = parse_seed_rows(content)
    if not rows:
        raise HTTPException(status_code=400, detail="File tidak berisi data valid. Gunakan template dengan pemisah ';'")
    inserted, updated = 0, 0
    for r in rows:
        existing = await db.products.find_one({"sku": r["sku"]})
        if existing:
            await db.products.update_one({"sku": r["sku"]}, {"$set": {k: v for k, v in r.items() if k != "damaged"}})
            updated += 1
        else:
            r["id"] = new_id()
            await db.products.insert_one(dict(r))
            inserted += 1
    existing_sups = {s["name"] for s in await db.suppliers.find({}, {"_id": 0, "name": 1}).to_list(1000)}
    for sup in suppliers_from_products(rows):
        if sup["name"] not in existing_sups:
            await db.suppliers.insert_one(dict(sup))
    return {"inserted": inserted, "updated": updated}


@api_router.post("/admin/reset-data")
async def reset_data(admin: dict = Depends(require_admin)):
    await seed_master(force=True)
    return {"ok": True, "message": "Data operasional direset. Master produk dan supplier dimuat dari CSV seed bila tersedia."}


@api_router.get("/")
async def root():
    return {"message": "Bulog Gudang API"}


app.include_router(api_router)

cors_origins = [
    origin.strip()
    for origin in os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")
    if origin.strip() and origin.strip() != "*"
]

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
