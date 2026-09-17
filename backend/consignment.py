from typing import Literal, List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from pymongo import ReturnDocument

from backend.server import build_xlsx, db, get_current_user, new_id, now_iso, operational_now, normalize_channel
from backend.role_four_config import has_role_permission, role_destination

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


class OpnameItemInput(BaseModel):
    productId: str
    actualQty: float = Field(ge=0)
    note: str = ""


class ConsignmentOpnameInput(BaseModel):
    destination: Literal["Gudang Bazar", "Gudang E-commerce"]
    items: List[OpnameItemInput] = Field(min_length=1)
    note: str = ""


def _scope_for_user(user: dict) -> str:
    return role_destination(user.get("role"))


def _ensure_destination_access(user: dict, destination: str, write: bool = False) -> str:
    destination = str(destination or "").strip()
    if destination not in DESTINATIONS:
        raise HTTPException(status_code=400, detail="Lokasi konsinyasi tidak valid")
    scope = _scope_for_user(user)
    if scope and scope != destination:
        raise HTTPException(status_code=403, detail=f"Akun ini hanya memiliki akses ke {scope}")
    permission = "bazarOps" if destination == "Gudang Bazar" else "ecomOps"
    view_permission = "bazarView" if destination == "Gudang Bazar" else "ecomView"
    required = permission if write else view_permission
    if not has_role_permission(user.get("role"), required):
        raise HTTPException(status_code=403, detail=f"Tidak memiliki akses ke {destination}")
    return destination


def _resolved_destination(user: dict, requested: str = "") -> str:
    scope = _scope_for_user(user)
    requested = str(requested or "").strip()
    if scope:
        if requested and requested != scope:
            raise HTTPException(status_code=403, detail=f"Akun ini hanya memiliki akses ke {scope}")
        return scope
    if requested:
        return _ensure_destination_access(user, requested, write=False)
    return ""


def _source_document(load: dict, item: dict) -> str:
    return str(item.get("documentNo") or load.get("ref") or "").strip()


def _settled_qty(load: dict, product_id: str, source_document_no: str = "") -> float:
    target = str(source_document_no or load.get("ref") or "").strip()
    settled = 0.0
    for link in load.get("document_links", []):
        link_source = str(link.get("sourceDocumentNo") or load.get("ref") or "").strip()
        if target and link_source != target:
            continue
        for item in link.get("items", []):
            if item.get("productId") != product_id:
                continue
            if link.get("type") in {"CR", "RETUR"}:
                settled += float(item.get("goodQty", 0) or 0) + float(item.get("damagedQty", 0) or 0)
            elif link.get("type") == "SO":
                settled += float(item.get("qty", 0) or 0)
    return settled


async def consignment_stock(destination: str = "") -> list[dict]:
    query = {"document_type": {"$in": ["MEMO", "ND"]}, "status": "Selesai", "consignment_destination": {"$in": list(DESTINATIONS)}}
    if destination:
        if destination not in DESTINATIONS:
            raise HTTPException(status_code=400, detail="Lokasi konsinyasi tidak valid")
        query["consignment_destination"] = destination
    loads = await db.outbound_loads.find(query, {"_id": 0}).to_list(5000)
    result: dict[tuple[str, str, str], dict] = {}
    for load in loads:
        source_rows: dict[tuple[str, str, str], dict] = {}
        for item in load.get("items", []):
            product_id = item.get("productId", "")
            if not product_id:
                continue
            source_document = _source_document(load, item)
            channel = normalize_channel(item.get("channel"), "KOM")
            source_key = (source_document, product_id, channel)
            row = source_rows.setdefault(source_key, {**item, "qty": 0.0})
            row["qty"] += float(item.get("qty", 0) or 0)
        for (source_document, product_id, channel), item in source_rows.items():
            qty = max(float(item.get("qty", 0) or 0) - _settled_qty(load, product_id, source_document), 0)
            if qty <= 0:
                continue
            key = (load.get("consignment_destination", ""), product_id, channel)
            row = result.setdefault(key, {
                "destination": key[0], "productId": product_id, "channel": channel, "sku": item.get("sku", ""),
                "name": item.get("name", ""), "unit": item.get("unit", ""), "weight": float(item.get("weight", 0) or 0),
                "measureUnit": item.get("measureUnit", "kg") or "kg", "secondary": item.get("secondary", ""),
                "secondaryQty": float(item.get("secondaryQty", 0) or 0), "qty": 0.0, "totalWeight": 0.0,
                "documents": [], "requestDocuments": [],
            })
            row["qty"] += qty
            row["totalWeight"] += qty * float(item.get("weight", 0) or 0)
            if source_document and source_document not in row["documents"]:
                row["documents"].append(source_document)
            if load.get("request_document") and load["request_document"] not in row["requestDocuments"]:
                row["requestDocuments"].append(load["request_document"])
    return sorted(result.values(), key=lambda row: (row["destination"] != "Gudang Bazar", row["name"].lower(), row["channel"], row["sku"]))


