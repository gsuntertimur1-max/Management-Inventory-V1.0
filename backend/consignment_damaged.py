from __future__ import annotations

from collections import defaultdict
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from backend.server import db, get_current_user, new_id, now_iso, normalize_channel, next_sequence, operational_now
from backend.role_four_config import has_role_permission, role_destination, require_operational_approval
from backend.operational_guards import idempotent_operation, lock_keys
from backend.consignment_locations import normalize_consignment_stack_code
import backend.consignment as consignment_module

router = APIRouter(prefix="/api")

BAZAR = "Gudang Bazar"
ECOM = "Gudang E-commerce"
DESTINATIONS = {BAZAR, ECOM}
DAMAGED_LOCATIONS = {
    BAZAR: "Area Barang Rusak Bazar",
    ECOM: "Area Barang Rusak E-commerce",
}
EPS = 1e-9


def _n(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


async def _good_stock_state(destination: str, product_id: str, channel: str, stack_code: str) -> tuple[dict, float, float]:
    rows = await consignment_module.consignment_stock(destination)
    matches = [
        row for row in rows
        if row.get("productId") == product_id and normalize_channel(row.get("channel"), "KOM") == channel
    ]
    if not matches:
        raise HTTPException(status_code=404, detail="Stok baik konsinyasi tidak ditemukan")
    identity = dict(matches[0])
    physical = sum(_n(row.get("qty")) for row in matches)

    reserved_total = 0.0
    reserved_stack = 0.0
    if destination == BAZAR:
        trips = await db.bazar_trips.find({"status": "BERJALAN"}, {"_id": 0, "items": 1}).to_list(5000)
        for trip in trips:
            for item in trip.get("items", []):
                if item.get("productId") != product_id or normalize_channel(item.get("channel"), "KOM") != channel:
                    continue
                qty = _n(item.get("loadedQty"))
                reserved_total += qty
                if str(item.get("stackCode") or "").strip().upper() == stack_code:
                    reserved_stack += qty
    else:
        orders = await db.ecom_orders.find({"status": {"$in": ["RESERVED", "PACKING"]}}, {"_id": 0, "items": 1}).to_list(10000)
        for order in orders:
            for item in order.get("items", []):
                if item.get("productId") == product_id and normalize_channel(item.get("channel"), "KOM") == channel:
                    reserved_total += _n(item.get("qty"))

    layout = await db.consignment_layouts.find_one(
        {"destination": destination, "productId": product_id, "stackCode": stack_code},
        {"_id": 0},
    )
    if not layout:
        raise HTTPException(status_code=404, detail=f"Perkalian lokasi {stack_code} tidak ditemukan")
    stack_available = max(_n(layout.get("primaryQty")) - reserved_stack, 0.0)
    total_available = max(physical - reserved_total, 0.0)
    return identity, total_available, stack_available


def _ensure_access(user: dict, destination: str, write: bool = False) -> str:
    destination = str(destination or "").strip()
    if destination not in DESTINATIONS:
        raise HTTPException(status_code=400, detail="Lokasi barang rusak konsinyasi tidak valid")
    scoped = role_destination(user.get("role"))
    if scoped and scoped != destination:
        raise HTTPException(status_code=403, detail=f"Akun ini hanya memiliki akses ke {scoped}")
    permission = ("bazarOps" if destination == BAZAR else "ecomOps") if write else ("bazarView" if destination == BAZAR else "ecomView")
    if not has_role_permission(user.get("role"), permission):
        raise HTTPException(status_code=403, detail=f"Tidak memiliki akses ke {destination}")
    return destination


async def ensure_consignment_damaged_indexes() -> None:
    await db.consignment_damaged_balances.create_index(
        [("destination", 1), ("productId", 1), ("channel", 1)],
        unique=True,
        name="consignment_damaged_balance_unique",
    )
    await db.consignment_damaged_movements.create_index("eventKey", unique=True, name="consignment_damaged_event_unique")
    await db.consignment_damaged_movements.create_index([("destination", 1), ("time", -1)])
    await db.consignment_damaged_opnames.create_index(
        [("destination", 1), ("status", 1), ("createdAt", -1)],
        name="consignment_damaged_opname_status",
    )


async def reconcile_legacy_consignment_damaged() -> dict:
    """Backfill damaged subledger for completed legacy operations.

    Good-stock movements were already applied historically. This reconciliation
    ONLY creates the missing damaged-area balance/movement and is idempotent by
    the same eventKey used by current operational flows.
    """
    repaired = {"bazar": 0, "package": 0, "ecom": 0}

    async def identity_for(product_id: str, source: dict) -> dict:
        product = await db.products.find_one({"id": product_id}, {"_id": 0}) or {}
        return {
            "productId": product_id,
            "sku": source.get("sku") or product.get("sku", ""),
            "name": source.get("name") or product.get("name", ""),
            "unit": source.get("unit") or product.get("unit", ""),
            "channel": normalize_channel(source.get("channel"), normalize_channel(product.get("channel"), "KOM")),
            "weight": _n(source.get("weight", product.get("weight", 0))),
            "measureUnit": source.get("measureUnit") or product.get("measureUnit", "kg") or "kg",
        }

    trips = await db.bazar_trips.find(
        {"status": "SELESAI"},
        {"_id": 0, "id": 1, "tripNo": 1, "resultItems": 1},
    ).to_list(10000)
    for trip in trips:
        trip_id = str(trip.get("id") or "")
        for item in trip.get("resultItems") or []:
            qty = _n(item.get("returnedDamagedQty"))
            product_id = str(item.get("productId") or "")
            if qty <= EPS or not trip_id or not product_id:
                continue
            stack_code = str(item.get("stackCode") or "").strip().upper()
            event_key = f"bazar-damaged-return:{trip_id}:{product_id}:{stack_code}"
            if await db.consignment_damaged_movements.find_one({"eventKey": event_key}, {"_id": 1}):
                continue
            identity = await identity_for(product_id, item)
            await credit_consignment_damaged(
                BAZAR,
                identity,
                qty,
                event_key,
                "BAZAR_RETUR_RUSAK",
                trip_id,
                str(trip.get("tripNo") or ""),
                "Sistem (rekonsiliasi legacy)",
                "Backfill retur rusak Bazar historis; stok baik sudah dikurangi pada transaksi asal.",
            )
            repaired["bazar"] += 1

    package_loads = await db.bazar_package_loads.find(
        {"status": "SELESAI"},
        {"_id": 0, "id": 1, "loadNo": 1, "resultItems": 1},
    ).to_list(10000)
    for load in package_loads:
        load_id = str(load.get("id") or "")
        for loaded in load.get("resultItems") or []:
            damaged_packages = _n(loaded.get("returnedDamagedQty"))
            template_id = str(loaded.get("templateId") or "")
            if damaged_packages <= EPS or not load_id or not template_id:
                continue
            for component in loaded.get("components") or []:
                product_id = str(component.get("productId") or "")
                qty = damaged_packages * _n(component.get("qty"))
                if qty <= EPS or not product_id:
                    continue
                event_key = f"package-damaged-return:{load_id}:{template_id}:{product_id}"
                if await db.consignment_damaged_movements.find_one({"eventKey": event_key}, {"_id": 1}):
                    continue
                identity = await identity_for(product_id, component)
                await credit_consignment_damaged(
                    BAZAR,
                    identity,
                    qty,
                    event_key,
                    "PAKET_RETUR_RUSAK",
                    load_id,
                    str(load.get("loadNo") or ""),
                    "Sistem (rekonsiliasi legacy)",
                    "Backfill retur rusak Paket historis; stok baik sudah dikurangi pada transaksi asal.",
                )
                repaired["package"] += 1

    ecom_returns = await db.consignment_movements.find(
        {"destination": ECOM, "movementType": "ECOM_RETUR", "damagedQty": {"$gt": EPS}},
        {"_id": 0},
    ).to_list(20000)
    for movement in ecom_returns:
        return_id = str(movement.get("returnId") or "")
        product_id = str(movement.get("productId") or "")
        qty = _n(movement.get("damagedQty"))
        if not return_id or not product_id or qty <= EPS:
            continue
        event_key = f"ecom-damaged-return:{return_id}:{product_id}"
        if await db.consignment_damaged_movements.find_one({"eventKey": event_key}, {"_id": 1}):
            continue
        identity = await identity_for(product_id, movement)
        await credit_consignment_damaged(
            ECOM,
            identity,
            qty,
            event_key,
            "ECOM_RETUR_RUSAK",
            str(movement.get("referenceId") or ""),
            str(movement.get("referenceNo") or ""),
            "Sistem (rekonsiliasi legacy)",
            "Backfill retur rusak E-commerce historis.",
        )
        repaired["ecom"] += 1

    return repaired


async def damaged_stock_rows(destination: str = "") -> list[dict]:
    query = {}
    if destination:
        query["destination"] = destination
    rows = await db.consignment_damaged_balances.find(query, {"_id": 0}).sort([("destination", 1), ("name", 1)]).to_list(10000)
    return [row for row in rows if float(row.get("qty", 0) or 0) > EPS]


async def credit_consignment_damaged(
    destination: str,
    identity: dict,
    qty: float,
    event_key: str,
    movement_type: str,
    reference_id: str,
    reference_no: str,
    operator: str,
    note: str = "",
) -> dict:
    qty = float(qty or 0)
    if qty <= EPS:
        return {}
    destination = str(destination or "").strip()
    if destination not in DESTINATIONS:
        raise HTTPException(status_code=400, detail="Lokasi barang rusak konsinyasi tidak valid")
    channel = normalize_channel(identity.get("channel"), "KOM")
    event_key = str(event_key or "").strip()
    if not event_key:
        raise HTTPException(status_code=500, detail="Event key barang rusak tidak tersedia")

    existing = await db.consignment_damaged_movements.find_one({"eventKey": event_key}, {"_id": 0})
    if existing:
        return existing

    balance_filter = {"destination": destination, "productId": identity.get("productId", ""), "channel": channel}
    now = now_iso()
    balance_patch = {
        "destination": destination,
        "location": DAMAGED_LOCATIONS[destination],
        "productId": identity.get("productId", ""),
        "sku": identity.get("sku", ""),
        "name": identity.get("name", ""),
        "unit": identity.get("unit", ""),
        "channel": channel,
        "weight": float(identity.get("weight", 0) or 0),
        "measureUnit": identity.get("measureUnit", "kg") or "kg",
        "updatedAt": now,
    }
    await db.consignment_damaged_balances.update_one(
        balance_filter,
        {"$inc": {"qty": qty}, "$set": balance_patch, "$setOnInsert": {"id": new_id(), "createdAt": now}},
        upsert=True,
    )
    movement = {
        "id": new_id(),
        "eventKey": event_key,
        "time": now,
        "destination": destination,
        "location": DAMAGED_LOCATIONS[destination],
        "movementType": movement_type,
        "referenceId": str(reference_id or ""),
        "referenceNo": str(reference_no or ""),
        "productId": identity.get("productId", ""),
        "sku": identity.get("sku", ""),
        "name": identity.get("name", ""),
        "unit": identity.get("unit", ""),
        "channel": channel,
        "delta": qty,
        "operator": operator,
        "note": str(note or "").strip(),
    }
    try:
        await db.consignment_damaged_movements.insert_one(dict(movement))
    except DuplicateKeyError:
        await db.consignment_damaged_balances.update_one(balance_filter, {"$inc": {"qty": -qty}})
        return await db.consignment_damaged_movements.find_one({"eventKey": event_key}, {"_id": 0}) or {}
    except Exception:
        await db.consignment_damaged_balances.update_one(balance_filter, {"$inc": {"qty": -qty}})
        raise
    return movement


class DamagedDiscoveryInput(BaseModel):
    destination: Literal["Gudang Bazar", "Gudang E-commerce"]
    productId: str
    channel: str = ""
    stackCode: str
    qty: float = Field(gt=0)
    cause: str = Field(min_length=3, max_length=200)
    referenceNo: str = ""
    note: str = ""


@router.post("/consignment-damaged/discoveries")
async def record_consignment_damage(body: DamagedDiscoveryInput, request: Request, user: dict = Depends(get_current_user)):
    destination = _ensure_access(user, body.destination, write=True)
    product_id = body.productId.strip()
    if not product_id:
        raise HTTPException(status_code=400, detail="Produk wajib dipilih")
    channel = normalize_channel(body.channel, "KOM")
    stack_code = normalize_consignment_stack_code(destination, body.stackCode)
    qty = float(body.qty)
    cause = body.cause.strip()

    async def action():
        identity, total_available, stack_available = await _good_stock_state(destination, product_id, channel, stack_code)
        if qty > total_available + EPS:
            raise HTTPException(status_code=409, detail=f"Stok baik tersedia hanya {total_available:g} {identity.get('unit', '')} setelah reservasi")
        if qty > stack_available + EPS:
            raise HTTPException(status_code=409, detail=f"Stok tersedia di {stack_code} hanya {stack_available:g} {identity.get('unit', '')}")

        now = now_iso()
        operation_id = new_id()
        good_event = f"consignment-damage-good:{operation_id}"
        damaged_event = f"consignment-damage-credit:{operation_id}"
        reference_no = body.referenceNo.strip() or f"TR-RUSAK-{now[:10].replace('-', '')}"
        movement = {
            "id": new_id(),
            "eventKey": good_event,
            "time": now,
            "destination": destination,
            "movementType": "BAZAR_TEMUAN_RUSAK" if destination == BAZAR else "ECOM_TEMUAN_RUSAK",
            "referenceId": operation_id,
            "referenceNo": reference_no,
            "productId": product_id,
            "sku": identity.get("sku", ""),
            "name": identity.get("name", ""),
            "unit": identity.get("unit", ""),
            "channel": channel,
            "delta": -qty,
            "damagedQty": qty,
            "stackCode": stack_code,
            "cause": cause,
            "operator": user.get("name", ""),
            "note": body.note.strip(),
        }

        layout_changed = False
        damaged_credited = False
        try:
            await db.consignment_movements.insert_one(dict(movement))
            await consignment_module.decrease_consignment_layouts(
                destination,
                product_id,
                qty,
                user.get("name", ""),
                stack_code,
                strict_preferred=True,
                operation_key=good_event,
            )
            layout_changed = True
            await credit_consignment_damaged(
                destination,
                {**identity, "productId": product_id, "channel": channel},
                qty,
                damaged_event,
                movement["movementType"],
                operation_id,
                reference_no,
                user.get("name", ""),
                f"{cause}{' · ' + body.note.strip() if body.note.strip() else ''}",
            )
            damaged_credited = True
            await db.consignment_operation_history.insert_one({
                "id": new_id(),
                "time": now,
                "destination": destination,
                "eventType": "BAZAR_TEMUAN_RUSAK" if destination == BAZAR else "ECOM_TEMUAN_RUSAK",
                "referenceId": operation_id,
                "referenceNo": reference_no,
                "operator": user.get("name", ""),
                "items": [{
                    "productId": product_id,
                    "sku": identity.get("sku", ""),
                    "name": identity.get("name", ""),
                    "unit": identity.get("unit", ""),
                    "channel": channel,
                    "qty": qty,
                    "stackCode": stack_code,
                    "cause": cause,
                }],
                "note": body.note.strip(),
                "damagedArea": DAMAGED_LOCATIONS[destination],
            })
        except Exception:
            if damaged_credited:
                await db.consignment_damaged_movements.delete_one({"eventKey": damaged_event})
                await db.consignment_damaged_balances.update_one(
                    {"destination": destination, "productId": product_id, "channel": channel},
                    {"$inc": {"qty": -qty}, "$set": {"updatedAt": now_iso()}},
                )
            if layout_changed:
                await db.consignment_layouts.update_one(
                    {"destination": destination, "productId": product_id, "stackCode": stack_code},
                    {"$inc": {"primaryQty": qty}, "$pull": {"appliedOperations": {"key": good_event}}},
                )
                await db.consignment_layout_history.delete_many({"operationKey": good_event})
            await db.consignment_movements.delete_one({"eventKey": good_event})
            raise

        return {
            "operationId": operation_id,
            "referenceNo": reference_no,
            "destination": destination,
            "damagedArea": DAMAGED_LOCATIONS[destination],
            "productId": product_id,
            "channel": channel,
            "stackCode": stack_code,
            "qty": qty,
        }

    return await idempotent_operation(
        request,
        user,
        f"consignment-damage-discovery:{destination}:{product_id}:{channel}:{stack_code}",
        [f"consignment:{destination}:{product_id}", f"consignment-damaged:{destination}:{product_id}:{channel}"],
        action,
    )


class DamagedSaleInput(BaseModel):
    destination: Literal["Gudang Bazar", "Gudang E-commerce"]
    productId: str
    channel: str = ""
    qty: float = Field(gt=0)
    recipient: str = ""
    referenceNo: str = ""
    note: str = ""


@router.get("/consignment-damaged-stock")
async def list_consignment_damaged_stock(destination: str = "", user: dict = Depends(get_current_user)):
    scoped = role_destination(user.get("role"))
    requested = str(destination or "").strip()
    resolved = scoped or requested
    if scoped and requested and requested != scoped:
        raise HTTPException(status_code=403, detail=f"Akun ini hanya memiliki akses ke {scoped}")
    if resolved:
        _ensure_access(user, resolved, write=False)
    elif not has_role_permission(user.get("role"), "consignmentView"):
        raise HTTPException(status_code=403, detail="Tidak memiliki akses stok rusak Bazar/E-commerce")
    return await damaged_stock_rows(resolved)


@router.get("/consignment-damaged-history")
async def list_consignment_damaged_history(destination: str = "", user: dict = Depends(get_current_user)):
    scoped = role_destination(user.get("role"))
    requested = str(destination or "").strip()
    resolved = scoped or requested
    if scoped and requested and requested != scoped:
        raise HTTPException(status_code=403, detail=f"Akun ini hanya memiliki akses ke {scoped}")
    if resolved:
        _ensure_access(user, resolved, write=False)
    elif not has_role_permission(user.get("role"), "consignmentHistory"):
        raise HTTPException(status_code=403, detail="Tidak memiliki akses histori barang rusak")
    query = {"destination": resolved} if resolved else {}
    return await db.consignment_damaged_movements.find(query, {"_id": 0}).sort("time", -1).to_list(10000)


@router.post("/consignment-damaged/sales")
async def sell_consignment_damaged(body: DamagedSaleInput, request: Request, user: dict = Depends(get_current_user)):
    destination = _ensure_access(user, body.destination, write=True)
    product_id = body.productId.strip()
    if not product_id:
        raise HTTPException(status_code=400, detail="Produk barang rusak wajib dipilih")

    channel = normalize_channel(body.channel, "KOM")

    async def action():
        balance = await db.consignment_damaged_balances.find_one(
            {"destination": destination, "productId": product_id, "channel": channel},
            {"_id": 0},
        )
        if not balance:
            raise HTTPException(status_code=404, detail="Saldo barang rusak tidak ditemukan")
        qty = float(body.qty)
        updated = await db.consignment_damaged_balances.find_one_and_update(
            {
                "destination": destination,
                "productId": product_id,
                "channel": channel,
                "qty": {"$gte": qty},
            },
            {"$inc": {"qty": -qty}, "$set": {"updatedAt": now_iso()}},
            return_document=ReturnDocument.AFTER,
        )
        if not updated:
            current = float(balance.get("qty", 0) or 0)
            raise HTTPException(status_code=409, detail=f"Saldo barang rusak tinggal {current:g} {balance.get('unit', '')}")

        now = now_iso()
        ref = body.referenceNo.strip() or f"JUAL-RUSAK-{now[:10].replace('-', '')}"
        movement = {
            "id": new_id(),
            "eventKey": f"damaged-sale:{destination}:{new_id()}",
            "time": now,
            "destination": destination,
            "location": DAMAGED_LOCATIONS[destination],
            "movementType": "PENJUALAN_BARANG_RUSAK",
            "referenceId": "",
            "referenceNo": ref,
            "productId": product_id,
            "sku": balance.get("sku", ""),
            "name": balance.get("name", ""),
            "unit": balance.get("unit", ""),
            "channel": balance.get("channel", "KOM"),
            "delta": -qty,
            "recipient": body.recipient.strip(),
            "operator": user.get("name", ""),
            "note": body.note.strip(),
        }
        try:
            await db.consignment_damaged_movements.insert_one(dict(movement))
        except Exception:
            await db.consignment_damaged_balances.update_one(
                {"destination": destination, "productId": product_id, "channel": channel},
                {"$inc": {"qty": qty}},
            )
            raise
        await db.consignment_operation_history.insert_one({
            "id": new_id(),
            "time": now,
            "destination": destination,
            "eventType": "BAZAR_RUSAK_TERJUAL" if destination == BAZAR else "ECOM_RUSAK_TERJUAL",
            "referenceId": "",
            "referenceNo": ref,
            "operator": user.get("name", ""),
            "items": [{
                "productId": product_id,
                "sku": balance.get("sku", ""),
                "name": balance.get("name", ""),
                "unit": balance.get("unit", ""),
                "qty": qty,
                "recipient": body.recipient.strip(),
            }],
            "note": body.note.strip(),
            "damagedArea": DAMAGED_LOCATIONS[destination],
        })
        return {
            "movement": movement,
            "balance": {k: v for k, v in updated.items() if k != "_id"},
        }

    return await idempotent_operation(
        request,
        user,
        f"consignment-damaged-sale:{destination}:{product_id}:{channel}",
        [f"consignment-damaged:{destination}:{product_id}:{channel}"],
        action,
    )


class DamagedOpnameItemInput(BaseModel):
    productId: str
    channel: str = ""
    actualQty: float = Field(ge=0)
    note: str = ""


class DamagedOpnameCreate(BaseModel):
    destination: Literal["Gudang Bazar", "Gudang E-commerce"]
    items: list[DamagedOpnameItemInput] = Field(default_factory=list)
    note: str = ""


class DamagedOpnameUpdate(BaseModel):
    items: list[DamagedOpnameItemInput] = Field(default_factory=list)
    note: str = ""


class DamagedOpnameDecision(BaseModel):
    note: str = ""


async def _damaged_opname_snapshot(destination: str) -> list[dict]:
    destination = str(destination or "").strip()
    balances = await db.consignment_damaged_balances.find(
        {"destination": destination},
        {"_id": 0},
    ).to_list(10000)

    rows: dict[tuple[str, str], dict] = {}
    for balance in balances:
        product_id = str(balance.get("productId") or "")
        if not product_id:
            continue
        channel = normalize_channel(balance.get("channel"), "KOM")
        rows[(product_id, channel)] = {
            "productId": product_id,
            "channel": channel,
            "sku": balance.get("sku", ""),
            "name": balance.get("name", ""),
            "unit": balance.get("unit", ""),
            "systemQty": _n(balance.get("qty")),
            "actualQty": _n(balance.get("qty")),
            "difference": 0.0,
            "note": "",
        }

    # Sertakan produk konsinyasi aktif walaupun saldo rusaknya masih nol agar
    # temuan fisik saat opname dapat dicatat sebagai adjustment resmi.
    stock_rows = await consignment_module.consignment_stock(destination)
    for row in stock_rows:
        product_id = str(row.get("productId") or "")
        if not product_id:
            continue
        channel = normalize_channel(row.get("channel"), "KOM")
        key = (product_id, channel)
        if key not in rows:
            rows[key] = {
                "productId": product_id,
                "channel": channel,
                "sku": row.get("sku", ""),
                "name": row.get("name", ""),
                "unit": row.get("unit", ""),
                "systemQty": 0.0,
                "actualQty": 0.0,
                "difference": 0.0,
                "note": "",
            }

    return sorted(
        rows.values(),
        key=lambda row: (str(row.get("name") or "").lower(), row.get("channel", ""), row.get("sku", "")),
    )


async def _current_damaged_qty(destination: str) -> dict[tuple[str, str], float]:
    rows = await db.consignment_damaged_balances.find(
        {"destination": destination},
        {"_id": 0, "productId": 1, "channel": 1, "qty": 1},
    ).to_list(10000)
    return {
        (str(row.get("productId") or ""), normalize_channel(row.get("channel"), "KOM")): _n(row.get("qty"))
        for row in rows
        if str(row.get("productId") or "")
    }


@router.get("/consignment-damaged-opnames")
async def list_consignment_damaged_opnames(
    destination: str = "",
    user: dict = Depends(get_current_user),
):
    scoped = role_destination(user.get("role"))
    requested = str(destination or "").strip()
    resolved = scoped or requested
    if scoped and requested and requested != scoped:
        raise HTTPException(status_code=403, detail=f"Akun ini hanya memiliki akses ke {scoped}")
    if resolved:
        _ensure_access(user, resolved, write=False)
    elif not has_role_permission(user.get("role"), "consignmentView"):
        raise HTTPException(status_code=403, detail="Tidak memiliki akses stock opname barang rusak")
    query = {"destination": resolved} if resolved else {}
    return await db.consignment_damaged_opnames.find(query, {"_id": 0}).sort("createdAt", -1).to_list(5000)


@router.post("/consignment-damaged-opnames")
async def create_consignment_damaged_opname(
    body: DamagedOpnameCreate,
    request: Request,
    user: dict = Depends(get_current_user),
):
    destination = _ensure_access(user, body.destination, write=True)

    async def action():
        existing = await db.consignment_damaged_opnames.find_one(
            {"destination": destination, "status": {"$in": ["DRAFT", "SUBMITTED"]}},
            {"_id": 0, "no": 1},
        )
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"Masih ada stock opname barang rusak aktif: {existing.get('no', '')}",
            )

        snapshot = await _damaged_opname_snapshot(destination)
        if not snapshot:
            raise HTTPException(status_code=400, detail="Belum ada produk Bazar/E-commerce yang dapat diopname pada Area Barang Rusak")

        submitted = {
            (item.productId, normalize_channel(item.channel, "KOM")): item
            for item in body.items
        }
        valid_keys = {(row["productId"], row["channel"]) for row in snapshot}
        if any(key not in valid_keys for key in submitted):
            raise HTTPException(status_code=400, detail="Ada produk yang tidak termasuk snapshot Area Barang Rusak")

        lines = []
        for row in snapshot:
            patch = submitted.get((row["productId"], row["channel"]))
            actual = float(patch.actualQty) if patch else float(row["systemQty"])
            lines.append({
                **row,
                "actualQty": actual,
                "difference": actual - float(row["systemQty"]),
                "note": patch.note.strip() if patch else "",
            })

        op_now = operational_now()
        date_text = op_now.strftime("%Y%m%d")
        seq = await next_sequence(f"consignment-damaged-opname:{date_text}")
        now = now_iso()
        doc = {
            "id": new_id(),
            "no": f"OPR-{date_text}-{seq:03d}",
            "time": now,
            "destination": destination,
            "location": DAMAGED_LOCATIONS[destination],
            "status": "DRAFT",
            "items": lines,
            "note": body.note.strip(),
            "operator": user.get("name", ""),
            "createdAt": now,
            "createdBy": user.get("name", ""),
            "updatedAt": now,
            "updatedBy": user.get("name", ""),
            "submittedAt": "",
            "submittedBy": "",
            "approvedAt": "",
            "approvedBy": "",
            "approvalNote": "",
            "rejectedAt": "",
            "rejectedBy": "",
            "rejectionNote": "",
        }
        await db.consignment_damaged_opnames.insert_one(dict(doc))
        return doc

    return await idempotent_operation(
        request,
        user,
        f"consignment-damaged-opname-create:{destination}",
        [f"consignment-damaged-opname-active:{destination}"],
        action,
    )


