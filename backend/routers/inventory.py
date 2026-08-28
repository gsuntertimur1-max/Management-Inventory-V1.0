from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException

from lib.db import db
from lib.seeder import run_seed
from models.inventory import (
    CategoryStat,
    Product,
    ProductCreate,
    Stats,
    Supplier,
    SupplierCreate,
    TimelinePoint,
    Transaction,
    TransactionCreate,
)

router = APIRouter()


# ---------- Suppliers ----------
@router.get("/suppliers", response_model=List[Supplier])
async def list_suppliers():
    docs = await db.suppliers.find().sort("name", 1).to_list(500)
    return [Supplier(**d) for d in docs]


@router.post("/suppliers", response_model=Supplier)
async def create_supplier(payload: SupplierCreate):
    supplier = Supplier(**payload.model_dump())
    await db.suppliers.insert_one(supplier.model_dump())
    return supplier


@router.put("/suppliers/{supplier_id}", response_model=Supplier)
async def update_supplier(supplier_id: str, payload: SupplierCreate):
    existing = await db.suppliers.find_one({"id": supplier_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Supplier tidak ditemukan")
    await db.suppliers.update_one({"id": supplier_id}, {"$set": payload.model_dump()})
    await db.products.update_many({"supplier_id": supplier_id}, {"$set": {"supplier_name": payload.name}})
    merged = {**existing, **payload.model_dump()}
    return Supplier(**merged)


@router.delete("/suppliers/{supplier_id}")
async def delete_supplier(supplier_id: str):
    res = await db.suppliers.delete_one({"id": supplier_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Supplier tidak ditemukan")
    await db.products.update_many({"supplier_id": supplier_id},
                                  {"$set": {"supplier_id": None, "supplier_name": ""}})
    return {"ok": True}


# ---------- Products ----------
async def _supplier_name(supplier_id: Optional[str]) -> str:
    if not supplier_id:
        return ""
    doc = await db.suppliers.find_one({"id": supplier_id})
    return doc["name"] if doc else ""


@router.get("/products", response_model=List[Product])
async def list_products():
    docs = await db.products.find().sort("name", 1).to_list(1000)
    return [Product(**d) for d in docs]


@router.get("/products/{product_id}", response_model=Product)
async def get_product(product_id: str):
    doc = await db.products.find_one({"id": product_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Produk tidak ditemukan")
    return Product(**doc)


@router.post("/products", response_model=Product)
async def create_product(payload: ProductCreate):
    if await db.products.find_one({"sku": payload.sku}):
        raise HTTPException(status_code=409, detail="Kode SKU sudah digunakan")
    product = Product(**payload.model_dump(), supplier_name=await _supplier_name(payload.supplier_id))
    await db.products.insert_one(product.model_dump())
    return product


@router.put("/products/{product_id}", response_model=Product)
async def update_product(product_id: str, payload: ProductCreate):
    existing = await db.products.find_one({"id": product_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Produk tidak ditemukan")
    clash = await db.products.find_one({"sku": payload.sku, "id": {"$ne": product_id}})
    if clash:
        raise HTTPException(status_code=409, detail="Kode SKU sudah digunakan produk lain")
    update = payload.model_dump()
    update["supplier_name"] = await _supplier_name(payload.supplier_id)
    await db.products.update_one({"id": product_id}, {"$set": update})
    return Product(**{**existing, **update})


@router.delete("/products/{product_id}")
async def delete_product(product_id: str):
    res = await db.products.delete_one({"id": product_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Produk tidak ditemukan")
    return {"ok": True}


# ---------- Transactions ----------
@router.get("/transactions", response_model=List[Transaction])
async def list_transactions():
    docs = await db.transactions.find().sort("created_at", -1).to_list(1000)
    return [Transaction(**d) for d in docs]


@router.get("/transactions/by-ids", response_model=List[Transaction])
async def transactions_by_ids(ids: str):
    """Batch lookup used by the print surfaces (surat jalan / bon muat)."""
    wanted = [i for i in ids.split(",") if i]
    docs = await db.transactions.find({"id": {"$in": wanted}}).to_list(200)
    by_id = {d["id"]: d for d in docs}
    return [Transaction(**by_id[i]) for i in wanted if i in by_id]


@router.post("/transactions", response_model=Transaction)
async def create_transaction(payload: TransactionCreate):
    product = await db.products.find_one({"id": payload.product_id})
    if not product:
        raise HTTPException(status_code=404, detail="Produk tidak ditemukan")

    stock = int(product.get("current_stock", 0))
    if payload.type == "KELUAR" and payload.quantity > stock:
        raise HTTPException(status_code=400, detail=f"Stok tidak cukup. Tersedia {stock} unit")

    after = stock + payload.quantity if payload.type == "MASUK" else stock - payload.quantity
    today = payload.date or datetime.now(timezone.utc).date().isoformat()

    # Outbound movements get a daily queue number (A-001, A-002, ...) for the bon muat.
    queue_no = ""
    if payload.type == "KELUAR":
        same_day = await db.transactions.count_documents({"type": "KELUAR", "date": today})
        queue_no = f"A-{same_day + 1:03d}"

    tx = Transaction(
        product_id=product["id"],
        product_name=product["name"],
        product_sku=product["sku"],
        category=product.get("category", "Lainnya"),
        type=payload.type,
        quantity=payload.quantity,
        stock_after=after,
        party=payload.party or (product.get("supplier_name", "") if payload.type == "MASUK" else ""),
        reference_no=payload.reference_no,
        queue_no=queue_no,
        notes=payload.notes,
        date=today,
    )
    await db.transactions.insert_one(tx.model_dump())
    await db.products.update_one({"id": product["id"]}, {"$set": {"current_stock": after}})
    return tx


# ---------- Stats ----------
@router.get("/stats", response_model=Stats)
async def get_stats():
    products = await db.products.find().to_list(1000)
    total_units = sum(int(p.get("current_stock", 0)) for p in products)
    valuation = sum(float(p.get("purchase_price", 0)) * int(p.get("current_stock", 0)) for p in products)

    per_cat: Dict[str, int] = {}
    for p in products:
        per_cat[p.get("category", "Lainnya")] = per_cat.get(p.get("category", "Lainnya"), 0) + int(p.get("current_stock", 0))

    now = datetime.now(timezone.utc)
    txs = await db.transactions.find().to_list(2000)
    recent = 0
    buckets: Dict[str, Dict[str, int]] = {}
    for i in range(6, -1, -1):
        buckets[(now - timedelta(days=i)).date().isoformat()] = {"masuk": 0, "keluar": 0}

    for t in txs:
        created = t.get("created_at")
        if isinstance(created, datetime):
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if (now - created).days <= 30:
                recent += int(t.get("quantity", 0))
        key = t.get("date", "")
        if key in buckets:
            side = "masuk" if t.get("type") == "MASUK" else "keluar"
            buckets[key][side] += int(t.get("quantity", 0))

    return Stats(
        total_products=len(products),
        total_units=total_units,
        total_valuation=valuation,
        recent_movements=recent,
        by_category=[CategoryStat(category=k, units=v) for k, v in sorted(per_cat.items())],
        timeline=[TimelinePoint(date=k, masuk=v["masuk"], keluar=v["keluar"]) for k, v in buckets.items()],
    )


@router.post("/seed")
async def seed():
    counts = await run_seed()
    return {"ok": True, **counts}