@router.get("/consignment-stock")
async def list_consignment_stock(destination: str = "", user: dict = Depends(get_current_user)):
    resolved = _resolved_destination(user, destination)
    if not resolved and not has_role_permission(user.get("role"), "consignmentView"):
        raise HTTPException(status_code=403, detail="Tidak memiliki akses stok Bazar/E-commerce")
    return await consignment_stock(resolved)


async def monitoring_stock(destination_scope: str = "", include_main: bool = True) -> list[dict]:
    rows = []
    if include_main:
        products = await db.products.find({}, {"_id": 0}).sort("name", 1).to_list(5000)
        for product in products:
            balances = product.get("channelStock") if isinstance(product.get("channelStock"), dict) else {}
            if not balances:
                channel = normalize_channel(product.get("channel"), "KOM")
                balances = {channel: {"stock": float(product.get("stock", 0) or 0), "damaged": float(product.get("damaged", 0) or 0)}}
            for channel in ("PSO", "KOM"):
                balance = balances.get(channel) or {}
                qty = float(balance.get("stock", 0) or 0)
                damaged = float(balance.get("damaged", 0) or 0)
                if qty <= 0 and damaged <= 0:
                    continue
                weight = float(product.get("weight", 0) or 0)
                rows.append({
                    "channel": channel, "location": product.get("location") or "Gudang Utama",
                    "locationType": "GUDANG", "productId": product.get("id", ""), "sku": product.get("sku", ""),
                    "name": product.get("name", ""), "unit": product.get("unit", ""), "qty": qty,
                    "damaged": damaged, "weight": weight, "measureUnit": product.get("measureUnit", "kg") or "kg", "totalWeight": qty * weight,
                    "secondary": product.get("secondary", ""), "secondaryQty": float(product.get("secondaryQty", 0) or 0), "documents": [],
                })
    for item in await consignment_stock(destination_scope):
        rows.append({
            "channel": normalize_channel(item.get("channel"), "KOM"), "location": item["destination"],
            "locationType": "KONSINYASI", "productId": item["productId"], "sku": item.get("sku", ""),
            "name": item.get("name", ""), "unit": item.get("unit", ""), "qty": float(item.get("qty", 0) or 0),
            "damaged": 0.0, "weight": float(item.get("weight", 0) or 0), "measureUnit": item.get("measureUnit", "kg") or "kg", "totalWeight": float(item.get("totalWeight", 0) or 0),
            "secondary": item.get("secondary", ""), "secondaryQty": float(item.get("secondaryQty", 0) or 0), "documents": item.get("documents", []),
        })
    return sorted(rows, key=lambda row: (row["location"] not in {"Gudang Bazar", "Gudang E-commerce"}, row["location"], row["channel"], row["name"].lower(), row["sku"]))


@router.get("/monitoring-stock")
async def list_monitoring_stock(user: dict = Depends(get_current_user)):
    scope = _scope_for_user(user)
    if scope:
        _ensure_destination_access(user, scope, write=False)
        return await monitoring_stock(scope, include_main=False)
    return await monitoring_stock()