@router.put("/consignment-damaged-opnames/{opname_id}")
async def update_consignment_damaged_opname(
    opname_id: str,
    body: DamagedOpnameUpdate,
    request: Request,
    user: dict = Depends(get_current_user),
):
    initial = await db.consignment_damaged_opnames.find_one({"id": opname_id}, {"_id": 0})
    if not initial:
        raise HTTPException(status_code=404, detail="Stock opname barang rusak tidak ditemukan")
    destination = _ensure_access(user, initial.get("destination", ""), write=True)

    async def action():
        current = await db.consignment_damaged_opnames.find_one({"id": opname_id}, {"_id": 0})
        if not current or current.get("status") != "DRAFT":
            raise HTTPException(status_code=409, detail="Hanya stock opname barang rusak DRAFT yang dapat diubah")

        submitted = {
            (item.productId, normalize_channel(item.channel, "KOM")): item
            for item in body.items
        }
        valid_keys = {
            (str(row.get("productId") or ""), normalize_channel(row.get("channel"), "KOM"))
            for row in current.get("items", [])
        }
        if any(key not in valid_keys for key in submitted):
            raise HTTPException(status_code=400, detail="Ada produk yang tidak termasuk snapshot opname")

        lines = []
        for original in current.get("items", []):
            revised = dict(original)
            key = (str(original.get("productId") or ""), normalize_channel(original.get("channel"), "KOM"))
            patch = submitted.get(key)
            if patch:
                revised["actualQty"] = float(patch.actualQty)
                revised["note"] = patch.note.strip()
            revised["difference"] = _n(revised.get("actualQty")) - _n(revised.get("systemQty"))
            lines.append(revised)

        now = now_iso()
        result = await db.consignment_damaged_opnames.update_one(
            {"id": opname_id, "status": "DRAFT"},
            {"$set": {
                "items": lines,
                "note": body.note.strip(),
                "updatedAt": now,
                "updatedBy": user.get("name", ""),
            }},
        )
        if result.matched_count == 0:
            raise HTTPException(status_code=409, detail="Stock opname barang rusak berubah saat disimpan")
        return await db.consignment_damaged_opnames.find_one({"id": opname_id}, {"_id": 0})

    return await idempotent_operation(
        request,
        user,
        f"consignment-damaged-opname-update:{opname_id}",
        [f"consignment-damaged-opname:{opname_id}", f"consignment-damaged-opname-active:{destination}"],
        action,
    )


