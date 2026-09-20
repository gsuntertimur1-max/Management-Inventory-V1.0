from __future__ import annotations

from collections import defaultdict
from typing import List, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from pymongo import ReturnDocument

from backend.server import build_xlsx, db, get_current_user, new_id, next_sequence, normalize_channel, now_iso, operational_now
from backend.role_four_config import has_role_permission, role_destination
from backend.consignment_documents import next_bazar_document_numbers
import backend.consignment as consignment_module
from backend.consignment_damaged import credit_consignment_damaged
from backend.operational_guards import idempotent_operation, lock_keys

router = APIRouter(prefix="/api")
EPS = 1e-9
BAZAR = "Gudang Bazar"
ECOM = "Gudang E-commerce"

_base_consignment_stock = consignment_module.consignment_stock


def _n(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _ensure_access(user: dict, destination: str, write: bool = False) -> None:
    scoped = role_destination(user.get("role"))
    if scoped and scoped != destination:
        raise HTTPException(status_code=403, detail=f"Akun ini hanya memiliki akses ke {scoped}")
    permission = ("bazarOps" if destination == BAZAR else "ecomOps") if write else ("bazarView" if destination == BAZAR else "ecomView")
    if not has_role_permission(user.get("role"), permission):
        raise HTTPException(status_code=403, detail=f"Tidak memiliki akses ke {destination}")


async def adjusted_consignment_stock(destination: str = "") -> list[dict]:
    rows = await _base_consignment_stock(destination)
    query = {}
    if destination:
        query["destination"] = destination
    movements = await db.consignment_movements.find(query, {"_id": 0}).to_list(50000)
    deltas = defaultdict(float)
    for movement in movements:
        key = (
            str(movement.get("destination") or ""),
            str(movement.get("productId") or ""),
            normalize_channel(movement.get("channel"), "KOM"),
        )
        deltas[key] += _n(movement.get("delta"))

    indexed = {}
    for row in rows:
        key = (row.get("destination", ""), row.get("productId", ""), normalize_channel(row.get("channel"), "KOM"))
        row = dict(row)
        row["qty"] = max(_n(row.get("qty")) + deltas.pop(key, 0.0), 0.0)
        row["totalWeight"] = row["qty"] * _n(row.get("weight"))
        indexed[key] = row

    # Positive return movements can revive a row whose original consignment balance is already zero.
    for (dest, product_id, channel), delta in list(deltas.items()):
        if delta <= EPS:
            continue
        product = await db.products.find_one({"id": product_id}, {"_id": 0})
        if not product:
            continue
        indexed[(dest, product_id, channel)] = {
            "destination": dest,
            "productId": product_id,
            "channel": channel,
            "sku": product.get("sku", ""),
            "name": product.get("name", ""),
            "unit": product.get("unit", ""),
            "weight": _n(product.get("weight")),
            "measureUnit": product.get("measureUnit", "kg") or "kg",
            "secondary": product.get("secondary", ""),
            "secondaryQty": _n(product.get("secondaryQty")),
            "qty": delta,
            "totalWeight": delta * _n(product.get("weight")),
            "documents": [],
            "requestDocuments": [],
        }

    return sorted(
        [row for row in indexed.values() if _n(row.get("qty")) > EPS],
        key=lambda row: (row.get("destination") != BAZAR, str(row.get("name") or "").lower(), row.get("channel", ""), row.get("sku", "")),
    )


# Patch the existing consignment module so dashboard/layout/opname use the same adjusted balance.
consignment_module.consignment_stock = adjusted_consignment_stock


async def _available(destination: str, product_id: str, exclude_kind: str = "", exclude_id: str = "") -> tuple[float, float, float]:
    stock_rows = await adjusted_consignment_stock(destination)
    physical = sum(_n(row.get("qty")) for row in stock_rows if row.get("productId") == product_id)
    reserved = 0.0
    if destination == BAZAR:
        trips = await db.bazar_trips.find({"status": "BERJALAN"}, {"_id": 0, "id": 1, "items": 1}).to_list(5000)
        for trip in trips:
            if exclude_kind == "BAZAR" and trip.get("id") == exclude_id:
                continue
            for item in trip.get("items", []):
                if item.get("productId") == product_id:
                    reserved += _n(item.get("loadedQty"))
    else:
        orders = await db.ecom_orders.find({"status": {"$in": ["RESERVED", "PACKING"]}}, {"_id": 0, "id": 1, "items": 1}).to_list(10000)
        for order in orders:
            if exclude_kind == "ECOM" and order.get("id") == exclude_id:
                continue
            for item in order.get("items", []):
                if item.get("productId") == product_id:
                    reserved += _n(item.get("qty"))
    return physical, reserved, max(physical - reserved, 0.0)


async def _bazar_stack_reserved(product_id: str, stack_code: str, exclude_trip_id: str = "") -> float:
    target = str(stack_code or "").strip().upper()
    reserved = 0.0
    trips = await db.bazar_trips.find({"status": "BERJALAN"}, {"_id": 0, "id": 1, "items": 1}).to_list(5000)
    for trip in trips:
        if exclude_trip_id and trip.get("id") == exclude_trip_id:
            continue
        for item in trip.get("items", []):
            if (
                item.get("productId") == product_id
                and str(item.get("stackCode") or "").strip().upper() == target
            ):
                reserved += _n(item.get("loadedQty"))
    return reserved


async def _identity(destination: str, product_id: str) -> dict:
    rows = await adjusted_consignment_stock(destination)
    row = next((item for item in rows if item.get("productId") == product_id), None)
    if row:
        return row
    product = await db.products.find_one({"id": product_id}, {"_id": 0})
    if not product:
        raise HTTPException(status_code=404, detail="Produk tidak ditemukan")
    return {
        "productId": product_id,
        "sku": product.get("sku", ""),
        "name": product.get("name", ""),
        "unit": product.get("unit", ""),
        "channel": normalize_channel(product.get("channel"), "KOM"),
    }


async def _history(destination: str, event_type: str, ref_id: str, ref_no: str, operator: str, items: list[dict], note: str = "", extra: dict | None = None) -> None:
    doc = {
        "id": new_id(), "time": now_iso(), "destination": destination, "eventType": event_type,
        "referenceId": ref_id, "referenceNo": ref_no, "operator": operator, "items": items,
        "note": str(note or "").strip(),
    }
    if extra:
        doc.update(extra)
    await db.consignment_operation_history.insert_one(doc)


class QtyItem(BaseModel):
    productId: str
    qty: float = Field(gt=0)


class BazarTripItem(QtyItem):
    stackCode: str = ""


class BazarTripCreate(BaseModel):
    eventDate: str = ""
    location: str
    vehicleNo: str
    driver: str = ""
    items: List[BazarTripItem] = Field(min_length=1)
    note: str = ""


class BazarCloseItem(BaseModel):
    productId: str
    stackCode: str = ""
    soldQty: float = Field(ge=0)
    returnedGoodQty: float = Field(ge=0)
    returnedDamagedQty: float = Field(default=0, ge=0)


class BazarTripClose(BaseModel):
    items: List[BazarCloseItem] = Field(min_length=1)
    note: str = ""


@router.get("/bazar/trips")
async def list_bazar_trips(user: dict = Depends(get_current_user)):
    _ensure_access(user, BAZAR, write=False)
    return await db.bazar_trips.find({}, {"_id": 0}).sort("createdAt", -1).to_list(5000)


@router.get("/bazar/availability")
async def bazar_availability(user: dict = Depends(get_current_user)):
    _ensure_access(user, BAZAR, write=False)
    result = []
    for row in await adjusted_consignment_stock(BAZAR):
        physical, reserved, available = await _available(BAZAR, row["productId"])
        result.append({**row, "physicalQty": physical, "reservedQty": reserved, "availableQty": available})
    return result


@router.post("/bazar/trips")
async def create_bazar_trip(
    body: BazarTripCreate,
    request: Request,
    user: dict = Depends(get_current_user),
):
    _ensure_access(user, BAZAR, write=True)
    product_ids = sorted({
        str(item.productId or "")
        for item in body.items
        if str(item.productId or "")
    })

    async def action():
        grouped = defaultdict(float)
        for item in body.items:
            stack_code = str(item.stackCode or "").strip().upper()
            grouped[(item.productId, stack_code)] += float(item.qty)

        items = []
        requested_by_product = defaultdict(float)
        for (product_id, _), qty in grouped.items():
            requested_by_product[product_id] += qty

        for (product_id, requested_stack), qty in grouped.items():
            identity = await _identity(BAZAR, product_id)
            _, _, available = await _available(BAZAR, product_id)
            total_requested = requested_by_product[product_id]
            if total_requested > available + EPS:
                raise HTTPException(
                    status_code=409,
                    detail=f"Stok tersedia {identity.get('name', '')} hanya {available:g} {identity.get('unit', '')}",
                )

            if requested_stack:
                stack_code = consignment_module.normalize_consignment_stack_code(BAZAR, requested_stack)
            else:
                layout = await db.consignment_layouts.find_one(
                    {"destination": BAZAR, "productId": product_id},
                    {"_id": 0, "stackCode": 1},
                    sort=[("stackCode", 1)],
                )
                stack_code = str((layout or {}).get("stackCode") or "18/A01-BAZAR")

            product_layout_count = await db.consignment_layouts.count_documents(
                {"destination": BAZAR, "productId": product_id}
            )
            selected_layout = await db.consignment_layouts.find_one(
                {"destination": BAZAR, "productId": product_id, "stackCode": stack_code},
                {"_id": 0},
            )
            if product_layout_count and not selected_layout:
                raise HTTPException(
                    status_code=400,
                    detail=f"Tumpukan {stack_code} tidak memiliki perkalian aktif untuk {identity.get('name', '')}",
                )
            if selected_layout:
                reserved_on_stack = await _bazar_stack_reserved(product_id, stack_code)
                stack_available = max(
                    consignment_module._layout_primary_qty(selected_layout) - reserved_on_stack,
                    0.0,
                )
                if qty > stack_available + EPS:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Stok tersedia {identity.get('name', '')} pada {stack_code} hanya {stack_available:g} {identity.get('unit', '')} setelah reservasi perjalanan aktif",
                    )

            items.append({
                "productId": product_id,
                "sku": identity.get("sku", ""),
                "name": identity.get("name", ""),
                "unit": identity.get("unit", ""),
                "channel": normalize_channel(identity.get("channel"), "KOM"),
                "weight": _n(identity.get("weight")),
                "measureUnit": identity.get("measureUnit", "kg") or "kg",
                "secondary": identity.get("secondary", ""),
                "secondaryQty": _n(identity.get("secondaryQty")),
                "stackCode": stack_code,
                "loadedQty": qty,
            })

        event_date = body.eventDate or operational_now().strftime("%Y-%m-%d")
        today = operational_now().strftime("%Y%m%d")
        seq = await next_sequence(f"bazar-trip:{today}")
        trip_no = f"BZ-{today}-{seq:03d}"
        document_numbers = await next_bazar_document_numbers("BAZAR", event_date)
        now = now_iso()
        operation_id = f"bazar-trip-create:{new_id()}"
        doc = {
            "id": new_id(),
            "tripNo": trip_no,
            "eventDate": event_date,
            "location": body.location.strip(),
            "vehicleNo": body.vehicleNo.strip().upper(),
            "driver": body.driver.strip(),
            "items": items,
            "status": "BERJALAN",
            "bonNo": document_numbers["bonNo"],
            "suratJalanNo": document_numbers["suratJalanNo"],
            "note": body.note.strip(),
            "operationId": operation_id,
            "createdAt": now,
            "createdBy": user.get("name", ""),
        }

        trip_saved = False
        history_saved = False
        try:
            await db.bazar_trips.insert_one(dict(doc))
            trip_saved = True
            await _history(
                BAZAR,
                "BAZAR_MUAT",
                doc["id"],
                trip_no,
                user.get("name", ""),
                items,
                body.note,
                {
                    "location": doc["location"],
                    "vehicleNo": doc["vehicleNo"],
                    "bonNo": doc["bonNo"],
                    "suratJalanNo": doc["suratJalanNo"],
                    "operationId": operation_id,
                },
            )
            history_saved = True
            return doc
        except Exception:
            if history_saved:
                await db.consignment_operation_history.delete_many({"operationId": operation_id})
            if trip_saved:
                await db.bazar_trips.delete_one({"id": doc["id"], "operationId": operation_id})
            raise

    keys = lock_keys(
        (f"consignment:{BAZAR}:{product_id}" for product_id in product_ids),
    )
    return await idempotent_operation(
        request,
        user,
        "bazar-trip-create",
        keys,
        action,
    )

