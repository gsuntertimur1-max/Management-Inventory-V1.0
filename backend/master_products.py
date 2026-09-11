from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.server import db, new_id, require_write

router = APIRouter(prefix="/api")


class MasterProductBody(BaseModel):
    name: str
    sku: str
    category: str = ""
    cost: float = Field(default=0, ge=0)
    location: str = ""
    supplier: str = ""
    min: float = Field(default=0, ge=0)
    unit: str = "Pcs"
    weight: float = Field(default=0, ge=0)
    secondary: str = ""
    secondaryQty: float = Field(default=0, ge=0)


def clean_master(body: MasterProductBody) -> dict:
    doc = body.model_dump()
    doc["name"] = doc["name"].strip()
    doc["sku"] = doc["sku"].strip()
    doc["unit"] = doc["unit"].strip() or "Pcs"
    doc["secondary"] = doc["secondary"].strip()
    if doc["secondary"] and doc["secondaryQty"] <= 0:
        raise HTTPException(status_code=400, detail="Isi kemasan sekunder harus lebih dari 0")
    if doc["secondaryQty"] > 0 and not doc["secondary"]:
        raise HTTPException(status_code=400, detail="Nama kemasan sekunder wajib diisi")
    if doc["secondaryQty"] > 0 and abs(doc["secondaryQty"] - round(doc["secondaryQty"])) > 1e-6:
        raise HTTPException(status_code=400, detail="Isi kemasan sekunder harus berupa jumlah pack utuh")
    if not doc["name"]:
        raise HTTPException(status_code=400, detail="Nama produk wajib diisi")
    if not doc["sku"]:
        raise HTTPException(status_code=400, detail="SKU wajib diisi")
    return doc


@router.post("/products-master")
async def create_master_product(body: MasterProductBody, user: dict = Depends(require_write)):
    master = clean_master(body)
    if await db.products.find_one({"sku": master["sku"]}):
        raise HTTPException(status_code=409, detail="SKU sudah digunakan")

    doc = {
        **master,
        "id": new_id(),
        "stock": 0,
        "damaged": 0,
        "exp": "",
    }
    await db.products.insert_one(dict(doc))
    return doc


@router.put("/products-master/{product_id}")
async def update_master_product(product_id: str, body: MasterProductBody, user: dict = Depends(require_write)):
    master = clean_master(body)
    duplicate = await db.products.find_one({"sku": master["sku"], "id": {"$ne": product_id}})
    if duplicate:
        raise HTTPException(status_code=409, detail="SKU sudah digunakan")

    result = await db.products.update_one({"id": product_id}, {"$set": master})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Produk tidak ditemukan")
    return await db.products.find_one({"id": product_id}, {"_id": 0})


@router.delete("/products-master/{product_id}")
async def delete_master_product(product_id: str, user: dict = Depends(require_write)):
    product = await db.products.find_one({"id": product_id}, {"_id": 0})
    if not product:
        raise HTTPException(status_code=404, detail="Produk tidak ditemukan")

    if float(product.get("stock", 0) or 0) > 0 or float(product.get("damaged", 0) or 0) > 0:
        raise HTTPException(status_code=400, detail="Master produk tidak dapat dihapus karena stok fisik masih tersedia")

    open_po = await db.purchase_orders.find_one({
        "items.productId": product_id,
        "status": {"$nin": ["Selesai", "Diterima"]},
    })
    if open_po:
        raise HTTPException(status_code=400, detail="Master produk masih digunakan pada Purchase Order yang belum selesai")

    await db.products.delete_one({"id": product_id})
    return {"ok": True}
