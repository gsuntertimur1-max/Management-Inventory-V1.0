from collections import defaultdict
from datetime import datetime
import re
import random
from typing import List, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.server import (
    db,
    get_current_user,
    max_suffix,
    new_id,
    next_sequence,
    now_iso,
    operational_now,
    require_write,
    require_admin,
    require_cost_view,
    ensure_channel_stock,
    normalize_channel,
    channel_balance,
    get_operational_location,
    has_role_permission,
)
from backend.stack_allocations import valid_stack_codes, allocate_stock_to_stack, decrease_stack_allocation, reconcile_product_allocations
from backend.fefo_selection import get_fefo_pick_guide, selection_requires_reason
from backend.stack_reservations import available_stack_qty
from backend.consignment_locations import normalize_consignment_stack_code
from backend.work_time_costs import handling_fee, holiday_from_settings, local_datetime, work_split

router = APIRouter(prefix="/api")


def _validate_pack_qty(product: dict, qty: float) -> None:
    if float(product.get("secondaryQty", 0) or 0) > 0 and abs(qty - round(qty)) > 1e-6:
        raise HTTPException(
            status_code=400,
            detail=f"Jumlah {product.get('name', 'produk')} harus berupa kemasan primer/pack utuh",
        )


class OutboundItemInput(BaseModel):
    productId: str
    qty: float = Field(gt=0)
    documentNo: str = ""
    # Total kuantum produk pada dokumen induk. Untuk SO baru wajib diisi;
    # untuk pengambilan SO berikutnya sistem memakai master SO yang sudah tersimpan.
    documentQty: float = Field(default=0, ge=0)
    stackCode: str = ""
    channel: str = ""
    fefoExceptionReason: str = Field(default="", max_length=500)


class OutboundCreateInput(BaseModel):
    items: List[OutboundItemInput] = Field(min_length=1)
    party: str
    ref: str = ""
    polisi: str = ""
    pengambil: str = ""
    kondisi: Literal["BAIK", "RUSAK"] = "BAIK"
    keterangan: str = ""
    documentType: Literal["SO", "TM", "CT", "ND", "MEMO"] = "SO"
    transferScope: Literal["", "LOKAL", "REGIONAL", "NASIONAL"] = ""
    documents: List[str] = Field(default_factory=list, max_length=20)
    requestDocument: str = ""
    dispatchPurpose: Literal["BAZAR", "ECOMMERCE", "PEMINJAMAN", "LAINNYA"] = "LAINNYA"
    consignmentDestination: str = ""
    consignmentZone: str = ""
    weighingForm: bool = False
    grossWeight: float = Field(default=0, ge=0)
    grossMin: float = Field(default=0, ge=0)
    grossMax: float = Field(default=0, ge=0)
    # Kosong memakai pengaturan master produk. PENGAMBIL berarti ditagihkan,
    # TERMAKSUK berarti biaya sudah melekat pada SO/harga dokumen.
    loadingFeeChargeMode: Literal["", "PENGAMBIL", "TERMASUK"] = ""


class LoadingFeePaymentInput(BaseModel):
    amount: float = Field(gt=0)
    method: Literal["TUNAI", "TRANSFER", "PIUTANG"] = "TUNAI"
    payer: str = ""
    note: str = ""


class LoadingCompletionItemInput(BaseModel):
    index: int = Field(ge=0)
    normalQtyBefore1600: float = Field(ge=0)


class LoadingCompletionInput(BaseModel):
    items: List[LoadingCompletionItemInput] = Field(default_factory=list, max_length=200)


class DocumentCancelInput(BaseModel):
    documentNo: str = ""
    reason: str = Field(min_length=3, max_length=500)


class SOQuantityCorrectionInput(BaseModel):
    documentNo: str
    productId: str
    orderedQty: float = Field(gt=0)
    reason: str = Field(min_length=3, max_length=500)


class OutboundEditInput(BaseModel):
    items: List[OutboundItemInput] = Field(min_length=1)
    documents: List[str] = Field(min_length=1, max_length=20)
    polisi: str = ""
    pengambil: str = ""


class DailyLoadingSettlementInput(BaseModel):
    recipient: Literal["BURUH", "HARIAN"]
    group: str = ""
    note: str = ""


def _crew_group(unit_loading: str) -> str:
    """Compatibility helper only; unknown locations never fall back to Grup 1."""
    text = str(unit_loading or "").strip().upper()
    if "RTR" in text:
        return "GRUP 3 - RTR"
    if "MP1" in text or any(re.search(rf"(?:UNIT\\s*)?{x}(?:/|\\b)", text) for x in ("21", "22", "23", "24")):
        return "GRUP 2 - MP1/21-24"
    if any(re.search(rf"(?:UNIT\\s*)?{x}(?:/|\\b)", text) for x in ("17", "18", "19", "20")):
        return "GRUP 1 - GBB 17-20"
    return ""


def _loading_fee(
    product: dict,
    qty: float,
    when=None,
    apply_overtime=None,
    apply_holiday=None,
    charge_mode_override: str = "",
    overtime_qty: float | None = None,
    holiday_override: bool | None = None,
) -> dict:
    current = when or operational_now()
    if isinstance(current, str):
        current = datetime.fromisoformat(current.replace("Z", "+00:00")).astimezone(operational_now().tzinfo)
    if overtime_qty is None:
        is_overtime = current.hour >= 16
        if apply_overtime is not None:
            is_overtime = bool(apply_overtime)
        overtime_qty = float(qty or 0) if is_overtime else 0.0
    result = handling_fee(
        product,
        qty,
        overtime_qty,
        current,
        "loading",
        "PENGAMBIL",
        charge_mode_override,
        holiday_override if apply_holiday is None else bool(apply_holiday),
    )
    return result

class ReturnPlacementInput(BaseModel):
    goodQty: float = Field(gt=0)
    stackCode: str


class ReturnItemInput(BaseModel):
    productId: str
    goodQty: float = Field(default=0, ge=0)
    damagedQty: float = Field(default=0, ge=0)
    stackCode: str = ""
    placements: List[ReturnPlacementInput] = Field(default_factory=list, max_length=10)


class ConsignmentReturnInput(BaseModel):
    documentNo: str
    sourceDocumentNo: str = ""
    items: List[ReturnItemInput] = Field(min_length=1)
    note: str = ""
    returnType: Literal["CR", "RETUR"] = "CR"


class SalesReturnInput(BaseModel):
    documentNo: str
    sourceDocumentNo: str
    items: List[ReturnItemInput] = Field(min_length=1)
    note: str = ""


class SettlementItemInput(BaseModel):
    productId: str
    qty: float = Field(gt=0)


class SettlementInput(BaseModel):
    documentNo: str
    sourceDocumentNo: str = ""
    items: List[SettlementItemInput] = Field(min_length=1)
    note: str = ""


def _doc_key(value: str) -> str:
    return str(value or "").strip().upper()


async def _so_usage(document_no: str, exclude_load_id: str = "") -> dict[str, dict]:
    target = _doc_key(document_no)
    query: dict = {
        "document_type": "SO",
        "status": {"$ne": "Dibatalkan"},
        "$or": [{"ref": {"$regex": f"^{re.escape(target)}$", "$options": "i"}}, {"documents": {"$regex": f"^{re.escape(target)}$", "$options": "i"}}],
    }
    if exclude_load_id:
        query["id"] = {"$ne": exclude_load_id}
    loads = await db.outbound_loads.find(query, {"_id": 0, "id": 1, "ref": 1, "status": 1, "items": 1}).to_list(10000)
    usage: dict[str, dict] = defaultdict(lambda: {"completedQty": 0.0, "reservedQty": 0.0})
    for load in loads:
        status = str(load.get("status") or "")
        if status not in {"Menunggu", "Sedang Dimuat", "Selesai"}:
            continue
        fallback = _doc_key(load.get("ref", ""))
        for item in load.get("items", []):
            if _doc_key(item.get("documentNo") or fallback) != target:
                continue
            product_id = str(item.get("productId") or "")
            if not product_id:
                continue
            qty = float(item.get("qty", 0) or 0)
            if status == "Selesai":
                usage[product_id]["completedQty"] += qty
            else:
                usage[product_id]["reservedQty"] += qty
    return dict(usage)


async def _so_balance(document_no: str, exclude_load_id: str = "") -> dict:
    key = _doc_key(document_no)
    master = await db.outbound_documents.find_one({"documentNo": key, "documentType": "SO"}, {"_id": 0})
    usage = await _so_usage(key, exclude_load_id=exclude_load_id)
    if not master:
        return {
            "exists": False,
            "documentNo": key,
            "documentType": "SO",
            "status": "BELUM_TERDAFTAR",
            "items": [],
            "legacyUsage": usage,
        }

    rows = []
    all_complete = bool(master.get("items"))
    any_completed = False
    for item in master.get("items", []):
        product_id = str(item.get("productId") or "")
        ordered = float(item.get("orderedQty", 0) or 0)
        used = usage.get(product_id, {})
        completed = float(used.get("completedQty", 0) or 0)
        reserved = float(used.get("reservedQty", 0) or 0)
        committed = completed + reserved
        remaining = max(ordered - committed, 0.0)
        any_completed = any_completed or completed > 1e-9
        all_complete = all_complete and completed + 1e-9 >= ordered
        rows.append({
            **item,
            "completedQty": completed,
            "reservedQty": reserved,
            "committedQty": committed,
            "remainingQty": remaining,
        })
    status = "SELESAI" if all_complete else "SEBAGIAN" if any_completed else "BELUM_DIAMBIL"
    return {**master, "exists": True, "status": status, "items": rows}