@router.post("/bazar/trips/{trip_id}/close")
async def close_bazar_trip(trip_id: str, body: BazarTripClose, user: dict = Depends(get_current_user)):
    _ensure_access(user, BAZAR, write=True)
    trip = await db.bazar_trips.find_one({"id": trip_id}, {"_id": 0})
    if not trip:
        raise HTTPException(status_code=404, detail="Perjalanan Bazar tidak ditemukan")
    if trip.get("status") == "SELESAI":
        return trip
    if trip.get("status") != "BERJALAN":
        raise HTTPException(status_code=409, detail="Perjalanan Bazar tidak dapat ditutup dari status saat ini")

    result_map = {
        (item.productId, str(item.stackCode or "").strip().upper()): item
        for item in body.items
    }
    expected = {
        (item.get("productId"), str(item.get("stackCode") or "").strip().upper())
        for item in trip.get("items", [])
    }
    if set(result_map) != expected:
        raise HTTPException(status_code=400, detail="Rekonsiliasi harus mencakup seluruh komoditi dan tumpukan yang dimuat")

    final_items = []
    movements = []
    now = now_iso()
    for loaded in trip.get("items", []):
        stack_code = str(loaded.get("stackCode") or "").strip().upper()
        result = result_map[(loaded["productId"], stack_code)]
        sold = float(result.soldQty)
        returned_good = float(result.returnedGoodQty)
        returned_damaged = float(result.returnedDamagedQty)
        loaded_qty = _n(loaded.get("loadedQty"))
        if abs((sold + returned_good + returned_damaged) - loaded_qty) > EPS:
            raise HTTPException(status_code=400, detail=f"{loaded.get('name', '')}: Terjual + Retur Baik + Retur Rusak harus sama dengan jumlah muat {loaded_qty:g}")
        row = {**loaded, "soldQty": sold, "returnedGoodQty": returned_good, "returnedDamagedQty": returned_damaged}
        final_items.append(row)
        consumed = sold + returned_damaged
        if consumed > EPS:
            movements.append({
                "id": new_id(), "eventKey": f"bazar-close:{trip_id}:{loaded['productId']}:{stack_code}", "time": now,
                "destination": BAZAR, "movementType": "BAZAR_PENJUALAN", "referenceId": trip_id,
                "referenceNo": trip.get("tripNo", ""), "productId": loaded["productId"], "sku": loaded.get("sku", ""),
                "name": loaded.get("name", ""), "unit": loaded.get("unit", ""), "channel": loaded.get("channel", "KOM"),
                "delta": -consumed, "soldQty": sold, "damagedQty": returned_damaged, "operator": user.get("name", ""),
            })

    for movement in movements:
        await db.consignment_movements.update_one({"eventKey": movement["eventKey"]}, {"$setOnInsert": movement}, upsert=True)
    for item in final_items:
        consumed = _n(item.get("soldQty")) + _n(item.get("returnedDamagedQty"))
        if consumed > EPS:
            await consignment_module.decrease_consignment_layouts(
                BAZAR,
                item.get("productId", ""),
                consumed,
                user.get("name", ""),
                item.get("stackCode", ""),
                strict_preferred=True,
                operation_key=f"bazar-close:{trip_id}:{item.get('productId', '')}:{item.get('stackCode', '')}",
            )
    for item in final_items:
        damaged_qty = _n(item.get("returnedDamagedQty"))
        if damaged_qty > EPS:
            await credit_consignment_damaged(
                BAZAR,
                item,
                damaged_qty,
                f"bazar-damaged-return:{trip_id}:{item.get('productId', '')}:{item.get('stackCode', '')}",
                "BAZAR_RETUR_RUSAK",
                trip_id,
                trip.get("tripNo", ""),
                user.get("name", ""),
                body.note,
            )

    await db.bazar_trips.update_one({"id": trip_id, "status": "BERJALAN"}, {"$set": {
        "status": "SELESAI", "resultItems": final_items, "closedAt": now, "closedBy": user.get("name", ""), "closeNote": body.note.strip(),
    }})
    updated = await db.bazar_trips.find_one({"id": trip_id}, {"_id": 0})
    await _history(BAZAR, "BAZAR_SELESAI", trip_id, trip.get("tripNo", ""), user.get("name", ""), final_items, body.note,
                   {"location": trip.get("location", ""), "vehicleNo": trip.get("vehicleNo", "")})
    return updated


