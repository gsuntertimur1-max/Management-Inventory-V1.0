from typing import List, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.server import db, get_current_user, new_id, next_sequence, now_iso, require_write

router = APIRouter(prefix="/api")


class MoveInItemInput(BaseModel):
    productId: str
    qty: float = Field(gt=0)


class MoveInPlottingInput(BaseModel):
    plottingDate: str
    scope: Literal["LOKAL", "REGIONAL", "NASIONAL", "REBAGGING", "REPROSES"]
    senderType: Literal["GUDANG", "MITRA"]
    senderName: str = Field(min_length=2, max_length=150)
    items: List[MoveInItemInput] = Field(min_length=1)
    note: str = Field(default="", max_length=500)


class MoveInReceiptItemInput(BaseModel):
    productId: str
    qty: float = Field(gt=0)


class MoveInReceiptInput(BaseModel):
    receiptDate: str
    vehicleNo: str = Field(default="", max_length=30)
    items: List[MoveInReceiptItemInput] = Field(min_length=1)
    note: str = Field(default="", max_length=500)


class MoveInDocumentAllocationInput(BaseModel):
    documentType: Literal["TM", "MO"]
    documentNo: str = Field(min_length=2, max_length=150)
    productId: str
    qty: float = Field(gt=0)
    note: str = Field(default="", max_length=500)


def _status(plotting: dict) -> str:
    planned = sum(float(x.get("qty", 0) or 0) for x in plotting.get("items", []))
    received = float(plotting.get("_receivedQty", 0) or 0)
    tm_alloc = sum(float(x.get("qty", 0) or 0) for x in plotting.get("documentAllocations", []) if x.get("documentType") == "TM")
    if received <= 1e-9:
        return "Belum Diterima"
    if received + 1e-9 < planned:
        return "Sebagian Diterima"
    if tm_alloc + 1e-9 < received:
        return "Fisik Selesai · Dokumen Pending"
    return "Dokumen Lengkap"


async def _hydrate(doc: dict) -> dict:
    row = dict(doc)
    row.pop("_id", None)

    po = None
    if row.get("poId"):
        po = await db.purchase_orders.find_one({"id": row["poId"]}, {"_id": 0})
    if po:
        po_items = {str(x.get("productId") or ""): x for x in po.get("items", [])}
        for item in row.get("items", []):
            po_item = po_items.get(str(item.get("productId") or ""))
            if po_item:
                item["receivedQty"] = float(po_item.get("receivedQty", 0) or 0)
                item["cancelledQty"] = float(po_item.get("cancelledQty", 0) or 0)
        row["_receivedQty"] = sum(float(x.get("receivedQty", 0) or 0) for x in po.get("items", []))
        row["poStatus"] = po.get("status", "")
        loads = await db.inbound_loads.find({"poId": row["poId"]}, {"_id": 0}).sort("createdAt", -1).to_list(1000)
        row["inboundLoads"] = loads
        row["unloadingCostTotal"] = sum(float((x.get("unloadingCost") or {}).get("chargeable", 0) or 0) for x in loads if x.get("status") == "Selesai")
        row["completedStacks"] = sorted({
            str(item.get("stackCode") or "").strip()
            for load in loads if load.get("status") == "Selesai"
            for item in load.get("items", [])
            if str(item.get("stackCode") or "").strip()
        })
    else:
        row["_receivedQty"] = sum(float(x.get("qty", 0) or 0) for r in row.get("receipts", []) for x in r.get("items", []))
        row["inboundLoads"] = []
        row["unloadingCostTotal"] = 0
        row["completedStacks"] = []

    product_ids = {x.get("productId") for x in row.get("items", []) if x.get("productId")}
    products = {
        p["id"]: p
        for p in await db.products.find({"id": {"$in": list(product_ids)}}, {"_id": 0}).to_list(500)
    } if product_ids else {}
    items = []
    for item in row.get("items", []):
        product = products.get(item.get("productId"), {})
        item2 = dict(item)
        item2.update({
            "name": product.get("name", item2.get("name", "")),
            "sku": product.get("sku", item2.get("sku", "")),
            "unit": product.get("unit", item2.get("unit", "")),
            "weight": float(product.get("weight", item2.get("weight", 0)) or 0),
        })
        items.append(item2)
    row["items"] = items
    row["status"] = _status(row)
    return row


