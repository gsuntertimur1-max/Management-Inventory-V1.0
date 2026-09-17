from __future__ import annotations

import re
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend.server import db, new_id, now_iso, require_write
from backend.operational_guards import idempotent_operation, product_lock_keys
from backend.stack_allocations import valid_stack_codes, record_stack_history
from backend.stack_lots import EPS, _n, lot_sort_key
from backend.stack_reservations import available_stack_qty

router = APIRouter(prefix="/api")


class StockTransferInput(BaseModel):
    productId: str
    sourceStackCode: str
    destinationStackCode: str
    qty: float = Field(gt=0)
    lotId: str = ""
    note: str = ""


def split_transfer_qty(physical_qty: float, tracked_qty: float, requested_qty: float) -> tuple[float, float]:
    """Mutasi tanpa lot eksplisit memakai stok legacy/untracked lebih dulu.

    Ini konsisten dengan kebijakan FEFO legacy-first: sistem tidak menebak lot untuk stok
    yang identitas batch/expired-nya belum diketahui. Setelah saldo untracked habis,
    sisa mutasi diambil dari lot terlacak menurut FEFO.
    """
    physical = max(_n(physical_qty), 0.0)
    tracked = max(min(_n(tracked_qty), physical), 0.0)
    requested = max(_n(requested_qty), 0.0)
    untracked_available = max(physical - tracked, 0.0)
    untracked_take = min(requested, untracked_available)
    return untracked_take, max(requested - untracked_take, 0.0)


async def _active_lots(product_id: str, stack_code: str) -> list[dict]:
    rows = await db.stack_lots.find(
        {
            "productId": product_id,
            "stackCode": stack_code,
            "remainingQty": {"$gt": EPS},
            "status": {"$nin": ["DIBATALKAN"]},
        },
        {"_id": 0},
    ).to_list(10000)
    rows.sort(key=lot_sort_key)
    return rows


