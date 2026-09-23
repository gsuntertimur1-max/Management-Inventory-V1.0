from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.server import db, get_current_user, new_id, next_sequence, now_iso, operational_now, require_write
from backend.inventory_flow import (
    ReceiptInput,
    ReceiptItemInput,
    _hydrate_legacy_po,
    _unloading_user_key,
    receive_stock,
)
from backend.correction_receipts import enrich_receipt_result
from backend.stack_lots import record_receipt_lots
from backend.operational_guards import lock_keys, operation_guard, product_lock_keys

router = APIRouter(prefix="/api")
EPS = 1e-9
ACTIVE_STATUSES = ["Menunggu Bongkar", "Sedang Bongkar"]


async def ensure_inbound_load_indexes() -> None:
    await db.inbound_loads.create_index("id", unique=True)
    await db.inbound_loads.create_index("loadNo", unique=True)
    await db.inbound_loads.create_index([("poId", 1), ("status", 1)])
    await db.inbound_loads.create_index([("createdAt", -1)])


class InboundPlanItem(BaseModel):
    productId: str
    qty: float = Field(gt=0)
    stackCode: str = ""
    exp: str = ""
    channel: str = ""


class InboundLoadCreate(BaseModel):
    poId: str
    items: list[InboundPlanItem] = Field(min_length=1)
    polisi: str
    driver: str = ""
    keterangan: str = ""
    weighingForm: bool = False
    grossWeight: float = Field(default=0, ge=0)
    grossMin: float = Field(default=0, ge=0)
    grossMax: float = Field(default=0, ge=0)
    unloadingFeeChargeMode: str = "PENGIRIM"


class InboundCompleteItem(BaseModel):
    productId: str
    goodQty: float = Field(default=0, ge=0)
    damagedQty: float = Field(default=0, ge=0)
    overtimeQty: float | None = Field(default=None, ge=0)
    stackCode: str = ""
    exp: str = ""
    channel: str = ""


class InboundLoadComplete(BaseModel):
    items: list[InboundCompleteItem] = Field(min_length=1)
    note: str = ""


class InboundCancelInput(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


async def _active_reserved(po_id: str, exclude_id: str = "") -> dict[str, float]:
    query = {"poId": po_id, "status": {"$in": ACTIVE_STATUSES}}
    if exclude_id:
        query["id"] = {"$ne": exclude_id}
    rows = await db.inbound_loads.find(query, {"_id": 0, "items": 1}).to_list(5000)
    totals: dict[str, float] = defaultdict(float)
    for row in rows:
        for item in row.get("items", []):
            totals[str(item.get("productId") or "")] += float(item.get("qty", 0) or 0)
    return dict(totals)


async def _load_po(po_id: str) -> dict:
    raw = await db.purchase_orders.find_one({"id": po_id}, {"_id": 0})
    if not raw:
        raise HTTPException(status_code=404, detail="Purchase Order tidak ditemukan")
    po = await _hydrate_legacy_po(raw)
    if po.get("status") == "Selesai" or "Dibatalkan" in str(po.get("status", "")):
        raise HTTPException(status_code=400, detail="PO sudah selesai atau sisa penerimaannya telah dibatalkan")
    return po


def _started_minutes(value: str) -> int | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        jakarta = operational_now().tzinfo
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=jakarta)
        else:
            dt = dt.astimezone(jakarta)
        return dt.hour * 60 + dt.minute
    except Exception:
        return None


@router.get("/inbound-loads")
async def list_inbound_loads(user: dict = Depends(get_current_user)):
    return await db.inbound_loads.find({}, {"_id": 0}).sort("createdAt", -1).to_list(1000)


@router.get("/inbound-loads/reservations")
async def inbound_load_reservations(user: dict = Depends(get_current_user)):
    rows = await db.inbound_loads.find(
        {"status": {"$in": ACTIVE_STATUSES}},
        {"_id": 0, "poId": 1, "items": 1},
    ).to_list(5000)
    result: dict[str, dict[str, float]] = {}
    for row in rows:
        po_map = result.setdefault(str(row.get("poId") or ""), {})
        for item in row.get("items", []):
            product_id = str(item.get("productId") or "")
            po_map[product_id] = po_map.get(product_id, 0.0) + float(item.get("qty", 0) or 0)
    return result