@router.get("/move-in-plottings")
async def list_move_in_plottings(user: dict = Depends(get_current_user)):
    docs = await db.move_in_plottings.find({}, {"_id": 0}).sort([("plottingDate", -1), ("createdAt", -1)]).to_list(1000)
    return [await _hydrate(doc) for doc in docs]


@router.post("/move-in-plottings")
async def create_move_in_plotting(body: MoveInPlottingInput, user: dict = Depends(require_write)):
    seen = set()
    items = []
    for item in body.items:
        if item.productId in seen:
            raise HTTPException(status_code=400, detail="Produk yang sama tidak boleh muncul dua kali dalam satu plotting")
        seen.add(item.productId)
        product = await db.products.find_one({"id": item.productId}, {"_id": 0})
        if not product:
            raise HTTPException(status_code=404, detail="Produk plotting tidak ditemukan")
        items.append({
            "productId": product["id"],
            "sku": product.get("sku", ""),
            "name": product.get("name", ""),
            "qty": float(item.qty),
            "unit": product.get("unit", ""),
            "weight": float(product.get("weight", 0) or 0),
        })

    plotting_date = body.plottingDate.strip()
    date_key = plotting_date.replace("-", "")
    if len(date_key) != 8 or not date_key.isdigit():
        raise HTTPException(status_code=400, detail="Tanggal plotting harus YYYY-MM-DD")

    number = await next_sequence(f"move-in-plotting:{date_key}")
    plot_no = f"PLT-IN/{date_key}/{number:03d}"
    plotting_id = new_id()
    po_id = new_id()
    po_items = []
    for item in items:
        po_items.append({
            **item,
            "receivedQty": 0.0,
            "cancelledQty": 0.0,
            "secondary": "",
            "secondaryQty": 0.0,
            "cost": 0.0,
            "channel": "KOM",
        })

    po_doc = {
        "id": po_id,
        "no": plot_no,
        "supplier": body.senderName.strip(),
        "date": f"{plotting_date}T00:00:00+07:00",
        "status": "Belum Diterima",
        "items": po_items,
        "total": 0,
        "sourceType": "MOVE_IN",
        "moveInPlottingId": plotting_id,
        "moveInScope": body.scope,
        "moveInSenderType": body.senderType,
        "created_by": user.get("name", ""),
        "created_at": now_iso(),
    }
    await db.purchase_orders.insert_one(dict(po_doc))

    doc = {
        "id": plotting_id,
        "poId": po_id,
        "plotNo": plot_no,
        "plottingDate": plotting_date,
        "scope": body.scope,
        "senderType": body.senderType,
        "senderName": body.senderName.strip(),
        "items": items,
        "receipts": [],
        "documentAllocations": [],
        "note": body.note.strip(),
        "createdBy": user.get("name", ""),
        "createdAt": now_iso(),
        "updatedAt": now_iso(),
    }
    await db.move_in_plottings.insert_one(dict(doc))
    return await _hydrate(doc)


@router.post("/move-in-plottings/{plotting_id}/receipts", deprecated=True)
async def add_move_in_receipt(plotting_id: str, body: MoveInReceiptInput, user: dict = Depends(require_write)):
    plotting = await db.move_in_plottings.find_one({"id": plotting_id}, {"_id": 0})
    if not plotting:
        raise HTTPException(status_code=404, detail="Plotting Move In tidak ditemukan")

    planned = {x.get("productId"): float(x.get("qty", 0) or 0) for x in plotting.get("items", [])}
    already = {}
    for rec in plotting.get("receipts", []):
        for item in rec.get("items", []):
            pid = item.get("productId")
            already[pid] = already.get(pid, 0.0) + float(item.get("qty", 0) or 0)

    receipt_items = []
    for item in body.items:
        if item.productId not in planned:
            raise HTTPException(status_code=400, detail="Produk penerimaan tidak termasuk dalam plotting ini")
        remaining = max(planned[item.productId] - already.get(item.productId, 0.0), 0.0)
        if float(item.qty) > remaining + 1e-9:
            raise HTTPException(status_code=400, detail=f"Jumlah fisik melebihi sisa plotting ({remaining:g})")
        product = await db.products.find_one({"id": item.productId}, {"_id": 0})
        receipt_items.append({
            "productId": item.productId,
            "name": (product or {}).get("name", ""),
            "sku": (product or {}).get("sku", ""),
            "unit": (product or {}).get("unit", ""),
            "qty": float(item.qty),
        })

    receipt = {
        "id": new_id(),
        "receiptDate": body.receiptDate,
        "vehicleNo": body.vehicleNo.strip().upper(),
        "items": receipt_items,
        "note": body.note.strip(),
        "recordedBy": user.get("name", ""),
        "recordedAt": now_iso(),
        "stockMutation": False,
    }
    await db.move_in_plottings.update_one(
        {"id": plotting_id},
        {"$push": {"receipts": receipt}, "$set": {"updatedAt": now_iso()}},
    )
    updated = await db.move_in_plottings.find_one({"id": plotting_id}, {"_id": 0})
    return await _hydrate(updated)