def _allocation_values(allocation: dict, qty: float) -> dict:
    per_secondary = _n(allocation.get("secondaryQty"))
    remaining = max(_n(qty), 0.0)
    return {
        "primaryQty": remaining,
        "secondaryCount": int(remaining // per_secondary) if per_secondary > 0 else 0,
        "primaryRemainder": remaining % per_secondary if per_secondary > 0 else remaining,
        "length": 0,
        "width": 0,
        "height": 0,
        "arrangements": [],
        "extraSecondary": 0,
        "extraPrimary": remaining % per_secondary if per_secondary > 0 else remaining,
        "arrangementAdjusted": True,
        "updatedAt": now_iso(),
    }


async def _upsert_destination_allocation(source: dict, destination: str, qty: float, operator: str) -> dict:
    existing = await db.stack_allocations.find_one(
        {"productId": source["productId"], "stackCode": destination}, {"_id": 0}
    )
    if existing:
        total = _n(existing.get("primaryQty")) + qty
        changes = _allocation_values(existing, total)
        await db.stack_allocations.update_one({"id": existing["id"]}, {"$set": changes})
        updated = {**existing, **changes}
        await record_stack_history("MUTASI_MASUK", updated, operator)
        return updated

    doc = {
        **{k: v for k, v in source.items() if k not in {"_id", "id", "stackCode", "warehouse", "zone", "createdAt", "updatedAt"}},
        "id": new_id(),
        "stackCode": destination,
        "warehouse": destination.split("/", 1)[0],
        "zone": re.sub(r"\d", "", destination.split("/", 1)[1]),
        "createdAt": now_iso(),
        "note": f"Mutasi dari {source.get('stackCode', '')}",
    }
    doc.update(_allocation_values(source, qty))
    await db.stack_allocations.insert_one(dict(doc))
    await record_stack_history("MUTASI_MASUK", doc, operator)
    return doc


async def _decrease_source_allocation(source: dict, qty: float, operator: str) -> dict | None:
    remaining = _n(source.get("primaryQty")) - qty
    if remaining <= EPS:
        await db.stack_allocations.delete_one({"id": source["id"]})
        await record_stack_history("MUTASI_KELUAR_HABIS", {**source, "primaryQty": 0.0}, operator)
        return None
    changes = _allocation_values(source, remaining)
    await db.stack_allocations.update_one({"id": source["id"]}, {"$set": changes})
    updated = {**source, **changes}
    await record_stack_history("MUTASI_KELUAR", updated, operator)
    return updated


async def _move_tracked_lot(lot: dict, take: float, destination: str, mutation_id: str, operator: str) -> dict:
    before = _n(lot.get("remainingQty"))
    after = max(before - take, 0.0)
    now = now_iso()
    if after <= EPS:
        await db.stack_lots.update_one(
            {"id": lot["id"], "remainingQty": {"$gte": take - EPS}},
            {"$set": {"stackCode": destination, "remainingQty": take, "status": "AKTIF", "updatedAt": now, "lastMutationId": mutation_id}},
        )
        target_lot_id = lot["id"]
    else:
        result = await db.stack_lots.update_one(
            {"id": lot["id"], "remainingQty": {"$gte": take - EPS}},
            {"$inc": {"remainingQty": -take}, "$set": {"updatedAt": now, "lastMutationId": mutation_id}},
        )
        if result.matched_count == 0:
            raise HTTPException(status_code=409, detail="Saldo lot berubah saat mutasi. Muat ulang lalu coba kembali.")
        target_lot_id = new_id()
        child = {
            **{k: v for k, v in lot.items() if k not in {"_id", "id", "sourceTransactionId", "originalQty", "remainingQty", "stackCode", "status", "createdAt", "updatedAt"}},
            "id": target_lot_id,
            "parentLotId": lot.get("parentLotId") or lot.get("id"),
            "sourceLotId": lot.get("id"),
            "mutationId": mutation_id,
            "stackCode": destination,
            "originalQty": take,
            "remainingQty": take,
            "status": "AKTIF",
            "createdAt": now,
            "updatedAt": now,
        }
        await db.stack_lots.insert_one(child)

    common = {
        "time": now,
        "loadId": "",
        "mutationId": mutation_id,
        "lotId": lot.get("id", ""),
        "targetLotId": target_lot_id,
        "lotCode": lot.get("lotCode", ""),
        "productId": lot.get("productId", ""),
        "sku": lot.get("sku", ""),
        "product": lot.get("product", ""),
        "unit": lot.get("unit", ""),
        "exp": lot.get("exp", ""),
        "operator": operator,
    }
    await db.stack_lot_movements.insert_many([
        {**common, "id": new_id(), "movementType": "MUTATION_OUT", "stackCode": lot.get("stackCode", ""), "destinationStackCode": destination, "qty": -take},
        {**common, "id": new_id(), "movementType": "MUTATION_IN", "stackCode": destination, "sourceStackCode": lot.get("stackCode", ""), "qty": take},
    ])
    return {"lotCode": lot.get("lotCode", ""), "lotId": lot.get("id", ""), "targetLotId": target_lot_id, "qty": take, "exp": lot.get("exp", "")}


async def _execute_transfer(body: StockTransferInput, user: dict) -> dict:
    source = body.sourceStackCode.strip().upper()
    destination = body.destinationStackCode.strip().upper()
    product_id = body.productId.strip()
    qty = float(body.qty)
    if source == destination:
        raise HTTPException(status_code=400, detail="Tumpukan asal dan tujuan harus berbeda")
    valid = await valid_stack_codes()
    if source not in valid or destination not in valid:
        raise HTTPException(status_code=400, detail="Kode tumpukan asal/tujuan tidak valid")

    product = await db.products.find_one({"id": product_id}, {"_id": 0})
    if not product:
        raise HTTPException(status_code=404, detail="Produk tidak ditemukan")
    allocation = await db.stack_allocations.find_one({"productId": product_id, "stackCode": source}, {"_id": 0})
    if not allocation:
        raise HTTPException(status_code=404, detail=f"Produk tidak ditemukan pada tumpukan {source}")

    physical = _n(allocation.get("primaryQty"))
    reserved, available = await available_stack_qty(product_id, source, physical)
    if qty > available + EPS:
        raise HTTPException(
            status_code=409,
            detail=f"Stok tersedia {source} hanya {available:g} {product.get('unit', '')}; {reserved:g} sedang direservasi untuk antrean outbound.",
        )

    lots = await _active_lots(product_id, source)
    tracked_total = sum(_n(row.get("remainingQty")) for row in lots)
    selected_lot = None
    if body.lotId.strip():
        selected_lot = next((row for row in lots if str(row.get("id")) == body.lotId.strip()), None)
        if not selected_lot:
            raise HTTPException(status_code=400, detail="Lot yang dipilih tidak aktif pada tumpukan asal")
        if qty > _n(selected_lot.get("remainingQty")) + EPS:
            raise HTTPException(status_code=400, detail="Jumlah mutasi melebihi saldo lot yang dipilih")
        untracked_take, tracked_needed = 0.0, qty
    else:
        untracked_take, tracked_needed = split_transfer_qty(physical, tracked_total, qty)

    lot_plan: list[tuple[dict, float]] = []
    if selected_lot:
        lot_plan.append((selected_lot, qty))
    else:
        needed = tracked_needed
        for lot in lots:
            if needed <= EPS:
                break
            take = min(_n(lot.get("remainingQty")), needed)
            if take > EPS:
                lot_plan.append((lot, take))
                needed -= take
        if needed > EPS:
            # Physical stock may legitimately contain legacy/untracked quantity. If the tracked
            # remainder is insufficient because data changed after planning, fail before mutation.
            raise HTTPException(status_code=409, detail="Saldo lot berubah saat mutasi. Muat ulang lalu coba kembali.")

    mutation_id = new_id()
    operator = user.get("name") or user.get("username") or "Operator"

    await _decrease_source_allocation(allocation, qty, operator)
    target = await _upsert_destination_allocation(allocation, destination, qty, operator)

    moved_lots = []
    for lot, take in lot_plan:
        moved_lots.append(await _move_tracked_lot(lot, take, destination, mutation_id, operator))

    if untracked_take > EPS:
        now = now_iso()
        base = {
            "time": now, "loadId": "", "mutationId": mutation_id, "lotId": "", "lotCode": "",
            "productId": product_id, "sku": product.get("sku", ""), "product": product.get("name", ""),
            "unit": product.get("unit", ""), "operator": operator,
            "note": "Mutasi stok legacy/untracked; identitas lot tidak ditebak oleh sistem.",
        }
        await db.stack_lot_movements.insert_many([
            {**base, "id": new_id(), "movementType": "MUTATION_UNTRACKED_OUT", "stackCode": source, "destinationStackCode": destination, "qty": -untracked_take},
            {**base, "id": new_id(), "movementType": "MUTATION_UNTRACKED_IN", "stackCode": destination, "sourceStackCode": source, "qty": untracked_take},
        ])

    transfer = {
        "id": mutation_id,
        "time": now_iso(),
        "productId": product_id,
        "sku": product.get("sku", ""),
        "product": product.get("name", ""),
        "unit": product.get("unit", ""),
        "qty": qty,
        "sourceStackCode": source,
        "destinationStackCode": destination,
        "scope": "DALAM_GBB" if source.split("/", 1)[0] == destination.split("/", 1)[0] else "ANTAR_GBB",
        "reservedAtSource": reserved,
        "untrackedQty": untracked_take,
        "trackedQty": sum(item[1] for item in lot_plan),
        "lots": moved_lots,
        "note": body.note.strip(),
        "operator": operator,
    }
    await db.stock_transfers.insert_one(dict(transfer))
    await db.transactions.insert_one({
        "id": new_id(), "time": transfer["time"], "type": "MUTASI", "change": 0, "mutated_qty": qty,
        "product_id": product_id, "product": transfer["product"], "sku": transfer["sku"], "unit": transfer["unit"],
        "from_stack": source, "to_stack": destination, "stackCode": destination, "ref": mutation_id,
        "keterangan": body.note.strip() or f"Mutasi {source} → {destination}", "operator": operator,
    })
    return {**transfer, "destinationAllocation": {k: v for k, v in target.items() if k != "_id"}}


@router.get("/stock-transfers")
async def list_stock_transfers(limit: int = 50, user: dict = Depends(require_write)):
    size = max(1, min(int(limit or 50), 500))
    return await db.stock_transfers.find({}, {"_id": 0}).sort("time", -1).to_list(size)


@router.get("/stock-transfers/availability")
async def transfer_availability(productId: str, stackCode: str, user: dict = Depends(require_write)):
    product_id = productId.strip()
    stack_code = stackCode.strip().upper()
    allocation = await db.stack_allocations.find_one({"productId": product_id, "stackCode": stack_code}, {"_id": 0})
    if not allocation:
        raise HTTPException(status_code=404, detail="Alokasi tumpukan tidak ditemukan")
    physical = _n(allocation.get("primaryQty"))
    reserved, available = await available_stack_qty(product_id, stack_code, physical)
    lots = await _active_lots(product_id, stack_code)
    tracked = sum(_n(row.get("remainingQty")) for row in lots)
    return {
        "physicalQty": physical,
        "reservedQty": reserved,
        "availableQty": available,
        "trackedQty": tracked,
        "untrackedQty": max(physical - tracked, 0.0),
        "lots": [{k: v for k, v in row.items() if k != "_id"} for row in lots],
    }


@router.post("/stock-transfers")
async def create_stock_transfer(body: StockTransferInput, request: Request, user: dict = Depends(require_write)):
    keys = product_lock_keys([body.productId])
    keys.extend([
        f"stack:{body.productId}:{body.sourceStackCode.strip().upper()}",
        f"stack:{body.productId}:{body.destinationStackCode.strip().upper()}",
    ])
    return await idempotent_operation(
        request,
        user,
        "stock-transfer",
        keys,
        lambda: _execute_transfer(body, user),
    )