@router.post("/inbound-loads")
async def create_inbound_load(body: InboundLoadCreate, user: dict = Depends(require_write)):
    if not body.poId.strip():
        raise HTTPException(status_code=400, detail="Pilih PO untuk membuat antrian bongkar")
    if not body.polisi.strip():
        raise HTTPException(status_code=400, detail="Nomor polisi kendaraan wajib diisi")
    if body.weighingForm and (body.grossWeight <= 0 or body.grossMin <= 0 or body.grossMax <= 0):
        raise HTTPException(status_code=400, detail="Rata-rata bruto serta rentang timbang wajib diisi")
    if body.weighingForm and not body.grossMin <= body.grossWeight <= body.grossMax:
        raise HTTPException(status_code=400, detail="Rata-rata bruto harus berada di dalam rentang timbang")

    product_ids = [item.productId for item in body.items]
    async with operation_guard(lock_keys([f"po:{body.poId}"], product_lock_keys(product_ids))):
        po = await _load_po(body.poId)
        po_items = {str(item.get("productId") or ""): item for item in po.get("items", [])}
        reserved = await _active_reserved(body.poId)

        seen: set[str] = set()
        stored_items = []
        for item in body.items:
            if item.productId in seen:
                raise HTTPException(status_code=400, detail="Produk yang sama tidak boleh muncul dua kali pada satu kendaraan")
            seen.add(item.productId)
            po_item = po_items.get(item.productId)
            if not po_item:
                raise HTTPException(status_code=400, detail="Produk kendaraan tidak tercantum pada PO")
            ordered = float(po_item.get("qty", 0) or 0)
            received = float(po_item.get("receivedQty", 0) or 0)
            pending = float(reserved.get(item.productId, 0) or 0)
            available = max(ordered - received - pending, 0)
            if float(item.qty) > available + EPS:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Jumlah kendaraan untuk {po_item.get('name', 'produk')} melebihi sisa yang dapat dijadwalkan "
                        f"({available:g} {po_item.get('unit', '')})."
                    ),
                )
            stored_items.append({
                "productId": item.productId,
                "sku": po_item.get("sku", ""),
                "name": po_item.get("name", ""),
                "unit": po_item.get("unit", ""),
                "qty": float(item.qty),
                "stackCode": item.stackCode.strip().upper(),
                "exp": item.exp.strip(),
                "channel": item.channel or po_item.get("channel", "KOM"),
            })

        today = operational_now().strftime("%Y%m%d")
        number = await next_sequence(f"inbound-load:{today}")
        load_no = f"PB-{today}-{number:03d}"
        now = now_iso()
        doc = {
            "id": new_id(),
            "loadNo": load_no,
            "poId": po["id"],
            "poNo": po.get("no", ""),
            "party": po.get("supplier", ""),
            "polisi": body.polisi.strip().upper(),
            "driver": body.driver.strip(),
            "items": stored_items,
            "status": "Menunggu Bongkar",
            "keterangan": body.keterangan.strip(),
            "weighingForm": bool(body.weighingForm),
            "grossWeight": float(body.grossWeight or 0),
            "grossMin": float(body.grossMin or 0),
            "grossMax": float(body.grossMax or 0),
            "unloadingFeeChargeMode": body.unloadingFeeChargeMode or "PENGIRIM",
            "createdAt": now,
            "createdBy": user.get("name", ""),
            "history": [{
                "time": now,
                "status": "Menunggu Bongkar",
                "by": user.get("name", ""),
                "note": "Kendaraan didaftarkan; belum mengubah stok atau penerimaan PO.",
            }],
        }
        await db.inbound_loads.insert_one(dict(doc))
        return doc


@router.post("/inbound-loads/{load_id}/start")
async def start_inbound_load(load_id: str, user: dict = Depends(require_write)):
    user_key = _unloading_user_key(user)
    async with operation_guard([f"inbound-load:{load_id}", f"unloading-user:{user_key}"]):
        load = await db.inbound_loads.find_one({"id": load_id}, {"_id": 0})
        if not load:
            raise HTTPException(status_code=404, detail="Kendaraan penerimaan tidak ditemukan")
        if load.get("status") != "Menunggu Bongkar":
            raise HTTPException(status_code=409, detail="Kendaraan tidak lagi berstatus Menunggu Bongkar")

        active = await db.unloading_sessions.find_one(
            {"startedByKey": user_key, "status": "BERJALAN"},
            {"_id": 0},
        )
        if active:
            raise HTTPException(status_code=409, detail="Masih ada sesi bongkar aktif pada akun ini. Selesaikan atau batalkan terlebih dahulu.")

        started = operational_now()
        session_id = new_id()
        session = {
            "id": session_id,
            "status": "BERJALAN",
            "startedAt": started.isoformat(),
            "startedBy": user.get("name", ""),
            "startedByKey": user_key,
            "createdAt": now_iso(),
            "inboundLoadId": load_id,
        }
        await db.unloading_sessions.insert_one(dict(session))
        event = {"time": now_iso(), "status": "Sedang Bongkar", "by": user.get("name", ""), "note": "Mulai bongkar"}
        result = await db.inbound_loads.update_one(
            {"id": load_id, "status": "Menunggu Bongkar"},
            {"$set": {
                "status": "Sedang Bongkar",
                "startedAt": started.isoformat(),
                "startedBy": user.get("name", ""),
                "unloadingSessionId": session_id,
            }, "$push": {"history": event}},
        )
        if result.matched_count == 0:
            await db.unloading_sessions.delete_one({"id": session_id})
            raise HTTPException(status_code=409, detail="Status kendaraan berubah. Muat ulang halaman.")
        return {**load, "status": "Sedang Bongkar", "startedAt": started.isoformat(), "startedBy": user.get("name", ""), "unloadingSessionId": session_id, "history": list(load.get("history") or []) + [event]}


