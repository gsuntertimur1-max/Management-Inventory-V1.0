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
    documentDate: str = Field(default="", max_length=20)
    productId: str
    qty: float = Field(gt=0)
    note: str = Field(default="", max_length=500)


def _status(plotting: dict) -> str:
    planned = sum(float(x.get("qty", 0) or 0) for x in plotting.get("items", []))
    received = float(plotting.get("_receivedQty", 0) or 0)
    tm_alloc = sum(float(x.get("qty", 0) or 0) for x in plotting.get("documentAllocations", []) if x.get("documentType") == "TM")
    mo_alloc = sum(float(x.get("qty", 0) or 0) for x in plotting.get("documentAllocations", []) if x.get("documentType") == "MO")
    process_scope = plotting.get("scope") in ("REBAGGING", "REPROSES")
    if received <= 1e-9:
        return "Belum Diterima"
    if received + 1e-9 < planned:
        return "Sebagian Diterima"
    if tm_alloc + 1e-9 < received or (process_scope and mo_alloc + 1e-9 < received):
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
        row["pendingInboundQty"] = sum(
            float(item.get("qty", 0) or 0)
            for load in loads if load.get("status") in ("Menunggu Bongkar", "Sedang Bongkar")
            for item in load.get("items", [])
        )
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
        row["pendingInboundQty"] = 0
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
            "secondary": product.get("secondary", ""),
            "secondaryQty": float(product.get("secondaryQty", 0) or 0),
            "channel": product.get("channel", "KOM"),
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
            "secondary": item.get("secondary", ""),
            "secondaryQty": float(item.get("secondaryQty", 0) or 0),
            "cost": 0.0,
            "channel": item.get("channel", "KOM"),
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

    process_scope = plotting.get("scope") in ("REBAGGING", "REPROSES")
    if body.documentType == "MO" and not process_scope:
        raise HTTPException(status_code=400, detail="Nomor MO hanya berlaku untuk Move In Rebagging/Reproses")

    document_no = body.documentNo.strip().upper()
    if process_scope:
        allocations = list(plotting.get("documentAllocations") or [])
        same_type_numbers = {
            str(x.get("documentNo") or "").strip().upper()
            for x in allocations
            if x.get("documentType") == body.documentType and str(x.get("documentNo") or "").strip()
        }
        if same_type_numbers and document_no not in same_type_numbers:
            raise HTTPException(
                status_code=400,
                detail=f"Satu plotting Rebagging/Reproses hanya boleh memakai satu nomor {body.documentType}. Nomor yang sudah tertaut: {', '.join(sorted(same_type_numbers))}",
            )

        other_type = "TM" if body.documentType == "MO" else "MO"
        counterpart_numbers = {
            str(x.get("documentNo") or "").strip().upper()
            for x in allocations
            if x.get("documentType") == other_type and str(x.get("documentNo") or "").strip()
        }
        if len(counterpart_numbers) > 1:
            raise HTTPException(status_code=409, detail="Data dokumen lama tidak konsisten: satu plotting memiliki lebih dari satu pasangan MO/TM")

        # Aturan bisnis Rebagging/Reproses: satu MO hanya boleh berpasangan
        # dengan satu TM, dan satu TM hanya boleh berpasangan dengan satu MO.
        if counterpart_numbers:
            counterpart = next(iter(counterpart_numbers))
            docs = await db.move_in_plottings.find(
                {"scope": {"$in": ["REBAGGING", "REPROSES"]}},
                {"_id": 0, "documentAllocations": 1},
            ).to_list(5000)
            for other_plot in docs:
                other_allocs = list(other_plot.get("documentAllocations") or [])
                has_this = any(
                    x.get("documentType") == body.documentType
                    and str(x.get("documentNo") or "").strip().upper() == document_no
                    for x in other_allocs
                )
                has_counterpart = any(
                    x.get("documentType") == other_type
                    and str(x.get("documentNo") or "").strip().upper() == counterpart
                    for x in other_allocs
                )
                if has_this:
                    foreign_counterparts = {
                        str(x.get("documentNo") or "").strip().upper()
                        for x in other_allocs
                        if x.get("documentType") == other_type and str(x.get("documentNo") or "").strip()
                    }
                    if foreign_counterparts and counterpart not in foreign_counterparts:
                        raise HTTPException(
                            status_code=400,
                            detail=f"{body.documentType} {document_no} sudah berpasangan dengan {other_type} {', '.join(sorted(foreign_counterparts))}. Aturan: 1 MO = 1 TM.",
                        )
                if has_counterpart:
                    foreign_same = {
                        str(x.get("documentNo") or "").strip().upper()
                        for x in other_allocs
                        if x.get("documentType") == body.documentType and str(x.get("documentNo") or "").strip()
                    }
                    if foreign_same and document_no not in foreign_same:
                        raise HTTPException(
                            status_code=400,
                            detail=f"{other_type} {counterpart} sudah berpasangan dengan {body.documentType} {', '.join(sorted(foreign_same))}. Aturan: 1 MO = 1 TM.",
                        )

    if body.productId not in {x.get("productId") for x in plotting.get("items", [])}:
        raise HTTPException(status_code=400, detail="Produk dokumen tidak termasuk plotting ini")

    planned_qty = sum(
        float(x.get("qty", 0) or 0)
        for x in plotting.get("items", [])
        if x.get("productId") == body.productId
    )
    allocated_same_type = sum(
        float(x.get("qty", 0) or 0)
        for x in plotting.get("documentAllocations", [])
        if x.get("documentType") == body.documentType and x.get("productId") == body.productId
    )
    if float(body.qty) > max(planned_qty - allocated_same_type, 0) + 1e-9:
        raise HTTPException(status_code=400, detail="Alokasi dokumen melebihi kuantum plotting yang belum tertaut")

    allocation = {
        "id": new_id(),
        "documentType": body.documentType,
        "documentNo": document_no,
        "documentDate": body.documentDate.strip(),
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


async def _ensure_plotting_inbound_plan(plotting: dict) -> dict:
    """Create/reuse the PO-compatible inbound parent for a Move In plotting.

    Legacy Move In progress rows never changed stock. They are converted only
    into Menunggu Bongkar vehicle plans so the normal inbound engine remains
    authoritative for stack, cost, good/damaged stock and PO receivedQty.
    """
    plotting_id = str(plotting.get("id") or "")
    po = None
    po_id = str(plotting.get("poId") or "")
    if po_id:
        po = await db.purchase_orders.find_one({"id": po_id}, {"_id": 0})
    if not po:
        po = await db.purchase_orders.find_one({"moveInPlottingId": plotting_id}, {"_id": 0})
    if not po:
        product_ids = [str(x.get("productId") or "") for x in plotting.get("items", []) if x.get("productId")]
        products = {
            p["id"]: p
            for p in await db.products.find({"id": {"$in": product_ids}}, {"_id": 0}).to_list(500)
        } if product_ids else {}
        po_id = new_id()
        po_items = []
        for item in plotting.get("items", []):
            product = products.get(str(item.get("productId") or ""), {})
            po_items.append({
                "productId": item.get("productId", ""),
                "sku": product.get("sku", item.get("sku", "")),
                "name": product.get("name", item.get("name", "")),
                "qty": float(item.get("qty", 0) or 0),
                "receivedQty": 0.0,
                "cancelledQty": 0.0,
                "unit": product.get("unit", item.get("unit", "")),
                "weight": float(product.get("weight", item.get("weight", 0)) or 0),
                "secondary": product.get("secondary", item.get("secondary", "")),
                "secondaryQty": float(product.get("secondaryQty", item.get("secondaryQty", 0)) or 0),
                "cost": 0.0,
                "channel": product.get("channel", item.get("channel", "KOM")),
            })
        po = {
            "id": po_id,
            "no": plotting.get("plotNo", f"PLT-IN/{plotting_id[:8]}"),
            "supplier": plotting.get("senderName", ""),
            "date": f"{plotting.get('plottingDate', '')}T00:00:00+07:00",
            "status": "Belum Diterima",
            "items": po_items,
            "total": 0,
            "sourceType": "MOVE_IN",
            "moveInPlottingId": plotting_id,
            "moveInScope": plotting.get("scope", ""),
            "moveInSenderType": plotting.get("senderType", ""),
            "created_by": plotting.get("createdBy", "Sistem"),
            "created_at": plotting.get("createdAt", now_iso()),
        }
        await db.purchase_orders.insert_one(dict(po))
    po_id = str(po.get("id") or "")
    if po_id and plotting.get("poId") != po_id:
        await db.move_in_plottings.update_one(
            {"id": plotting_id},
            {"$set": {"poId": po_id, "updatedAt": now_iso()}},
        )

    receipts = list(plotting.get("receipts", []))
    changed = False
    po_items = {str(x.get("productId") or ""): x for x in po.get("items", [])}
    for receipt in receipts:
        if receipt.get("inboundLoadId"):
            continue
        existing = await db.inbound_loads.find_one(
            {"legacyMoveInReceiptId": receipt.get("id")},
            {"_id": 0, "id": 1},
        )
        if existing:
            receipt["inboundLoadId"] = existing.get("id")
            changed = True
            continue

        stored_items = []
        for item in receipt.get("items", []):
            po_item = po_items.get(str(item.get("productId") or ""), {})
            stored_items.append({
                "productId": item.get("productId", ""),
                "sku": po_item.get("sku", item.get("sku", "")),
                "name": po_item.get("name", item.get("name", "")),
                "unit": po_item.get("unit", item.get("unit", "")),
                "qty": float(item.get("qty", 0) or 0),
                "stackCode": "",
                "exp": "",
                "channel": po_item.get("channel", "KOM"),
            })
        if not stored_items:
            continue

        receipt_date = str(receipt.get("receiptDate") or plotting.get("plottingDate") or "").replace("-", "")
        load_no = f"PB-MIG-{receipt_date or 'LEGACY'}-{str(receipt.get('id') or new_id())[:8].upper()}"
        load_id = new_id()
        created_at = receipt.get("recordedAt") or now_iso()
        load_doc = {
            "id": load_id,
            "loadNo": load_no,
            "poId": po_id,
            "poNo": po.get("no", plotting.get("plotNo", "")),
            "party": po.get("supplier", plotting.get("senderName", "")),
            "polisi": str(receipt.get("vehicleNo") or "-").strip().upper(),
            "driver": "",
            "items": stored_items,
            "status": "Menunggu Bongkar",
            "keterangan": "Migrasi catatan progres Move In lama; stok belum berubah.",
            "weighingForm": False,
            "grossWeight": 0.0,
            "grossMin": 0.0,
            "grossMax": 0.0,
            "unloadingFeeChargeMode": "PENGIRIM",
            "createdAt": created_at,
            "createdBy": receipt.get("recordedBy", plotting.get("createdBy", "Sistem")),
            "moveInPlottingId": plotting_id,
            "legacyMoveInReceiptId": receipt.get("id"),
            "history": [{
                "time": created_at,
                "status": "Menunggu Bongkar",
                "by": receipt.get("recordedBy", "Sistem"),
                "note": "Migrasi dari pencatatan progres Move In lama. Belum mengubah stok/biaya/tumpukan.",
            }],
        }
        await db.inbound_loads.insert_one(dict(load_doc))
        receipt["inboundLoadId"] = load_id
        receipt["migratedAt"] = now_iso()
        changed = True

    if changed:
        await db.move_in_plottings.update_one(
            {"id": plotting_id},
            {"$set": {"receipts": receipts, "updatedAt": now_iso()}},
        )
    return po


async def ensure_move_in_indexes():
    await db.move_in_plottings.create_index([("plottingDate", -1)])
    await db.move_in_plottings.create_index([("senderName", 1), ("plottingDate", -1)])
    await db.move_in_plottings.create_index("plotNo", unique=True)
    await db.purchase_orders.create_index("moveInPlottingId")
    await db.inbound_loads.create_index("legacyMoveInReceiptId")

    legacy = await db.move_in_plottings.find({}, {"_id": 0}).to_list(1000)
    for plotting in legacy:
        await _ensure_plotting_inbound_plan(plotting)
