import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException

from lib.auth import principal
from lib.db import db
from lib.seeder import run_seed
from models.importing import ProductImportRequest, ProductImportResult
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


def _mask_prices(product: Product, role: Optional[str]) -> Product:
    """Viewers see quantities only — money fields are stripped server-side."""
    if role == "viewer":
        product.purchase_price = 0
        product.selling_price = 0
    return product


@router.get("/products", response_model=List[Product])
async def list_products(caller=Depends(principal)):
    docs = await db.products.find().sort("name", 1).to_list(1000)
    role = caller.role if caller else None
    return [_mask_prices(Product(**d), role) for d in docs]


@router.get("/products/{product_id}", response_model=Product)
async def get_product(product_id: str, caller=Depends(principal)):
    doc = await db.products.find_one({"id": product_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Produk tidak ditemukan")
    return _mask_prices(Product(**doc), caller.role if caller else None)


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


@router.post("/products/import", response_model=ProductImportResult)
async def import_products(payload: ProductImportRequest):
    """Bulk create/update products by SKU. One supplier may supply many products."""
    if not payload.items:
        raise HTTPException(status_code=400, detail="Tidak ada baris data untuk diimpor")

    result = ProductImportResult()
    today = datetime.now(timezone.utc).date().isoformat()

    default_supplier_name = ""
    if payload.supplier_id:
        doc = await db.suppliers.find_one({"id": payload.supplier_id})
        if not doc:
            raise HTTPException(status_code=404, detail="Supplier default tidak ditemukan")
        default_supplier_name = doc["name"]

    for index, row in enumerate(payload.items, start=1):
        sku = row.sku.strip()
        if not sku:
            result.errors.append(f"Baris {index}: kode SKU wajib diisi")
            continue
        if row.quantity < 0:
            result.errors.append(f"Baris {index} ({sku}): jumlah tidak boleh negatif")
            continue

        # Resolve the supplier: explicit name on the row wins, else the form default.
        supplier_id = payload.supplier_id
        supplier_name = default_supplier_name
        if row.supplier_name and row.supplier_name.strip():
            wanted = row.supplier_name.strip()
            found = await db.suppliers.find_one({"name": {"$regex": f"^{re.escape(wanted)}$", "$options": "i"}})
            if not found:
                created_supplier = Supplier(name=wanted, phone="")
                await db.suppliers.insert_one(created_supplier.model_dump())
                result.suppliers_created += 1
                supplier_id, supplier_name = created_supplier.id, created_supplier.name
            else:
                supplier_id, supplier_name = found["id"], found["name"]

        existing = await db.products.find_one({"sku": sku})

        if existing:
            current = int(existing.get("current_stock", 0))
            new_stock = current + row.quantity if payload.mode == "add" else row.quantity
            update: Dict[str, object] = {"current_stock": new_stock}
            if row.name.strip():
                update["name"] = row.name.strip()
            for field, value in (
                ("category", row.category),
                ("unit", row.unit),
                ("location", row.location),
            ):
                if value is not None and str(value).strip():
                    update[field] = str(value).strip()
            for field, value in (("purchase_price", row.purchase_price), ("selling_price", row.selling_price)):
                if value is not None:
                    update[field] = float(value)
            if supplier_id:
                update["supplier_id"] = supplier_id
                update["supplier_name"] = supplier_name

            await db.products.update_one({"id": existing["id"]}, {"$set": update})
            result.updated += 1

            delta = new_stock - current
            if delta != 0:
                tx = Transaction(
                    product_id=existing["id"],
                    product_name=str(update.get("name", existing.get("name", ""))),
                    product_sku=sku,
                    category=str(update.get("category", existing.get("category", "Lainnya"))),
                    type="MASUK" if delta > 0 else "KELUAR",
                    quantity=abs(delta),
                    stock_after=new_stock,
                    party=supplier_name,
                    reference_no="IMPORT-DATA",
                    notes="Penyesuaian stok dari import data",
                    date=today,
                )
                await db.transactions.insert_one(tx.model_dump())
                if delta > 0:
                    result.units_added += delta
            continue

        if not row.name.strip():
            result.errors.append(f"Baris {index} ({sku}): nama produk wajib untuk SKU baru")
            continue

        product = Product(
            name=row.name.strip(),
            sku=sku,
            category=(row.category or "Lainnya").strip() or "Lainnya",
            unit=(row.unit or "Pcs").strip() or "Pcs",
            purchase_price=float(row.purchase_price or 0),
            selling_price=float(row.selling_price or 0),
            current_stock=row.quantity,
            supplier_id=supplier_id,
            supplier_name=supplier_name,
            location=(row.location or "").strip(),
        )
        await db.products.insert_one(product.model_dump())
        result.created += 1

        if row.quantity > 0:
            tx = Transaction(
                product_id=product.id,
                product_name=product.name,
                product_sku=product.sku,
                category=product.category,
                type="MASUK",
                quantity=row.quantity,
                stock_after=row.quantity,
                party=supplier_name,
                reference_no="IMPORT-DATA",
                notes="Stok awal dari import data",
                date=today,
            )
            await db.transactions.insert_one(tx.model_dump())
            result.units_added += row.quantity

    return result


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
async def get_stats(caller=Depends(principal)):
    products = await db.products.find().to_list(1000)
    total_units = sum(int(p.get("current_stock", 0)) for p in products)
    valuation = sum(float(p.get("purchase_price", 0)) * int(p.get("current_stock", 0)) for p in products)
    if caller and caller.role == "viewer":
        valuation = 0.0

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