@router.post("/inbound-loads/{load_id}/cancel")
async def cancel_inbound_load(load_id: str, body: InboundCancelInput, user: dict = Depends(require_write)):
    async with operation_guard([f"inbound-load:{load_id}"]):
        load = await db.inbound_loads.find_one({"id": load_id}, {"_id": 0})
        if not load:
            raise HTTPException(status_code=404, detail="Kendaraan penerimaan tidak ditemukan")
        if load.get("status") == "Selesai":
            raise HTTPException(status_code=400, detail="Penerimaan sudah selesai. Gunakan Koreksi Operasional untuk reversal.")
        if load.get("status") == "Dibatalkan":
            raise HTTPException(status_code=409, detail="Kendaraan ini sudah dibatalkan")
        if load.get("status") not in ACTIVE_STATUSES:
            raise HTTPException(status_code=409, detail="Status kendaraan tidak dapat dibatalkan")

        now = now_iso()
        session_id = str(load.get("unloadingSessionId") or "")
        if session_id:
            await db.unloading_sessions.update_one(
                {"id": session_id, "status": "BERJALAN"},
                {"$set": {"status": "DIBATALKAN", "cancelledAt": now, "cancelledBy": user.get("name", "")}},
            )
        event = {"time": now, "status": "Dibatalkan", "by": user.get("name", ""), "note": body.reason.strip()}
        await db.inbound_loads.update_one(
            {"id": load_id, "status": {"$in": ACTIVE_STATUSES}},
            {"$set": {
                "status": "Dibatalkan",
                "cancelledAt": now,
                "cancelledBy": user.get("name", ""),
                "cancelReason": body.reason.strip(),
            }, "$push": {"history": event}},
        )
        return {**load, "status": "Dibatalkan", "cancelledAt": now, "cancelledBy": user.get("name", ""), "cancelReason": body.reason.strip()}