async def _prepare_so_documents(
    *,
    refs: list[str],
    body_items: list[OutboundItemInput],
    products: dict[str, dict],
    party: str,
    exclude_load_id: str = "",
) -> tuple[list[dict], dict[str, list[dict]]]:
    """Validate SO capacity and build master documents without mutating DB."""
    requested: dict[tuple[str, str], float] = defaultdict(float)
    supplied_totals: dict[tuple[str, str], set[float]] = defaultdict(set)
    for item in body_items:
        document_no = _doc_key(item.documentNo or (refs[0] if refs else ""))
        if not document_no:
            continue
        key = (document_no, item.productId)
        requested[key] += float(item.qty)
        if float(item.documentQty or 0) > 1e-9:
            supplied_totals[key].add(float(item.documentQty))

    prepared_docs: list[dict] = []
    progress: dict[str, list[dict]] = {}
    for raw_ref in refs:
        document_no = _doc_key(raw_ref)
        current = await db.outbound_documents.find_one(
            {"documentNo": document_no, "documentType": "SO"},
            {"_id": 0},
        )
        if current and str(current.get("party") or "").strip() and party.strip() and str(current.get("party") or "").strip() != party.strip():
            raise HTTPException(
                status_code=409,
                detail=f"SO {document_no} sudah terdaftar untuk penerima {current.get('party', '')}.",
            )

        usage = await _so_usage(document_no, exclude_load_id=exclude_load_id)
        existing_items = {
            str(item.get("productId") or ""): dict(item)
            for item in (current or {}).get("items", [])
            if str(item.get("productId") or "")
        }
        document_progress = []
        document_product_ids = sorted({
            product_id
            for (doc_no, product_id), qty in requested.items()
            if doc_no == document_no and qty > 1e-9
        })

        for product_id in document_product_ids:
            product = products.get(product_id) or {}
            req = float(requested.get((document_no, product_id), 0) or 0)
            totals = supplied_totals.get((document_no, product_id), set())
            if len(totals) > 1:
                raise HTTPException(
                    status_code=400,
                    detail=f"Kuantum induk SO {document_no} untuk {product.get('name', 'produk')} tidak konsisten pada beberapa baris.",
                )
            supplied = next(iter(totals), 0.0)
            existing = existing_items.get(product_id)
            if existing:
                ordered = float(existing.get("orderedQty", 0) or 0)
                if supplied > 1e-9 and abs(supplied - ordered) > 1e-9:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Kuantum induk SO {document_no} untuk {product.get('name', 'produk')} sudah tercatat {ordered:g} {product.get('unit', '')} dan tidak boleh berubah saat pengambilan.",
                    )
            else:
                if supplied <= 1e-9:
                    legacy = usage.get(product_id, {})
                    legacy_used = float(legacy.get("completedQty", 0) or 0) + float(legacy.get("reservedQty", 0) or 0)
                    extra = f" Pengambilan lama yang sudah tercatat {legacy_used:g} {product.get('unit', '')}." if legacy_used > 1e-9 else ""
                    raise HTTPException(
                        status_code=400,
                        detail=f"Isi Kuantum SO total untuk {product.get('name', 'produk')} pada {document_no}.{extra}",
                    )
                ordered = supplied
                existing = {
                    "productId": product_id,
                    "sku": product.get("sku", ""),
                    "name": product.get("name", ""),
                    "unit": product.get("unit", ""),
                    "channel": normalize_channel(product.get("channel"), "KOM"),
                    "orderedQty": ordered,
                }
                existing_items[product_id] = existing

            used = usage.get(product_id, {})
            completed = float(used.get("completedQty", 0) or 0)
            reserved = float(used.get("reservedQty", 0) or 0)
            committed = completed + reserved
            remaining_before = max(ordered - committed, 0.0)
            if req > remaining_before + 1e-9:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Sisa SO {document_no} untuk {product.get('name', 'produk')} hanya {remaining_before:g} {product.get('unit', '')}. "
                        f"Total SO {ordered:g}; selesai {completed:g}; masih terreservasi {reserved:g}."
                    ),
                )
            document_progress.append({
                "productId": product_id,
                "name": product.get("name", ""),
                "unit": product.get("unit", ""),
                "orderedQty": ordered,
                "completedBefore": completed,
                "reservedBefore": reserved,
                "currentLoadQty": req,
                "remainingAfter": max(remaining_before - req, 0.0),
            })

        if not current:
            now = now_iso()
            current = {
                "id": new_id(),
                "documentNo": document_no,
                "documentType": "SO",
                "party": party.strip(),
                "items": [],
                "createdAt": now,
                "createdBy": "",
                "updatedAt": now,
            }
        current = {
            **current,
            "documentNo": document_no,
            "documentType": "SO",
            "party": str(current.get("party") or party).strip(),
            "items": list(existing_items.values()),
            "updatedAt": now_iso(),
        }
        prepared_docs.append(current)
        progress[document_no] = document_progress

    return prepared_docs, progress


async def _persist_so_documents(prepared_docs: list[dict], operator: str) -> None:
    for doc in prepared_docs:
        saved = dict(doc)
        if not saved.get("createdBy"):
            saved["createdBy"] = operator
        saved["updatedBy"] = operator
        await db.outbound_documents.replace_one(
            {"documentNo": saved["documentNo"], "documentType": "SO"},
            saved,
            upsert=True,
        )


@router.get("/outbound-document-balance")
async def outbound_document_balance(documentNo: str, user: dict = Depends(get_current_user)):
    document_no = _doc_key(documentNo)
    if not document_no:
        raise HTTPException(status_code=400, detail="Nomor dokumen wajib diisi")
    if not document_no.startswith("SO/"):
        raise HTTPException(status_code=400, detail="Kontrol saldo dokumen bertahap saat ini khusus SO")
    return await _so_balance(document_no)


@router.post("/outbound-document-quantity-correction")
async def correct_outbound_document_quantity(body: SOQuantityCorrectionInput, user: dict = Depends(require_admin)):
    document_no = _doc_key(body.documentNo)
    if not document_no.startswith("SO/"):
        raise HTTPException(status_code=400, detail="Koreksi kuantum induk hanya berlaku untuk SO")

    master = await db.outbound_documents.find_one(
        {"documentNo": document_no, "documentType": "SO"},
        {"_id": 0},
    )
    if not master:
        raise HTTPException(status_code=404, detail="Master SO belum tersedia")

    items = [dict(item) for item in (master.get("items") or [])]
    index = next((i for i, item in enumerate(items) if str(item.get("productId") or "") == body.productId), -1)
    if index < 0:
        raise HTTPException(status_code=404, detail="Komoditas tidak ditemukan pada master SO")

    product = await db.products.find_one({"id": body.productId}, {"_id": 0})
    if product:
        _validate_pack_qty(product, float(body.orderedQty))

    usage = await _so_usage(document_no)
    used = usage.get(body.productId, {})
    completed = float(used.get("completedQty", 0) or 0)
    reserved = float(used.get("reservedQty", 0) or 0)
    committed = completed + reserved
    new_qty = float(body.orderedQty)
    if new_qty + 1e-9 < committed:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Kuantum SO tidak boleh lebih kecil dari yang sudah selesai + terreservasi "
                f"({committed:g} {items[index].get('unit', '')})."
            ),
        )

    old_qty = float(items[index].get("orderedQty", 0) or 0)
    if abs(new_qty - old_qty) <= 1e-9:
        return await _so_balance(document_no)

    now = now_iso()
    event = {
        "id": new_id(),
        "time": now,
        "by": user.get("name", ""),
        "productId": body.productId,
        "sku": items[index].get("sku", ""),
        "name": items[index].get("name", ""),
        "unit": items[index].get("unit", ""),
        "oldOrderedQty": old_qty,
        "newOrderedQty": new_qty,
        "completedQty": completed,
        "reservedQty": reserved,
        "reason": body.reason.strip(),
    }
    items[index]["orderedQty"] = new_qty
    history = list(master.get("quantityCorrectionHistory") or []) + [event]
    await db.outbound_documents.update_one(
        {"documentNo": document_no, "documentType": "SO"},
        {"$set": {
            "items": items,
            "quantityCorrectionHistory": history,
            "lastQuantityCorrection": event,
            "updatedAt": now,
            "updatedBy": user.get("name", ""),
        }},
    )

    # Samakan snapshot kuantum induk pada antrean SO aktif agar edit berikutnya
    # tidak membawa nilai lama, tanpa mengubah jumlah muat/reservasi yang berjalan.
    active_loads = await db.outbound_loads.find(
        {
            "document_type": "SO",
            "status": {"$in": ["Menunggu", "Sedang Dimuat"]},
            "$or": [{"documents": document_no}, {"ref": document_no}],
        },
        {"_id": 0, "id": 1, "items": 1, "ref": 1},
    ).to_list(5000)
    for load in active_loads:
        revised = []
        changed = False
        for item in load.get("items") or []:
            row = dict(item)
            source = _doc_key(row.get("documentNo") or "")
            if source == document_no and str(row.get("productId") or "") == body.productId:
                row["documentQty"] = new_qty
                changed = True
            revised.append(row)
        if changed:
            await db.outbound_loads.update_one(
                {"id": load.get("id")},
                {"$set": {"items": revised, "updated_at": now}},
            )

    return await _so_balance(document_no)


def _weighing_entries(average: float, minimum: float, maximum: float) -> list[dict]:
    target = round(average * 100)
    low, high = round(minimum * 100), round(maximum * 100)
    spread = min(target - low, high - target)
    chooser = random.SystemRandom()
    values = []
    for _ in range(10):
        delta = chooser.randint(0, spread)
        values.extend([target - delta, target + delta])
    chooser.shuffle(values)
    return [{"no": index, "gross": value / 100} for index, value in enumerate(values, 1)]


async def _reserved_qty(product_id: str, kondisi: str, exclude_id: str = "", channel: str = "") -> float:
    query = {"status": {"$in": ["Menunggu", "Sedang Dimuat"]}}
    if exclude_id:
        query["id"] = {"$ne": exclude_id}
    docs = await db.outbound_loads.find(query, {"_id": 0, "items": 1, "kondisi": 1}).to_list(5000)
    total = 0.0
    for doc in docs:
        if doc.get("kondisi", "BAIK") != kondisi:
            continue
        for item in doc.get("items", []):
            if item.get("productId") == product_id and (not channel or normalize_channel(item.get("channel"), normalize_channel(doc.get("channel"))) == channel):
                total += float(item.get("qty", 0) or 0)
    return total


def _loading_unit_from_products(products: List[dict]) -> tuple[str, str]:
    """Bentuk label unit pemuatan dan prefix antrean, contoh: Unit 17 / 17."""
    labels = []
    queue_prefix = ""
    for product in products:
        location = str(product.get("location") or "").strip()
        if not location:
            continue
        match = re.search(r"unit\s*0*(\d+)", location, re.IGNORECASE)
        if not match:
            match = re.search(r"\b(\d{1,3})\b", location)
        if match:
            number = str(int(match.group(1)))
            label = f"Unit {number}"
            if not queue_prefix:
                queue_prefix = number
        else:
            label = location
        if label not in labels:
            labels.append(label)
    return " / ".join(labels) if labels else "-", queue_prefix or "A"


def loading_units_from_items(items: List[dict]) -> tuple[str, str]:
    """Gunakan kode lokasi/tumpukan aktual; lokasi baru dari master tidak perlu hard-code."""
    units = []
    for item in items:
        source = str(item.get("stackCode") or item.get("location") or "").strip().upper()
        head = source.split("/", 1)[0].strip()
        head = re.sub(r"^(?:UNIT|GBB|GUDANG)\s*", "", head).strip()
        unit = head if head and re.fullmatch(r"[A-Z0-9-]+", head) else ""
        if unit and unit not in units:
            units.append(unit)
    if not units:
        return "Lokasi belum tercatat", "A"
    return " / ".join(f"Unit {unit}" if unit != "MP1" else "MP1" for unit in units), (units[0] if len(units) == 1 else "M")


