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
    ensure_channel_stock,
    normalize_channel,
    channel_balance,
)
from backend.stack_allocations import valid_stack_codes, allocate_stock_to_stack, decrease_stack_allocation, reconcile_product_allocations

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
    stackCode: str = ""
    channel: str = ""


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


class LoadingFeePaymentInput(BaseModel):
    amount: float = Field(gt=0)
    method: Literal["TUNAI", "TRANSFER", "PIUTANG"] = "TUNAI"
    payer: str = ""
    note: str = ""


class DailyLoadingSettlementInput(BaseModel):
    recipient: Literal["BURUH", "HARIAN"]
    note: str = ""


def _crew_group(unit_loading: str) -> str:
    text = str(unit_loading or "").upper()
    if "RTR" in text: return "GRUP 3 - RTR"
    if "MP1" in text or any(f"UNIT {x}" in text for x in ("21", "22", "23", "24")): return "GRUP 2 - MP1/21-24"
    return "GRUP 1 - GBB 17-20"


def _loading_fee(product: dict, qty: float, when=None, apply_overtime=None, apply_holiday=None) -> dict:
    current = when or operational_now()
    if isinstance(current, str):
        current = datetime.fromisoformat(current.replace("Z", "+00:00")).astimezone(operational_now().tzinfo)
    is_holiday = current.weekday() >= 5
    is_overtime = current.hour >= 16
    if apply_overtime is not None: is_overtime = bool(apply_overtime)
    if apply_holiday is not None: is_holiday = bool(apply_holiday)
    components = {"labor": 0.0, "daily": 0.0, "warehouse": 0.0}
    keys = {"labor": "Labor", "daily": "Daily", "warehouse": "Warehouse"}
    for target, suffix in keys.items():
        value = float(product.get(f"loadingFee{suffix}", 0) or 0)
        if is_overtime: value += float(product.get(f"loadingOvertime{suffix}", 0) or 0)
        if is_holiday: value += float(product.get(f"loadingHoliday{suffix}", 0) or 0)
        if is_holiday and is_overtime: value += float(product.get(f"loadingHolidayOvertime{suffix}", 0) or 0)
        components[target] = value * qty
    mode = str(product.get("loadingFeeChargeMode") or "TIDAK_ADA").strip().upper()
    total = sum(components.values())
    return {"mode": mode, **components, "total": total, "chargeable": total if mode == "PENGAMBIL" else 0.0, "overtime": is_overtime, "holiday": is_holiday}

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
    items: List[ReturnItemInput] = Field(min_length=1)
    note: str = ""
    returnType: Literal["CR", "RETUR"] = "CR"


class SettlementItemInput(BaseModel):
    productId: str
    qty: float = Field(gt=0)


class SettlementInput(BaseModel):
    documentNo: str
    items: List[SettlementItemInput] = Field(min_length=1)
    note: str = ""


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


@router.get("/outbound-loads")
async def list_outbound_loads(user: dict = Depends(get_current_user)):
    return await db.outbound_loads.find({}, {"_id": 0}).sort("created_at", -1).to_list(2000)


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

    load_items = []
    for item in body.items:
        product = products[item.productId]
        item_ref = item.documentNo.strip() or refs[0]
        if item_ref not in refs:
            raise HTTPException(status_code=400, detail=f"Dokumen komoditas {item_ref} belum didaftarkan")
        qty = float(item.qty)
        weight = float(product.get("weight", 0) or 0)
        stack_code = item.stackCode.strip().upper()
        channel = normalize_channel(item.channel, normalize_channel(product.get("channel")))
        if stack_code and stack_code not in await valid_stack_codes():
            raise HTTPException(status_code=400, detail="Tumpukan asal tidak valid")
        load_items.append({"productId": item.productId, "documentNo": item_ref, "sku": product.get("sku", ""), "name": product.get("name", ""), "channel": channel, "qty": qty, "unit": product.get("unit", ""), "weight": weight, "measureUnit": product.get("measureUnit", "kg") or "kg", "berat": weight * qty, "secondary": product.get("secondary", ""), "secondaryQty": float(product.get("secondaryQty", 0) or 0), "location": product.get("location", ""), "stackCode": stack_code, "loadingFee": _loading_fee(product, qty)})

    ordered_products = [products[product_id] for product_id in item_order]
    unit_loading, queue_prefix = _loading_unit_from_products(ordered_products)

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
        "kondisi": body.kondisi,
        "keterangan": body.keterangan.strip(),
        "document_type": body.documentType,
        "transfer_scope": body.transferScope if body.documentType == "TM" else "",
        "request_document": body.requestDocument.strip(),
        "dispatch_purpose": body.dispatchPurpose if body.documentType in {"MEMO", "ND"} else "",
        "consignment_destination": body.consignmentDestination.strip(),
        "consignment_zone": body.consignmentZone.strip(),
        "weighing_form": body.weighingForm,
        "gross_weight": float(body.grossWeight) if body.weighingForm else 0,
        "gross_min": float(body.grossMin) if body.weighingForm else 0,
        "gross_max": float(body.grossMax) if body.weighingForm else 0,
        "weighing_entries": _weighing_entries(float(body.grossWeight), float(body.grossMin), float(body.grossMax)) if body.weighingForm else [],
        "document_links": [],
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
    return doc


