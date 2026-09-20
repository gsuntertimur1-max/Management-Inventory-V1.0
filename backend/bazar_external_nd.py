from __future__ import annotations

from collections import defaultdict
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend.server import db, get_current_user, new_id, normalize_channel, now_iso
from backend.role_four_config import has_role_permission, role_destination
from backend.consignment_damaged import credit_consignment_damaged
from backend.consignment_locations import normalize_consignment_stack_code
from backend.operational_guards import idempotent_operation, lock_keys
import backend.consignment as consignment_module


router = APIRouter(prefix="/api/bazar/external-nds")
BAZAR = "Gudang Bazar"
EPS = 1e-9
ACTIVITY_TYPES = {"BAZAR", "PAKET", "BAZAR_DAN_PAKET"}


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


class ReturnItemInput(BaseModel):
    productId: str
    qty: float = Field(gt=0)
    stackCode: str


class ExternalNDReturn(BaseModel):
    returnDate: str
    items: List[ReturnItemInput] = Field(min_length=1)
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


class ExternalNDCancel(BaseModel):
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
        summary.append({
            **item,
            **totals,
            "received": received,
            "remainingToReceive": remaining_to_receive,
            "physicalBalance": physical_balance,
            "eligibleSoQty": eligible_so,
            "unsettledQty": physical_balance + eligible_so,
        })
    if doc.get("cancelledAt"):
        status = "DIBATALKAN"
    elif summary and all(row["remainingToReceive"] <= EPS and row["unsettledQty"] <= EPS for row in summary):
        status = "SELESAI"
    elif doc.get("soDocuments"):
        status = "SO_TERBIT_SEBAGIAN"
    elif doc.get("realizations"):
        status = "DIREALISASIKAN_SEBAGIAN"
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


def _product_ids(document: dict) -> list[str]:
    return sorted({
        str(item.get("productId") or "").strip()
        for item in document.get("items", [])
        if str(item.get("productId") or "").strip()
    })


def _nd_locks(nd_id: str, product_ids: list[str], extra: list[str] | None = None) -> list[str]:
    return lock_keys(
        [f"external-nd:{nd_id}"],
        (f"consignment:{BAZAR}:{product_id}" for product_id in product_ids),
        extra or [],
    )


async def _source_lots(nd_id: str, product_id: str = "") -> list[dict]:
    query = {"ndId": nd_id}
    if product_id:
        query["productId"] = product_id
    return await db.bazar_external_nd_lots.find(
        query,
        {"_id": 0},
    ).sort([("receiptDate", 1), ("createdAt", 1), ("lotNo", 1)]).to_list(20000)


async def _attach_source_lots(document: dict) -> dict:
    doc = summarize_external_nd(document)
    lots = await _source_lots(str(doc.get("id") or ""))
    doc["sourceLots"] = lots
    lot_by_product: dict[str, list[dict]] = defaultdict(list)
    for lot in lots:
        lot_by_product[str(lot.get("productId") or "")].append(lot)
    for row in doc.get("summaryItems", []):
        product_lots = lot_by_product.get(str(row.get("productId") or ""), [])
        row["sourceLotCount"] = len(product_lots)
        row["sourceLotRemaining"] = sum(_n(lot.get("remainingQty")) for lot in product_lots)
    return doc


async def _summarized_document(nd_id: str) -> dict:
    return await _attach_source_lots(await _document(nd_id))


async def _plan_source_lot_allocations(nd_id: str, product_id: str, qty: float) -> list[dict]:
    needed = float(qty or 0)
    if needed <= EPS:
        return []
    lots = await db.bazar_external_nd_lots.find(
        {"ndId": nd_id, "productId": product_id, "remainingQty": {"$gt": EPS}},
        {"_id": 0},
    ).sort([("receiptDate", 1), ("createdAt", 1), ("lotNo", 1)]).to_list(20000)
    allocations: list[dict] = []
    remaining = needed
    for lot in lots:
        if remaining <= EPS:
            break
        available = _n(lot.get("remainingQty"))
        if available <= EPS:
            continue
        take = min(available, remaining)
        allocations.append({
            "lotId": lot.get("id", ""),
            "lotNo": lot.get("lotNo", ""),
            "receiptId": lot.get("receiptId", ""),
            "receiptDate": lot.get("receiptDate", ""),
            "stackCode": lot.get("stackCode", ""),
            "qty": take,
        })
        remaining -= take
    if remaining > EPS:
        raise HTTPException(
            status_code=409,
            detail=f"Trace sumber ND tidak cukup untuk produk ini. Saldo lot kurang {remaining:g}. Periksa Kontrol Integritas.",
        )
    return allocations