@router.get("/outbound-loads")
async def list_outbound_loads(user: dict = Depends(get_current_user)):
    rows = await db.outbound_loads.find({}, {"_id": 0}).sort("created_at", -1).to_list(2000)
    if has_role_permission(user.get("role"), "costView"):
        return rows
    cleaned = []
    for row in rows:
        copy = dict(row)
        for field in ("loading_cost", "loading_fee_payments", "loading_fee_payment_total", "loading_fee_payment_status"):
            copy.pop(field, None)
        copy["items"] = [
            {key: value for key, value in item.items() if key not in {"loadingFee", "loadingCost"}}
            for item in row.get("items", [])
        ]
        cleaned.append(copy)
    return cleaned


@router.post("/outbound-loads")
async def create_outbound_load(body: OutboundCreateInput, user: dict = Depends(require_write)):
    party = body.party.strip()
    if not party:
        raise HTTPException(status_code=400, detail="Penerima barang wajib diisi")
    if body.weighingForm and (body.grossWeight <= 0 or body.grossMin <= 0 or body.grossMax <= 0):
        raise HTTPException(status_code=400, detail="Rata-rata bruto serta rentang timbang harus diisi")
    if body.weighingForm and not body.grossMin <= body.grossWeight <= body.grossMax:
        raise HTTPException(status_code=400, detail="Rata-rata bruto harus berada di dalam rentang timbang")
    refs = []
    for candidate in [body.ref, *body.documents]:
        value = str(candidate or "").strip()
        if value and value not in refs:
            refs.append(value)
    if not refs:
        raise HTTPException(status_code=400, detail=f"Nomor dokumen {body.documentType} wajib diisi")
    expected = {"SO": "SO/", "TM": "TM", "CT": "CT", "ND": "ND", "MEMO": "MEMO"}[body.documentType]
    if any(not ref.upper().startswith(expected) for ref in refs):
        raise HTTPException(status_code=400, detail=f"Nomor dokumen tidak sesuai jenis {body.documentType}")
    if body.documentType == "TM" and not body.transferScope:
        raise HTTPException(status_code=400, detail="Pilih cakupan Transfer Move")
    if body.consignmentDestination and body.documentType not in {"MEMO", "ND"}:
        raise HTTPException(status_code=400, detail="Stok Gudang Bazar/E-commerce harus dicatat menggunakan Memo atau ND")
    if body.consignmentDestination and body.consignmentDestination not in {"Gudang Bazar", "Gudang E-commerce"}:
        raise HTTPException(status_code=400, detail="Tujuan konsinyasi tidak valid")
    consignment_zone = ""
    if body.consignmentDestination:
        if not body.consignmentZone.strip():
            raise HTTPException(status_code=400, detail="Pilih tumpukan tujuan Bazar/E-commerce di Unit 18")
        consignment_zone = normalize_consignment_stack_code(body.consignmentDestination, body.consignmentZone)
        expected_destination = {"BAZAR": "Gudang Bazar", "ECOMMERCE": "Gudang E-commerce"}.get(body.dispatchPurpose)
        if expected_destination and expected_destination != body.consignmentDestination:
            raise HTTPException(status_code=400, detail="Keperluan Memo/ND tidak sesuai dengan tujuan Bazar/E-commerce")
    elif body.consignmentZone.strip():
        raise HTTPException(status_code=400, detail="Tumpukan tujuan hanya boleh diisi untuk Gudang Bazar/E-commerce")
    # Setiap baris komoditas harus memiliki asal dokumen yang jelas.
    # Untuk satu dokumen, sistem boleh mengisinya otomatis; untuk multi-dokumen wajib dipilih per baris.
    item_document_refs = [str(item.documentNo or "").strip() for item in body.items]
    if len(refs) > 1:
        if any(not item_ref for item_ref in item_document_refs):
            raise HTTPException(status_code=400, detail="Pilih nomor dokumen pada setiap komoditas untuk pemuatan multi-dokumen")
        unknown_refs = sorted({item_ref for item_ref in item_document_refs if item_ref not in refs})
        if unknown_refs:
            raise HTTPException(status_code=400, detail=f"Dokumen komoditas belum didaftarkan: {', '.join(unknown_refs)}")
        unassigned_refs = [ref for ref in refs if ref not in item_document_refs]
        if unassigned_refs:
            raise HTTPException(status_code=400, detail=f"Dokumen belum memiliki komoditas: {', '.join(unassigned_refs)}")
    elif any(item_ref and item_ref not in refs for item_ref in item_document_refs):
        raise HTTPException(status_code=400, detail="Dokumen komoditas belum didaftarkan")

    if body.documentType != "SO":
        for ref in refs:
            if await db.outbound_loads.find_one({"$or": [{"ref": ref}, {"documents": ref}, {"document_links.no": ref}]}):
                raise HTTPException(status_code=409, detail=f"Nomor dokumen {ref} sudah digunakan")

    requested = defaultdict(float)
    item_order = []
    for item in body.items:
        if item.productId not in requested:
            item_order.append(item.productId)
        requested[item.productId] += float(item.qty)

    products = {}
    for product_id in item_order:
        qty = requested[product_id]
        product = await db.products.find_one({"id": product_id}, {"_id": 0})
        if not product:
            raise HTTPException(status_code=404, detail="Produk pengeluaran tidak ditemukan")
        _validate_pack_qty(product, qty)
        if body.documentType in {"MEMO", "ND"} and body.consignmentDestination:
            if float(product.get("weight", 0) or 0) <= 0:
                raise HTTPException(status_code=400, detail=f"Berat per pack/pcs {product.get('name', '')} wajib diisi sebelum dikirim ke Bazar/E-commerce")
            if not product.get("secondary") or float(product.get("secondaryQty", 0) or 0) <= 0:
                raise HTTPException(status_code=400, detail=f"Kemasan sekunder {product.get('name', '')} wajib diisi sebelum dikirim ke Bazar/E-commerce")
        products[product_id] = product

        field = "damaged" if body.kondisi == "RUSAK" else "stock"
        physical = float(product.get(field, 0) or 0)
        reserved = await _reserved_qty(product_id, body.kondisi)
        available = max(physical - reserved, 0)
        if qty > available + 1e-9:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Stok tersedia untuk {product.get('name', 'produk')} tidak mencukupi. "
                    f"Fisik {physical:g}, sudah dialokasikan {reserved:g}, tersedia {available:g} {product.get('unit', '')}"
                ),
            )

    channel_requested = defaultdict(float)
    for item in body.items:
        channel = normalize_channel(item.channel, normalize_channel(products[item.productId].get("channel")))
        channel_requested[(item.productId, channel)] += float(item.qty)
    for (product_id, channel), qty in channel_requested.items():
        product = products[product_id]
        await ensure_channel_stock(product)
        reserved = await _reserved_qty(product_id, body.kondisi, channel=channel)
        available = max(channel_balance(product, channel, "damaged" if body.kondisi == "RUSAK" else "stock") - reserved, 0)
        if qty > available + 1e-9:
            raise HTTPException(status_code=400, detail=f"Stok {channel} untuk {product.get('name', 'produk')} tidak mencukupi. Tersedia {available:g} {product.get('unit', '')}")

    so_documents = []
    so_progress = {}
    if body.documentType == "SO":
        so_documents, so_progress = await _prepare_so_documents(
            refs=refs,
            body_items=body.items,
            products=products,
            party=party,
        )

    multi_source = len(refs) > 1 or len(body.items) > 1
    load_items = []
    fefo_guides = {}
    for item in body.items:
        product = products[item.productId]
        item_ref = item.documentNo.strip() or refs[0]
        if item_ref not in refs:
            raise HTTPException(status_code=400, detail=f"Dokumen komoditas {item_ref} belum didaftarkan")
        qty = float(item.qty)
        weight = float(product.get("weight", 0) or 0)
        stack_code = item.stackCode.strip().upper()
        if body.kondisi == "BAIK" and not stack_code:
            raise HTTPException(status_code=400, detail=f"Pilih tumpukan asal untuk {product.get('name', '')} agar kontrol FEFO dan lokasi pemuatan tercatat")
        channel = normalize_channel(item.channel, normalize_channel(product.get("channel")))
        if stack_code and stack_code not in await valid_stack_codes():
            raise HTTPException(status_code=400, detail="Tumpukan asal tidak valid")
        guide = {}
        selection_status = "NOT_APPLICABLE"
        exception_reason = item.fefoExceptionReason.strip()
        if body.kondisi == "BAIK":
            if item.productId not in fefo_guides:
                fefo_guides[item.productId] = await get_fefo_pick_guide(item.productId)
            guide = fefo_guides[item.productId]
            is_exception = selection_requires_reason(guide, stack_code)
            if is_exception and not exception_reason:
                priorities = ", ".join(guide.get("recommendedStacks", [])) or "-"
                raise HTTPException(status_code=400, detail=f"Tumpukan {stack_code} bukan prioritas {guide.get('mode', 'FEFO')} untuk {product.get('name', '')}. Prioritas: {priorities}. Isi alasan pengecualian.")
            selection_status = "EXCEPTION" if is_exception else ("PRIORITY" if stack_code in guide.get("recommendedStacks", []) else "NO_GUIDE")
        actual_location = stack_code or product.get("location", "")
        location_config = await get_operational_location(actual_location, "outbound") if actual_location else None
        crew_group = ""
        loading_fee = {}
        if location_config and bool(location_config.get("loadingCostEnabled", False)):
            crew_group = _crew_group(location_config.get("loadingGroup", "") or actual_location)
            if crew_group:
                loading_fee = _loading_fee(product, qty, charge_mode_override=body.loadingFeeChargeMode)
        load_items.append({"productId": item.productId, "documentNo": item_ref, "sku": product.get("sku", ""), "name": product.get("name", ""), "channel": channel, "qty": qty, "unit": product.get("unit", ""), "weight": weight, "measureUnit": product.get("measureUnit", "kg") or "kg", "berat": weight * qty, "secondary": product.get("secondary", ""), "secondaryQty": float(product.get("secondaryQty", 0) or 0), "location": product.get("location", ""), "stackCode": stack_code, "locationCode": (location_config or {}).get("code", ""), "locationName": (location_config or {}).get("name", ""), "crewGroup": crew_group, "loadingFee": loading_fee, "fefoPolicy": guide.get("policy", "") if guide else "", "fefoMode": guide.get("mode", "") if guide else "", "fefoRecommendedStacks": guide.get("recommendedStacks", []) if guide else [], "fefoSelectionStatus": selection_status, "fefoExceptionReason": exception_reason if selection_status == "EXCEPTION" else "", "documentQty": float(item.documentQty or 0)})

    if body.kondisi == "BAIK":
        quantities_by_stack = defaultdict(float)
        for item in load_items:
            quantities_by_stack[(item["productId"], item["stackCode"])] += item["qty"]
        for (product_id, stack_code), qty in quantities_by_stack.items():
            allocation = await db.stack_allocations.find_one({"productId": product_id, "stackCode": stack_code}, {"_id": 0, "primaryQty": 1})
            physical = float((allocation or {}).get("primaryQty", 0) or 0)
            reserved, available = await available_stack_qty(product_id, stack_code, physical)
            if qty > available + 1e-9:
                raise HTTPException(status_code=400, detail=f"Stok tumpukan {stack_code} untuk {products[product_id].get('name', '')} tidak cukup. Fisik {physical:g}, direservasi antrean lain {reserved:g}, tersedia {available:g}")

    unit_loading, queue_prefix = loading_units_from_items(load_items)

    op_now = operational_now()
    operational_date = op_now.strftime("%Y-%m-%d")

    queue_floor = await max_suffix(
        db.outbound_loads,
        "antrian",
        f"{queue_prefix}-",
        {"operational_date": operational_date},
    )
    queue_number = await next_sequence(
        f"loading-queue:{operational_date}:{queue_prefix}",
        queue_floor,
    )

    bon_prefix = f"BM-{op_now.strftime('%Y%m%d')}-"
    bon_floor = await max_suffix(
        db.outbound_loads,
        "bon_no",
        bon_prefix,
        {"operational_date": operational_date},
    )
    bon_number = await next_sequence(f"bon-muat:{operational_date}", bon_floor)

    total_unit = sum(float(item["qty"]) for item in load_items)
    total_berat = sum(float(item["berat"]) for item in load_items)
    loading_cost = {key: sum(float(item.get("loadingFee", {}).get(key, 0) or 0) for item in load_items) for key in ("labor", "daily", "warehouse", "total", "chargeable")}
    created_at = now_iso()
    doc = {
        "id": new_id(),
        "bon_no": f"{bon_prefix}{bon_number:03d}",
        "bon_format_version": "BON_72_V3",
        "antrian": f"{queue_prefix}-{queue_number:03d}",
        "operational_date": operational_date,
        "created_at": created_at,
        "started_at": "",
        "completed_at": "",
        "party": party,
        "penerima": party,
        "ref": refs[0],
        "documents": refs,
        "polisi": body.polisi.strip(),
        "pengambil": body.pengambil.strip(),
        "unit_loading": unit_loading,
        "crew_groups": sorted({item.get("crewGroup", "") for item in load_items if item.get("crewGroup")}),
        "kondisi": body.kondisi,
        "keterangan": body.keterangan.strip(),
        "document_type": body.documentType,
        "transfer_scope": body.transferScope if body.documentType == "TM" else "",
        "request_document": body.requestDocument.strip(),
        "dispatch_purpose": body.dispatchPurpose if body.documentType in {"MEMO", "ND"} else "",
        "consignment_destination": body.consignmentDestination.strip(),
        "consignment_zone": consignment_zone,
        "weighing_form": body.weighingForm,
        "gross_weight": float(body.grossWeight) if body.weighingForm else 0,
        "gross_min": float(body.grossMin) if body.weighingForm else 0,
        "gross_max": float(body.grossMax) if body.weighingForm else 0,
        "weighing_entries": _weighing_entries(float(body.grossWeight), float(body.grossMin), float(body.grossMax)) if body.weighingForm else [],
        "document_links": [],
        "so_document_progress": so_progress if body.documentType == "SO" else {},
        "document_status": "Menunggu Pemuatan",
        "loading_cost": loading_cost,
        "loading_fee_payments": [],
        "loading_fee_payment_total": 0.0,
        "loading_fee_payment_status": "TIDAK_DITAGIH" if loading_cost["chargeable"] <= 0 else "BELUM_DIBAYAR",
        "items": load_items,
        "total_unit": total_unit,
        "total_berat": total_berat,
        "status": "Menunggu",
        "created_by": user.get("name", ""),
        "started_by": "",
        "completed_by": "",
        "surat_jalan_id": "",
        "surat_jalan_no": "",
    }
    await db.outbound_loads.insert_one(dict(doc))
    try:
        if body.documentType == "SO":
            await _persist_so_documents(so_documents, user.get("name", ""))
    except Exception:
        await db.outbound_loads.delete_one({"id": doc["id"]})
        raise
    return doc