@router.post("/move-in-plottings/{plotting_id}/document-allocations")
async def add_move_in_document_allocation(plotting_id: str, body: MoveInDocumentAllocationInput, user: dict = Depends(require_write)):
    plotting = await db.move_in_plottings.find_one({"id": plotting_id}, {"_id": 0})
    if not plotting:
        raise HTTPException(status_code=404, detail="Plotting Move In tidak ditemukan")

    if body.documentType == "MO" and plotting.get("scope") not in ("REBAGGING", "REPROSES"):
        raise HTTPException(status_code=400, detail="Nomor MO hanya berlaku untuk Move In Rebagging/Reproses")

    if body.productId not in {x.get("productId") for x in plotting.get("items", [])}:
        raise HTTPException(status_code=400, detail="Produk dokumen tidak termasuk plotting ini")

    if plotting.get("poId"):
        po = await db.purchase_orders.find_one({"id": plotting["poId"]}, {"_id": 0}) or {}
        received = sum(
            float(x.get("receivedQty", 0) or 0)
            for x in po.get("items", [])
            if x.get("productId") == body.productId
        )
    else:
        received = sum(
            float(x.get("qty", 0) or 0)
            for rec in plotting.get("receipts", [])
            for x in rec.get("items", [])
            if x.get("productId") == body.productId
        )
    allocated_same_type = sum(
        float(x.get("qty", 0) or 0)
        for x in plotting.get("documentAllocations", [])
        if x.get("documentType") == body.documentType and x.get("productId") == body.productId
    )
    if float(body.qty) > max(received - allocated_same_type, 0) + 1e-9:
        raise HTTPException(status_code=400, detail="Alokasi dokumen melebihi fisik yang sudah dicatat pada plotting")

    allocation = {
        "id": new_id(),
        "documentType": body.documentType,
        "documentNo": body.documentNo.strip().upper(),
        "productId": body.productId,
        "qty": float(body.qty),
        "note": body.note.strip(),
        "linkedBy": user.get("name", ""),
        "linkedAt": now_iso(),
    }
    await db.move_in_plottings.update_one(
        {"id": plotting_id},
        {"$push": {"documentAllocations": allocation}, "$set": {"updatedAt": now_iso()}},
    )
    updated = await db.move_in_plottings.find_one({"id": plotting_id}, {"_id": 0})
    return await _hydrate(updated)


@router.get("/move-in-legacy-references")
async def list_move_in_legacy_references(user: dict = Depends(get_current_user)):
    docs = await db.purchase_orders.find({}, {"_id": 0}).sort("date", -1).to_list(1000)
    rows = []
    for po in docs:
        no = str(po.get("no") or "")
        supplier = str(po.get("supplier") or "")
        searchable = f"{no} {supplier}".lower()
        if not (no.upper().startswith("TM/") or "gudang" in searchable or "repro" in searchable or "rebag" in searchable or "mizan" in searchable):
            continue
        rows.append({
            "id": po.get("id"),
            "no": no,
            "supplier": supplier,
            "date": po.get("date", ""),
            "status": po.get("status", ""),
            "items": po.get("items", []),
        })
    return rows[:500]


async def ensure_move_in_indexes():
    await db.move_in_plottings.create_index([("plottingDate", -1)])
    await db.move_in_plottings.create_index([("senderName", 1), ("plottingDate", -1)])
    await db.move_in_plottings.create_index("plotNo", unique=True)