async def _apply_source_allocations(allocations: list[dict], counter_field: str) -> list[dict]:
    applied: list[dict] = []
    for allocation in allocations:
        qty = _n(allocation.get("qty"))
        result = await db.bazar_external_nd_lots.update_one(
            {"id": allocation.get("lotId"), "remainingQty": {"$gte": qty}},
            {
                "$inc": {"remainingQty": -qty, counter_field: qty},
                "$set": {"updatedAt": now_iso()},
            },
        )
        if result.matched_count == 0:
            for done in reversed(applied):
                rollback_qty = _n(done.get("qty"))
                await db.bazar_external_nd_lots.update_one(
                    {"id": done.get("lotId")},
                    {"$inc": {"remainingQty": rollback_qty, counter_field: -rollback_qty}, "$set": {"updatedAt": now_iso()}},
                )
            raise HTTPException(status_code=409, detail="Saldo lot sumber ND berubah. Muat ulang lalu coba kembali.")
        applied.append(allocation)
    return applied


async def _rollback_source_allocations(allocations: list[dict], counter_field: str) -> None:
    for allocation in reversed(allocations):
        qty = _n(allocation.get("qty"))
        await db.bazar_external_nd_lots.update_one(
            {"id": allocation.get("lotId")},
            {"$inc": {"remainingQty": qty, counter_field: -qty}, "$set": {"updatedAt": now_iso()}},
        )


def _source_slice(source_allocations: list[dict], skip_qty: float, take_qty: float) -> list[dict]:
    skip = float(skip_qty or 0)
    remaining = float(take_qty or 0)
    result: list[dict] = []
    for source in source_allocations or []:
        qty = _n(source.get("qty"))
        if skip >= qty - EPS:
            skip -= qty
            continue
        usable = qty - skip
        skip = 0.0
        take = min(usable, remaining)
        if take > EPS:
            result.append({**source, "qty": take})
            remaining -= take
        if remaining <= EPS:
            break
    return result


def _plan_realization_allocations(document: dict, product_id: str, qty: float) -> list[dict]:
    needed = float(qty or 0)
    settled_by_realization: dict[str, float] = defaultdict(float)
    for so in document.get("soDocuments", []):
        for item in so.get("items", []):
            if item.get("productId") != product_id:
                continue
            for allocation in item.get("realizationAllocations", []):
                settled_by_realization[str(allocation.get("realizationId") or "")] += _n(allocation.get("qty"))

    result: list[dict] = []
    remaining = needed
    for realization in document.get("realizations", []):
        if remaining <= EPS:
            break
        realization_id = str(realization.get("id") or "")
        item = next((row for row in realization.get("items", []) if row.get("productId") == product_id), None)
        if not item:
            continue
        realized_qty = _n(item.get("qty"))
        already_settled = _n(settled_by_realization.get(realization_id))
        available = max(realized_qty - already_settled, 0.0)
        if available <= EPS:
            continue
        take = min(available, remaining)
        result.append({
            "realizationId": realization_id,
            "realizationDate": realization.get("realizationDate", ""),
            "activityType": realization.get("activityType", ""),
            "referenceId": realization.get("referenceId", ""),
            "referenceNo": realization.get("referenceNo", ""),
            "qty": take,
            "sourceAllocations": _source_slice(item.get("sourceAllocations", []), already_settled, take),
        })
        remaining -= take
    if remaining > EPS:
        raise HTTPException(
            status_code=409,
            detail=f"Trace realisasi untuk SO tidak cukup {remaining:g}. Periksa histori ND sebelum menerbitkan SO.",
        )
    return result


async def _record_history(
    event_type: str,
    document: dict,
    user: dict,
    items: list[dict],
    note: str = "",
    extra: dict | None = None,
) -> None:
    row = {
        "id": new_id(),
        "time": now_iso(),
        "destination": BAZAR,
        "eventType": event_type,
        "referenceId": document["id"],
        "referenceNo": document.get("ndNo", ""),
        "operator": user.get("name", ""),
        "items": items,
        "note": str(note or "").strip(),
        "originWarehouse": document.get("originWarehouse", ""),
    }
    if extra:
        row.update(extra)
    await db.consignment_operation_history.insert_one(row)


def _validate_activity_allowed(document: dict, activity_type: str) -> str:
    activity_type = str(activity_type or "").strip().upper()
    if activity_type not in {"BAZAR", "PAKET"}:
        raise HTTPException(status_code=400, detail="Jenis realisasi harus BAZAR atau PAKET")
    scope = str(document.get("activityType") or "BAZAR").strip().upper()
    if scope == "BAZAR" and activity_type != "BAZAR":
        raise HTTPException(status_code=409, detail="ND ini hanya diperuntukkan untuk Bazar")
    if scope == "PAKET" and activity_type != "PAKET":
        raise HTTPException(status_code=409, detail="ND ini hanya diperuntukkan untuk Paket")
    if scope not in ACTIVITY_TYPES:
        raise HTTPException(status_code=409, detail="Jenis kegiatan pada ND tidak dikenali")
    return activity_type