@router.get("/loading-costs")
async def get_loading_costs(date: str = "", user: dict = Depends(require_cost_view)):
    target_date = date.strip() or operational_now().strftime("%Y-%m-%d")
    try:
        datetime.strptime(target_date, "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Tanggal harus YYYY-MM-DD") from exc
    loads = await db.outbound_loads.find({"status": "Selesai", "operational_date": target_date}, {"_id": 0}).sort("completed_at", 1).to_list(5000)
    rows, totals = [], {"labor": 0.0, "daily": 0.0, "warehouse": 0.0, "total": 0.0, "chargeable": 0.0, "collected": 0.0}
    groups = {name: {"labor": 0.0, "daily": 0.0, "warehouse": 0.0, "total": 0.0, "chargeable": 0.0, "collected": 0.0} for name in ("GRUP 1 - GBB 17-20", "GRUP 2 - MP1/21-24", "GRUP 3 - RTR")}
    for load in loads:
        cost = dict(load.get("loading_cost") or {})
        if not cost:
            cost = {key: sum(float(item.get("loadingFee", {}).get(key, 0) or 0) for item in load.get("items", [])) for key in ("labor", "daily", "warehouse", "total", "chargeable")}
        for key in ("labor", "daily", "warehouse", "total", "chargeable"):
            cost[key] = float(cost.get(key, 0) or 0)
            totals[key] += cost[key]
        collected = float(load.get("loading_fee_payment_total", 0) or 0)
        totals["collected"] += collected
        item_groups = defaultdict(lambda: {"labor": 0.0, "daily": 0.0, "warehouse": 0.0, "total": 0.0, "chargeable": 0.0})
        for item in load.get("items", []):
            group = item.get("crewGroup") or _crew_group(item.get("stackCode") or item.get("location") or load.get("unit_loading"))
            fee = item.get("loadingFee", {}) or {}
            for key in ("labor", "daily", "warehouse", "total", "chargeable"):
                item_groups[group][key] += float(fee.get(key, 0) or 0)
        for group, group_cost in item_groups.items():
            bucket = groups.setdefault(group, {"labor": 0.0, "daily": 0.0, "warehouse": 0.0, "total": 0.0, "chargeable": 0.0, "collected": 0.0})
            for key in ("labor", "daily", "warehouse", "total", "chargeable"):
                bucket[key] += group_cost[key]
        rows.append({"id": load["id"], "antrian": load.get("antrian", ""), "ref": load.get("ref", ""), "documents": load.get("documents", []), "party": load.get("party", ""), "pengambil": load.get("pengambil", ""), "items": load.get("items", []), "cost": cost, "crewGroups": dict(item_groups), "collected": collected, "paymentStatus": load.get("loading_fee_payment_status", "TIDAK_DITAGIH"), "payments": load.get("loading_fee_payments", [])})
    settlements = await db.loading_cost_settlements.find({"date": target_date}, {"_id": 0}).to_list(100)
    settled = {f"{row.get('recipient', '')}:{row.get('group', '')}": row for row in settlements}
    return {"date": target_date, "loads": rows, "totals": {**totals, "outstanding": max(totals["chargeable"] - totals["collected"], 0)}, "groups": {name: {**values, "outstanding": max(values["chargeable"] - values["collected"], 0)} for name, values in groups.items()}, "settlements": settled}


@router.post("/outbound-loads/{load_id}/loading-fee-payment")
async def record_loading_fee_payment(load_id: str, body: LoadingFeePaymentInput, user: dict = Depends(require_write)):
    load = await db.outbound_loads.find_one({"id": load_id}, {"_id": 0})
    if not load or load.get("status") != "Selesai":
        raise HTTPException(status_code=400, detail="Pembayaran biaya muat hanya dapat dicatat setelah pemuatan selesai")
    chargeable = float((load.get("loading_cost") or {}).get("chargeable", 0) or 0)
    if chargeable <= 0:
        raise HTTPException(status_code=400, detail="SO ini tidak memiliki biaya muat yang ditagihkan kepada pengambil")
    collected = float(load.get("loading_fee_payment_total", 0) or 0)
    amount = float(body.amount)
    if amount > chargeable - collected + 1e-9:
        raise HTTPException(status_code=400, detail="Nominal pembayaran melebihi sisa tagihan biaya muat")
    payment = {"id": new_id(), "time": now_iso(), "amount": amount, "method": body.method, "payer": body.payer.strip() or load.get("pengambil", "") or load.get("party", ""), "note": body.note.strip(), "operator": user.get("name", "")}
    total = collected + amount
    status = "LUNAS" if total + 1e-9 >= chargeable else "SEBAGIAN"
    await db.outbound_loads.update_one({"id": load_id}, {"$push": {"loading_fee_payments": payment}, "$set": {"loading_fee_payment_total": total, "loading_fee_payment_status": status}})
    return await db.outbound_loads.find_one({"id": load_id}, {"_id": 0})


@router.post("/loading-costs/{date}/settle")
async def settle_loading_cost(date: str, body: DailyLoadingSettlementInput, user: dict = Depends(require_write)):
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Tanggal harus YYYY-MM-DD") from exc
    key = "labor" if body.recipient == "BURUH" else "daily"
    loads = await db.outbound_loads.find(
        {
            "status": "Selesai",
            "$or": [
                {"operational_date": date},
                {"operational_date": {"$in": ["", None]}, "completed_at": {"$regex": f"^{date}"}},
                {"operational_date": {"$in": ["", None]}, "created_at": {"$regex": f"^{date}"}},
            ],
        },
        {"_id": 0, "loading_cost": 1, "items": 1},
    ).to_list(5000)
    group = _crew_group(body.group) if body.group.strip() else ""
    amount = 0.0
    for load in loads:
        if group:
            for item in load.get("items", []):
                item_group = _crew_group(item.get("crewGroup") or item.get("stackCode") or item.get("location") or load.get("unit_loading"))
                if item_group == group:
                    amount += float((item.get("loadingFee") or {}).get(key, 0) or 0)
        else:
            amount += float((load.get("loading_cost") or {}).get(key, 0) or 0)
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Tidak ada biaya yang perlu dibayarkan untuk grup/tanggal ini")
    doc = {"date": date, "recipient": body.recipient, "group": group, "amount": amount, "settledAt": now_iso(), "settledBy": user.get("name", ""), "note": body.note.strip()}
    await db.loading_cost_settlements.update_one(
        {"date": date, "recipient": body.recipient, "group": group},
        {"$set": doc, "$push": {"history": dict(doc)}},
        upsert=True,
    )
    return doc


