import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.server import db, get_current_user, new_id, now_iso, require_write

router = APIRouter(prefix="/api")


def valid_stack_codes() -> set[str]:
    unit_codes = {
        f"{unit}/{zone}{number:02d}"
        for unit in range(17, 25)
        for zone in ("A", "B", "C")
        for number in range(1, 5)
    }
    mp_codes = {
        f"MP/{zone}{number:02d}"
        for zone in ("A", "B")
        for number in range(1, 9)
    }
    return unit_codes | mp_codes


VALID_STACK_CODES = valid_stack_codes()


class StackAllocationBody(BaseModel):
    productId: str
    stackCode: str
    length: int = Field(ge=1, le=1000)
    width: int = Field(ge=1, le=1000)
    height: int = Field(ge=1, le=1000)
    note: str = ""


async def _build_allocation(body: StackAllocationBody, allocation_id: Optional[str] = None) -> dict:
    stack_code = body.stackCode.strip().upper()
    if stack_code not in VALID_STACK_CODES:
        raise HTTPException(status_code=400, detail="Kode tumpukan tidak valid")

    product = await db.products.find_one({"id": body.productId}, {"_id": 0})
    if not product:
        raise HTTPException(status_code=404, detail="Produk tidak ditemukan")

    per_secondary = float(product.get("secondaryQty", 0) or 0)
    secondary = str(product.get("secondary", "") or "").strip()
    if per_secondary <= 0 or not secondary:
        raise HTTPException(
            status_code=400,
            detail="Atur kemasan sekunder dan isi per kemasan pada master produk terlebih dahulu",
        )

    secondary_count = body.length * body.width * body.height
    primary_qty = secondary_count * per_secondary
    query = {"productId": body.productId}
    if allocation_id:
        query["id"] = {"$ne": allocation_id}
    allocated_elsewhere = 0.0
    async for allocation in db.stack_allocations.find(query, {"_id": 0, "primaryQty": 1}):
        allocated_elsewhere += float(allocation.get("primaryQty", 0) or 0)

    stock = float(product.get("stock", 0) or 0)
    if allocated_elsewhere + primary_qty > stock + 1e-9:
        available = max(stock - allocated_elsewhere, 0)
        raise HTTPException(
            status_code=400,
            detail=(
                f"Alokasi melebihi stok {product.get('name', '')}. "
                f"Tersedia untuk ditempatkan {available:g} {product.get('unit', '')}"
            ),
        )

    duplicate_query = {"productId": body.productId, "stackCode": stack_code}
    if allocation_id:
        duplicate_query["id"] = {"$ne": allocation_id}
    if await db.stack_allocations.find_one(duplicate_query):
        raise HTTPException(status_code=409, detail="Produk tersebut sudah tercatat pada tumpukan ini")

    return {
        "productId": product["id"],
        "sku": product.get("sku", ""),
        "productName": product.get("name", ""),
        "unit": product.get("unit", ""),
        "weight": float(product.get("weight", 0) or 0),
        "secondary": secondary,
        "secondaryQty": per_secondary,
        "stackCode": stack_code,
        "warehouse": stack_code.split("/", 1)[0],
        "zone": re.sub(r"\d", "", stack_code.split("/", 1)[1]),
        "length": body.length,
        "width": body.width,
        "height": body.height,
        "secondaryCount": secondary_count,
        "primaryQty": primary_qty,
        "note": body.note.strip(),
        "arrangementAdjusted": False,
        "updatedAt": now_iso(),
    }


async def reconcile_product_allocations(product_id: str) -> None:
    """Pastikan alokasi lokasi tidak pernah lebih besar daripada stok fisik produk."""
    product = await db.products.find_one({"id": product_id}, {"_id": 0, "stock": 1})
    if not product:
        return
    stock = float(product.get("stock", 0) or 0)
    allocations = await db.stack_allocations.find(
        {"productId": product_id}, {"_id": 0}
    ).sort("updatedAt", -1).to_list(5000)
    allocated = sum(float(item.get("primaryQty", 0) or 0) for item in allocations)
    excess = max(allocated - stock, 0)
    if excess <= 1e-9:
        return

    for allocation in allocations:
        if excess <= 1e-9:
            break
        current = float(allocation.get("primaryQty", 0) or 0)
        if excess >= current - 1e-9:
            await db.stack_allocations.delete_one({"id": allocation["id"]})
            excess -= current
            continue

        remaining = current - excess
        per_secondary = float(allocation.get("secondaryQty", 0) or 0)
        await db.stack_allocations.update_one(
            {"id": allocation["id"]},
            {"$set": {
                "primaryQty": remaining,
                "secondaryCount": int(remaining // per_secondary) if per_secondary > 0 else 0,
                "primaryRemainder": remaining % per_secondary if per_secondary > 0 else remaining,
                "length": 0,
                "width": 0,
                "height": 0,
                "arrangementAdjusted": True,
                "updatedAt": now_iso(),
            }},
        )
        excess = 0


@router.get("/stack-allocations")
async def list_stack_allocations(user: dict = Depends(get_current_user)):
    return await db.stack_allocations.find({}, {"_id": 0}).sort(
        [("stackCode", 1), ("productName", 1)]
    ).to_list(10000)


@router.post("/stack-allocations")
async def create_stack_allocation(body: StackAllocationBody, user: dict = Depends(require_write)):
    allocation = await _build_allocation(body)
    allocation["id"] = new_id()
    allocation["createdAt"] = now_iso()
    await db.stack_allocations.insert_one(dict(allocation))
    return allocation


@router.put("/stack-allocations/{allocation_id}")
async def update_stack_allocation(
    allocation_id: str,
    body: StackAllocationBody,
    user: dict = Depends(require_write),
):
    existing = await db.stack_allocations.find_one({"id": allocation_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Alokasi tumpukan tidak ditemukan")
    allocation = await _build_allocation(body, allocation_id)
    allocation["createdAt"] = existing.get("createdAt", now_iso())
    result = await db.stack_allocations.update_one({"id": allocation_id}, {"$set": allocation})
    if result.matched_count == 0:
        raise HTTPException(status_code=409, detail="Alokasi berubah. Muat ulang lalu coba lagi")
    return {**allocation, "id": allocation_id}


@router.delete("/stack-allocations/{allocation_id}")
async def delete_stack_allocation(allocation_id: str, user: dict = Depends(require_write)):
    result = await db.stack_allocations.delete_one({"id": allocation_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Alokasi tumpukan tidak ditemukan")
    return {"ok": True}