@router.get("/loading-costs")
async def get_loading_costs(date: str = "", user: dict = Depends(get_current_user)):
    target_date = date.strip() or operational_now().strftime("%Y-%m-%d")
    try:
        datetime.strptime(target_date, "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Tanggal harus YYYY-MM-DD") from exc
    loads = await db.outbound_loads.find({"status": "Selesai", "operational_date": target_date}, {"_id": 0}).sort("completed_at", 1).to_list(5000)
    rows, totals = [], {"labor": 0.0, "daily": 0.0, "warehouse": 0.0, "total": 0.0, "chargeable": 0.0, "collected": 0.0}
    for load in loads:
        cost = dict(load.get("loading_cost") or {})
        if not cost:
            cost = {key: sum(float(item.get("loadingFee", {}).get(key, 0) or 0) for item in load.get("items", [])) for key in ("labor", "daily", "warehouse", "total", "chargeable")}
        for key in ("labor", "daily", "warehouse", "total", "chargeable"):
            cost[key] = float(cost.get(key, 0) or 0)
            totals[key] += cost[key]
        collected = float(load.get("loading_fee_payment_total", 0) or 0)
        totals["collected"] += collected
        rows.append({"id": load["id"], "antrian": load.get("antrian", ""), "ref": load.get("ref", ""), "documents": load.get("documents", []), "party": load.get("party", ""), "pengambil": load.get("pengambil", ""), "items": load.get("items", []), "cost": cost, "collected": collected, "paymentStatus": load.get("loading_fee_payment_status", "TIDAK_DITAGIH"), "payments": load.get("loading_fee_payments", [])})
    settlements = await db.loading_cost_settlements.find({"date": target_date}, {"_id": 0}).to_list(20)
    settled = {row.get("recipient"): row for row in settlements}
    return {"date": target_date, "loads": rows, "totals": {**totals, "outstanding": max(totals["chargeable"] - totals["collected"], 0)}, "settlements": settled}


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
    loads = await db.outbound_loads.find({"status": "Selesai", "operational_date": date}, {"_id": 0, "loading_cost": 1, "items": 1}).to_list(5000)
    amount = 0.0
    for load in loads:
        cost = load.get("loading_cost") or {}
        amount += float(cost.get(key, 0) or 0)
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Tidak ada biaya yang perlu dibayarkan untuk tanggal ini")
    doc = {"date": date, "recipient": body.recipient, "amount": amount, "settledAt": now_iso(), "settledBy": user.get("name", ""), "note": body.note.strip()}
    await db.loading_cost_settlements.update_one({"date": date, "recipient": body.recipient}, {"$set": doc}, upsert=True)
    return doc