@router.put("/outbound-loads/{load_id}/edit")
async def edit_outbound_load(load_id: str, body: OutboundEditInput, user: dict = Depends(require_admin)):
    """Koreksi dokumen, kendaraan, sopir, dan kuantum sebelum pemuatan dimulai."""
    load = await db.outbound_loads.find_one({"id": load_id}, {"_id": 0})
    if not load:
        raise HTTPException(status_code=404, detail="Data pemuatan tidak ditemukan")
    if load.get("status") != "Menunggu":
        raise HTTPException(status_code=400, detail="Pengeluaran hanya dapat diedit saat masih menunggu pemuatan")

    documents = []
    for value in body.documents:
        value = str(value or "").strip()
        if value and value not in documents:
            documents.append(value)
    if len(documents) != len(body.documents):
        raise HTTPException(status_code=400, detail="Nomor dokumen wajib diisi dan tidak boleh duplikat")
    expected = {"SO": "SO/", "TM": "TM", "CT": "CT", "ND": "ND", "MEMO": "MEMO"}[load.get("document_type", "SO")]
    if any(not number.upper().startswith(expected) for number in documents):
        raise HTTPException(status_code=400, detail=f"Nomor dokumen tidak sesuai jenis {load.get('document_type', 'SO')}")

    original_items = list(load.get("items") or [])
    if len(body.items) != len(original_items) or [item.productId for item in body.items] != [item.get("productId") for item in original_items]:
        raise HTTPException(status_code=400, detail="Edit hanya dapat mengubah kuantum dan nomor dokumen pada baris komoditas yang sama")

    item_refs = [str(item.documentNo or "").strip() for item in body.items]
    if len(documents) > 1:
        if any(not item_ref for item_ref in item_refs):
            raise HTTPException(status_code=400, detail="Pilih nomor dokumen pada setiap komoditas")
        if any(item_ref not in documents for item_ref in item_refs):
            raise HTTPException(status_code=400, detail="Dokumen komoditas belum didaftarkan")
        missing = [number for number in documents if number not in item_refs]
        if missing:
            raise HTTPException(status_code=400, detail=f"Dokumen belum memiliki komoditas: {', '.join(missing)}")
    elif any(item_ref and item_ref not in documents for item_ref in item_refs):
        raise HTTPException(status_code=400, detail="Dokumen komoditas belum didaftarkan")

    if load.get("document_type") != "SO":
        for number in documents:
            duplicate = await db.outbound_loads.find_one({"id": {"$ne": load_id}, "$or": [{"ref": number}, {"documents": number}, {"document_links.no": number}]}, {"_id": 1})
            if duplicate:
                raise HTTPException(status_code=409, detail=f"Nomor dokumen {number} sudah digunakan")

    requested = defaultdict(float)
    channel_requested = defaultdict(float)
    for item in body.items:
        requested[item.productId] += float(item.qty)
    products = {}
    field = "damaged" if load.get("kondisi") == "RUSAK" else "stock"
    for product_id, qty in requested.items():
        product = await db.products.find_one({"id": product_id}, {"_id": 0})
        if not product:
            raise HTTPException(status_code=404, detail="Produk pengeluaran tidak ditemukan")
        _validate_pack_qty(product, qty)
        available = max(float(product.get(field, 0) or 0) - await _reserved_qty(product_id, load.get("kondisi", "BAIK"), exclude_id=load_id), 0)
        if qty > available + 1e-9:
            raise HTTPException(status_code=400, detail=f"Stok tersedia untuk {product.get('name', 'produk')} tidak mencukupi")
        products[product_id] = product

    for item in body.items:
        channel = normalize_channel(item.channel, normalize_channel(products[item.productId].get("channel")))
        channel_requested[(item.productId, channel)] += float(item.qty)
    for (product_id, channel), qty in channel_requested.items():
        product = products[product_id]
        await ensure_channel_stock(product)
        available = max(channel_balance(product, channel, field) - await _reserved_qty(product_id, load.get("kondisi", "BAIK"), exclude_id=load_id, channel=channel), 0)
        if qty > available + 1e-9:
            raise HTTPException(status_code=400, detail=f"Stok {channel} untuk {product.get('name', 'produk')} tidak mencukupi")

    edit_so_documents = []
    edit_so_progress = {}
    if load.get("document_type") == "SO":
        edit_so_documents, edit_so_progress = await _prepare_so_documents(
            refs=documents,
            body_items=body.items,
            products=products,
            party=load.get("party", ""),
            exclude_load_id=load_id,
        )

    revised_items = []
    edit_fefo_guides = {}
    for index, submitted in enumerate(body.items):
        previous = dict(original_items[index])
        product = products[submitted.productId]
        qty = float(submitted.qty)
        document_no = str(submitted.documentNo or "").strip() or documents[0]
        stack_code = str(submitted.stackCode or previous.get("stackCode") or "").strip().upper()
        if load.get("kondisi", "BAIK") == "BAIK" and not stack_code:
            raise HTTPException(status_code=400, detail=f"Pilih tumpukan asal untuk {product.get('name', '')} agar kontrol FEFO tetap tercatat")
        if stack_code:
            allocation = await db.stack_allocations.find_one({"productId": submitted.productId, "stackCode": stack_code}, {"_id": 0, "primaryQty": 1})
            physical = float((allocation or {}).get("primaryQty", 0) or 0)
            reserved, available = await available_stack_qty(submitted.productId, stack_code, physical, exclude_load_id=load_id)
            if not allocation or qty > available + 1e-9:
                raise HTTPException(status_code=400, detail=f"Stok {product.get('name', '')} pada {stack_code} tidak mencukupi. Fisik {physical:g}, reservasi antrean lain {reserved:g}, tersedia {available:g}")
        exception_reason = submitted.fefoExceptionReason.strip() or str(previous.get("fefoExceptionReason") or "").strip()
        guide = {}
        selection_status = previous.get("fefoSelectionStatus", "NOT_APPLICABLE")
        if load.get("kondisi", "BAIK") == "BAIK":
            if submitted.productId not in edit_fefo_guides:
                edit_fefo_guides[submitted.productId] = await get_fefo_pick_guide(submitted.productId)
            guide = edit_fefo_guides[submitted.productId]
            is_exception = selection_requires_reason(guide, stack_code)
            if is_exception and not exception_reason:
                raise HTTPException(status_code=400, detail=f"Tumpukan {stack_code} bukan prioritas FEFO. Isi alasan pengecualian sebelum menyimpan edit.")
            selection_status = "EXCEPTION" if is_exception else ("PRIORITY" if stack_code in guide.get("recommendedStacks", []) else "NO_GUIDE")
        channel = normalize_channel(submitted.channel, normalize_channel(product.get("channel")))
        revised_items.append({**previous, "documentNo": document_no, "qty": qty, "channel": channel, "berat": float(product.get("weight", 0) or 0) * qty, "loadingFee": _loading_fee(product, qty, charge_mode_override=(previous.get("loadingFee") or {}).get("mode", "")), "stackCode": stack_code, "crewGroup": _crew_group(stack_code or product.get("location", "")), "fefoPolicy": guide.get("policy", previous.get("fefoPolicy", "")) if guide else previous.get("fefoPolicy", ""), "fefoMode": guide.get("mode", previous.get("fefoMode", "")) if guide else previous.get("fefoMode", ""), "fefoRecommendedStacks": guide.get("recommendedStacks", previous.get("fefoRecommendedStacks", [])) if guide else previous.get("fefoRecommendedStacks", []), "fefoSelectionStatus": selection_status, "fefoExceptionReason": exception_reason if selection_status == "EXCEPTION" else "", "documentQty": float(submitted.documentQty or previous.get("documentQty", 0) or 0)})

    if load.get("kondisi", "BAIK") == "BAIK":
        edit_by_stack = defaultdict(float)
        for item in revised_items:
            edit_by_stack[(item["productId"], item["stackCode"])] += float(item.get("qty", 0) or 0)
        for (product_id, stack_code), qty in edit_by_stack.items():
            allocation = await db.stack_allocations.find_one({"productId": product_id, "stackCode": stack_code}, {"_id": 0, "primaryQty": 1})
            physical = float((allocation or {}).get("primaryQty", 0) or 0)
            reserved, available = await available_stack_qty(product_id, stack_code, physical, exclude_load_id=load_id)
            if qty > available + 1e-9:
                raise HTTPException(status_code=400, detail=f"Total edit pada {stack_code} melebihi stok tersedia setelah reservasi antrean lain ({available:g})")

    now = now_iso()
    old_snapshot = {"documents": load.get("documents", []), "polisi": load.get("polisi", ""), "pengambil": load.get("pengambil", ""), "items": original_items}
    loading_cost = {key: sum(float(item.get("loadingFee", {}).get(key, 0) or 0) for item in revised_items) for key in ("labor", "daily", "warehouse", "total", "chargeable")}
    changes = {
        "documents": documents, "ref": documents[0], "polisi": body.polisi.strip(), "pengambil": body.pengambil.strip(),
        "items": revised_items, "total_unit": sum(float(item.get("qty", 0) or 0) for item in revised_items),
        "total_berat": sum(float(item.get("berat", 0) or 0) for item in revised_items), "loading_cost": loading_cost,
        "so_document_progress": edit_so_progress if load.get("document_type") == "SO" else load.get("so_document_progress", {}),
        "edit_history": list(load.get("edit_history") or []) + [{"time": now, "by": user.get("name", ""), "before": old_snapshot}],
        "updated_at": now,
    }
    await db.outbound_loads.update_one({"id": load_id}, {"$set": changes})
    try:
        if load.get("document_type") == "SO":
            await _persist_so_documents(edit_so_documents, user.get("name", ""))
    except Exception:
        await db.outbound_loads.replace_one({"id": load_id}, dict(load), upsert=False)
        raise
    return await db.outbound_loads.find_one({"id": load_id}, {"_id": 0})