async def _reference_capacity(activity_type: str, reference_no: str) -> tuple[dict, dict[str, float]]:
    reference_no = str(reference_no or "").strip().upper()
    if not reference_no:
        raise HTTPException(status_code=400, detail="Referensi kegiatan Bazar/Paket wajib dipilih")

    capacity: dict[str, float] = defaultdict(float)
    if activity_type == "BAZAR":
        source = await db.bazar_trips.find_one({"tripNo": reference_no}, {"_id": 0})
        if not source:
            raise HTTPException(status_code=404, detail="Referensi perjalanan Bazar tidak ditemukan")
        if source.get("status") != "SELESAI":
            raise HTTPException(status_code=409, detail="Perjalanan Bazar harus selesai sebelum dapat direalisasikan ke ND")
        for item in source.get("resultItems", []):
            capacity[str(item.get("productId") or "")] += _n(item.get("soldQty"))
    else:
        source = await db.bazar_package_loads.find_one({"loadNo": reference_no}, {"_id": 0})
        if not source:
            raise HTTPException(status_code=404, detail="Referensi pemuatan Paket tidak ditemukan")
        if source.get("status") != "SELESAI":
            raise HTTPException(status_code=409, detail="Pemuatan Paket harus selesai sebelum dapat direalisasikan ke ND")
        for loaded in source.get("resultItems", []):
            delivered = _n(loaded.get("deliveredQty"))
            for component in loaded.get("components", []):
                product_id = str(component.get("productId") or "")
                if product_id:
                    capacity[product_id] += delivered * _n(component.get("qty"))
    return source, dict(capacity)


async def _reference_used_qty(activity_type: str, reference_no: str, product_id: str) -> float:
    used = 0.0
    rows = await db.bazar_external_nd.find(
        {
            "realizations": {
                "$elemMatch": {
                    "activityType": activity_type,
                    "referenceNo": reference_no,
                }
            }
        },
        {"_id": 0, "realizations": 1},
    ).to_list(5000)
    for document in rows:
        for entry in document.get("realizations", []):
            if entry.get("activityType") != activity_type or entry.get("referenceNo") != reference_no:
                continue
            for item in entry.get("items", []):
                if item.get("productId") == product_id:
                    used += _n(item.get("qty"))
    return used


async def _rollback_damaged_credit(event_key: str, item: dict, qty: float) -> None:
    movement = await db.consignment_damaged_movements.find_one({"eventKey": event_key}, {"_id": 0})
    if not movement:
        return
    channel = normalize_channel(item.get("channel"), "KOM")
    await db.consignment_damaged_movements.delete_one({"eventKey": event_key})
    await db.consignment_damaged_balances.update_one(
        {"destination": BAZAR, "productId": item.get("productId", ""), "channel": channel},
        {"$inc": {"qty": -qty}, "$set": {"updatedAt": now_iso()}},
    )


@router.get("")
async def list_external_nds(user: dict = Depends(get_current_user)):
    _ensure_access(user, write=False)
    rows = await db.bazar_external_nd.find({}, {"_id": 0}).sort("createdAt", -1).to_list(5000)
    return [await _attach_source_lots(row) for row in rows]


@router.post("")
async def create_external_nd(body: ExternalNDCreate, request: Request, user: dict = Depends(get_current_user)):
    _ensure_access(user, write=True)
    nd_no = body.ndNo.strip().upper()
    origin = body.originWarehouse.strip()
    activity_type = body.activityType.strip().upper() or "BAZAR"
    if not nd_no or not body.ndDate or not origin:
        raise HTTPException(status_code=400, detail="Nomor ND, tanggal ND, dan gudang asal wajib diisi")
    if activity_type not in ACTIVITY_TYPES:
        raise HTTPException(status_code=400, detail="Jenis kegiatan ND harus BAZAR, PAKET, atau BAZAR_DAN_PAKET")

    grouped = defaultdict(float)
    for item in body.items:
        grouped[item.productId] += float(item.qty)
    product_ids = sorted(grouped)

    async def action():
        if await db.bazar_external_nd.find_one({"ndNo": nd_no}, {"_id": 0, "id": 1}):
            raise HTTPException(status_code=409, detail="Nomor ND sudah terdaftar")
        items = [{**(await _identity(product_id)), "orderedQty": qty} for product_id, qty in grouped.items()]
        now = now_iso()
        document = {
            "id": new_id(),
            "ndNo": nd_no,
            "ndDate": body.ndDate,
            "originWarehouse": origin,
            "activityType": activity_type,
            "items": items,
            "receipts": [],
            "returns": [],
            "realizations": [],
            "soDocuments": [],
            "note": body.note.strip(),
            "createdAt": now,
            "createdBy": user.get("name", ""),
        }
        await db.bazar_external_nd.insert_one(dict(document))
        await _record_history("BAZAR_ND_EKSTERNAL_DIBUAT", document, user, items, body.note)
        return summarize_external_nd(document)

    return await idempotent_operation(
        request,
        user,
        f"external-nd-create:{nd_no}",
        lock_keys([f"external-nd-no:{nd_no}"], (f"consignment:{BAZAR}:{pid}" for pid in product_ids)),
        action,
    )