@router.post("/consignment-damaged-opnames/{opname_id}/submit")
async def submit_consignment_damaged_opname(
    opname_id: str,
    body: DamagedOpnameDecision,
    request: Request,
    user: dict = Depends(get_current_user),
):
    opname = await db.consignment_damaged_opnames.find_one({"id": opname_id}, {"_id": 0})
    if not opname:
        raise HTTPException(status_code=404, detail="Stock opname barang rusak tidak ditemukan")
    destination = _ensure_access(user, opname.get("destination", ""), write=True)

    async def action():
        now = now_iso()
        result = await db.consignment_damaged_opnames.update_one(
            {"id": opname_id, "status": "DRAFT"},
            {"$set": {
                "status": "SUBMITTED",
                "submittedAt": now,
                "submittedBy": user.get("name", ""),
                "submissionNote": body.note.strip(),
                "updatedAt": now,
                "updatedBy": user.get("name", ""),
            }},
        )
        if result.matched_count == 0:
            raise HTTPException(status_code=409, detail="Stock opname barang rusak sudah berubah atau tidak lagi DRAFT")
        return await db.consignment_damaged_opnames.find_one({"id": opname_id}, {"_id": 0})

    return await idempotent_operation(
        request,
        user,
        f"consignment-damaged-opname-submit:{opname_id}",
        [f"consignment-damaged-opname:{opname_id}", f"consignment-damaged-opname-active:{destination}"],
        action,
    )