@router.post("/outbound-loads/{load_id}/cancel")
async def cancel_outbound_load(load_id: str, body: DocumentCancelInput, user: dict = Depends(require_write)):
    """Batalkan dokumen yang belum dimuat tanpa menghapus jejak antrian."""
    load = await db.outbound_loads.find_one({"id": load_id}, {"_id": 0})
    if not load:
        raise HTTPException(status_code=404, detail="Data pemuatan tidak ditemukan")
    if load.get("status") != "Menunggu":
        raise HTTPException(status_code=400, detail="Hanya dokumen yang masih menunggu pemuatan dapat dibatalkan. Dokumen selesai harus dikoreksi melalui Retur atau dokumen balik.")

    documents = list(load.get("documents") or [load.get("ref", "")])
    requested = body.documentNo.strip()
    targets = documents if not requested or requested.upper() == "SEMUA" else [requested]
    unknown = [number for number in targets if number not in documents]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Dokumen tidak ditemukan pada antrian ini: {', '.join(unknown)}")

    previous_ref = load.get("ref", "")
    cancelled_items = [item for item in load.get("items", []) if (item.get("documentNo") or previous_ref) in targets]
    retained_items = [item for item in load.get("items", []) if (item.get("documentNo") or previous_ref) not in targets]
    if not cancelled_items:
        raise HTTPException(status_code=400, detail="Tidak ada komoditas yang dapat dibatalkan untuk dokumen tersebut")

    remaining_documents = [number for number in documents if number not in targets]
    event = {
        "id": new_id(), "documents": targets, "items": cancelled_items,
        "reason": body.reason.strip(), "cancelledAt": now_iso(), "cancelledBy": user.get("name", ""),
    }
    history = list(load.get("cancellation_history") or []) + [event]
    changes = {
        "items": retained_items, "documents": remaining_documents,
        "ref": remaining_documents[0] if remaining_documents else previous_ref,
        "cancellation_history": history,
        "cancelled_documents": list(load.get("cancelled_documents") or []) + targets,
        "document_status": "Dibatalkan Sebagian" if retained_items else "Dibatalkan",
        "status": "Menunggu" if retained_items else "Dibatalkan",
        "updated_at": now_iso(),
    }
    await db.outbound_loads.update_one({"id": load_id}, {"$set": changes})
    return await db.outbound_loads.find_one({"id": load_id}, {"_id": 0})


@router.post("/outbound-loads/{load_id}/start")
async def start_outbound_load(load_id: str, user: dict = Depends(require_write)):
    load = await db.outbound_loads.find_one({"id": load_id}, {"_id": 0})
    if not load:
        raise HTTPException(status_code=404, detail="Data pemuatan tidak ditemukan")
    if load.get("status") == "Dibatalkan":
        raise HTTPException(status_code=400, detail="Pemuatan sudah dibatalkan")
    if load.get("status") == "Selesai":
        raise HTTPException(status_code=400, detail="Pemuatan sudah selesai")
    if load.get("status") == "Sedang Dimuat":
        return load

    now = now_iso()
    await db.outbound_loads.update_one(
        {"id": load_id, "status": "Menunggu"},
        {"$set": {"status": "Sedang Dimuat", "started_at": now, "started_by": user.get("name", "")}},
    )
    return await db.outbound_loads.find_one({"id": load_id}, {"_id": 0})


@router.post("/outbound-loads/{load_id}/complete")
async def complete_outbound_load(load_id: str, body: LoadingCompletionInput | None = None, user: dict = Depends(require_write)):
    load = await db.outbound_loads.find_one({"id": load_id}, {"_id": 0})
    if not load:
        raise HTTPException(status_code=404, detail="Data pemuatan tidak ditemukan")

    if load.get("status") == "Selesai":
        sj = None
        if load.get("surat_jalan_id"):
            sj = await db.surat_jalan.find_one({"id": load["surat_jalan_id"]}, {"_id": 0})
        return {"load": load, "suratJalan": sj}

    if load.get("status") != "Sedang Dimuat":
        raise HTTPException(status_code=400, detail="Pemuatan harus dimulai sebelum dapat diselesaikan")

    operation_id = new_id()
    completed_at = now_iso()
    completed_local = operational_now()
    fee_settings = await db.settings.find_one({"_id": "app"}, {"_id": 0, "holidays": 1}) or {}
    started_local = local_datetime(load.get("started_at"), completed_local.tzinfo) or completed_local
    # Hari libur mengikuti hari aktivitas dimulai, bukan waktu Bon dicetak
    # dan bukan semata-mata waktu completion.
    loading_holiday = holiday_from_settings(started_local, fee_settings.get("holidays") or [])
    split_inputs = {row.index: float(row.normalQtyBefore1600) for row in (body.items if body else [])}
    final_items = []
    for index, original in enumerate(load.get("items", [])):
        item = dict(original)
        qty = float(item.get("qty", 0) or 0)
        normal_before_cutoff = split_inputs.get(index)
        split = work_split(started_local, completed_local, qty, normal_before_cutoff)
        product_for_fee = await db.products.find_one({"id": item.get("productId")}, {"_id": 0}) or item
        item["loadingFee"] = _loading_fee(
            product_for_fee,
            qty,
            completed_local,
            charge_mode_override=(item.get("loadingFee") or {}).get("mode", ""),
            overtime_qty=split["overtimeQty"],
            holiday_override=loading_holiday,
        )
        item["loadingWork"] = {
            **split,
            "startedAt": load.get("started_at", ""),
            "completedAt": completed_at,
            "cutoff": "16:00",
        }
        item["crewGroup"] = item.get("crewGroup") or _crew_group(item.get("stackCode") or item.get("location") or load.get("unit_loading"))
        final_items.append(item)
    final_loading_cost = {key: sum(float(item.get("loadingFee", {}).get(key, 0) or 0) for item in final_items) for key in ("labor", "daily", "warehouse", "total", "chargeable")}
    total_regular = sum(float((item.get("loadingWork") or {}).get("regularQty", 0) or 0) for item in final_items)
    total_overtime = sum(float((item.get("loadingWork") or {}).get("overtimeQty", 0) or 0) for item in final_items)
    work_status = "NORMAL" if total_overtime <= 1e-9 else "LEMBUR_PENUH" if total_regular <= 1e-9 else "LEMBUR_PARSIAL"
    stock_changes = []
    stack_changes = []
    transactions = []
    kondisi = load.get("kondisi", "BAIK")
    field = "damaged" if kondisi == "RUSAK" else "stock"

    try:
        for item in load.get("items", []):
            qty = float(item.get("qty", 0) or 0)
            if qty <= 0:
                continue
            product = await db.products.find_one({"id": item.get("productId")}, {"_id": 0})
            if not product:
                raise HTTPException(status_code=404, detail=f"Produk {item.get('name', '')} tidak ditemukan")
            if item.get("stackCode") and kondisi == "BAIK":
                from_stack = await db.stack_allocations.find_one({"productId": product["id"], "stackCode": item["stackCode"]}, {"_id": 0, "primaryQty": 1})
                if not from_stack or float(from_stack.get("primaryQty", 0) or 0) + 1e-9 < qty:
                    raise HTTPException(status_code=400, detail=f"Stok {product.get('name', '')} pada {item['stackCode']} tidak mencukupi")

            channel = normalize_channel(item.get("channel"), normalize_channel(product.get("channel")))
            await ensure_channel_stock(product)
            result = await db.products.update_one(
                {"id": product["id"], field: {"$gte": qty}, f"channelStock.{channel}.{field}": {"$gte": qty}},
                {"$inc": {field: -qty, f"channelStock.{channel}.{field}": -qty}},
            )
            if result.matched_count == 0:
                raise HTTPException(
                    status_code=409,
                    detail=f"Stok {product.get('name', '')} berubah atau tidak mencukupi. Periksa stok lalu coba lagi.",
                )
            stock_changes.append({"productId": product["id"], "qty": qty, "field": field, "channel": channel})
            if item.get("stackCode") and kondisi == "BAIK":
                await decrease_stack_allocation(product["id"], item["stackCode"], qty, user.get("name", "Sistem (pengeluaran)"))
                stack_changes.append({"product": product, "stackCode": item["stackCode"], "qty": qty})

            transactions.append({
                "id": new_id(),
                "operation_id": operation_id,
                "load_id": load["id"],
                "time": completed_at,
                "ref": item.get("documentNo") or load.get("ref") or load.get("antrian", ""),
                "source_document": item.get("documentNo") or load.get("ref", ""),
                "stackCode": item.get("stackCode", ""),
                "bon_no": load.get("bon_no", ""),
                "antrian": load.get("antrian", ""),
                "type": "KELUAR",
                "kondisi": kondisi,
                "product": product.get("name", ""),
                "sku": product.get("sku", ""),
                "change": -qty,
                "unit": product.get("unit", ""),
                "weight": float(product.get("weight", 0) or 0),
                "total_weight": float(product.get("weight", 0) or 0) * qty,
                "secondary": product.get("secondary", ""),
                "secondaryQty": float(product.get("secondaryQty", 0) or 0),
                "channel": channel,
                "penerima": load.get("party", "-"),
                "pengambil": load.get("pengambil", ""),
                "polisi": load.get("polisi", ""),
                "operator": user.get("name", ""),
                "keterangan": load.get("keterangan", ""),
                "document_type": load.get("document_type", "SO"),
                "parent_document": "",
                "request_document": load.get("request_document", ""),
                "consignment_destination": load.get("consignment_destination", ""),
                "consignment_zone": load.get("consignment_zone", ""),
                "fefo_policy": item.get("fefoPolicy", ""),
                "fefo_mode": item.get("fefoMode", ""),
                "fefo_selection_status": item.get("fefoSelectionStatus", ""),
                "fefo_exception_reason": item.get("fefoExceptionReason", ""),
            })

        op_now = operational_now()
        month_key = op_now.strftime("%Y%m")
        month_prefix = f"SJ/09100-09200/{month_key}/"
        sj_floor = await max_suffix(db.surat_jalan, "no", month_prefix)
        sj_number = await next_sequence(f"surat-jalan:{month_key}", sj_floor)
        sj_id = new_id()
        sj_no = f"{month_prefix}{sj_number:04d}"
        sj = {
            "id": sj_id,
            "operation_id": operation_id,
            "load_id": load["id"],
            "no": sj_no,
            "format_version": "SJ_A4_HALF_V3",
            "bon_no": load.get("bon_no", ""),
            "antrian": load.get("antrian", ""),
            "operational_date": load.get("operational_date", op_now.strftime("%Y-%m-%d")),
            "time": completed_at,
            "penerima": load.get("party", "-"),
            "pengambil": load.get("pengambil", ""),
            "polisi": load.get("polisi", ""),
            "unit_loading": load.get("unit_loading", ""),
            "operator": user.get("name", ""),
            "status": "Selesai",
            "ref": load.get("ref", ""),
            "document_type": load.get("document_type", "SO"),
            "transfer_scope": load.get("transfer_scope", ""),
            "request_document": load.get("request_document", ""),
            "consignment_destination": load.get("consignment_destination", ""),
            "consignment_zone": load.get("consignment_zone", ""),
            "documents": load.get("documents", [load.get("ref", "")]),
            "items": [
                {
                    "productId": item.get("productId", ""),
                    "name": item.get("name", ""),
                    "sku": item.get("sku", ""),
                    "channel": item.get("channel", ""),
                    "qty": float(item.get("qty", 0) or 0),
                    "unit": item.get("unit", ""),
                    "berat": float(item.get("berat", 0) or 0),
                    "stackCode": item.get("stackCode", ""),
                    "location": item.get("stackCode") or item.get("location", ""),
                    "documentNo": item.get("documentNo", load.get("ref", "")),
                    "secondary": item.get("secondary", ""),
                    "secondaryQty": float(item.get("secondaryQty", 0) or 0),
                    "measureUnit": item.get("measureUnit", "kg") or "kg",
                    "sec": (
                        f"{int(float(item.get('qty', 0) or 0) // float(item.get('secondaryQty', 0) or 1))} "
                        f"{item.get('secondary', '')} + "
                        f"{int(float(item.get('qty', 0) or 0) % float(item.get('secondaryQty', 0) or 1))} "
                        f"{item.get('unit', '')}"
                        if float(item.get("secondaryQty", 0) or 0) > 0
                        else ""
                    ),
                }
                for item in load.get("items", [])
            ],
            "berat": float(load.get("total_berat", 0) or 0),
            "unit": float(load.get("total_unit", 0) or 0),
            "issued_at": completed_at,
        }

        if transactions:
            await db.transactions.insert_many([dict(txn) for txn in transactions])
        await db.surat_jalan.insert_one(dict(sj))
        load_result = await db.outbound_loads.update_one(
            {"id": load_id, "status": "Sedang Dimuat"},
            {"$set": {
                "status": "Selesai",
                "completed_at": completed_at,
                "completed_by": user.get("name", ""),
                "items": final_items,
                "loading_cost": {
                    **final_loading_cost,
                    "group": _crew_group(load.get("unit_loading", "")),
                    "overtime": total_overtime > 1e-9,
                    "holiday": loading_holiday,
                    "regularQty": total_regular,
                    "overtimeQty": total_overtime,
                    "workStatus": work_status,
                    "startedAt": load.get("started_at", ""),
                    "completedAt": completed_at,
                    "cutoff": "16:00",
                },
                "surat_jalan_id": sj_id,
                "surat_jalan_no": sj_no,
                "document_status": "Menunggu CR/SO" if load.get("document_type") == "CT" else "Menunggu SO/Retur" if load.get("document_type") in {"MEMO", "ND"} else "Selesai",
            }},
        )
        if load_result.matched_count == 0:
            raise HTTPException(status_code=409, detail="Status pemuatan berubah. Muat ulang lalu periksa transaksi.")

    except Exception:
        await db.transactions.delete_many({"operation_id": operation_id})
        await db.surat_jalan.delete_many({"operation_id": operation_id})
        for change in reversed(stack_changes):
            try:
                await allocate_stock_to_stack(change["product"], change["stackCode"], change["qty"], "Sistem (rollback pengeluaran)")
            except Exception:
                pass
        for change in reversed(stock_changes):
            await db.products.update_one(
                {"id": change["productId"]},
                {"$inc": {change["field"]: change["qty"], f"channelStock.{change['channel']}.{change['field']}": change["qty"]}},
            )
        raise

    for product_id in {item.get("productId") for item in load.get("items", []) if item.get("productId")}:
        await reconcile_product_allocations(product_id)

    updated = await db.outbound_loads.find_one({"id": load_id}, {"_id": 0})
    return {"load": updated, "suratJalan": sj}