@router.post("/{nd_id}/receipts")
async def receive_external_nd(
    nd_id: str,
    body: ExternalNDReceipt,
    request: Request,
    user: dict = Depends(get_current_user),
):
    _ensure_access(user, write=True)
    initial = await _document(nd_id)

    async def action():
        document = await _document(nd_id)
        if document.get("cancelledAt"):
            raise HTTPException(status_code=409, detail="ND sudah dibatalkan")

        requested_by_product = defaultdict(float)
        receipt_items = []
        for entered in body.items:
            source = next((row for row in document.get("items", []) if row.get("productId") == entered.productId), None)
            if not source:
                raise HTTPException(status_code=400, detail="Penerimaan memuat produk yang tidak tercantum pada ND")
            good, damaged = float(entered.goodQty), float(entered.damagedQty)
            if good + damaged <= EPS:
                continue
            stack_code = ""
            if good > EPS:
                stack_code = normalize_consignment_stack_code(BAZAR, entered.stackCode or "18/A01-BAZAR")
            requested_by_product[entered.productId] += good + damaged
            receipt_items.append({
                **source,
                "goodQty": good,
                "damagedQty": damaged,
                "stackCode": stack_code,
            })

        if not receipt_items:
            raise HTTPException(status_code=400, detail="Isi minimal satu jumlah penerimaan")

        for product_id, requested in requested_by_product.items():
            totals = _item_totals(document, product_id)
            outstanding = max(totals["ordered"] - totals["good"] - totals["damaged"], 0.0)
            if requested > outstanding + EPS:
                source = next(row for row in document.get("items", []) if row.get("productId") == product_id)
                raise HTTPException(
                    status_code=409,
                    detail=f"Penerimaan {source.get('name', '')} melebihi sisa ND {outstanding:g}",
                )

        receipt_id, now = new_id(), now_iso()
        for index, item in enumerate(receipt_items):
            if _n(item.get("goodQty")) > EPS:
                lot_id = new_id()
                item["sourceLotId"] = lot_id
                item["sourceLotNo"] = f"NDL-{body.receiptDate.replace('-', '')}-{receipt_id[:6].upper()}-{index + 1:02d}"
        receipt = {
            "id": receipt_id,
            "receiptDate": body.receiptDate,
            "vehicleNo": body.vehicleNo.strip().upper(),
            "items": receipt_items,
            "note": body.note.strip(),
            "createdAt": now,
            "createdBy": user.get("name", ""),
        }
        good_events: list[tuple[str, dict]] = []
        damaged_events: list[tuple[str, dict, float]] = []
        inserted_lot_ids: list[str] = []
        receipt_saved = False
        try:
            for index, item in enumerate(receipt_items):
                good_qty = _n(item.get("goodQty"))
                damaged_qty = _n(item.get("damagedQty"))
                if good_qty > EPS:
                    event_key = f"bazar-external-nd-receipt:{receipt_id}:{index}:{item['productId']}"
                    lot_doc = {
                        "id": item.get("sourceLotId", ""),
                        "lotNo": item.get("sourceLotNo", ""),
                        "ndId": nd_id,
                        "ndNo": document.get("ndNo", ""),
                        "originWarehouse": document.get("originWarehouse", ""),
                        "receiptId": receipt_id,
                        "receiptDate": body.receiptDate,
                        "productId": item["productId"],
                        "sku": item.get("sku", ""),
                        "name": item.get("name", ""),
                        "unit": item.get("unit", ""),
                        "channel": item.get("channel", "KOM"),
                        "stackCode": item.get("stackCode", ""),
                        "receivedQty": good_qty,
                        "remainingQty": good_qty,
                        "returnedQty": 0.0,
                        "realizedQty": 0.0,
                        "createdAt": now,
                        "createdBy": user.get("name", ""),
                        "updatedAt": now,
                    }
                    await db.bazar_external_nd_lots.insert_one(dict(lot_doc))
                    inserted_lot_ids.append(lot_doc["id"])
                    movement = {
                        "id": new_id(),
                        "eventKey": event_key,
                        "time": now,
                        "destination": BAZAR,
                        "movementType": "ND_EKSTERNAL_DITERIMA",
                        "referenceId": nd_id,
                        "referenceNo": document.get("ndNo", ""),
                        "sourceType": "GUDANG_EKSTERNAL",
                        "originWarehouse": document.get("originWarehouse", ""),
                        "productId": item["productId"],
                        "sku": item.get("sku", ""),
                        "name": item.get("name", ""),
                        "unit": item.get("unit", ""),
                        "channel": item.get("channel", "KOM"),
                        "delta": good_qty,
                        "stackCode": item.get("stackCode", ""),
                        "sourceLotId": item.get("sourceLotId", ""),
                        "sourceLotNo": item.get("sourceLotNo", ""),
                        "operator": user.get("name", ""),
                    }
                    await db.consignment_movements.insert_one(dict(movement))
                    good_events.append((event_key, item))
                    await consignment_module.sync_consignment_layout_balance(
                        BAZAR,
                        item["productId"],
                        operator=user.get("name", ""),
                        preferred_stack=item.get("stackCode", ""),
                        operation_key=event_key,
                        note=f"Penerimaan ND eksternal {document.get('ndNo', '')} ditempatkan ke lokasi fisik.",
                    )
                if damaged_qty > EPS:
                    damaged_key = f"bazar-external-nd-damaged:{receipt_id}:{index}:{item['productId']}"
                    await credit_consignment_damaged(
                        BAZAR,
                        item,
                        damaged_qty,
                        damaged_key,
                        "ND_EKSTERNAL_RUSAK_DITERIMA",
                        nd_id,
                        document.get("ndNo", ""),
                        user.get("name", ""),
                        body.note,
                    )
                    damaged_events.append((damaged_key, item, damaged_qty))

            result = await db.bazar_external_nd.update_one(
                {"id": nd_id, "cancelledAt": {"$exists": False}, "receipts.id": {"$ne": receipt_id}},
                {"$push": {"receipts": receipt}, "$set": {"updatedAt": now, "updatedBy": user.get("name", "")}},
            )
            if result.matched_count == 0:
                raise HTTPException(status_code=409, detail="ND berubah saat penerimaan. Muat ulang lalu coba kembali.")
            receipt_saved = True
            await _record_history(
                "BAZAR_ND_EKSTERNAL_DITERIMA",
                document,
                user,
                receipt_items,
                body.note,
                {"vehicleNo": receipt["vehicleNo"], "operationId": receipt_id},
            )
            return await _summarized_document(nd_id)
        except Exception:
            if receipt_saved:
                await db.bazar_external_nd.update_one({"id": nd_id}, {"$pull": {"receipts": {"id": receipt_id}}})
            await db.consignment_operation_history.delete_many({"operationId": receipt_id})
            if inserted_lot_ids:
                await db.bazar_external_nd_lots.delete_many({"id": {"$in": inserted_lot_ids}})
            for damaged_key, item, qty in reversed(damaged_events):
                await _rollback_damaged_credit(damaged_key, item, qty)
            for event_key, item in reversed(good_events):
                await db.consignment_movements.delete_one({"eventKey": event_key})
                try:
                    await consignment_module.sync_consignment_layout_balance(
                        BAZAR,
                        item["productId"],
                        operator="Sistem (rollback ND eksternal)",
                        preferred_stack=item.get("stackCode", ""),
                        operation_key=f"{event_key}:rollback",
                        note="Rollback penerimaan ND eksternal yang tidak selesai.",
                    )
                except Exception:
                    pass
            raise

    return await idempotent_operation(
        request,
        user,
        f"external-nd-receipt:{nd_id}",
        _nd_locks(nd_id, _product_ids(initial)),
        action,
    )