@router.get("/export/monitoring-stock.xlsx")
async def export_monitoring_stock(user: dict = Depends(get_current_user)):
    scope = _scope_for_user(user)
    if scope:
        _ensure_destination_access(user, scope, write=False)
    rows = await monitoring_stock(scope, include_main=not bool(scope))
    headers = ["Saluran", "Lokasi", "Jenis Lokasi", "SKU", "Nama Komoditi", "Kuantum Pack/PCS", "Satuan", "Kuantum Fisik", "Stok Rusak", "Dokumen Memo/ND"]
    values = [[row["channel"], row["location"], row["locationType"], row["sku"], row["name"], row["qty"], row["unit"], f"{row['totalWeight']:g} {row.get('measureUnit', 'kg')}", row["damaged"], ", ".join(row.get("documents", []))] for row in rows]
    output = build_xlsx(headers, values, "Monitoring Stok")
    filename = f"monitoring_stok_{operational_now().strftime('%Y%m%d_%H%M')}.xlsx"
    return StreamingResponse(output, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/consignment-layouts")
async def list_consignment_layouts(user: dict = Depends(get_current_user)):
    scope = _scope_for_user(user)
    if scope:
        _ensure_destination_access(user, scope, write=False)
        return await db.consignment_layouts.find({"destination": scope}, {"_id": 0}).to_list(5000)
    if not has_role_permission(user.get("role"), "consignmentView"):
        raise HTTPException(status_code=403, detail="Tidak memiliki akses layout Bazar/E-commerce")
    return await db.consignment_layouts.find({}, {"_id": 0}).to_list(5000)


@router.get("/consignment-layout-history")
async def list_consignment_layout_history(destination: str = "", user: dict = Depends(get_current_user)):
    resolved = _resolved_destination(user, destination)
    query = {"destination": resolved} if resolved else {}
    return await db.consignment_layout_history.find(query, {"_id": 0}).sort("time", -1).to_list(5000)


@router.get("/consignment-opnames")
async def list_consignment_opnames(destination: str = "", user: dict = Depends(get_current_user)):
    resolved = _resolved_destination(user, destination)
    query = {"destination": resolved} if resolved else {}
    return await db.consignment_opnames.find(query, {"_id": 0}).sort("time", -1).to_list(5000)


@router.put("/consignment-layouts")
async def save_consignment_layout(body: ConsignmentLayoutInput, user: dict = Depends(get_current_user)):
    _ensure_destination_access(user, body.destination, write=True)
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
        "extraSecondary": body.extraSecondary, "extraPrimary": body.extraPrimary, "note": body.note.strip(), "updatedAt": now, "updatedBy": user.get("name", ""),
    }
    previous = await db.consignment_layouts.find_one_and_update(
        {"destination": body.destination, "productId": body.productId},
        {"$set": doc, "$setOnInsert": {"id": new_id(), "createdAt": now}}, upsert=True, return_document=ReturnDocument.AFTER,
    )
    result = {k: v for k, v in previous.items() if k != "_id"}
    await db.consignment_layout_history.insert_one({"id": new_id(), "time": now, "destination": body.destination, "productId": body.productId, "before": {k: v for k, v in (await db.consignment_layout_history.find_one({"destination": body.destination, "productId": body.productId}, {"_id": 0}, sort=[("time", -1)]) or {}).get("after", {}).items()}, "after": result, "operator": user.get("name", ""), "note": body.note.strip()})
    return result


@router.post("/consignment-opnames")
async def create_consignment_opname(body: ConsignmentOpnameInput, user: dict = Depends(get_current_user)):
    _ensure_destination_access(user, body.destination, write=True)
    stock_by_product = {row["productId"]: row for row in await consignment_stock(body.destination)}
    items = []
    for item in body.items:
        system = stock_by_product.get(item.productId)
        if not system:
            raise HTTPException(status_code=400, detail="Produk opname tidak memiliki saldo konsinyasi aktif")
        actual = float(item.actualQty)
        items.append({"productId": item.productId, "sku": system.get("sku", ""), "name": system.get("name", ""), "unit": system.get("unit", ""), "systemQty": float(system["qty"]), "actualQty": actual, "difference": actual - float(system["qty"]), "note": item.note.strip()})
    doc = {"id": new_id(), "time": now_iso(), "destination": body.destination, "items": items, "note": body.note.strip(), "operator": user.get("name", "")}
    await db.consignment_opnames.insert_one(dict(doc))
    return doc