@router.post("/outbound-loads/{load_id}/start")
async def start_outbound_load(load_id: str, user: dict = Depends(require_write)):
    load = await db.outbound_loads.find_one({"id": load_id}, {"_id": 0})
    if not load:
        raise HTTPException(status_code=404, detail="Data pemuatan tidak ditemukan")
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
async def complete_outbound_load(load_id: str, user: dict = Depends(require_write)):
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
    final_items = []
    for original in load.get("items", []):
        item = dict(original)
        product_for_fee = await db.products.find_one({"id": item.get("productId")}, {"_id": 0}) or item
        item["loadingFee"] = _loading_fee(product_for_fee, float(item.get("qty", 0) or 0), completed_local)
        final_items.append(item)
    final_loading_cost = {key: sum(float(item.get("loadingFee", {}).get(key, 0) or 0) for item in final_items) for key in ("labor", "daily", "warehouse", "total", "chargeable")}
    stock_changes = []
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
            if item.get("stackCode"):
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
            stock_changes.append((product["id"], qty))
            if item.get("stackCode"):
                await decrease_stack_allocation(product["id"], item["stackCode"], qty, user.get("name", "Sistem (pengeluaran)"))

            transactions.append({
                "id": new_id(),
                "operation_id": operation_id,
                "load_id": load["id"],
                "time": completed_at,
                "ref": load.get("ref") or load.get("antrian", ""),
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
            })

        op_now = operational_now()
        month_prefix = op_now.strftime("SJ-%Y%m")
        sj_floor = await max_suffix(db.surat_jalan, "no", f"{month_prefix}-")
        sj_number = await next_sequence(f"surat-jalan:{op_now.strftime('%Y%m')}", sj_floor)
        sj_id = new_id()
        sj_no = f"{month_prefix}-{sj_number:03d}"
        sj = {
            "id": sj_id,
            "operation_id": operation_id,
            "load_id": load["id"],
            "no": sj_no,
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
                    "name": item.get("name", ""),
                    "sku": item.get("sku", ""),
                    "channel": item.get("channel", ""),
                    "qty": float(item.get("qty", 0) or 0),
                    "unit": item.get("unit", ""),
                    "berat": float(item.get("berat", 0) or 0),
                    "location": item.get("location", ""),
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
        await db.outbound_loads.update_one(
            {"id": load_id},
            {"$set": {
                "status": "Selesai",
                "completed_at": completed_at,
                "completed_by": user.get("name", ""),
                "items": final_items,
                "loading_cost": {**final_loading_cost, "group": _crew_group(load.get("unit_loading", "")), "overtime": completed_local.hour >= 16, "holiday": completed_local.weekday() >= 5},
                "surat_jalan_id": sj_id,
                "surat_jalan_no": sj_no,
                "document_status": "Menunggu CR/SO" if load.get("document_type") == "CT" else "Menunggu SO/Retur" if load.get("document_type") in {"MEMO", "ND"} else "Selesai",
            }},
        )

    except Exception:
        await db.transactions.delete_many({"operation_id": operation_id})
        await db.surat_jalan.delete_many({"operation_id": operation_id})
        for product_id, qty in reversed(stock_changes):
            await db.products.update_one({"id": product_id}, {"$inc": {field: qty}})
        raise

    for product_id in {item.get("productId") for item in load.get("items", []) if item.get("productId")}:
        await reconcile_product_allocations(product_id)

    updated = await db.outbound_loads.find_one({"id": load_id}, {"_id": 0})
    return {"load": updated, "suratJalan": sj}


def _linked_totals(load: dict, product_id: str) -> tuple[float, float]:
    returned = sold = 0.0
    for link in load.get("document_links", []):
        for item in link.get("items", []):
            if item.get("productId") != product_id:
                continue
            if link.get("type") in {"CR", "RETUR"}:
                returned += float(item.get("goodQty", 0) or 0) + float(item.get("damagedQty", 0) or 0)
            elif link.get("type") == "SO":
                sold += float(item.get("qty", 0) or 0)
    return returned, sold


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
        raise HTTPException(status_code=409, detail="Nomor CR sudah digunakan")
    if len({item.productId for item in body.items}) != len(body.items):
        raise HTTPException(status_code=400, detail="Produk retur tidak boleh dicatat lebih dari satu baris")

    original = {item.get("productId"): item for item in load.get("items", [])}
    link_items, stock_changes = [], []
    try:
        for item in body.items:
            source = original.get(item.productId)
            if not source:
                raise HTTPException(status_code=400, detail="Produk retur tidak terdapat pada dokumen induk")
            placements = [placement for placement in item.placements if float(placement.goodQty) > 0] or ([ReturnPlacementInput(goodQty=item.goodQty, stackCode=item.stackCode)] if item.goodQty else [])
            good_qty = sum(float(placement.goodQty) for placement in placements)
            qty = good_qty + float(item.damagedQty)
            if qty <= 0:
                continue
            returned, sold = _linked_totals(load, item.productId)
            if qty > float(source.get("qty", 0) or 0) - returned - sold + 1e-9:
                raise HTTPException(status_code=400, detail=f"Jumlah retur {source.get('name', '')} melebihi sisa dokumen")
            product = await db.products.find_one({"id": item.productId}, {"_id": 0})
            if not product:
                raise HTTPException(status_code=404, detail="Produk pengembalian tidak ditemukan")
            if good_qty:
                for placement in placements:
                    if placement.stackCode.strip().upper() not in await valid_stack_codes():
                        raise HTTPException(status_code=400, detail=f"Pilih lokasi tumpukan untuk barang Good {source.get('name', '')}")
                return_channel = normalize_channel(source.get("channel"), normalize_channel(product.get("channel")))
                await ensure_channel_stock(product)
                await db.products.update_one({"id": item.productId}, {"$inc": {"stock": good_qty, f"channelStock.{return_channel}.stock": good_qty}})
                stock_changes.append((item.productId, "stock", good_qty))
                for placement in placements:
                    await allocate_stock_to_stack(product, placement.stackCode, float(placement.goodQty), user.get("name", ""))
            if item.damagedQty:
                return_channel = normalize_channel(source.get("channel"), normalize_channel(product.get("channel")))
                await ensure_channel_stock(product)
                await db.products.update_one({"id": item.productId}, {"$inc": {"damaged": float(item.damagedQty), f"channelStock.{return_channel}.damaged": float(item.damagedQty)}})
                stock_changes.append((item.productId, "damaged", float(item.damagedQty)))
            link_items.append({"productId": item.productId, "name": source.get("name", ""), "unit": source.get("unit", ""), "channel": source.get("channel", ""), "goodQty": good_qty, "damagedQty": float(item.damagedQty), "stackCode": placements[0].stackCode.strip().upper() if len(placements) == 1 else "", "placements": [{"goodQty": float(placement.goodQty), "stackCode": placement.stackCode.strip().upper()} for placement in placements]})
        if not link_items:
            raise HTTPException(status_code=400, detail="Isi jumlah barang yang dikembalikan")
        link = {"id": new_id(), "type": body.returnType, "no": document_no, "time": now_iso(), "items": link_items, "note": body.note.strip(), "operator": user.get("name", "")}
        prospective = {**load, "document_links": [*load.get("document_links", []), link]}
        complete = all(sum(_linked_totals(prospective, product_id)) >= float(source.get("qty", 0) or 0) - 1e-9 for product_id, source in original.items())
        status = "Selesai Dokumen" if complete else f"{body.returnType} Tercatat · Menunggu SO"
        await db.outbound_loads.update_one({"id": load_id}, {"$push": {"document_links": link}, "$set": {"document_status": status}})
        txns = [{"id": new_id(), "load_id": load_id, "time": link["time"], "ref": document_no, "type": "MASUK", "kondisi": "PENGEMBALIAN", "document_type": body.returnType, "parent_document": load.get("ref", ""), "product": x["name"], "change": x["goodQty"] + x["damagedQty"], "good_change": x["goodQty"], "damaged_change": x["damagedQty"], "unit": x["unit"], "channel": x.get("channel", ""), "penerima": load.get("party", ""), "operator": user.get("name", ""), "keterangan": body.note.strip()} for x in link_items]
        await db.transactions.insert_many(txns)
        return link
    except Exception:
        for product_id, field, qty in reversed(stock_changes):
            await db.products.update_one({"id": product_id}, {"$inc": {field: -qty}})
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
    original = {item.get("productId"): item for item in load.get("items", [])}
    items = []
    for item in body.items:
        source = original.get(item.productId)
        if not source:
            raise HTTPException(status_code=400, detail="Produk SO tidak terdapat pada dokumen induk")
        returned, sold = _linked_totals(load, item.productId)
        if float(item.qty) > float(source.get("qty", 0) or 0) - returned - sold + 1e-9:
            raise HTTPException(status_code=400, detail=f"Jumlah SO {source.get('name', '')} melebihi sisa dokumen")
        items.append({"productId": item.productId, "name": source.get("name", ""), "unit": source.get("unit", ""), "channel": source.get("channel", ""), "qty": float(item.qty)})
    link = {"id": new_id(), "type": "SO", "no": document_no, "time": now_iso(), "items": items, "note": body.note.strip(), "operator": user.get("name", "")}
    prospective = {**load, "document_links": [*load.get("document_links", []), link]}
    complete = all(sum(_linked_totals(prospective, pid)) >= float(source.get("qty", 0) or 0) - 1e-9 for pid, source in original.items())
    await db.outbound_loads.update_one({"id": load_id}, {"$push": {"document_links": link}, "$set": {"document_status": "Selesai Dokumen" if complete else "SO Sebagian · Belum Selesai"}})
    await db.transactions.insert_many([{"id": new_id(), "load_id": load_id, "time": link["time"], "ref": document_no, "type": "DOKUMEN", "kondisi": "—", "document_type": "SO", "parent_document": load.get("ref", ""), "product": item["name"], "change": 0, "settled_qty": item["qty"], "unit": item["unit"], "channel": item.get("channel", ""), "penerima": load.get("party", ""), "operator": user.get("name", ""), "keterangan": body.note.strip()} for item in items])
    return link