@router.post("/{nd_id}/returns")
async def return_external_nd(
    nd_id: str,
    body: ExternalNDReturn,
    request: Request,
    user: dict = Depends(get_current_user),
):
    _ensure_access(user, write=True)
    initial = await _document(nd_id)

    async def action():
        document = await _document(nd_id)
        if document.get("cancelledAt"):
            raise HTTPException(status_code=409, detail="ND sudah dibatalkan")

        grouped = defaultdict(float)
        prepared = []
        for row in body.items:
            source = next((item for item in document.get("items", []) if item.get("productId") == row.productId), None)
            if not source:
                raise HTTPException(status_code=400, detail="Produk retur tidak tercantum pada ND")
            stack_code = normalize_consignment_stack_code(BAZAR, row.stackCode)
            grouped[row.productId] += float(row.qty)
            prepared.append({**source, "qty": float(row.qty), "stackCode": stack_code})

        for product_id, qty in grouped.items():
            totals = _item_totals(document, product_id)
            returnable = max(totals["good"] - totals["returned"] - totals["realized"], 0.0)
            if qty > returnable + EPS:
                source = next(row for row in document.get("items", []) if row.get("productId") == product_id)
                raise HTTPException(status_code=409, detail=f"Saldo belum SO {source.get('name', '')} hanya {returnable:g}")

        allocations_by_product = {
            product_id: await _plan_source_lot_allocations(nd_id, product_id, qty)
            for product_id, qty in grouped.items()
        }
        allocation_offsets: dict[str, int] = defaultdict(int)
        for item in prepared:
            product_id = str(item.get("productId") or "")
            needed = _n(item.get("qty"))
            source_allocations = allocations_by_product.get(product_id, [])
            offset = allocation_offsets[product_id]
            item["sourceAllocations"] = _source_slice(source_allocations, offset, needed)
            allocation_offsets[product_id] += needed

        return_id, now = new_id(), now_iso()
        entry = {
            "id": return_id,
            "returnDate": body.returnDate,
            "items": prepared,
            "note": body.note.strip(),
            "createdAt": now,
            "createdBy": user.get("name", ""),
        }
        events: list[tuple[str, dict]] = []
        applied_source_allocations: list[dict] = []
        saved = False
        try:
            for product_id, allocations in allocations_by_product.items():
                applied_source_allocations.extend(await _apply_source_allocations(allocations, "returnedQty"))
            for index, item in enumerate(prepared):
                event_key = f"bazar-external-nd-return:{return_id}:{index}:{item['productId']}"
                movement = {
                    "id": new_id(),
                    "eventKey": event_key,
                    "time": now,
                    "destination": BAZAR,
                    "movementType": "RETUR_KE_GUDANG_ASAL",
                    "referenceId": nd_id,
                    "referenceNo": document.get("ndNo", ""),
                    "originWarehouse": document.get("originWarehouse", ""),
                    "productId": item["productId"],
                    "sku": item.get("sku", ""),
                    "name": item.get("name", ""),
                    "unit": item.get("unit", ""),
                    "channel": item.get("channel", "KOM"),
                    "delta": -_n(item.get("qty")),
                    "stackCode": item.get("stackCode", ""),
                    "operator": user.get("name", ""),
                }
                await db.consignment_movements.insert_one(dict(movement))
                events.append((event_key, item))
                try:
                    await consignment_module.decrease_consignment_layouts(
                        BAZAR,
                        item["productId"],
                        _n(item.get("qty")),
                        user.get("name", ""),
                        item.get("stackCode", ""),
                        strict_preferred=True,
                        operation_key=event_key,
                    )
                except Exception:
                    await db.consignment_movements.delete_one({"eventKey": event_key})
                    events.pop()
                    raise

            result = await db.bazar_external_nd.update_one(
                {"id": nd_id, "cancelledAt": {"$exists": False}, "returns.id": {"$ne": return_id}},
                {"$push": {"returns": entry}, "$set": {"updatedAt": now, "updatedBy": user.get("name", "")}},
            )
            if result.matched_count == 0:
                raise HTTPException(status_code=409, detail="ND berubah saat retur. Muat ulang lalu coba kembali.")
            saved = True
            await _record_history(
                "BAZAR_RETUR_KE_GUDANG_ASAL",
                document,
                user,
                prepared,
                body.note,
                {"returnDate": body.returnDate, "operationId": return_id},
            )
            return await _summarized_document(nd_id)
        except Exception:
            if saved:
                await db.bazar_external_nd.update_one({"id": nd_id}, {"$pull": {"returns": {"id": return_id}}})
            await db.consignment_operation_history.delete_many({"operationId": return_id})
            if applied_source_allocations:
                await _rollback_source_allocations(applied_source_allocations, "returnedQty")
            for event_key, item in reversed(events):
                await db.consignment_movements.delete_one({"eventKey": event_key})
                try:
                    await consignment_module.sync_consignment_layout_balance(
                        BAZAR,
                        item["productId"],
                        operator="Sistem (rollback retur ND)",
                        preferred_stack=item.get("stackCode", ""),
                        operation_key=f"{event_key}:rollback",
                        note="Rollback retur ke gudang asal yang tidak selesai.",
                    )
                except Exception:
                    pass
            raise

    return await idempotent_operation(
        request,
        user,
        f"external-nd-return:{nd_id}",
        _nd_locks(nd_id, _product_ids(initial)),
        action,
    )


