from __future__ import annotations

from collections import defaultdict
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.server import db, get_current_user, new_id, normalize_channel, now_iso
from backend.role_four_config import has_role_permission, role_destination
from backend.consignment_damaged import credit_consignment_damaged
import backend.consignment as consignment_module


router = APIRouter(prefix="/api/bazar/external-nds")
BAZAR = "Gudang Bazar"
EPS = 1e-9


def _n(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _ensure_access(user: dict, write: bool = False) -> None:
    scoped = role_destination(user.get("role"))
    if scoped and scoped != BAZAR:
        raise HTTPException(status_code=403, detail=f"Akun ini hanya memiliki akses ke {scoped}")
    permission = "bazarOps" if write else "bazarView"
    if not has_role_permission(user.get("role"), permission):
        raise HTTPException(status_code=403, detail="Tidak memiliki akses ke Register ND Bazar")


class NDItemInput(BaseModel):
    productId: str
    qty: float = Field(gt=0)


class ExternalNDCreate(BaseModel):
    ndNo: str
    ndDate: str
    originWarehouse: str
    activityType: str = "BAZAR"
    items: List[NDItemInput] = Field(min_length=1)
    note: str = ""


class ReceiptItemInput(BaseModel):
    productId: str
    goodQty: float = Field(ge=0)
    damagedQty: float = Field(default=0, ge=0)
    stackCode: str = ""


class ExternalNDReceipt(BaseModel):
    receiptDate: str
    vehicleNo: str = ""
    items: List[ReceiptItemInput] = Field(min_length=1)
    note: str = ""


class SettlementItemInput(BaseModel):
    productId: str
    qty: float = Field(gt=0)


class ExternalNDReturn(BaseModel):
    returnDate: str
    items: List[SettlementItemInput] = Field(min_length=1)
    note: str = ""


class ExternalNDRealization(BaseModel):
    realizationDate: str
    activityType: str = "BAZAR"
    referenceNo: str = ""
    items: List[SettlementItemInput] = Field(min_length=1)
    note: str = ""


class ExternalNDSO(BaseModel):
    soNo: str
    soDate: str
    items: List[SettlementItemInput] = Field(min_length=1)
    note: str = ""


async def _identity(product_id: str) -> dict:
    product = await db.products.find_one({"id": product_id}, {"_id": 0})
    if not product:
        raise HTTPException(status_code=404, detail="Produk tidak ditemukan")
    return {
        "productId": product_id,
        "sku": product.get("sku", ""),
        "name": product.get("name", ""),
        "unit": product.get("unit", ""),
        "channel": normalize_channel(product.get("channel"), "KOM"),
        "weight": _n(product.get("weight")),
        "measureUnit": product.get("measureUnit", "kg") or "kg",
        "secondary": product.get("secondary", ""),
        "secondaryQty": _n(product.get("secondaryQty")),
    }


def _item_totals(document: dict, product_id: str) -> dict:
    ordered = sum(_n(row.get("orderedQty")) for row in document.get("items", []) if row.get("productId") == product_id)
    good = sum(_n(row.get("goodQty")) for receipt in document.get("receipts", []) for row in receipt.get("items", []) if row.get("productId") == product_id)
    damaged = sum(_n(row.get("damagedQty")) for receipt in document.get("receipts", []) for row in receipt.get("items", []) if row.get("productId") == product_id)
    returned = sum(_n(row.get("qty")) for entry in document.get("returns", []) for row in entry.get("items", []) if row.get("productId") == product_id)
    realized = sum(_n(row.get("qty")) for entry in document.get("realizations", []) for row in entry.get("items", []) if row.get("productId") == product_id)
    settled = sum(_n(row.get("qty")) for entry in document.get("soDocuments", []) for row in entry.get("items", []) if row.get("productId") == product_id)
    return {"ordered": ordered, "good": good, "damaged": damaged, "returned": returned, "realized": realized, "settled": settled}


def summarize_external_nd(document: dict) -> dict:
    doc = dict(document)
    summary = []
    for item in doc.get("items", []):
        totals = _item_totals(doc, item.get("productId", ""))
        received = totals["good"] + totals["damaged"]
        remaining_to_receive = max(totals["ordered"] - received, 0.0)
        physical_balance = max(totals["good"] - totals["returned"] - totals["realized"], 0.0)
        eligible_so = max(totals["realized"] - totals["settled"], 0.0)
        summary.append({**item, **totals, "received": received, "remainingToReceive": remaining_to_receive, "physicalBalance": physical_balance, "eligibleSoQty": eligible_so, "unsettledQty": physical_balance + eligible_so})
    if doc.get("cancelledAt"):
        status = "DIBATALKAN"
    elif summary and all(row["remainingToReceive"] <= EPS and row["unsettledQty"] <= EPS for row in summary):
        status = "SELESAI"
    elif doc.get("soDocuments"):
        status = "SO_TERBIT_SEBAGIAN"
    elif doc.get("returns"):
        status = "ADA_RETUR"
    elif doc.get("receipts") and all(row["remainingToReceive"] <= EPS for row in summary):
        status = "DITERIMA"
    elif doc.get("receipts"):
        status = "DITERIMA_SEBAGIAN"
    else:
        status = "ND_TERDAFTAR"
    doc["status"] = status
    doc["summaryItems"] = summary
    return doc


async def _document(nd_id: str) -> dict:
    document = await db.bazar_external_nd.find_one({"id": nd_id}, {"_id": 0})
    if not document:
        raise HTTPException(status_code=404, detail="ND eksternal tidak ditemukan")
    return document


async def _record_history(event_type: str, document: dict, user: dict, items: list[dict], note: str = "", extra: dict | None = None) -> None:
    row = {
        "id": new_id(), "time": now_iso(), "destination": BAZAR, "eventType": event_type,
        "referenceId": document["id"], "referenceNo": document.get("ndNo", ""),
        "operator": user.get("name", ""), "items": items, "note": str(note or "").strip(),
        "originWarehouse": document.get("originWarehouse", ""),
    }
    if extra:
        row.update(extra)
    await db.consignment_operation_history.insert_one(row)


@router.get("")
async def list_external_nds(user: dict = Depends(get_current_user)):
    _ensure_access(user, write=False)
    rows = await db.bazar_external_nd.find({}, {"_id": 0}).sort("createdAt", -1).to_list(5000)
    return [summarize_external_nd(row) for row in rows]


@router.post("")
async def create_external_nd(body: ExternalNDCreate, user: dict = Depends(get_current_user)):
    _ensure_access(user, write=True)
    nd_no = body.ndNo.strip().upper()
    origin = body.originWarehouse.strip()
    if not nd_no or not body.ndDate or not origin:
        raise HTTPException(status_code=400, detail="Nomor ND, tanggal ND, dan gudang asal wajib diisi")
    if await db.bazar_external_nd.find_one({"ndNo": nd_no, "cancelledAt": {"$exists": False}}):
        raise HTTPException(status_code=409, detail="Nomor ND sudah terdaftar")
    grouped = defaultdict(float)
    for item in body.items:
        grouped[item.productId] += float(item.qty)
    items = [{**(await _identity(product_id)), "orderedQty": qty} for product_id, qty in grouped.items()]
    now = now_iso()
    document = {
        "id": new_id(), "ndNo": nd_no, "ndDate": body.ndDate, "originWarehouse": origin,
        "activityType": body.activityType.strip().upper() or "BAZAR", "items": items,
        "receipts": [], "returns": [], "realizations": [], "soDocuments": [], "note": body.note.strip(),
        "createdAt": now, "createdBy": user.get("name", ""),
    }
    await db.bazar_external_nd.insert_one(dict(document))
    await _record_history("BAZAR_ND_EKSTERNAL_DIBUAT", document, user, items, body.note)
    return summarize_external_nd(document)


@router.post("/{nd_id}/receipts")
async def receive_external_nd(nd_id: str, body: ExternalNDReceipt, user: dict = Depends(get_current_user)):
    _ensure_access(user, write=True)
    document = await _document(nd_id)
    if document.get("cancelledAt"):
        raise HTTPException(status_code=409, detail="ND sudah dibatalkan")
    input_map = {row.productId: row for row in body.items}
    receipt_items = []
    for ordered in document.get("items", []):
        entered = input_map.pop(ordered["productId"], None)
        if not entered:
            continue
        good, damaged = float(entered.goodQty), float(entered.damagedQty)
        if good + damaged <= EPS:
            continue
        totals = _item_totals(document, ordered["productId"])
        outstanding = max(totals["ordered"] - totals["good"] - totals["damaged"], 0.0)
        if good + damaged > outstanding + EPS:
            raise HTTPException(status_code=409, detail=f"Penerimaan {ordered.get('name', '')} melebihi sisa ND {outstanding:g}")
        stack_code = str(entered.stackCode or "BZR/A01").strip().upper()
        receipt_items.append({**ordered, "goodQty": good, "damagedQty": damaged, "stackCode": stack_code})
    if input_map:
        raise HTTPException(status_code=400, detail="Penerimaan memuat produk yang tidak tercantum pada ND")
    if not receipt_items:
        raise HTTPException(status_code=400, detail="Isi minimal satu jumlah penerimaan")
    receipt_id, now = new_id(), now_iso()
    receipt = {"id": receipt_id, "receiptDate": body.receiptDate, "vehicleNo": body.vehicleNo.strip().upper(), "items": receipt_items, "note": body.note.strip(), "createdAt": now, "createdBy": user.get("name", "")}
    for item in receipt_items:
        if _n(item.get("goodQty")) > EPS:
            event_key = f"bazar-external-nd-receipt:{receipt_id}:{item['productId']}"
            movement = {
                "id": new_id(), "eventKey": event_key, "time": now, "destination": BAZAR,
                "movementType": "ND_EKSTERNAL_DITERIMA", "referenceId": nd_id, "referenceNo": document.get("ndNo", ""),
                "sourceType": "GUDANG_EKSTERNAL", "originWarehouse": document.get("originWarehouse", ""),
                "productId": item["productId"], "sku": item.get("sku", ""), "name": item.get("name", ""),
                "unit": item.get("unit", ""), "channel": item.get("channel", "KOM"), "delta": _n(item.get("goodQty")),
                "stackCode": item.get("stackCode", ""), "operator": user.get("name", ""),
            }
            await db.consignment_movements.update_one({"eventKey": event_key}, {"$setOnInsert": movement}, upsert=True)
        if _n(item.get("damagedQty")) > EPS:
            await credit_consignment_damaged(
                BAZAR, item, _n(item.get("damagedQty")), f"bazar-external-nd-damaged:{receipt_id}:{item['productId']}",
                "ND_EKSTERNAL_RUSAK_DITERIMA", nd_id, document.get("ndNo", ""), user.get("name", ""), body.note,
            )
    await db.bazar_external_nd.update_one({"id": nd_id}, {"$push": {"receipts": receipt}, "$set": {"updatedAt": now, "updatedBy": user.get("name", "")}})
    await _record_history("BAZAR_ND_EKSTERNAL_DITERIMA", document, user, receipt_items, body.note, {"vehicleNo": receipt["vehicleNo"]})
    return summarize_external_nd(await _document(nd_id))


@router.post("/{nd_id}/returns")
async def return_external_nd(nd_id: str, body: ExternalNDReturn, user: dict = Depends(get_current_user)):
    _ensure_access(user, write=True)
    document = await _document(nd_id)
    grouped = defaultdict(float)
    for row in body.items:
        grouped[row.productId] += float(row.qty)
    items = []
    for product_id, qty in grouped.items():
        source = next((row for row in document.get("items", []) if row.get("productId") == product_id), None)
        if not source:
            raise HTTPException(status_code=400, detail="Produk retur tidak tercantum pada ND")
        totals = _item_totals(document, product_id)
        returnable = max(totals["good"] - totals["returned"] - totals["realized"], 0.0)
        if qty > returnable + EPS:
            raise HTTPException(status_code=409, detail=f"Saldo belum SO {source.get('name', '')} hanya {returnable:g}")
        items.append({**source, "qty": qty})
    return_id, now = new_id(), now_iso()
    entry = {"id": return_id, "returnDate": body.returnDate, "items": items, "note": body.note.strip(), "createdAt": now, "createdBy": user.get("name", "")}
    for item in items:
        event_key = f"bazar-external-nd-return:{return_id}:{item['productId']}"
        await db.consignment_movements.update_one({"eventKey": event_key}, {"$setOnInsert": {
            "id": new_id(), "eventKey": event_key, "time": now, "destination": BAZAR,
            "movementType": "RETUR_KE_GUDANG_ASAL", "referenceId": nd_id, "referenceNo": document.get("ndNo", ""),
            "originWarehouse": document.get("originWarehouse", ""), "productId": item["productId"],
            "sku": item.get("sku", ""), "name": item.get("name", ""), "unit": item.get("unit", ""),
            "channel": item.get("channel", "KOM"), "delta": -_n(item.get("qty")), "operator": user.get("name", ""),
        }}, upsert=True)
        await consignment_module.decrease_consignment_layouts(BAZAR, item["productId"], _n(item.get("qty")), user.get("name", ""), operation_key=event_key)
    await db.bazar_external_nd.update_one({"id": nd_id}, {"$push": {"returns": entry}, "$set": {"updatedAt": now, "updatedBy": user.get("name", "")}})
    await _record_history("BAZAR_RETUR_KE_GUDANG_ASAL", document, user, items, body.note, {"returnDate": body.returnDate})
    return summarize_external_nd(await _document(nd_id))


@router.post("/{nd_id}/realizations")
async def realize_external_nd(nd_id: str, body: ExternalNDRealization, user: dict = Depends(get_current_user)):
    _ensure_access(user, write=True)
    document = await _document(nd_id)
    grouped = defaultdict(float)
    for row in body.items:
        grouped[row.productId] += float(row.qty)
    items = []
    for product_id, qty in grouped.items():
        source = next((row for row in document.get("items", []) if row.get("productId") == product_id), None)
        if not source:
            raise HTTPException(status_code=400, detail="Produk realisasi tidak tercantum pada ND")
        totals = _item_totals(document, product_id)
        realizable = max(totals["good"] - totals["returned"] - totals["realized"], 0.0)
        if qty > realizable + EPS:
            raise HTTPException(status_code=409, detail=f"Saldo fisik belum direalisasi {source.get('name', '')} hanya {realizable:g}")
        items.append({**source, "qty": qty})
    realization_id, now = new_id(), now_iso()
    entry = {
        "id": realization_id, "realizationDate": body.realizationDate,
        "activityType": body.activityType.strip().upper() or "BAZAR", "referenceNo": body.referenceNo.strip().upper(),
        "items": items, "note": body.note.strip(), "createdAt": now, "createdBy": user.get("name", ""),
    }
    # Penjualan sudah mengurangi stok melalui penutupan Bazar/Paket. Catatan ini hanya mengikat realisasi ke ND.
    await db.bazar_external_nd.update_one({"id": nd_id}, {"$push": {"realizations": entry}, "$set": {"updatedAt": now, "updatedBy": user.get("name", "")}})
    await _record_history("BAZAR_ND_DIREALISASIKAN", document, user, items, body.note, {"activityType": entry["activityType"], "activityReferenceNo": entry["referenceNo"]})
    return summarize_external_nd(await _document(nd_id))


@router.post("/{nd_id}/so-documents")
async def settle_external_nd_with_so(nd_id: str, body: ExternalNDSO, user: dict = Depends(get_current_user)):
    _ensure_access(user, write=True)
    document = await _document(nd_id)
    so_no = body.soNo.strip().upper()
    if not so_no or not body.soDate:
        raise HTTPException(status_code=400, detail="Nomor dan tanggal SO wajib diisi")
    if any(str(row.get("soNo", "")).upper() == so_no for row in document.get("soDocuments", [])):
        raise HTTPException(status_code=409, detail="Nomor SO sudah dicatat pada ND ini")
    grouped = defaultdict(float)
    for row in body.items:
        grouped[row.productId] += float(row.qty)
    items = []
    for product_id, qty in grouped.items():
        source = next((row for row in document.get("items", []) if row.get("productId") == product_id), None)
        if not source:
            raise HTTPException(status_code=400, detail="Produk SO tidak tercantum pada ND")
        totals = _item_totals(document, product_id)
        eligible = max(totals["realized"] - totals["settled"], 0.0)
        if qty > eligible + EPS:
            raise HTTPException(status_code=409, detail=f"Realisasi yang belum memiliki SO untuk {source.get('name', '')} hanya {eligible:g}")
        items.append({**source, "qty": qty})
    so_id, now = new_id(), now_iso()
    entry = {"id": so_id, "soNo": so_no, "soDate": body.soDate, "items": items, "note": body.note.strip(), "createdAt": now, "createdBy": user.get("name", "")}
    # SO diterbitkan setelah realisasi. Ia menyelesaikan dokumen ND dan tidak membuat mutasi stok kedua.
    await db.bazar_external_nd.update_one({"id": nd_id}, {"$push": {"soDocuments": entry}, "$set": {"updatedAt": now, "updatedBy": user.get("name", "")}})
    await _record_history("BAZAR_SO_TERBIT", document, user, items, body.note, {"soNo": so_no, "soDate": body.soDate})
    return summarize_external_nd(await _document(nd_id))


async def ensure_bazar_external_nd_indexes() -> None:
    await db.bazar_external_nd.create_index("ndNo", unique=True, name="bazar_external_nd_no_unique")
    await db.bazar_external_nd.create_index([("status", 1), ("createdAt", -1)], name="bazar_external_nd_status")