@router.post("/inbound-loads/{load_id}/complete")
async def complete_inbound_load(load_id: str, body: InboundLoadComplete, user: dict = Depends(require_write)):
    load = await db.inbound_loads.find_one({"id": load_id}, {"_id": 0})
    if not load:
        raise HTTPException(status_code=404, detail="Kendaraan penerimaan tidak ditemukan")
    if load.get("status") != "Sedang Bongkar":
        raise HTTPException(status_code=409, detail="Kendaraan harus berstatus Sedang Bongkar")

    planned = {str(item.get("productId") or ""): item for item in load.get("items", [])}
    product_ids = list(planned)
    async with operation_guard(lock_keys([f"inbound-load:{load_id}", f"po:{load.get('poId', '')}"], product_lock_keys(product_ids))):
        load = await db.inbound_loads.find_one({"id": load_id}, {"_id": 0})
        if not load or load.get("status") != "Sedang Bongkar":
            raise HTTPException(status_code=409, detail="Status kendaraan berubah. Muat ulang halaman.")

        completion_map = {item.productId: item for item in body.items}
        receipt_items = []
        stored_actual = []
        total_actual = 0.0
        started_minutes = _started_minutes(str(load.get("startedAt") or ""))
        completed_at = operational_now()
        completed_minutes = completed_at.hour * 60 + completed_at.minute

        for product_id, planned_item in planned.items():
            actual = completion_map.get(product_id)
            if not actual:
                continue
            good = float(actual.goodQty or 0)
            damaged = float(actual.damagedQty or 0)
            total = good + damaged
            if total <= EPS:
                continue
            planned_qty = float(planned_item.get("qty", 0) or 0)
            if total > planned_qty + EPS:
                raise HTTPException(
                    status_code=400,
                    detail=f"Total aktual {planned_item.get('name', 'produk')} melebihi rencana kendaraan ({planned_qty:g} {planned_item.get('unit', '')})",
                )

            if started_minutes is None:
                raise HTTPException(status_code=409, detail="Waktu mulai bongkar kendaraan tidak valid. Batalkan sesi dan mulai kembali.")
            if started_minutes >= 16 * 60:
                # Mulai setelah pukul 16.00: seluruh aktual otomatis lembur.
                overtime = total
            elif completed_minutes < 16 * 60:
                # Selesai sebelum pukul 16.00: seluruh aktual otomatis normal.
                overtime = 0.0
            else:
                # Mulai sebelum 16.00 dan selesai setelah 16.00: operator hanya
                # mengisi jumlah yang benar-benar dibongkar setelah pukul 16.00.
                if actual.overtimeQty is None:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Isi jumlah {planned_item.get('name', 'produk')} yang dibongkar setelah pukul 16.00.",
                    )
                overtime = float(actual.overtimeQty)
            if overtime > total + EPS:
                raise HTTPException(status_code=400, detail=f"Jumlah setelah 16.00 {planned_item.get('name', 'produk')} tidak boleh melebihi total aktual")
            normal = max(total - overtime, 0)

            stack_code = actual.stackCode.strip().upper() or str(planned_item.get("stackCode") or "").strip().upper()
            receipt_items.append(ReceiptItemInput(
                productId=product_id,
                qty=total,
                goodQty=good,
                damagedQty=damaged,
                normalQtyBefore1600=normal,
                exp=actual.exp.strip() or str(planned_item.get("exp") or ""),
                stackCode=stack_code,
                channel=actual.channel or str(planned_item.get("channel") or ""),
            ))
            stored_actual.append({
                "productId": product_id,
                "sku": planned_item.get("sku", ""),
                "name": planned_item.get("name", ""),
                "unit": planned_item.get("unit", ""),
                "plannedQty": planned_qty,
                "goodQty": good,
                "damagedQty": damaged,
                "actualQty": total,
                "overtimeQty": overtime,
                "normalQty": normal,
                "stackCode": stack_code,
                "exp": actual.exp.strip() or str(planned_item.get("exp") or ""),
                "channel": actual.channel or str(planned_item.get("channel") or ""),
            })
            total_actual += total

        if total_actual <= EPS:
            raise HTTPException(status_code=400, detail="Isi minimal satu jumlah aktual penerimaan. Jika kendaraan tidak jadi bongkar, gunakan Batalkan.")

        session_id = str(load.get("unloadingSessionId") or "")
        if not session_id:
            raise HTTPException(status_code=409, detail="Sesi bongkar kendaraan tidak ditemukan")
        await db.unloading_sessions.update_one(
            {"id": session_id, "status": "BERJALAN"},
            {"$set": {"startedByKey": _unloading_user_key(user)}},
        )

        receipt_body = ReceiptInput(
            poId=str(load.get("poId") or ""),
            items=receipt_items,
            party=str(load.get("party") or ""),
            ref=str(load.get("poNo") or ""),
            polisi=str(load.get("polisi") or ""),
            keterangan=(body.note.strip() or str(load.get("keterangan") or "")),
            weighingForm=bool(load.get("weighingForm")),
            grossWeight=float(load.get("grossWeight", 0) or 0),
            grossMin=float(load.get("grossMin", 0) or 0),
            grossMax=float(load.get("grossMax", 0) or 0),
            unloadingFeeChargeMode=str(load.get("unloadingFeeChargeMode") or "PENGIRIM"),
            unloadingSessionId=session_id,
        )
        result = await receive_stock(receipt_body, user)
        result = await enrich_receipt_result(receipt_body, result)
        await record_receipt_lots(receipt_body, result)

        cost_keys = ("labor", "daily", "warehouse", "total", "chargeable", "baseTotal", "overtimeTotal", "holidayTotal", "holidayOvertimeTotal")
        unloading_cost = {key: 0.0 for key in cost_keys}
        unloading_groups: set[str] = set()
        for transaction in result.get("transactions", []):
            fee = transaction.get("unloading_cost") or {}
            for key in cost_keys:
                unloading_cost[key] += float(fee.get(key, 0) or 0)
            group = str(transaction.get("unloading_group") or "").strip()
            if group:
                unloading_groups.add(group)
        unloading_cost["groups"] = sorted(unloading_groups)

        now = now_iso()
        event = {"time": now, "status": "Selesai", "by": user.get("name", ""), "note": body.note.strip() or "Bongkar selesai"}
        completed_load = {
            **load,
            "status": "Selesai",
            "completedAt": now,
            "completedBy": user.get("name", ""),
            "operationId": result.get("operationId", ""),
            "actualItems": stored_actual,
            "unloadingCost": unloading_cost,
        }
        await db.inbound_loads.update_one(
            {"id": load_id, "status": "Sedang Bongkar"},
            {"$set": {
                "status": "Selesai",
                "completedAt": now,
                "completedBy": user.get("name", ""),
                "operationId": result.get("operationId", ""),
                "actualItems": stored_actual,
                "unloadingCost": unloading_cost,
            }, "$push": {"history": event}},
        )
        return {
            "load": completed_load,
            "operationId": result.get("operationId", ""),
            "purchaseOrder": result.get("purchaseOrder"),
            "transactions": result.get("transactions", []),
        }