class EcomOrderCreate(BaseModel):
    marketplace: str = "Manual"
    orderNo: str
    buyer: str = ""
    items: List[QtyItem] = Field(min_length=1)
    note: str = ""


class EcomStatusBody(BaseModel):
    status: Literal["PACKING", "SHIPPED", "CANCELLED"]
    trackingNo: str = ""
    note: str = ""


class EcomReturnItem(BaseModel):
    productId: str
    goodQty: float = Field(default=0, ge=0)
    damagedQty: float = Field(default=0, ge=0)
    stackCode: str = ""


class EcomReturnBody(BaseModel):
    items: List[EcomReturnItem] = Field(min_length=1)
    note: str = ""


@router.get("/ecom/orders")
async def list_ecom_orders(user: dict = Depends(get_current_user)):
    _ensure_access(user, ECOM, write=False)
    return await db.ecom_orders.find({}, {"_id": 0}).sort("createdAt", -1).to_list(10000)


@router.get("/ecom/availability")
async def ecom_availability(user: dict = Depends(get_current_user)):
    _ensure_access(user, ECOM, write=False)
    result = []
    for row in await adjusted_consignment_stock(ECOM):
        physical, reserved, available = await _available(ECOM, row["productId"])
        result.append({**row, "physicalQty": physical, "reservedQty": reserved, "availableQty": available})
    return result