@router.post("/{nd_id}/realizations")
async def realize_external_nd(
    nd_id: str,
    body: ExternalNDRealization,
    request: Request,
    user: dict = Depends(get_current_user),
):
    _ensure_access(user, write=True)
    initial = await _document(nd_id)
    activity_type = _validate_activity_allowed(initial, body.activityType)
    reference_no = body.referenceNo.strip().upper()
    if not reference_no:
        raise HTTPException(status_code=400, detail="Referensi Bazar/Paket wajib dipilih")

    async def action():
        document = await _document(nd_id)
        if document.get("cancelledAt"):
            raise HTTPException(status_code=409, detail="ND sudah dibatalkan")
        current_activity = _validate_activity_allowed(document, activity_type)
        source_operation, capacity = await _reference_capacity(current_activity, reference_no)

        grouped = defaultdict(float)
        for row in body.items:
            grouped[row.productId] += float(row.qty)

        items = []
        for product_id, qty in grouped.items():
            source = next((row for row in document.get("items", []) if row.get("productId") == product_id), None)
            if not source:
                raise HTTPException(status_code=400, detail="Produk realisasi tidak tercantum pada ND")
            totals = _item_totals(document, product_id)
            realizable_nd = max(totals["good"] - totals["returned"] - totals["realized"], 0.0)
            if qty > realizable_nd + EPS:
                raise HTTPException(
                    status_code=409,
                    detail=f"Saldo ND yang belum direalisasi {source.get('name', '')} hanya {realizable_nd:g}",
                )
            operation_qty = _n(capacity.get(product_id))
            used = await _reference_used_qty(current_activity, reference_no, product_id)
            available_reference = max(operation_qty - used, 0.0)
            if qty > available_reference + EPS:
                raise HTTPException(
                    status_code=409,
                    detail=f"Realisasi {source.get('name', '')} pada {reference_no} tersedia hanya {available_reference:g}",
                )
            items.append({
                **source,
                "qty": qty,
                "sourceAllocations": await _plan_source_lot_allocations(nd_id, product_id, qty),
            })

        realization_id, now = new_id(), now_iso()
        entry = {
            "id": realization_id,
            "realizationDate": body.realizationDate,
            "activityType": current_activity,
            "referenceId": source_operation.get("id", ""),
            "referenceNo": reference_no,
            "items": items,
            "note": body.note.strip(),
            "createdAt": now,
            "createdBy": user.get("name", ""),
        }
        applied_source_allocations: list[dict] = []
        saved = False
        try:
            for item in items:
                applied_source_allocations.extend(
                    await _apply_source_allocations(item.get("sourceAllocations", []), "realizedQty")
                )
            result = await db.bazar_external_nd.update_one(
                {"id": nd_id, "cancelledAt": {"$exists": False}, "realizations.id": {"$ne": realization_id}},
                {"$push": {"realizations": entry}, "$set": {"updatedAt": now, "updatedBy": user.get("name", "")}},
            )
            if result.matched_count == 0:
                raise HTTPException(status_code=409, detail="ND berubah saat realisasi. Muat ulang lalu coba kembali.")
            saved = True
            await _record_history(
                "BAZAR_ND_DIREALISASIKAN",
                document,
                user,
                items,
                body.note,
                {
                    "activityType": current_activity,
                    "activityReferenceId": source_operation.get("id", ""),
                    "activityReferenceNo": reference_no,
                    "operationId": realization_id,
                },
            )
            return await _summarized_document(nd_id)
        except Exception:
            if saved:
                await db.bazar_external_nd.update_one({"id": nd_id}, {"$pull": {"realizations": {"id": realization_id}}})
            await db.consignment_operation_history.delete_many({"operationId": realization_id})
            if applied_source_allocations:
                await _rollback_source_allocations(applied_source_allocations, "realizedQty")
            raise

    return await idempotent_operation(
        request,
        user,
        f"external-nd-realize:{nd_id}:{activity_type}:{reference_no}",
        _nd_locks(
            nd_id,
            _product_ids(initial),
            [f"external-nd-reference:{activity_type}:{reference_no}"],
        ),
        action,
    )