def _item_source_document(load: dict, item: dict) -> str:
    return str(item.get("documentNo") or load.get("ref") or "").strip()


def _source_product_totals(load: dict, source_document_no: str) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for item in load.get("items", []):
        if _item_source_document(load, item) != source_document_no:
            continue
        product_id = item.get("productId", "")
        if not product_id:
            continue
        row = rows.setdefault(product_id, {**item, "qty": 0.0, "documentNo": source_document_no})
        row["qty"] += float(item.get("qty", 0) or 0)
    return rows


def _resolve_source_document(load: dict, requested: str = "") -> str:
    documents = [str(value or "").strip() for value in (load.get("documents") or [load.get("ref", "")]) if str(value or "").strip()]
    source = str(requested or "").strip()
    if not source:
        if len(documents) > 1:
            raise HTTPException(status_code=400, detail="Pilih satu dokumen sumber ND/Memo/CT terlebih dahulu")
        source = documents[0] if documents else str(load.get("ref") or "").strip()
    if source not in documents:
        raise HTTPException(status_code=400, detail="Dokumen sumber tidak terdapat pada pengeluaran ini")
    return source


def _linked_totals(load: dict, product_id: str, source_document_no: str = "") -> tuple[float, float]:
    target = str(source_document_no or load.get("ref") or "").strip()
    returned = sold = 0.0
    for link in load.get("document_links", []):
        link_source = str(link.get("sourceDocumentNo") or load.get("ref") or "").strip()
        if target and link_source != target:
            continue
        for item in link.get("items", []):
            if item.get("productId") != product_id:
                continue
            if link.get("type") in {"CR", "RETUR"}:
                returned += float(item.get("goodQty", 0) or 0) + float(item.get("damagedQty", 0) or 0)
            elif link.get("type") == "SO":
                sold += float(item.get("qty", 0) or 0)
    return returned, sold


def _all_source_documents_settled(load: dict) -> bool:
    documents = []
    for item in load.get("items", []):
        source = _item_source_document(load, item)
        if source and source not in documents:
            documents.append(source)
    for source_document in documents:
        for product_id, source in _source_product_totals(load, source_document).items():
            returned, sold = _linked_totals(load, product_id, source_document)
            if returned + sold + 1e-9 < float(source.get("qty", 0) or 0):
                return False
    return True


@router.post("/outbound-loads/{load_id}/return")
async def create_consignment_return(load_id: str, body: ConsignmentReturnInput, user: dict = Depends(require_write)):
    load = await db.outbound_loads.find_one({"id": load_id}, {"_id": 0})
    if not load or load.get("document_type") not in {"CT", "MEMO", "ND"} or load.get("status") != "Selesai":
        raise HTTPException(status_code=400, detail="Pengembalian hanya dapat dibuat dari CT, Memo, atau ND yang sudah selesai dimuat")
    expected_return = "CR" if load.get("document_type") == "CT" else "RETUR"
    if body.returnType != expected_return:
        raise HTTPException(status_code=400, detail=f"Dokumen {load.get('document_type')} harus menggunakan {expected_return}")
    document_no = body.documentNo.strip()
    valid_prefix = ("CR",) if body.returnType == "CR" else ("RT", "RET", "RM")
    if not document_no.upper().startswith(valid_prefix):
        raise HTTPException(status_code=400, detail=f"Nomor pengembalian harus berupa dokumen {body.returnType}")
    if await db.outbound_loads.find_one({"$or": [{"ref": document_no}, {"document_links.no": document_no}]}):
        raise HTTPException(status_code=409, detail="Nomor dokumen pengembalian sudah digunakan")
    if len({item.productId for item in body.items}) != len(body.items):
        raise HTTPException(status_code=400, detail="Produk retur tidak boleh dicatat lebih dari satu baris")
    source_document = _resolve_source_document(load, body.sourceDocumentNo)
    original = _source_product_totals(load, source_document)
    if not original:
        raise HTTPException(status_code=400, detail="Dokumen sumber tidak memiliki komoditas yang dapat diselesaikan")
    link_items, stock_changes, stack_changes = [], [], []
    link_applied = False
    try:
        for item in body.items:
            source = original.get(item.productId)
            if not source:
                raise HTTPException(status_code=400, detail="Produk retur tidak terdapat pada dokumen sumber yang dipilih")
            placements = [placement for placement in item.placements if float(placement.goodQty) > 0] or ([ReturnPlacementInput(goodQty=item.goodQty, stackCode=item.stackCode)] if item.goodQty else [])
            good_qty = sum(float(placement.goodQty) for placement in placements)
            qty = good_qty + float(item.damagedQty)
            if qty <= 0:
                continue
            returned, sold = _linked_totals(load, item.productId, source_document)
            if qty > float(source.get("qty", 0) or 0) - returned - sold + 1e-9:
                raise HTTPException(status_code=400, detail=f"Jumlah retur {source.get('name', '')} melebihi sisa dokumen sumber")
            product = await db.products.find_one({"id": item.productId}, {"_id": 0})
            if not product:
                raise HTTPException(status_code=404, detail="Produk pengembalian tidak ditemukan")
            channel = normalize_channel(source.get("channel"), normalize_channel(product.get("channel")))
            await ensure_channel_stock(product)
            if good_qty:
                for placement in placements:
                    if placement.stackCode.strip().upper() not in await valid_stack_codes():
                        raise HTTPException(status_code=400, detail=f"Pilih lokasi tumpukan untuk barang Good {source.get('name', '')}")
                await db.products.update_one({"id": item.productId}, {"$inc": {"stock": good_qty, f"channelStock.{channel}.stock": good_qty}})
                stock_changes.append((item.productId, "stock", good_qty, channel))
                for placement in placements:
                    await allocate_stock_to_stack(product, placement.stackCode, float(placement.goodQty), user.get("name", ""))
                    stack_changes.append((item.productId, placement.stackCode.strip().upper(), float(placement.goodQty)))
            if item.damagedQty:
                await db.products.update_one({"id": item.productId}, {"$inc": {"damaged": float(item.damagedQty), f"channelStock.{channel}.damaged": float(item.damagedQty)}})
                stock_changes.append((item.productId, "damaged", float(item.damagedQty), channel))
            link_items.append({"productId": item.productId, "name": source.get("name", ""), "unit": source.get("unit", ""), "channel": channel, "goodQty": good_qty, "damagedQty": float(item.damagedQty), "stackCode": placements[0].stackCode.strip().upper() if len(placements) == 1 else "", "placements": [{"goodQty": float(placement.goodQty), "stackCode": placement.stackCode.strip().upper()} for placement in placements]})
        if not link_items:
            raise HTTPException(status_code=400, detail="Isi jumlah barang yang dikembalikan")
        link = {"id": new_id(), "type": body.returnType, "no": document_no, "sourceDocumentNo": source_document, "time": now_iso(), "items": link_items, "note": body.note.strip(), "operator": user.get("name", "")}
        prospective = {**load, "document_links": [*load.get("document_links", []), link]}
        status = "Selesai Dokumen" if _all_source_documents_settled(prospective) else f"{body.returnType} Tercatat · Menunggu SO"
        await db.outbound_loads.update_one({"id": load_id}, {"$push": {"document_links": link}, "$set": {"document_status": status}})
        link_applied = True
        await db.transactions.insert_many([{"id": new_id(), "load_id": load_id, "time": link["time"], "ref": document_no, "type": "MASUK", "kondisi": "PENGEMBALIAN", "document_type": body.returnType, "parent_document": source_document, "product": x["name"], "change": x["goodQty"] + x["damagedQty"], "good_change": x["goodQty"], "damaged_change": x["damagedQty"], "unit": x["unit"], "channel": x["channel"], "penerima": load.get("party", ""), "operator": user.get("name", ""), "keterangan": body.note.strip()} for x in link_items])
        return link
    except Exception:
        await db.transactions.delete_many({"load_id": load_id, "ref": document_no, "document_type": body.returnType})
        if link_applied:
            await db.outbound_loads.update_one({"id": load_id}, {"$pull": {"document_links": {"id": link["id"]}}, "$set": {"document_status": load.get("document_status", "Selesai")}})
        for product_id, stack_code, qty in reversed(stack_changes):
            try:
                await decrease_stack_allocation(product_id, stack_code, qty, "Sistem (rollback retur)")
            except Exception:
                pass
        for product_id, field, qty, channel in reversed(stock_changes):
            await db.products.update_one({"id": product_id}, {"$inc": {field: -qty, f"channelStock.{channel}.{field}": -qty}})
        raise