@router.post("/ecom/orders")
async def create_ecom_order(body: EcomOrderCreate, user: dict = Depends(get_current_user)):
    _ensure_access(user, ECOM, write=True)
    marketplace = body.marketplace.strip() or "Manual"
    order_no = body.orderNo.strip()
    if not order_no:
        raise HTTPException(status_code=400, detail="Nomor pesanan wajib diisi")
    existing = await db.ecom_orders.find_one({"marketplace": marketplace, "orderNo": order_no}, {"_id": 0})
    if existing:
        return existing
    grouped = defaultdict(float)
    for item in body.items:
        grouped[item.productId] += float(item.qty)
    items = []
    for product_id, qty in grouped.items():
        identity = await _identity(ECOM, product_id)
        _, _, available = await _available(ECOM, product_id)
        if qty > available + EPS:
            raise HTTPException(status_code=409, detail=f"Stok E-commerce tersedia {identity.get('name', '')} hanya {available:g} {identity.get('unit', '')}")
        items.append({
            "productId": product_id, "sku": identity.get("sku", ""), "name": identity.get("name", ""),
            "unit": identity.get("unit", ""), "channel": normalize_channel(identity.get("channel"), "KOM"), "qty": qty,
        })
    now = now_iso()
    doc = {
        "id": new_id(), "marketplace": marketplace, "orderNo": order_no, "buyer": body.buyer.strip(), "items": items,
        "status": "RESERVED", "trackingNo": "", "note": body.note.strip(), "createdAt": now, "createdBy": user.get("name", ""),
    }
    await db.ecom_orders.insert_one(dict(doc))
    await _history(ECOM, "ECOM_RESERVED", doc["id"], f"{marketplace}/{order_no}", user.get("name", ""), items, body.note,
                   {"marketplace": marketplace})
    return doc


