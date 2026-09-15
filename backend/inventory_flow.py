import csv
import io
from openpyxl import load_workbook
import random
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import List, Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.server import (
    build_xlsx,
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
)
from backend.stack_allocations import decrease_stack_allocation

router = APIRouter(prefix="/api")


class POItemInput(BaseModel):
    productId: str
    qty: float = Field(gt=0)


class PurchaseOrderInput(BaseModel):
    supplier: str
    no: str = ""
    items: List[POItemInput] = Field(min_length=1)
    date: str = ""


class PurchaseOrderCancelInput(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class ReceiptItemInput(BaseModel):
    productId: str
    qty: float = Field(gt=0)
    exp: str = ""
    stackCode: str = ""
    channel: str = ""


class ReceiptInput(BaseModel):
    poId: str = ""
    items: List[ReceiptItemInput] = Field(min_length=1)
    party: str = ""
    ref: str = ""
    polisi: str = ""
    kondisi: Literal["BAIK", "RUSAK"] = "BAIK"
    keterangan: str = ""
    weighingForm: bool = False
    grossWeight: float = Field(default=0, ge=0)
    grossMin: float = Field(default=0, ge=0)
    grossMax: float = Field(default=0, ge=0)
    # PENGIRIM ditagihkan pada pengirim; TERMAKSUK berarti sudah masuk harga/dokumen.
    unloadingFeeChargeMode: Literal["", "PENGIRIM", "TERMASUK"] = ""


class DamageDiscoveryInput(BaseModel):
    productId: str
    stackCode: str
    qty: float = Field(gt=0)
    channel: str = ""
    cause: str = Field(min_length=3, max_length=200)
    note: str = ""
    referenceNo: str = ""


def _number(value, default=0.0) -> float:
    if value is None or value == "":
        return default
    text = str(value).strip().replace(" ", "")
    if not text:
        return default
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return default


def _crew_group_from_location(location: str) -> str:
    text = str(location or "").upper()
    if "RTR" in text:
        return "GRUP 3 - RTR"
    if "MP1" in text or any(re.search(rf"(?:UNIT\\s*)?{unit}(?:/|\\b)", text) for unit in ("21", "22", "23", "24")):
        return "GRUP 2 - MP1/21-24"
    return "GRUP 1 - GBB 17-20"


def _unloading_fee(product: dict, qty: float, at, charge_mode_override: str = "") -> dict:
    holiday = at.weekday() >= 5
    overtime = at.hour >= 16
    parts = {}
    for target, suffix in (("labor", "Labor"), ("daily", "Daily"), ("warehouse", "Warehouse")):
        value = float(product.get(f"unloadingFee{suffix}", 0) or 0)
        if overtime:
            value += float(product.get(f"unloadingOvertime{suffix}", 0) or 0)
        if holiday:
            value += float(product.get(f"unloadingHoliday{suffix}", 0) or 0)
        if holiday and overtime:
            value += float(product.get(f"unloadingHolidayOvertime{suffix}", 0) or 0)
        parts[target] = value * qty
    total = sum(parts.values())
    mode = str(charge_mode_override or product.get("unloadingFeeChargeMode") or "TIDAK_ADA").upper()
    return {**parts, "total": total, "mode": mode, "chargeable": total if mode == "PENGIRIM" else 0.0, "overtime": overtime, "holiday": holiday}


def _validate_exp(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Format tanggal kedaluwarsa harus YYYY-MM-DD") from exc
    return value


def _validate_pack_qty(product: dict, qty: float) -> None:
    if float(product.get("secondaryQty", 0) or 0) > 0 and abs(qty - round(qty)) > 1e-6:
        raise HTTPException(
            status_code=400,
            detail=f"Jumlah {product.get('name', 'produk')} harus berupa kemasan primer/pack utuh",
        )


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


def _po_status(items: list[dict]) -> str:
    ordered = sum(float(item.get("qty", 0) or 0) for item in items)
    received = sum(float(item.get("receivedQty", item.get("received_qty", 0)) or 0) for item in items)
    cancelled = sum(float(item.get("cancelledQty", 0) or 0) for item in items)
    if cancelled > 1e-9:
        return "Dibatalkan" if received <= 1e-9 else "Diterima Sebagian · Sisa Dibatalkan"
    if ordered <= 0 or received <= 0:
        return "Belum Diterima"
    if received + 1e-9 < ordered:
        return "Sebagian"
    return "Selesai"


def _normalize_po(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    normalized_items = []
    for item in doc.get("items", []):
        normalized = dict(item)
        normalized["receivedQty"] = float(
            normalized.get("receivedQty", normalized.get("received_qty", 0)) or 0
        )
        normalized.setdefault("unit", "")
        normalized.setdefault("sku", "")
        normalized.setdefault("productId", "")
        normalized_items.append(normalized)
    doc["items"] = normalized_items
    doc["status"] = _po_status(normalized_items)
    return doc


async def _hydrate_legacy_po(doc: dict) -> dict:
    """Lengkapi PO lama yang belum menyimpan productId/satuan agar tetap bisa dipakai."""
    normalized = _normalize_po(doc)
    changed = False
    for item in normalized.get("items", []):
        if item.get("productId"):
            continue
        query = {"sku": item.get("sku")} if item.get("sku") else {"name": item.get("name", "")}
        product = await db.products.find_one(query, {"_id": 0}) if query else None
        if not product:
            continue
        item["productId"] = product.get("id", "")
        item["sku"] = product.get("sku", "")
        item["unit"] = product.get("unit", "")
        item["cost"] = float(item.get("cost", product.get("cost", 0)) or 0)
        changed = True
    normalized["status"] = _po_status(normalized["items"])
    if changed and normalized.get("id"):
        await db.purchase_orders.update_one(
            {"id": normalized["id"]},
            {"$set": {"items": normalized["items"], "status": normalized["status"]}},
        )
    return normalized


@router.get("/purchase-orders-v2")
async def list_purchase_orders(user: dict = Depends(get_current_user)):
    docs = await db.purchase_orders.find({}, {"_id": 0}).sort("date", -1).to_list(1000)
    return [await _hydrate_legacy_po(doc) for doc in docs]


@router.post("/purchase-orders-v2")
async def create_purchase_order(body: PurchaseOrderInput, user: dict = Depends(require_write)):
    supplier = body.supplier.strip()
    if not supplier:
        raise HTTPException(status_code=400, detail="Supplier wajib dipilih")

    if not await db.suppliers.find_one({"name": supplier}):
        raise HTTPException(status_code=404, detail="Supplier tidak ditemukan")

    seen = set()
    items = []
    for item in body.items:
        if item.productId in seen:
            raise HTTPException(status_code=400, detail="Produk yang sama tidak boleh muncul dua kali dalam satu PO")
        seen.add(item.productId)

        product = await db.products.find_one({"id": item.productId}, {"_id": 0})
        if not product:
            raise HTTPException(status_code=404, detail="Produk pada PO tidak ditemukan")
        _validate_pack_qty(product, float(item.qty))

        items.append({
            "productId": product["id"],
            "sku": product.get("sku", ""),
            "name": product.get("name", ""),
            "qty": float(item.qty),
            "receivedQty": 0.0,
            "unit": product.get("unit", ""),
            "weight": float(product.get("weight", 0) or 0),
            "secondary": product.get("secondary", ""),
            "secondaryQty": float(product.get("secondaryQty", 0) or 0),
            "cost": float(product.get("cost", 0) or 0),
            "channel": normalize_channel(product.get("channel")),
        })

    manual_no = body.no.strip()
    if len(manual_no) > 100:
        raise HTTPException(status_code=400, detail="Nomor PO maksimal 100 karakter")
    if manual_no and await db.purchase_orders.find_one({"no": manual_no}, {"_id": 1}):
        raise HTTPException(status_code=409, detail="Nomor PO sudah digunakan")
    if manual_no:
        po_no = manual_no
    else:
        year = operational_now().strftime("%Y")
        prefix = f"PO-{year}-"
        floor = await max_suffix(db.purchase_orders, "no", prefix)
        number = await next_sequence(f"purchase-order:{year}", floor)
        po_no = f"{prefix}{number:03d}"

    doc = {
        "id": new_id(),
        "no": po_no,
        "supplier": supplier,
        "date": body.date or now_iso(),
        "status": "Belum Diterima",
        "items": items,
        "total": sum(item["qty"] * item["cost"] for item in items),
        "created_by": user.get("name", ""),
        "created_at": now_iso(),
    }
    await db.purchase_orders.insert_one(dict(doc))
    return doc


@router.post("/purchase-orders-v2/{po_id}/cancel")
async def cancel_purchase_order(po_id: str, body: PurchaseOrderCancelInput, user: dict = Depends(require_write)):
    """Batalkan sisa PO yang belum diterima, tanpa mengubah penerimaan yang sudah tercatat."""
    raw_po = await db.purchase_orders.find_one({"id": po_id}, {"_id": 0})
    if not raw_po:
        raise HTTPException(status_code=404, detail="Purchase Order tidak ditemukan")
    po = await _hydrate_legacy_po(raw_po)
    if po.get("status") == "Selesai":
        raise HTTPException(status_code=400, detail="PO sudah selesai diterima dan tidak dapat dibatalkan")
    if "Dibatalkan" in str(po.get("status", "")):
        raise HTTPException(status_code=400, detail="Sisa PO sudah dibatalkan")

    items = []
    cancelled_total = 0.0
    for item in po.get("items", []):
        row = dict(item)
        remaining = max(float(row.get("qty", 0) or 0) - float(row.get("receivedQty", 0) or 0), 0)
        row["cancelledQty"] = remaining
        cancelled_total += remaining
        items.append(row)
    if cancelled_total <= 1e-9:
        raise HTTPException(status_code=400, detail="Tidak ada sisa PO yang dapat dibatalkan")

    event = {"id": new_id(), "reason": body.reason.strip(), "cancelledAt": now_iso(), "cancelledBy": user.get("name", ""), "qty": cancelled_total}
    updated = {**po, "items": items, "status": _po_status(items), "cancellation_history": list(po.get("cancellation_history") or []) + [event], "updated_at": now_iso()}
    await db.purchase_orders.update_one({"id": po_id}, {"$set": {key: value for key, value in updated.items() if key != "id"}})
    return updated


@router.post("/receipts")
async def receive_stock(body: ReceiptInput, user: dict = Depends(require_write)):
    if body.weighingForm and (body.grossWeight <= 0 or body.grossMin <= 0 or body.grossMax <= 0):
        raise HTTPException(status_code=400, detail="Rata-rata bruto serta rentang timbang harus diisi")
    if body.weighingForm and not body.grossMin <= body.grossWeight <= body.grossMax:
        raise HTTPException(status_code=400, detail="Rata-rata bruto harus berada di dalam rentang timbang")
    po = None
    if body.poId:
        raw_po = await db.purchase_orders.find_one({"id": body.poId}, {"_id": 0})
        if not raw_po:
            raise HTTPException(status_code=404, detail="Purchase Order tidak ditemukan")
        po = await _hydrate_legacy_po(raw_po)
        if po["status"] == "Selesai" or "Dibatalkan" in str(po.get("status", "")):
            raise HTTPException(status_code=400, detail="PO sudah selesai atau sisa penerimaannya telah dibatalkan")

    products = []
    requested_by_product = defaultdict(float)
    for item in body.items:
        product = await db.products.find_one({"id": item.productId}, {"_id": 0})
        if not product:
            raise HTTPException(status_code=404, detail="Produk penerimaan tidak ditemukan")
        _validate_pack_qty(product, float(item.qty))
        products.append({**product, "_channel": normalize_channel(item.channel, normalize_channel(product.get("channel")))})
        requested_by_product[item.productId] += float(item.qty)
        _validate_exp(item.exp)

    party = (po.get("supplier") if po else body.party).strip() if (po or body.party) else ""
    if not party:
        raise HTTPException(status_code=400, detail="Supplier pengirim wajib dipilih")

    if po:
        po_item_map = {item.get("productId", ""): item for item in po.get("items", []) if item.get("productId")}
        for product_id, qty in requested_by_product.items():
            po_item = po_item_map.get(product_id)
            if not po_item:
                raise HTTPException(status_code=400, detail="Produk penerimaan tidak tercantum pada PO")
            ordered = float(po_item.get("qty", 0) or 0)
            received = float(po_item.get("receivedQty", 0) or 0)
            remaining = max(ordered - received, 0)
            if qty > remaining + 1e-9:
                raise HTTPException(
                    status_code=400,
                    detail=f"Jumlah diterima untuk {po_item.get('name', 'produk')} melebihi sisa PO ({remaining:g} {po_item.get('unit', '')})",
                )

    op_now = operational_now()
    operation_id = new_id()
    transaction_ref = po.get("no") if po else (body.ref.strip() or f"IN-{op_now.strftime('%Y%m%d%H%M%S%f')}")
    time = now_iso()
    stock_changes = []
    txns = []

    try:
        for item, product in zip(body.items, products):
            field = "damaged" if body.kondisi == "RUSAK" else "stock"
            channel = product.get("_channel", normalize_channel(product.get("channel")))
            await ensure_channel_stock(product)
            exp = _validate_exp(item.exp)
            previous_exp = product.get("exp", "") or ""
            update_doc = {"$inc": {field: float(item.qty), f"channelStock.{channel}.{field}": float(item.qty)}}

            # Di master produk hanya disimpan expired terdekat sebagai ringkasan.
            # Expired aktual tiap penerimaan tetap tersimpan pada transaksi.
            if body.kondisi == "BAIK" and exp and (not previous_exp or exp < previous_exp):
                update_doc["$set"] = {"exp": exp}

            result = await db.products.update_one({"id": product["id"]}, update_doc)
            if result.matched_count == 0:
                raise HTTPException(status_code=409, detail=f"Produk {product.get('name', '')} berubah. Muat ulang lalu coba lagi.")

            stock_changes.append({
                "productId": product["id"],
                "field": field,
                "qty": float(item.qty),
                "previousExp": previous_exp,
                "expChanged": bool(update_doc.get("$set")),
                "channel": channel,
            })

            stack_code = item.stackCode.strip().upper()
            if body.kondisi == "BAIK" and stack_code:
                from backend.stack_allocations import allocate_stock_to_stack
                await allocate_stock_to_stack(product, stack_code, float(item.qty), user.get("name", ""))

            txns.append({
                "id": new_id(),
                "operation_id": operation_id,
                "time": time,
                "ref": transaction_ref,
                "po_id": po.get("id", "") if po else "",
                "po_no": po.get("no", "") if po else "",
                "antrian": "",
                "type": "MASUK",
                "kondisi": body.kondisi,
                "product": product.get("name", ""),
                "sku": product.get("sku", ""),
                "change": float(item.qty),
                "unit": product.get("unit", ""),
                "weight": float(product.get("weight", 0) or 0),
                "total_weight": float(product.get("weight", 0) or 0) * float(item.qty),
                "secondary": product.get("secondary", ""),
                "secondaryQty": float(product.get("secondaryQty", 0) or 0),
                "channel": channel,
                "exp": exp,
                "penerima": party,
                "polisi": body.polisi,
                "operator": user.get("name", ""),
                "keterangan": body.keterangan,
                "weighing_form": body.weighingForm,
                "gross_weight": float(body.grossWeight) if body.weighingForm else 0,
                "gross_min": float(body.grossMin) if body.weighingForm else 0,
                "gross_max": float(body.grossMax) if body.weighingForm else 0,
                "weighing_entries": _weighing_entries(float(body.grossWeight), float(body.grossMin), float(body.grossMax)) if body.weighingForm else [],
                "unloading_group": _crew_group_from_location(item.stackCode or product.get("location", "")),
                "unloading_cost": _unloading_fee(product, float(item.qty), op_now, body.unloadingFeeChargeMode),
            })

        if txns:
            await db.transactions.insert_many([dict(txn) for txn in txns])

        updated_po = None
        if po:
            updated_items = []
            for item in po["items"]:
                updated = dict(item)
                product_id = updated.get("productId", "")
                if product_id in requested_by_product:
                    updated["receivedQty"] = float(updated.get("receivedQty", 0) or 0) + requested_by_product[product_id]
                updated_items.append(updated)

            new_status = _po_status(updated_items)
            result = await db.purchase_orders.update_one(
                {"id": po["id"]},
                {"$set": {
                    "items": updated_items,
                    "status": new_status,
                    "last_received_at": time,
                    "last_received_by": user.get("name", ""),
                }},
            )
            if result.matched_count == 0:
                raise HTTPException(status_code=409, detail="PO berubah. Muat ulang lalu coba kembali.")
            updated_po = {**po, "items": updated_items, "status": new_status}

    except Exception:
        await db.transactions.delete_many({"operation_id": operation_id})
        for change in reversed(stock_changes):
            rollback = {"$inc": {change["field"]: -change["qty"], f"channelStock.{change['channel']}.{change['field']}": -change["qty"]}}
            if change["expChanged"]:
                rollback["$set"] = {"exp": change["previousExp"]}
            await db.products.update_one({"id": change["productId"]}, rollback)
        raise

    return {
        "transactions": txns,
        "operationId": operation_id,
        "purchaseOrder": updated_po,
        "message": "Penerimaan stok berhasil disimpan",
    }


@router.post("/stock-damage-discoveries")
async def record_stock_damage_discovery(body: DamageDiscoveryInput, user: dict = Depends(require_write)):
    """Pindahkan stok baik yang ditemukan rusak ke saldo rusak tanpa menghapus jejak asal."""
    product = await db.products.find_one({"id": body.productId}, {"_id": 0})
    if not product:
        raise HTTPException(status_code=404, detail="Produk tidak ditemukan")
    _validate_pack_qty(product, float(body.qty))
    stack_code = body.stackCode.strip().upper()
    allocation = await db.stack_allocations.find_one({"productId": body.productId, "stackCode": stack_code}, {"_id": 0, "primaryQty": 1})
    if not allocation or float(allocation.get("primaryQty", 0) or 0) + 1e-9 < float(body.qty):
        raise HTTPException(status_code=400, detail=f"Stok baik pada tumpukan {stack_code} tidak mencukupi")
    channel = normalize_channel(body.channel, normalize_channel(product.get("channel")))
    await ensure_channel_stock(product)
    if float(product.get("stock", 0) or 0) + 1e-9 < float(body.qty) or float(product.get("channelStock", {}).get(channel, {}).get("stock", 0) or 0) + 1e-9 < float(body.qty):
        raise HTTPException(status_code=400, detail="Saldo stok baik tidak mencukupi untuk dipindahkan menjadi stok rusak")

    operation_id, time = new_id(), now_iso()
    await db.products.update_one({"id": product["id"]}, {"$inc": {"stock": -float(body.qty), "damaged": float(body.qty), f"channelStock.{channel}.stock": -float(body.qty), f"channelStock.{channel}.damaged": float(body.qty)}})
    try:
        await decrease_stack_allocation(product["id"], stack_code, float(body.qty), user.get("name", ""))
        transaction = {"id": new_id(), "operation_id": operation_id, "time": time, "ref": body.referenceNo.strip() or f"TR-{time[:10].replace('-', '')}", "type": "PENYESUAIAN", "document_type": "TEMUAN_RUSAK", "kondisi": "RUSAK", "product": product.get("name", ""), "sku": product.get("sku", ""), "change": 0, "good_change": -float(body.qty), "damaged_change": float(body.qty), "unit": product.get("unit", ""), "weight": float(product.get("weight", 0) or 0), "total_weight": float(product.get("weight", 0) or 0) * float(body.qty), "secondary": product.get("secondary", ""), "secondaryQty": float(product.get("secondaryQty", 0) or 0), "channel": channel, "stackCode": stack_code, "operator": user.get("name", ""), "cause": body.cause.strip(), "keterangan": body.note.strip()}
        await db.transactions.insert_one(dict(transaction))
    except Exception:
        await db.products.update_one({"id": product["id"]}, {"$inc": {"stock": float(body.qty), "damaged": -float(body.qty), f"channelStock.{channel}.stock": float(body.qty), f"channelStock.{channel}.damaged": -float(body.qty)}})
        raise
    return {"operationId": operation_id, "transaction": transaction}


@router.post("/import/master-csv")
async def import_master_csv(file: UploadFile = File(...), user: dict = Depends(require_write)):
    raw = await file.read()
    if (file.filename or "").lower().endswith(".xlsx"):
        try:
            workbook = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
            sheet = workbook.active
            values = list(sheet.iter_rows(values_only=True))
            if not values:
                raise HTTPException(status_code=400, detail="File XLSX kosong")
            headers = [str(value or "").strip().lower() for value in values[0]]
            reader = [dict(zip(headers, ["" if value is None else str(value) for value in row])) for row in values[1:]]
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail="File XLSX tidak dapat dibaca") from exc
    else:
        raise HTTPException(status_code=400, detail="Gunakan file XLSX (.xlsx) dari template aplikasi")
    inserted = 0
    updated = 0
    supplier_names = set()

    for row in reader:
        sku = (row.get("sku") or "").strip().strip("[]")
        name = (row.get("nama") or "").strip()
        if not sku or not name:
            continue

        master = {
            "name": name,
            "sku": sku,
            "category": (row.get("kategori") or "").strip(),
            "cost": _number(row.get("harga_beli"), 0),
            "location": (row.get("lokasi") or "").strip(),
            "supplier": (row.get("supplier") or "").strip(),
            "min": _number(row.get("stok_minimum"), 0),
            "unit": (row.get("satuan") or "Pcs").strip() or "Pcs",
            "weight": _number(row.get("berat_unit"), 0),
            "measureUnit": (row.get("satuan_kuantum") or "kg").strip().lower() or "kg",
            "secondary": (row.get("kemasan_sekunder") or "").strip(),
            "secondaryQty": _number(row.get("isi_kemasan_sekunder"), 0),
            "channel": normalize_channel(row.get("saluran") or row.get("channel")),
        }
        if master["measureUnit"] not in {"kg", "liter", "pcs"}:
            raise HTTPException(status_code=400, detail=f"Satuan kuantum SKU {sku} harus kg, liter, atau pcs")
        fee_columns = {"biaya_muat_buruh":"loadingFeeLabor","biaya_muat_uh":"loadingFeeDaily","biaya_muat_gudang":"loadingFeeWarehouse","lembur_muat_buruh":"loadingOvertimeLabor","lembur_muat_uh":"loadingOvertimeDaily","lembur_muat_gudang":"loadingOvertimeWarehouse","libur_muat_buruh":"loadingHolidayLabor","libur_muat_uh":"loadingHolidayDaily","libur_muat_gudang":"loadingHolidayWarehouse","libur_sore_muat_buruh":"loadingHolidayOvertimeLabor","libur_sore_muat_uh":"loadingHolidayOvertimeDaily","libur_sore_muat_gudang":"loadingHolidayOvertimeWarehouse","biaya_bongkar_buruh":"unloadingFeeLabor","biaya_bongkar_uh":"unloadingFeeDaily","biaya_bongkar_gudang":"unloadingFeeWarehouse","lembur_bongkar_buruh":"unloadingOvertimeLabor","lembur_bongkar_uh":"unloadingOvertimeDaily","lembur_bongkar_gudang":"unloadingOvertimeWarehouse","libur_bongkar_buruh":"unloadingHolidayLabor","libur_bongkar_uh":"unloadingHolidayDaily","libur_bongkar_gudang":"unloadingHolidayWarehouse","libur_sore_bongkar_buruh":"unloadingHolidayOvertimeLabor","libur_sore_bongkar_uh":"unloadingHolidayOvertimeDaily","libur_sore_bongkar_gudang":"unloadingHolidayOvertimeWarehouse"}
        for column, key in fee_columns.items(): master[key] = _number(row.get(column), 0)
        master["loadingFeeChargeMode"] = (row.get("tagihan_muat") or "TIDAK_ADA").strip().upper()
        master["unloadingFeeChargeMode"] = (row.get("tagihan_bongkar") or "TIDAK_ADA").strip().upper()
        if master["secondary"] and master["secondaryQty"] <= 0:
            raise HTTPException(
                status_code=400,
                detail=f"Isi kemasan sekunder untuk SKU {sku} harus lebih dari 0",
            )
        if master["secondaryQty"] > 0 and not master["secondary"]:
            raise HTTPException(status_code=400, detail=f"Kemasan sekunder untuk SKU {sku} wajib diisi")
        if master["secondaryQty"] > 0 and abs(master["secondaryQty"] - round(master["secondaryQty"])) > 1e-6:
            raise HTTPException(status_code=400, detail=f"Isi kemasan sekunder untuk SKU {sku} harus berupa pack utuh")
        if master["supplier"]:
            supplier_names.add(master["supplier"])

        existing = await db.products.find_one({"sku": sku}, {"_id": 0, "id": 1})
        if existing:
            # Import master tidak pernah mengubah stock, damaged, atau expired.
            await db.products.update_one({"sku": sku}, {"$set": master})
            updated += 1
        else:
            doc = {
                **master,
                "id": new_id(),
                "stock": 0,
                "damaged": 0,
                "exp": "",
            }
            await db.products.insert_one(doc)
            inserted += 1

    if inserted == 0 and updated == 0:
        raise HTTPException(status_code=400, detail="File tidak berisi master SKU yang valid")

    existing_suppliers = {
        doc["name"]
        for doc in await db.suppliers.find({}, {"_id": 0, "name": 1}).to_list(1000)
    }
    for name in sorted(supplier_names - existing_suppliers):
        await db.suppliers.insert_one({
            "id": new_id(), "name": name, "pic": "", "phone": "",
            "email": "", "address": "", "category": "",
        })

    return {"inserted": inserted, "updated": updated}


@router.get("/export/master-template.xlsx")
async def export_master_template(user: dict = Depends(get_current_user)):
    headers = ["sku","nama","kategori","saluran","satuan","satuan_kuantum","berat_unit","kemasan_sekunder","isi_kemasan_sekunder","harga_beli","supplier","lokasi","stok_minimum","tagihan_muat","biaya_muat_buruh","biaya_muat_uh","biaya_muat_gudang","lembur_muat_buruh","lembur_muat_uh","lembur_muat_gudang","libur_muat_buruh","libur_muat_uh","libur_muat_gudang","libur_sore_muat_buruh","libur_sore_muat_uh","libur_sore_muat_gudang","tagihan_bongkar","biaya_bongkar_buruh","biaya_bongkar_uh","biaya_bongkar_gudang","lembur_bongkar_buruh","lembur_bongkar_uh","lembur_bongkar_gudang","libur_bongkar_buruh","libur_bongkar_uh","libur_bongkar_gudang","libur_sore_bongkar_buruh","libur_sore_bongkar_uh","libur_sore_bongkar_gudang"]
    rows = [
        ["B0010001X","CONTOH BERAS MEDIUM 5 KG","Beras","PSO","Pack","kg",5,"Karung",8,0,"Nama Supplier","GBB 17",0,"PENGAMBIL",410,10,60,50,5,0,75,10,0,25,5,0,"TIDAK_ADA",0,0,0,0,0,0,0,0,0,0,0,0],
        ["B0100152X","CONTOH MINYAK 2 L","Minyak","KOM","Botol","liter",2,"Dus",6,0,"Nama Supplier","GBB 18",0,"PENGAMBIL",480,10,60,50,5,0,75,10,0,25,5,0,"TIDAK_ADA",0,0,0,0,0,0,0,0,0,0,0,0],
    ]
    output = build_xlsx(headers, rows, "Master Produk")
    return StreamingResponse(output, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": 'attachment; filename="template_import_master_produk.xlsx"'})


@router.get("/export/transactions-v2.xlsx")
async def export_transactions_with_expiry(user: dict = Depends(get_current_user)):
    now = operational_now()
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)

    transactions = await db.transactions.find(
        {
            "time": {
                "$gte": start.astimezone(timezone.utc).isoformat(),
                "$lt": end.astimezone(timezone.utc).isoformat(),
            }
        },
        {"_id": 0},
    ).sort("time", 1).to_list(10000)

    headers = [
        "Waktu", "No. Referensi", "No. PO", "Antrian", "Tipe", "Kondisi",
        "Produk", "SKU", "Jumlah", "Satuan", "Tanggal Kedaluwarsa",
        "Berat Total (kg)", "Kemasan Sekunder", "Isi/Kemasan Sekunder",
        "Pihak Terkait", "No. Polisi", "Jenis Dokumen", "Dokumen Induk",
        "Jumlah Diselesaikan SO", "Good Kembali", "Damage Kembali", "Dicatat Oleh", "Keterangan",
    ]
    rows = [
        [
            t.get("time", ""), t.get("ref", ""), t.get("po_no", ""), t.get("antrian", ""),
            t.get("type", ""), t.get("kondisi", ""), t.get("product", ""), t.get("sku", ""),
            t.get("change", 0), t.get("unit", ""), t.get("exp", ""),
            t.get("total_weight", abs(t.get("change", 0) or 0) * (t.get("weight", 0) or 0)),
            t.get("secondary", ""), t.get("secondaryQty", 0), t.get("penerima", ""),
            t.get("polisi", ""), t.get("document_type", ""), t.get("parent_document", ""),
            t.get("settled_qty", ""), t.get("good_change", ""), t.get("damaged_change", ""),
            t.get("operator", ""), t.get("keterangan", ""),
        ]
        for t in transactions
    ]
    output = build_xlsx(headers, rows, "Riwayat Transaksi")
    filename = f"riwayat_transaksi_{start.strftime('%Y_%m')}.xlsx"
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