@router.post("/consignment-damaged-opnames/{opname_id}/approve")
async def approve_consignment_damaged_opname(
    opname_id: str,
    body: DamagedOpnameDecision,
    request: Request,
    user: dict = Depends(require_operational_approval),
):
    initial = await db.consignment_damaged_opnames.find_one({"id": opname_id}, {"_id": 0})
    if not initial:
        raise HTTPException(status_code=404, detail="Stock opname barang rusak tidak ditemukan")
    destination = str(initial.get("destination") or "")
    affected = [
        (
            str(line.get("productId") or ""),
            normalize_channel(line.get("channel"), "KOM"),
        )
        for line in initial.get("items", [])
        if abs(_n(line.get("difference"))) > EPS and str(line.get("productId") or "")
    ]

    async def action():
        opname = await db.consignment_damaged_opnames.find_one({"id": opname_id}, {"_id": 0})
        if not opname or opname.get("status") != "SUBMITTED":
            raise HTTPException(status_code=409, detail="Stock opname barang rusak tidak lagi menunggu persetujuan")

        current = await _current_damaged_qty(destination)
        for line in opname.get("items", []):
            key = (str(line.get("productId") or ""), normalize_channel(line.get("channel"), "KOM"))
            current_qty = _n(current.get(key, 0.0))
            snapshot_qty = _n(line.get("systemQty"))
            if abs(current_qty - snapshot_qty) > EPS:
                raise HTTPException(
                    status_code=409,
                    detail=f"Saldo rusak {line.get('name', '')} berubah sejak snapshot ({snapshot_qty:g} → {current_qty:g}). Buat ulang opname.",
                )

        operation_id = new_id()
        approved_at = now_iso()
        inserted_events: list[str] = []
        applied_balances: list[dict] = []
        history_saved = False
        status_saved = False

        try:
            for line in opname.get("items", []):
                difference = _n(line.get("actualQty")) - _n(line.get("systemQty"))
                if abs(difference) <= EPS:
                    continue

                product_id = str(line.get("productId") or "")
                channel = normalize_channel(line.get("channel"), "KOM")
                event_key = f"consignment-damaged-opname:{opname_id}:{product_id}:{channel}"
                movement = {
                    "id": new_id(),
                    "eventKey": event_key,
                    "operationId": operation_id,
                    "time": approved_at,
                    "destination": destination,
                    "location": DAMAGED_LOCATIONS[destination],
                    "movementType": "OPNAME_RUSAK_ADJUSTMENT",
                    "referenceId": opname_id,
                    "referenceNo": opname.get("no", ""),
                    "productId": product_id,
                    "sku": line.get("sku", ""),
                    "name": line.get("name", ""),
                    "unit": line.get("unit", ""),
                    "channel": channel,
                    "delta": difference,
                    "systemQty": _n(line.get("systemQty")),
                    "physicalQty": _n(line.get("actualQty")),
                    "operator": user.get("name", ""),
                    "note": line.get("note", "") or body.note.strip(),
                }
                await db.consignment_damaged_movements.insert_one(dict(movement))
                inserted_events.append(event_key)

                balance_filter = {
                    "destination": destination,
                    "productId": product_id,
                    "channel": channel,
                }
                existing = await db.consignment_damaged_balances.find_one(balance_filter, {"_id": 0})
                if existing:
                    result = await db.consignment_damaged_balances.update_one(
                        {**balance_filter, "qty": _n(line.get("systemQty"))},
                        {"$inc": {"qty": difference}, "$set": {
                            "updatedAt": approved_at,
                            "updatedBy": user.get("name", ""),
                        }},
                    )
                    if result.matched_count == 0:
                        raise HTTPException(status_code=409, detail=f"Saldo rusak {line.get('name', '')} berubah saat approval")
                    applied_balances.append({
                        "mode": "UPDATE",
                        "filter": balance_filter,
                        "difference": difference,
                    })
                else:
                    if difference < -EPS:
                        raise HTTPException(status_code=409, detail=f"Saldo rusak {line.get('name', '')} tidak tersedia untuk dikurangi")
                    doc = {
                        "id": new_id(),
                        "destination": destination,
                        "location": DAMAGED_LOCATIONS[destination],
                        "productId": product_id,
                        "sku": line.get("sku", ""),
                        "name": line.get("name", ""),
                        "unit": line.get("unit", ""),
                        "channel": channel,
                        "qty": difference,
                        "createdAt": approved_at,
                        "updatedAt": approved_at,
                        "updatedBy": user.get("name", ""),
                    }
                    await db.consignment_damaged_balances.insert_one(dict(doc))
                    applied_balances.append({
                        "mode": "INSERT",
                        "filter": balance_filter,
                        "id": doc["id"],
                    })

            await db.consignment_operation_history.insert_one({
                "id": new_id(),
                "operationId": operation_id,
                "time": approved_at,
                "destination": destination,
                "eventType": "OPNAME_BARANG_RUSAK_DISETUJUI",
                "referenceId": opname_id,
                "referenceNo": opname.get("no", ""),
                "operator": user.get("name", ""),
                "items": opname.get("items", []),
                "note": body.note.strip(),
                "damagedArea": DAMAGED_LOCATIONS[destination],
            })
            history_saved = True

            result = await db.consignment_damaged_opnames.update_one(
                {"id": opname_id, "status": "SUBMITTED"},
                {"$set": {
                    "status": "APPROVED",
                    "approvedAt": approved_at,
                    "approvedBy": user.get("name", ""),
                    "approvalNote": body.note.strip(),
                    "adjustmentOperationId": operation_id,
                    "updatedAt": approved_at,
                    "updatedBy": user.get("name", ""),
                }},
            )
            if result.matched_count == 0:
                raise HTTPException(status_code=409, detail="Status opname barang rusak berubah saat approval")
            status_saved = True
            return await db.consignment_damaged_opnames.find_one({"id": opname_id}, {"_id": 0})

        except Exception:
            if status_saved:
                await db.consignment_damaged_opnames.update_one(
                    {"id": opname_id, "status": "APPROVED", "adjustmentOperationId": operation_id},
                    {"$set": {"status": "SUBMITTED", "updatedAt": now_iso(), "updatedBy": "Sistem (rollback opname rusak)"},
                     "$unset": {"approvedAt": "", "approvedBy": "", "approvalNote": "", "adjustmentOperationId": ""}},
                )
            if history_saved:
                await db.consignment_operation_history.delete_many({"operationId": operation_id})
            for applied in reversed(applied_balances):
                if applied["mode"] == "UPDATE":
                    await db.consignment_damaged_balances.update_one(
                        applied["filter"],
                        {"$inc": {"qty": -_n(applied["difference"])}, "$set": {"updatedAt": now_iso(), "updatedBy": "Sistem (rollback opname rusak)"}},
                    )
                else:
                    await db.consignment_damaged_balances.delete_one({**applied["filter"], "id": applied["id"]})
            if inserted_events:
                await db.consignment_damaged_movements.delete_many({"eventKey": {"$in": inserted_events}})
            raise

    keys = lock_keys(
        [f"consignment-damaged-opname:{opname_id}", f"consignment-damaged-opname-active:{destination}"],
        (f"consignment-damaged:{destination}:{product_id}:{channel}" for product_id, channel in affected),
    )
    return await idempotent_operation(
        request,
        user,
        f"consignment-damaged-opname-approve:{opname_id}",
        keys,
        action,
    )