@router.post("/ecom/orders/{order_id}/status")
async def update_ecom_status(
    order_id: str,
    body: EcomStatusBody,
    request: Request,
    user: dict = Depends(get_current_user),
):
    _ensure_access(user, ECOM, write=True)
    initial = await db.ecom_orders.find_one({"id": order_id}, {"_id": 0})
    if not initial:
        raise HTTPException(status_code=404, detail="Pesanan E-commerce tidak ditemukan")

    product_ids = sorted({
        str(item.get("productId") or "")
        for item in initial.get("items", [])
        if str(item.get("productId") or "")
    })

    async def action():
        order = await db.ecom_orders.find_one({"id": order_id}, {"_id": 0})
        if not order:
            raise HTTPException(status_code=404, detail="Pesanan E-commerce tidak ditemukan")
        current = order.get("status", "RESERVED")
        allowed = {"RESERVED": {"PACKING", "CANCELLED", "SHIPPED"}, "PACKING": {"SHIPPED", "CANCELLED"}}
        if body.status == current:
            return order
        if body.status not in allowed.get(current, set()):
            raise HTTPException(status_code=409, detail=f"Status {current} tidak dapat diubah menjadi {body.status}")

        now = now_iso()
        movement_keys: list[str] = []
        synced_products: set[str] = set()
        operation_id = f"ecom-status:{order_id}:{body.status}"
        order_updated = False
        history_saved = False

        try:
            if body.status == "SHIPPED":
                for item in order.get("items", []):
                    product_id = str(item.get("productId") or "")
                    if not product_id:
                        continue
                    await consignment_module.sync_consignment_layout_balance(
                        ECOM,
                        product_id,
                        operator=user.get("name", ""),
                        operation_key=f"{operation_id}:pre:{product_id}",
                        note="Validasi lokasi fisik sebelum pesanan E-commerce dikirim.",
                    )

                    event_key = f"ecom-ship:{order_id}:{product_id}"
                    if await db.consignment_movements.find_one({"eventKey": event_key}, {"_id": 1}):
                        raise HTTPException(
                            status_code=409,
                            detail="Movement pengiriman E-commerce sudah ada tetapi status order belum selesai. Periksa Kontrol Integritas.",
                        )
                    movement = {
                        "id": new_id(),
                        "eventKey": event_key,
                        "operationId": operation_id,
                        "time": now,
                        "destination": ECOM,
                        "movementType": "ECOM_DIKIRIM",
                        "referenceId": order_id,
                        "referenceNo": order.get("orderNo", ""),
                        "productId": product_id,
                        "sku": item.get("sku", ""),
                        "name": item.get("name", ""),
                        "unit": item.get("unit", ""),
                        "channel": item.get("channel", "KOM"),
                        "delta": -_n(item.get("qty")),
                        "operator": user.get("name", ""),
                    }
                    await db.consignment_movements.insert_one(dict(movement))
                    movement_keys.append(event_key)
                    synced_products.add(product_id)

                for product_id in sorted(synced_products):
                    await consignment_module.sync_consignment_layout_balance(
                        ECOM,
                        product_id,
                        operator=user.get("name", ""),
                        operation_key=f"{operation_id}:ship:{product_id}",
                        note=f"Pengurangan lokasi fisik untuk order E-commerce {order.get('orderNo', '')}.",
                    )

            patch = {
                "status": body.status,
                "updatedAt": now,
                "updatedBy": user.get("name", ""),
                "statusNote": body.note.strip(),
            }
            if body.trackingNo.strip():
                patch["trackingNo"] = body.trackingNo.strip()
            if body.status == "SHIPPED":
                patch["shippedAt"] = now
            if body.status == "CANCELLED":
                patch["cancelledAt"] = now

            result = await db.ecom_orders.update_one(
                {"id": order_id, "status": current},
                {"$set": patch},
            )
            if result.matched_count == 0:
                raise HTTPException(status_code=409, detail="Status order berubah saat diproses")
            order_updated = True

            await _history(
                ECOM,
                f"ECOM_{body.status}",
                order_id,
                f"{order.get('marketplace', '')}/{order.get('orderNo', '')}",
                user.get("name", ""),
                order.get("items", []),
                body.note,
                {
                    "trackingNo": patch.get("trackingNo", order.get("trackingNo", "")),
                    "fromStatus": current,
                    "toStatus": body.status,
                    "operationId": operation_id,
                },
            )
            history_saved = True
            return await db.ecom_orders.find_one({"id": order_id}, {"_id": 0})
        except Exception:
            if history_saved:
                await db.consignment_operation_history.delete_many({"operationId": operation_id})
            if order_updated:
                await db.ecom_orders.replace_one({"id": order_id}, dict(order), upsert=False)
            if movement_keys:
                await db.consignment_movements.delete_many({"eventKey": {"$in": movement_keys}})
            for product_id in sorted(synced_products):
                try:
                    await consignment_module.sync_consignment_layout_balance(
                        ECOM,
                        product_id,
                        operator="Sistem (rollback E-commerce)",
                        operation_key=f"{operation_id}:rollback:{product_id}",
                        note="Rollback perubahan status E-commerce yang tidak selesai.",
                    )
                except Exception:
                    pass
            raise

    keys = lock_keys(
        [f"ecom-order:{order_id}"],
        (f"consignment:{ECOM}:{product_id}" for product_id in product_ids),
    )
    return await idempotent_operation(
        request,
        user,
        f"ecom-order-status:{order_id}:{body.status}",
        keys,
        action,
    )