@router.post("/{nd_id}/so-documents")
async def settle_external_nd_with_so(
    nd_id: str,
    body: ExternalNDSO,
    request: Request,
    user: dict = Depends(get_current_user),
):
    _ensure_access(user, write=True)
    initial = await _document(nd_id)
    so_no = body.soNo.strip().upper()
    if not so_no or not body.soDate:
        raise HTTPException(status_code=400, detail="Nomor dan tanggal SO wajib diisi")

    async def action():
        document = await _document(nd_id)
        if document.get("cancelledAt"):
            raise HTTPException(status_code=409, detail="ND sudah dibatalkan")
        duplicate_external = await db.bazar_external_nd.find_one(
            {"soDocuments.soNo": so_no},
            {"_id": 0, "id": 1, "ndNo": 1},
        )
        if duplicate_external:
            raise HTTPException(status_code=409, detail=f"Nomor SO sudah digunakan pada ND {duplicate_external.get('ndNo', '')}")
        duplicate_main = await db.outbound_loads.find_one(
            {"$or": [{"ref": so_no}, {"documents": so_no}, {"document_links.no": so_no}]},
            {"_id": 0, "id": 1},
        )
        if duplicate_main:
            raise HTTPException(status_code=409, detail="Nomor SO sudah digunakan pada dokumen Gudang Utama")

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
                raise HTTPException(
                    status_code=409,
                    detail=f"Realisasi yang belum memiliki SO untuk {source.get('name', '')} hanya {eligible:g}",
                )
            items.append({
                **source,
                "qty": qty,
                "realizationAllocations": _plan_realization_allocations(document, product_id, qty),
            })

        so_id, now = new_id(), now_iso()
        entry = {
            "id": so_id,
            "soNo": so_no,
            "soDate": body.soDate,
            "items": items,
            "note": body.note.strip(),
            "createdAt": now,
            "createdBy": user.get("name", ""),
        }
        result = await db.bazar_external_nd.update_one(
            {"id": nd_id, "cancelledAt": {"$exists": False}, "soDocuments.soNo": {"$ne": so_no}},
            {"$push": {"soDocuments": entry}, "$set": {"updatedAt": now, "updatedBy": user.get("name", "")}},
        )
        if result.matched_count == 0:
            raise HTTPException(status_code=409, detail="SO sudah tercatat atau ND berubah. Muat ulang lalu coba kembali.")
        await _record_history(
            "BAZAR_SO_TERBIT",
            document,
            user,
            items,
            body.note,
            {"soNo": so_no, "soDate": body.soDate, "operationId": so_id},
        )
        return await _summarized_document(nd_id)

    return await idempotent_operation(
        request,
        user,
        f"external-nd-so:{nd_id}:{so_no}",
        _nd_locks(nd_id, _product_ids(initial), [f"document:{so_no}"]),
        action,
    )


