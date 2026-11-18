from typing import List, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.server import db, get_current_user, new_id, now_iso, normalize_channel, require_write
from backend.outbound_flow import PARTIAL_DOCUMENT_TYPES, _doc_key, _document_type, _so_balance, _validate_pack_qty

router = APIRouter(prefix="/api")

PROCESS_SCOPES = {"REBAGGING", "REPROSES"}


class OutboundMasterItemInput(BaseModel):
    productId: str
    orderedQty: float = Field(gt=0, allow_inf_nan=False)
    inputMode: Literal["QTY", "WEIGHT"] = "QTY"
    inputValue: float = Field(gt=0, allow_inf_nan=False)


class OutboundMasterCreateInput(BaseModel):
    documentType: Literal["SO", "TM", "CT", "ND", "MEMO"]
    documentNo: str = Field(min_length=2, max_length=150)
    documentDate: str = Field(default="", max_length=20)
    party: str = Field(min_length=2, max_length=200)
    items: List[OutboundMasterItemInput] = Field(min_length=1, max_length=100)
    transferScope: Literal["", "LOKAL", "REGIONAL", "NASIONAL", "REBAGGING", "REPROSES"] = ""
    processMoNo: str = Field(default="", max_length=100)
    note: str = Field(default="", max_length=500)


@router.get("/outbound-document-masters")
async def list_outbound_document_masters(user: dict = Depends(get_current_user)):
    docs = await db.outbound_documents.find({}, {"_id": 0}).sort([("documentDate", -1), ("createdAt", -1)]).to_list(2000)
    rows = []
    for doc in docs:
        document_no = _doc_key(doc.get("documentNo"))
        if not document_no:
            continue
        try:
            balance = await _so_balance(document_no)
        except HTTPException:
            continue
        rows.append(balance)
    return rows


@router.post("/outbound-document-masters")
async def create_outbound_document_master(body: OutboundMasterCreateInput, user: dict = Depends(require_write)):
    document_no = _doc_key(body.documentNo)
    detected_type = _document_type(document_no)
    if detected_type != body.documentType:
        expected = {"SO": "SO/", "TM": "TM", "CT": "CT", "ND": "ND", "MEMO": "MEMO"}[body.documentType]
        raise HTTPException(status_code=400, detail=f"Nomor dokumen harus sesuai jenis {body.documentType} (awalan {expected})")

    if body.documentType not in PARTIAL_DOCUMENT_TYPES:
        raise HTTPException(status_code=400, detail="Jenis dokumen tidak mendukung outstanding")

    existing = await db.outbound_documents.find_one(
        {"documentNo": document_no, "documentType": body.documentType},
        {"_id": 0},
    )
    if existing:
        raise HTTPException(status_code=409, detail=f"{body.documentType} {document_no} sudah terdaftar")

    transfer_scope = body.transferScope.strip().upper()
    process_mo_no = body.processMoNo.strip().upper()
    if body.documentType == "TM":
        if not transfer_scope:
            raise HTTPException(status_code=400, detail="Pilih cakupan Transfer Move")
        if transfer_scope in PROCESS_SCOPES and not process_mo_no:
            raise HTTPException(status_code=400, detail="Nomor MO wajib diisi untuk TM Rebagging/Reproses")
    else:
        transfer_scope = ""
        process_mo_no = ""

    seen = set()
    items = []
    for row in body.items:
        if row.productId in seen:
            raise HTTPException(status_code=400, detail="Produk yang sama tidak boleh muncul dua kali dalam satu dokumen")
        seen.add(row.productId)
        product = await db.products.find_one({"id": row.productId}, {"_id": 0})
        if not product:
            raise HTTPException(status_code=404, detail="Produk dokumen tidak ditemukan")
        ordered = float(row.orderedQty)
        _validate_pack_qty(product, ordered)
        items.append({
            "productId": product["id"],
            "sku": product.get("sku", ""),
            "name": product.get("name", ""),
            "unit": product.get("unit", ""),
            "channel": normalize_channel(product.get("channel"), "KOM"),
            "orderedQty": ordered,
            "inputMode": row.inputMode,
            "inputValue": float(row.inputValue),
            "unitWeight": float(product.get("weight", 0) or 0),
        })

    now = now_iso()
    doc = {
        "id": new_id(),
        "documentNo": document_no,
        "documentType": body.documentType,
        "documentDate": body.documentDate.strip(),
        "party": body.party.strip(),
        "items": items,
        "transferScope": transfer_scope,
        "processMoNo": process_mo_no,
        "note": body.note.strip(),
        "createdAt": now,
        "createdBy": user.get("name", ""),
        "updatedAt": now,
        "updatedBy": user.get("name", ""),
        "source": "MASTER_PRELOAD",
    }
    await db.outbound_documents.insert_one(dict(doc))
    return await _so_balance(document_no)