@router.post("/consignment-damaged-opnames/{opname_id}/reject")
async def reject_consignment_damaged_opname(
    opname_id: str,
    body: DamagedOpnameDecision,
    request: Request,
    user: dict = Depends(require_operational_approval),
):
    opname = await db.consignment_damaged_opnames.find_one({"id": opname_id}, {"_id": 0})
    if not opname:
        raise HTTPException(status_code=404, detail="Stock opname barang rusak tidak ditemukan")
    destination = str(opname.get("destination") or "")

    async def action():
        now = now_iso()
        result = await db.consignment_damaged_opnames.update_one(
            {"id": opname_id, "status": "SUBMITTED"},
            {"$set": {
                "status": "REJECTED",
                "rejectedAt": now,
                "rejectedBy": user.get("name", ""),
                "rejectionNote": body.note.strip(),
                "updatedAt": now,
                "updatedBy": user.get("name", ""),
            }},
        )
        if result.matched_count == 0:
            raise HTTPException(status_code=409, detail="Hanya opname barang rusak SUBMITTED yang dapat ditolak")
        return await db.consignment_damaged_opnames.find_one({"id": opname_id}, {"_id": 0})

    return await idempotent_operation(
        request,
        user,
        f"consignment-damaged-opname-reject:{opname_id}",
        [f"consignment-damaged-opname:{opname_id}", f"consignment-damaged-opname-active:{destination}"],
        action,
    )
