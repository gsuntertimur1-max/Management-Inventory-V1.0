from typing import Literal, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from pymongo import ReturnDocument

from backend.server import db, get_current_user, new_id, now_iso, require_write

router = APIRouter(prefix="/api")

DESTINATIONS = {"Gudang Bazar", "Gudang E-commerce"}


class Arrangement(BaseModel):
    hamparan: int = Field(ge=1, le=1000)
    kaki: int = Field(ge=1, le=1000)
    height: int = Field(ge=1, le=1000)


class ConsignmentLayoutInput(BaseModel):
    destination: Literal["Gudang Bazar", "Gudang E-commerce"]
    productId: str
    arrangements: List[Arrangement] = Field(default_factory=list, max_length=10)
    extraSecondary: int = Field(default=0, ge=0, le=1000000)
    extraPrimary: int = Field(default=0, ge=0, le=1000000)
    note: str = ""


def _settled_qty(load: dict, product_id: str) -> float:
    settled = 0.0
    for link in load.get("document_links", []):
        for item in link.get("items", []):
            if item.get("productId") != product_id:
                continue
            if link.get("type") in {"CR", "RETUR"}:
                settled += float(item.get("goodQty", 0) or 0) + float(item.get("damagedQty", 0) or 0)
            elif link.get("type") == "SO":
                settled += float(item.get("qty", 0) or 0)
    return settled


async def consignment_stock(destination: str = "") -> list[dict]:
    query = {"document_type": "CT", "status": "Selesai", "consignment_destination": {"$in": list(DESTINATIONS)}}
    if destination:
        if destination not in DESTINATIONS:
            raise HTTPException(status_code=400, detail="Lokasi konsinyasi tidak valid")
        query["consignment_destination"] = destination
    loads = await db.outbound_loads.find(query, {"_id": 0}).to_list(5000)
    result: dict[tuple[str, str], dict] = {}
    for load in loads:
        for item in load.get("items", []):
            product_id = item.get("productId", "")
            qty = max(float(item.get("qty", 0) or 0) - _settled_qty(load, product_id), 0)
            if qty <= 0:
                continue
            key = (load.get("consignment_destination", ""), product_id)
            row = result.setdefault(key, {
                "destination": key[0], "productId": product_id, "sku": item.get("sku", ""),
                "name": item.get("name", ""), "unit": item.get("unit", ""),
                "weight": float(item.get("weight", 0) or 0),
                "secondary": item.get("secondary", ""), "secondaryQty": float(item.get("secondaryQty", 0) or 0),
                "qty": 0.0, "totalWeight": 0.0, "documents": [], "requestDocuments": [],
            })
            row["qty"] += qty
            row["totalWeight"] += qty * float(item.get("weight", 0) or 0)
            if load.get("ref") and load["ref"] not in row["documents"]:
                row["documents"].append(load["ref"])
            if load.get("request_document") and load["request_document"] not in row["requestDocuments"]:
                row["requestDocuments"].append(load["request_document"])
    return sorted(result.values(), key=lambda row: (row["destination"] != "Gudang Bazar", row["name"].lower(), row["sku"]))


@router.get("/consignment-stock")
async def list_consignment_stock(destination: str = "", user: dict = Depends(get_current_user)):
    return await consignment_stock(destination.strip())


@router.get("/consignment-layouts")
async def list_consignment_layouts(user: dict = Depends(get_current_user)):
    return await db.consignment_layouts.find({}, {"_id": 0}).to_list(5000)


@router.put("/consignment-layouts")
async def save_consignment_layout(body: ConsignmentLayoutInput, user: dict = Depends(require_write)):
    rows = await consignment_stock(body.destination)
    stock = next((row for row in rows if row["productId"] == body.productId), None)
    if not stock:
        raise HTTPException(status_code=400, detail="Produk tidak memiliki stok konsinyasi aktif pada lokasi ini")
    secondary_count = sum(row.hamparan * row.kaki * row.height for row in body.arrangements) + body.extraSecondary
    calculated = secondary_count * stock["secondaryQty"] + body.extraPrimary
    if stock["secondaryQty"] <= 0 and calculated:
        raise HTTPException(status_code=400, detail="Kemasan sekunder produk belum diatur")
    if calculated > stock["qty"] + 1e-9:
        raise HTTPException(status_code=400, detail="Hasil perkalian melebihi saldo konsinyasi aktif")
    now = now_iso()
    doc = {
        "destination": body.destination, "productId": body.productId, "arrangements": [row.model_dump() for row in body.arrangements],
        "extraSecondary": body.extraSecondary, "extraPrimary": body.extraPrimary, "note": body.note.strip(),
        "updatedAt": now, "updatedBy": user.get("name", ""),
    }
    previous = await db.consignment_layouts.find_one_and_update(
        {"destination": body.destination, "productId": body.productId},
        {"$set": doc, "$setOnInsert": {"id": new_id(), "createdAt": now}}, upsert=True, return_document=ReturnDocument.AFTER,
    )
    return {k: v for k, v in previous.items() if k != "_id"}
