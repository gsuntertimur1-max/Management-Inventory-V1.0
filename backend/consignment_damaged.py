from __future__ import annotations

from collections import defaultdict
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from backend.server import db, get_current_user, new_id, now_iso, normalize_channel
from backend.role_four_config import has_role_permission, role_destination
from backend.operational_guards import idempotent_operation

router = APIRouter(prefix="/api")

BAZAR = "Gudang Bazar"
ECOM = "Gudang E-commerce"
DESTINATIONS = {BAZAR, ECOM}
DAMAGED_LOCATIONS = {
    BAZAR: "Area Barang Rusak Bazar",
    ECOM: "Area Barang Rusak E-commerce",
}
EPS = 1e-9


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