@router.post("/{nd_id}/cancel")
async def cancel_external_nd(
    nd_id: str,
    body: ExternalNDCancel,
    request: Request,
    user: dict = Depends(get_current_user),
):
    _ensure_access(user, write=True)
    initial = await _document(nd_id)

    async def action():
        document = await _document(nd_id)
        if document.get("cancelledAt"):
            return await _attach_source_lots(document)
        if document.get("receipts") or document.get("returns") or document.get("realizations") or document.get("soDocuments"):
            raise HTTPException(
                status_code=409,
                detail="ND yang sudah memiliki penerimaan/realisasi/retur/SO tidak dapat dibatalkan langsung",
            )
        now = now_iso()
        await db.bazar_external_nd.update_one(
            {"id": nd_id, "cancelledAt": {"$exists": False}},
            {"$set": {
                "cancelledAt": now,
                "cancelledBy": user.get("name", ""),
                "cancelNote": body.note.strip(),
                "updatedAt": now,
                "updatedBy": user.get("name", ""),
            }},
        )
        await _record_history(
            "BAZAR_ND_EKSTERNAL_DIBATALKAN",
            document,
            user,
            [],
            body.note,
            {"operationId": f"cancel:{nd_id}"},
        )
        return await _summarized_document(nd_id)

    return await idempotent_operation(
        request,
        user,
        f"external-nd-cancel:{nd_id}",
        _nd_locks(nd_id, _product_ids(initial)),
        action,
    )


async def ensure_bazar_external_nd_indexes() -> None:
    await db.bazar_external_nd.create_index("ndNo", unique=True, name="bazar_external_nd_no_unique")
    await db.bazar_external_nd.create_index([("status", 1), ("createdAt", -1)], name="bazar_external_nd_status")
    await db.bazar_external_nd.create_index("realizations.referenceNo", name="bazar_external_nd_realization_reference")
    await db.bazar_external_nd.create_index("soDocuments.soNo", name="bazar_external_nd_so_reference")
    await db.bazar_external_nd_lots.create_index("lotNo", unique=True, name="bazar_external_nd_lot_no_unique")
    await db.bazar_external_nd_lots.create_index(
        [("ndId", 1), ("productId", 1), ("receiptDate", 1), ("createdAt", 1)],
        name="bazar_external_nd_lot_fifo",
    )