def _sales_returned_qty(load: dict, product_id: str, source_document_no: str) -> float:
    total = 0.0
    for link in load.get("document_links", []):
        if link.get("type") != "SO_RETUR" or link.get("sourceDocumentNo") != source_document_no:
            continue
        for item in link.get("items", []):
            if item.get("productId") == product_id:
                total += float(item.get("goodQty", 0) or 0) + float(item.get("damagedQty", 0) or 0)
    return total


@router.post("/outbound-loads/{load_id}/sales-return")
async def create_sales_return(load_id: str, body: SalesReturnInput, user: dict = Depends(require_write)):
    """Retur terhadap SO yang sudah selesai; SO asal tidak diubah atau dihapus."""
    load = await db.outbound_loads.find_one({"id": load_id}, {"_id": 0})
    if not load or load.get("document_type") != "SO" or load.get("status") != "Selesai":
        raise HTTPException(status_code=400, detail="Retur SO hanya dapat dibuat dari SO yang sudah selesai dimuat")

    source_no = body.sourceDocumentNo.strip()
    documents = list(load.get("documents") or [load.get("ref", "")])
    if source_no not in documents:
        raise HTTPException(status_code=400, detail="Nomor SO asal tidak terdapat pada pengeluaran ini")
    return_no = body.documentNo.strip()
    if not return_no.upper().startswith(("RT", "RET", "RM")):
        raise HTTPException(status_code=400, detail="Nomor retur harus diawali RT, RET, atau RM")
    if await db.outbound_loads.find_one({"$or": [{"ref": return_no}, {"document_links.no": return_no}]}):
        raise HTTPException(status_code=409, detail="Nomor retur sudah digunakan")
    if len({item.productId for item in body.items}) != len(body.items):
        raise HTTPException(status_code=400, detail="Produk retur tidak boleh dicatat lebih dari satu baris")

    original = {}
    for item in load.get("items", []):
        if (item.get("documentNo") or load.get("ref", "")) != source_no:
            continue
        product_id = item.get("productId")
        original[product_id] = {**item, "qty": float(original.get(product_id, {}).get("qty", 0) or 0) + float(item.get("qty", 0) or 0)}

    link_items, reversals, stack_changes = [], [], []
    link_applied = False
    try:
        for item in body.items:
            source = original.get(item.productId)
            if not source:
                raise HTTPException(status_code=400, detail="Produk retur tidak terdapat pada SO yang dipilih")
            good_qty = float(item.goodQty or 0)
            damaged_qty = float(item.damagedQty or 0)
            qty = good_qty + damaged_qty
            if qty <= 0:
                continue
            if qty > float(source.get("qty", 0) or 0) - _sales_returned_qty(load, item.productId, source_no) + 1e-9:
                raise HTTPException(status_code=400, detail=f"Jumlah retur {source.get('name', '')} melebihi kuantum SO yang belum diretur")
            product = await db.products.find_one({"id": item.productId}, {"_id": 0})
            if not product:
                raise HTTPException(status_code=404, detail="Produk retur tidak ditemukan")
            channel = normalize_channel(source.get("channel"), normalize_channel(product.get("channel")))
            await ensure_channel_stock(product)
            if good_qty:
                stack_code = item.stackCode.strip().upper()
                if stack_code not in await valid_stack_codes():
                    raise HTTPException(status_code=400, detail=f"Pilih satu tumpukan tujuan untuk barang baik {source.get('name', '')}")
                await db.products.update_one({"id": item.productId}, {"$inc": {"stock": good_qty, f"channelStock.{channel}.stock": good_qty}})
                reversals.append((item.productId, "stock", good_qty, channel))
                await allocate_stock_to_stack(product, stack_code, good_qty, user.get("name", ""))
                stack_changes.append((item.productId, stack_code, good_qty))
            if damaged_qty:
                await db.products.update_one({"id": item.productId}, {"$inc": {"damaged": damaged_qty, f"channelStock.{channel}.damaged": damaged_qty}})
                reversals.append((item.productId, "damaged", damaged_qty, channel))
            link_items.append({"productId": item.productId, "name": source.get("name", ""), "unit": source.get("unit", ""), "channel": channel, "goodQty": good_qty, "damagedQty": damaged_qty, "stackCode": item.stackCode.strip().upper() if good_qty else ""})
        if not link_items:
            raise HTTPException(status_code=400, detail="Isi jumlah barang yang diretur")

        link = {"id": new_id(), "type": "SO_RETUR", "no": return_no, "sourceDocumentNo": source_no, "time": now_iso(), "items": link_items, "note": body.note.strip(), "operator": user.get("name", "")}
        await db.outbound_loads.update_one({"id": load_id}, {"$push": {"document_links": link}, "$set": {"document_status": "Retur SO Tercatat"}})
        link_applied = True
        await db.transactions.insert_many([{"id": new_id(), "load_id": load_id, "time": link["time"], "ref": return_no, "type": "MASUK", "kondisi": "RETUR_SO", "document_type": "SO_RETUR", "parent_document": source_no, "product": item["name"], "change": item["goodQty"] + item["damagedQty"], "good_change": item["goodQty"], "damaged_change": item["damagedQty"], "unit": item["unit"], "channel": item["channel"], "penerima": load.get("party", ""), "operator": user.get("name", ""), "keterangan": body.note.strip()} for item in link_items])
        return link
    except Exception:
        await db.transactions.delete_many({"load_id": load_id, "ref": return_no, "document_type": "SO_RETUR"})
        if link_applied:
            await db.outbound_loads.update_one({"id": load_id}, {"$pull": {"document_links": {"id": link["id"]}}, "$set": {"document_status": load.get("document_status", "Selesai")}})
        for product_id, stack_code, qty in reversed(stack_changes):
            try:
                await decrease_stack_allocation(product_id, stack_code, qty, "Sistem (rollback retur SO)")
            except Exception:
                pass
        for product_id, field, qty, channel in reversed(reversals):
            await db.products.update_one({"id": product_id}, {"$inc": {field: -qty, f"channelStock.{channel}.{field}": -qty}})
        raise


@router.post("/outbound-loads/{load_id}/settle")
async def settle_outbound_document(load_id: str, body: SettlementInput, user: dict = Depends(require_write)):
    load = await db.outbound_loads.find_one({"id": load_id}, {"_id": 0})
    if not load or load.get("document_type") not in {"CT", "MEMO", "ND"} or load.get("status") != "Selesai":
        raise HTTPException(status_code=400, detail="SO lanjutan hanya dapat dibuat dari CT, Memo, atau ND yang selesai")
    document_no = body.documentNo.strip()
    if not document_no.upper().startswith("SO/"):
        raise HTTPException(status_code=400, detail="Nomor penyelesaian harus berupa dokumen SO")
    if await db.outbound_loads.find_one({"$or": [{"ref": document_no}, {"document_links.no": document_no}]}):
        raise HTTPException(status_code=409, detail="Nomor SO sudah digunakan")
    if len({item.productId for item in body.items}) != len(body.items):
        raise HTTPException(status_code=400, detail="Produk SO tidak boleh dicatat lebih dari satu baris")
    source_document = _resolve_source_document(load, body.sourceDocumentNo)
    original = _source_product_totals(load, source_document)
    if not original:
        raise HTTPException(status_code=400, detail="Dokumen sumber tidak memiliki komoditas yang dapat diselesaikan")
    items = []
    for item in body.items:
        source = original.get(item.productId)
        if not source:
            raise HTTPException(status_code=400, detail="Produk SO tidak terdapat pada dokumen sumber yang dipilih")
        returned, sold = _linked_totals(load, item.productId, source_document)
        if float(item.qty) > float(source.get("qty", 0) or 0) - returned - sold + 1e-9:
            raise HTTPException(status_code=400, detail=f"Jumlah SO {source.get('name', '')} melebihi sisa dokumen sumber")
        items.append({"productId": item.productId, "name": source.get("name", ""), "unit": source.get("unit", ""), "channel": source.get("channel", ""), "qty": float(item.qty)})
    link = {"id": new_id(), "type": "SO", "no": document_no, "sourceDocumentNo": source_document, "time": now_iso(), "items": items, "note": body.note.strip(), "operator": user.get("name", "")}
    prospective = {**load, "document_links": [*load.get("document_links", []), link]}
    try:
        await db.outbound_loads.update_one({"id": load_id}, {"$push": {"document_links": link}, "$set": {"document_status": "Selesai Dokumen" if _all_source_documents_settled(prospective) else "SO Sebagian · Belum Selesai"}})
        await db.transactions.insert_many([{"id": new_id(), "load_id": load_id, "time": link["time"], "ref": document_no, "type": "DOKUMEN", "kondisi": "—", "document_type": "SO", "parent_document": source_document, "product": item["name"], "change": 0, "settled_qty": item["qty"], "unit": item["unit"], "channel": item.get("channel", ""), "penerima": load.get("party", ""), "operator": user.get("name", ""), "keterangan": body.note.strip()} for item in items])
        return link
    except Exception:
        await db.transactions.delete_many({"load_id": load_id, "ref": document_no, "document_type": "SO"})
        await db.outbound_loads.update_one({"id": load_id}, {"$pull": {"document_links": {"id": link["id"]}}, "$set": {"document_status": load.get("document_status", "Selesai")}})
        raise
