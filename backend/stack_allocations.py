import re
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.server import build_xlsx, db, get_current_user, new_id, now_iso, require_write

router = APIRouter(prefix="/api")


def valid_stack_codes() -> set[str]:
    unit_codes = {
        f"{unit}/{zone}{number:02d}"
        for unit in range(17, 25)
        for zone in ("A", "B", "C")
        for number in range(1, 5)
    }
    mp_codes = {
        f"MP1/{zone}{number:02d}"
        for zone in ("A", "B")
        for number in range(1, 9)
    }
    return unit_codes | mp_codes


VALID_STACK_CODES = valid_stack_codes()


async def allocate_stock_to_stack(product: dict, stack_code: str, qty: float, operator: str = "") -> None:
    stack_code = stack_code.strip().upper()
    if stack_code not in VALID_STACK_CODES:
        raise HTTPException(status_code=400, detail="Lokasi tumpukan penerimaan tidak valid")
    per_secondary = float(product.get("secondaryQty", 0) or 0)
    if per_secondary <= 0 or not product.get("secondary"):
        raise HTTPException(status_code=400, detail=f"Kemasan sekunder {product.get('name', '')} belum diatur")
    existing = await db.stack_allocations.find_one({"productId": product["id"], "stackCode": stack_code}, {"_id": 0})
    if existing:
        total = float(existing.get("primaryQty", 0) or 0) + qty
        await db.stack_allocations.update_one({"id": existing["id"]}, {"$set": {
            "primaryQty": total, "secondaryCount": int(total // per_secondary),
            "primaryRemainder": total % per_secondary, "length": 0, "width": 0, "height": 0,
            "arrangementAdjusted": True, "updatedAt": now_iso(),
        }})
        return
    await db.stack_allocations.insert_one({
        "id": new_id(), "productId": product["id"], "sku": product.get("sku", ""),
        "productName": product.get("name", ""), "unit": product.get("unit", ""),
        "weight": float(product.get("weight", 0) or 0), "secondary": product.get("secondary", ""),
        "secondaryQty": per_secondary, "stackCode": stack_code, "warehouse": stack_code.split('/')[0],
        "zone": re.sub(r"\d", "", stack_code.split('/')[1]), "length": 0, "width": 0, "height": 0,
        "secondaryCount": int(qty // per_secondary), "primaryRemainder": qty % per_secondary,
        "primaryQty": qty, "note": f"Penerimaan oleh {operator}" if operator else "Penerimaan",
        "arrangementAdjusted": True, "createdAt": now_iso(), "updatedAt": now_iso(),
    })


class StackArrangement(BaseModel):
    hamparan: int = Field(ge=1, le=1000)
    kaki: int = Field(ge=1, le=1000)
    height: int = Field(ge=1, le=1000)


class StackAllocationBody(BaseModel):
    productId: str
    stackCode: str
    length: int = Field(ge=1, le=1000)
    width: int = Field(ge=1, le=1000)
    height: int = Field(ge=1, le=1000)
    arrangements: List[StackArrangement] = Field(default_factory=list, max_length=10)
    extraSecondary: int = Field(default=0, ge=0, le=1000000)
    extraPrimary: int = Field(default=0, ge=0, le=1000000)
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

    arrangements = [item.model_dump() for item in body.arrangements] or [{"hamparan": body.length, "kaki": body.width, "height": body.height}]
    secondary_count = sum(item["hamparan"] * item["kaki"] * item["height"] for item in arrangements) + body.extraSecondary
    primary_qty = secondary_count * per_secondary + body.extraPrimary
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
        "arrangements": arrangements,
        "extraSecondary": body.extraSecondary,
        "extraPrimary": body.extraPrimary,
        "primaryRemainder": body.extraPrimary,
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


async def migrate_default_locations() -> None:
    """Tempatkan stok lama yang sudah mempunyai kode tumpukan default yang valid."""
    legacy = await db.stack_allocations.find({"stackCode": {"$regex": "^MP/"}}, {"_id": 0}).to_list(1000)
    for item in legacy:
        new_code = item["stackCode"].replace("MP/", "MP1/", 1)
        await db.stack_allocations.update_one({"id": item["id"]}, {"$set": {"stackCode": new_code, "warehouse": "MP1"}})
    await db.products.update_many({"location": {"$regex": "^MP/"}}, [{"$set": {"location": {"$replaceOne": {"input": "$location", "find": "MP/", "replacement": "MP1/"}}}}])
    minyak = await db.stack_allocations.find_one({"stackCode": "19/A01", "productName": {"$regex": "MINYAK", "$options": "i"}}, {"_id": 0})
    if minyak and int(minyak.get("length", 0) or 0) == 35 and int(minyak.get("width", 0) or 0) == 19 and int(minyak.get("height", 0) or 0) == 6 and not minyak.get("extraSecondary"):
        product = await db.products.find_one({"id": minyak["productId"]}, {"_id": 0})
        per_secondary = float(minyak.get("secondaryQty", 0) or 0)
        corrected_qty = 4000 * per_secondary
        if product and corrected_qty <= float(product.get("stock", 0) or 0) + 1e-9:
            await db.stack_allocations.update_one({"id": minyak["id"]}, {"$set": {
                "arrangements": [{"hamparan": 35, "kaki": 19, "height": 6}],
                "extraSecondary": 10, "secondaryCount": 4000, "primaryQty": corrected_qty,
            }})
    minyak_2l = await db.stack_allocations.find_one({"stackCode": "19/A02", "productName": {"$regex": r"MINYAK.*2\s*L", "$options": "i"}}, {"_id": 0})
    if minyak_2l and not minyak_2l.get("extraPrimary"):
        product = await db.products.find_one({"id": minyak_2l["productId"]}, {"_id": 0})
        corrected_qty = float(minyak_2l.get("primaryQty", 0) or 0) + 3
        if product and corrected_qty <= float(product.get("stock", 0) or 0) + 1e-9:
            await db.stack_allocations.update_one({"id": minyak_2l["id"]}, {"$set": {
                "extraPrimary": 3, "primaryRemainder": 3, "primaryQty": corrected_qty,
            }})
    products = await db.products.find({"location": {"$in": sorted(VALID_STACK_CODES)}}, {"_id": 0}).to_list(5000)
    for product in products:
        if not product.get("secondary") or float(product.get("secondaryQty", 0) or 0) <= 0:
            continue
        allocations = await db.stack_allocations.find({"productId": product["id"]}, {"_id": 0, "primaryQty": 1}).to_list(1000)
        unallocated = float(product.get("stock", 0) or 0) - sum(float(x.get("primaryQty", 0) or 0) for x in allocations)
        if unallocated > 1e-9:
            await allocate_stock_to_stack(product, product["location"], unallocated, "Migrasi stok lama")


@router.get("/stack-allocations")
async def list_stack_allocations(user: dict = Depends(get_current_user)):
    await migrate_default_locations()
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


@router.get("/export/stack-card.xlsx")
async def export_stack_card(stackCode: str, user: dict = Depends(get_current_user)):
    code = stackCode.strip().upper()
    if code not in VALID_STACK_CODES:
        raise HTTPException(status_code=400, detail="Kode tumpukan tidak valid")
    items = await db.stack_allocations.find({"stackCode": code}, {"_id": 0}).sort("productName", 1).to_list(1000)
    headers = ["KARTU TUMPUKAN", code, "", "", "", "", "", ""]
    rows = [["No", "SKU", "Nama Komoditas", "Susunan P×L×T", "Kemasan Sekunder", "Jumlah Primer", "Satuan", "Berat (kg)"]]
    for index, item in enumerate(items, 1):
        parts = [f"{x.get('hamparan', 0)}×{x.get('kaki', 0)}×{x.get('height', 0)}" for x in item.get("arrangements", [])]
        if not parts:
            parts = [f"{item.get('length', 0)}×{item.get('width', 0)}×{item.get('height', 0)}"]
        arrangement = "Perlu dihitung ulang" if item.get("arrangementAdjusted") else " + ".join(parts)
        if not item.get("arrangementAdjusted") and item.get("extraSecondary", 0):
            arrangement += f" + {item.get('extraSecondary')} tambahan"
        loose = f" + {item.get('extraPrimary')} {item.get('unit', '')} lepas" if item.get("extraPrimary", 0) else ""
        rows.append([index, item.get("sku", ""), item.get("productName", ""), arrangement,
                     f"{item.get('secondaryCount', 0)} {item.get('secondary', '')}{loose}", item.get("primaryQty", 0),
                     item.get("unit", ""), float(item.get("primaryQty", 0) or 0) * float(item.get("weight", 0) or 0)])
    output = build_xlsx(headers, rows, "Kartu Tumpukan")
    return StreamingResponse(output, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f'attachment; filename="kartu_tumpukan_{code.replace("/", "-")}.xlsx"'})