@router.post("/ecom/orders/{order_id}/return")
async def receive_ecom_return(order_id: str, body: EcomReturnBody, user: dict = Depends(get_current_user)):
    _ensure_access(user, ECOM, write=True)
    order = await db.ecom_orders.find_one({"id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Pesanan E-commerce tidak ditemukan")
    if order.get("status") not in {"SHIPPED", "PARTIAL_RETURN", "RETURNED"}:
        raise HTTPException(status_code=409, detail="Retur hanya dapat diterima untuk pesanan yang sudah dikirim")

    shipped = {item["productId"]: _n(item.get("qty")) for item in order.get("items", [])}
    prior = defaultdict(float)
    prior_moves = await db.consignment_movements.find({"referenceId": order_id, "movementType": "ECOM_RETUR"}, {"_id": 0}).to_list(10000)
    for move in prior_moves:
        prior[move.get("productId", "")] += _n(move.get("goodQty")) + _n(move.get("damagedQty"))

    now = now_iso()
    return_id = new_id()
    history_items = []
    for item in body.items:
        total = float(item.goodQty) + float(item.damagedQty)
        if total <= EPS:
            continue
        if item.productId not in shipped:
            raise HTTPException(status_code=400, detail="Produk retur tidak terdapat pada pesanan")
        if prior[item.productId] + total > shipped[item.productId] + EPS:
            raise HTTPException(status_code=400, detail="Jumlah retur melebihi jumlah yang dikirim")
        identity = next(row for row in order["items"] if row["productId"] == item.productId)
        return_stack = ""
        if float(item.goodQty) > EPS:
            requested_stack = str(item.stackCode or "").strip()
            if not requested_stack:
                raise HTTPException(status_code=400, detail=f"Pilih lokasi retur baik untuk {identity.get('name', '')}")
            return_stack = consignment_module.normalize_consignment_stack_code(ECOM, requested_stack)
        move = {
            "id": new_id(), "eventKey": f"ecom-return:{return_id}:{item.productId}", "time": now, "destination": ECOM,
            "movementType": "ECOM_RETUR", "referenceId": order_id, "referenceNo": order.get("orderNo", ""),
            "productId": item.productId, "sku": identity.get("sku", ""), "name": identity.get("name", ""),
            "unit": identity.get("unit", ""), "channel": identity.get("channel", "KOM"),
            "delta": float(item.goodQty), "goodQty": float(item.goodQty), "damagedQty": float(item.damagedQty),
            "stackCode": return_stack,
            "returnId": return_id, "operator": user.get("name", ""),
        }
        await db.consignment_movements.insert_one(move)
        if float(item.goodQty) > EPS:
            try:
                await consignment_module.sync_consignment_layout_balance(
                    ECOM,
                    item.productId,
                    operator=user.get("name", ""),
                    preferred_stack=return_stack,
                    operation_key=f"ecom-return-good:{return_id}:{item.productId}",
                    note="Retur baik E-commerce dikembalikan ke lokasi fisik yang dipilih.",
                )
            except Exception:
                await db.consignment_movements.delete_one({"eventKey": move["eventKey"]})
                raise
        if float(item.damagedQty) > EPS:
            await credit_consignment_damaged(
                ECOM,
                identity,
                float(item.damagedQty),
                f"ecom-damaged-return:{return_id}:{item.productId}",
                "ECOM_RETUR_RUSAK",
                order_id,
                order.get("orderNo", ""),
                user.get("name", ""),
                body.note,
            )
        history_items.append({
            **identity,
            "goodQty": float(item.goodQty),
            "damagedQty": float(item.damagedQty),
            "stackCode": return_stack,
        })
        prior[item.productId] += total

    if not history_items:
        raise HTTPException(status_code=400, detail="Isi minimal satu jumlah retur")
    fully_returned = all(prior[pid] >= qty - EPS for pid, qty in shipped.items())
    status = "RETURNED" if fully_returned else "PARTIAL_RETURN"
    await db.ecom_orders.update_one({"id": order_id}, {"$set": {"status": status, "updatedAt": now, "updatedBy": user.get("name", "")}})
    await _history(ECOM, "ECOM_RETUR", order_id, f"{order.get('marketplace', '')}/{order.get('orderNo', '')}", user.get("name", ""), history_items, body.note,
                   {"returnId": return_id, "toStatus": status})
    return await db.ecom_orders.find_one({"id": order_id}, {"_id": 0})


def _history_scope(user: dict, destination: str = "") -> str:
    if not has_role_permission(user.get("role"), "consignmentHistory"):
        raise HTTPException(status_code=403, detail="Tidak memiliki akses histori operasional Bazar/E-commerce")
    scoped = role_destination(user.get("role"))
    requested = str(destination or "").strip()
    if scoped:
        if requested and requested != scoped:
            raise HTTPException(status_code=403, detail=f"Akun ini hanya memiliki akses histori {scoped}")
        return scoped
    if requested:
        if requested not in {BAZAR, ECOM}:
            raise HTTPException(status_code=400, detail="Lokasi histori tidak valid")
        _ensure_access(user, requested, write=False)
    return requested


async def _operation_history_rows(
    user: dict,
    destination: str = "",
    start_date: str = "",
    end_date: str = "",
    event_type: str = "",
    product_id: str = "",
    search: str = "",
) -> list[dict]:
    resolved = _history_scope(user, destination)
    query: dict = {}
    if resolved:
        query["destination"] = resolved
    if str(event_type or "").strip():
        query["eventType"] = str(event_type).strip()
    time_query = {}
    if str(start_date or "").strip():
        time_query["$gte"] = f"{str(start_date).strip()}T00:00:00"
    if str(end_date or "").strip():
        time_query["$lte"] = f"{str(end_date).strip()}T23:59:59.999999"
    if time_query:
        query["time"] = time_query

    rows = await db.consignment_operation_history.find(query, {"_id": 0}).sort("time", -1).to_list(50000)
    product_id = str(product_id or "").strip()
    term = str(search or "").strip().lower()
    filtered = []
    for row in rows:
        items = row.get("items", []) or []
        if product_id and not any(str(item.get("productId") or "") == product_id for item in items):
            continue
        if term:
            values = [
                row.get("destination", ""), row.get("eventType", ""), row.get("referenceNo", ""),
                row.get("operator", ""), row.get("note", ""), row.get("location", ""),
                row.get("vehicleNo", ""), row.get("marketplace", ""),
            ]
            for item in items:
                values.extend([item.get("sku", ""), item.get("name", ""), item.get("packageName", ""), item.get("packageCode", "")])
            if term not in " ".join(str(value or "") for value in values).lower():
                continue
        filtered.append(row)
    return filtered


@router.get("/consignment-operation-history")
async def list_operation_history(
    destination: str = "",
    startDate: str = "",
    endDate: str = "",
    eventType: str = "",
    productId: str = "",
    search: str = "",
    user: dict = Depends(get_current_user),
):
    return await _operation_history_rows(
        user,
        destination=destination,
        start_date=startDate,
        end_date=endDate,
        event_type=eventType,
        product_id=productId,
        search=search,
    )


@router.get("/export/consignment-operation-history.xlsx")
async def export_operation_history(
    destination: str = "",
    startDate: str = "",
    endDate: str = "",
    eventType: str = "",
    productId: str = "",
    search: str = "",
    user: dict = Depends(get_current_user),
):
    rows = await _operation_history_rows(
        user,
        destination=destination,
        start_date=startDate,
        end_date=endDate,
        event_type=eventType,
        product_id=productId,
        search=search,
    )
    headers = [
        "Tanggal", "Lokasi", "Jenis Transaksi", "Referensi", "SKU", "Komoditi", "Satuan",
        "Qty", "Muat", "Terjual", "Disalurkan", "Retur Baik", "Retur Rusak",
        "Marketplace/Lokasi", "Kendaraan", "Petugas", "Keterangan",
    ]
    values = []
    for row in rows:
        items = row.get("items", []) or [{}]
        for item in items:
            values.append([
                row.get("time", ""),
                row.get("destination", ""),
                row.get("eventType", ""),
                row.get("referenceNo", ""),
                item.get("sku", ""),
                item.get("name", "") or item.get("packageName", ""),
                item.get("unit", ""),
                item.get("qty", item.get("requiredQty", item.get("packageQty", ""))),
                item.get("loadedQty", ""),
                item.get("soldQty", ""),
                item.get("deliveredQty", ""),
                item.get("returnedGoodQty", item.get("goodQty", "")),
                item.get("returnedDamagedQty", item.get("damagedQty", "")),
                row.get("marketplace", "") or row.get("location", "") or row.get("destinationName", ""),
                row.get("vehicleNo", ""),
                row.get("operator", ""),
                row.get("note", ""),
            ])
    output = build_xlsx(headers, values, "Riwayat Bazar Ecom")
    filename = f"riwayat_bazar_ecom_{operational_now().strftime('%Y%m%d_%H%M')}.xlsx"
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def ensure_consignment_operation_indexes() -> None:
    await db.consignment_movements.create_index("eventKey", unique=True, sparse=True, name="consignment_movement_event_unique")
    await db.consignment_movements.create_index([("destination", 1), ("productId", 1), ("time", -1)], name="consignment_movement_balance")
    await db.bazar_trips.create_index([("status", 1), ("createdAt", -1)], name="bazar_trip_status")
    await db.ecom_orders.create_index([("marketplace", 1), ("orderNo", 1)], unique=True, name="ecom_marketplace_order_unique")
    await db.ecom_orders.create_index([("status", 1), ("createdAt", -1)], name="ecom_order_status")
    await db.consignment_operation_history.create_index([("destination", 1), ("time", -1)], name="consignment_history_destination")
