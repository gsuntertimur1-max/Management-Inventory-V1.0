from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends

from backend.server import db, get_current_user, new_id, now_iso

router = APIRouter(prefix="/api")
EPS = 1e-9


def _n(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def lot_sort_key(lot: dict):
    exp = str(lot.get("exp") or "").strip()
    # FEFO: dated lots first, then undated lots in receiving order.
    return (0 if exp else 1, exp or "9999-12-31", str(lot.get("receivedAt") or ""), str(lot.get("id") or ""))


def expiry_status(exp: str) -> str:
    text = str(exp or "").strip()
    if not text:
        return "TANPA_EXPIRED"
    try:
        expiry = datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return "TANGGAL_INVALID"
    days = (expiry - date.today()).days
    if days < 0:
        return "EXPIRED"
    if days <= 30:
        return "LE_30_HARI"
    if days <= 90:
        return "LE_90_HARI"
    return "AMAN"


async def ensure_stack_lot_indexes() -> None:
    await db.stack_lots.create_index("sourceTransactionId", unique=True, sparse=True, name="stack_lot_source_tx_unique")
    await db.stack_lots.create_index([("productId", 1), ("stackCode", 1), ("exp", 1), ("receivedAt", 1)], name="stack_lot_fefo")
    await db.stack_lots.create_index([("remainingQty", 1), ("exp", 1)], name="stack_lot_remaining_exp")
    await db.stack_lot_movements.create_index([("loadId", 1), ("time", -1)], name="lot_movement_load")
    await db.stack_lot_movements.create_index([("lotId", 1), ("time", -1)], name="lot_movement_lot")


async def record_receipt_lots(body, result: dict) -> None:
    """Create one tracked lot for every good receipt transaction placed on a stack.

    This is idempotent by sourceTransactionId, so a retry through the receipt
    idempotency wrapper cannot create a duplicate lot.
    """
    transactions = result.get("transactions") or []
    received_at = now_iso()
    for txn in transactions:
        if str(txn.get("type") or "") != "MASUK" or str(txn.get("kondisi") or "").upper() != "BAIK":
            continue
        qty = _n(txn.get("good_change", txn.get("change")))
        stack_code = str(txn.get("stackCode") or txn.get("receipt_location") or "").strip().upper()
        source_tx = str(txn.get("id") or "")
        product_id = str(txn.get("product_id") or "")
        if qty <= EPS or not stack_code or not source_tx or not product_id:
            continue
        lot_code = f"LOT-{received_at[:10].replace('-', '')}-{source_tx[:8].upper()}"
        doc = {
            "id": new_id(),
            "lotCode": lot_code,
            "productId": product_id,
            "sku": txn.get("sku", ""),
            "product": txn.get("product", ""),
            "stackCode": stack_code,
            "channel": txn.get("channel", "KOM"),
            "sourceTransactionId": source_tx,
            "operationId": txn.get("operation_id", ""),
            "sourceRef": txn.get("ref", ""),
            "poNo": txn.get("po_no", ""),
            "receivedAt": txn.get("time") or received_at,
            "exp": txn.get("exp", ""),
            "originalQty": qty,
            "remainingQty": qty,
            "unit": txn.get("unit", ""),
            "status": "AKTIF",
            "createdAt": received_at,
        }
        await db.stack_lots.update_one(
            {"sourceTransactionId": source_tx},
            {"$setOnInsert": doc},
            upsert=True,
        )


async def consume_stack_lots_for_outbound(load: dict) -> dict:
    """Consume tracked stack lots in FEFO order after a successful good outbound.

    Older stock may not have lot history. Such quantity is recorded as
    UNTRACKED_LEGACY instead of inventing a batch/expired date.
    """
    if str(load.get("kondisi") or "BAIK").upper() != "BAIK":
        return {"tracked": 0.0, "untracked": 0.0}

    load_id = str(load.get("id") or "")
    if not load_id:
        return {"tracked": 0.0, "untracked": 0.0}
    if await db.stack_lot_movements.find_one({"loadId": load_id, "movementType": {"$in": ["OUTBOUND_FEFO", "OUTBOUND_UNTRACKED"]}}, {"_id": 1}):
        movements = await db.stack_lot_movements.find({"loadId": load_id}, {"_id": 0, "qty": 1, "movementType": 1}).to_list(10000)
        return {
            "tracked": sum(abs(_n(row.get("qty"))) for row in movements if row.get("movementType") == "OUTBOUND_FEFO"),
            "untracked": sum(abs(_n(row.get("qty"))) for row in movements if row.get("movementType") == "OUTBOUND_UNTRACKED"),
        }

    now = now_iso()
    tracked_total = untracked_total = 0.0
    for item in load.get("items", []):
        needed = _n(item.get("qty"))
        if needed <= EPS:
            continue
        product_id = str(item.get("productId") or "")
        stack_code = str(item.get("stackCode") or "").strip().upper()
        if not product_id or not stack_code:
            untracked_total += needed
            await db.stack_lot_movements.insert_one({
                "id": new_id(), "time": now, "loadId": load_id, "lotId": "", "lotCode": "",
                "movementType": "OUTBOUND_UNTRACKED", "productId": product_id,
                "sku": item.get("sku", ""), "product": item.get("name", ""), "stackCode": stack_code,
                "sourceDocument": item.get("documentNo") or load.get("ref", ""), "qty": -needed,
                "unit": item.get("unit", ""), "note": "Stok keluar belum memiliki subledger lot historis",
            })
            continue

        lots = await db.stack_lots.find(
            {"productId": product_id, "stackCode": stack_code, "remainingQty": {"$gt": EPS}},
            {"_id": 0},
        ).to_list(10000)
        lots.sort(key=lot_sort_key)
        for lot in lots:
            if needed <= EPS:
                break
            available = _n(lot.get("remainingQty"))
            if available <= EPS:
                continue
            take = min(available, needed)
            result = await db.stack_lots.update_one(
                {"id": lot["id"], "remainingQty": {"$gte": take - EPS}},
                {"$inc": {"remainingQty": -take}, "$set": {"updatedAt": now}},
            )
            if result.matched_count == 0:
                continue
            remaining = max(available - take, 0.0)
            if remaining <= EPS:
                await db.stack_lots.update_one({"id": lot["id"]}, {"$set": {"remainingQty": 0.0, "status": "HABIS", "updatedAt": now}})
            await db.stack_lot_movements.insert_one({
                "id": new_id(), "time": now, "loadId": load_id,
                "lotId": lot["id"], "lotCode": lot.get("lotCode", ""),
                "movementType": "OUTBOUND_FEFO", "productId": product_id,
                "sku": item.get("sku", ""), "product": item.get("name", ""), "stackCode": stack_code,
                "sourceDocument": item.get("documentNo") or load.get("ref", ""),
                "qty": -take, "unit": item.get("unit", ""), "exp": lot.get("exp", ""),
            })
            tracked_total += take
            needed -= take

        if needed > EPS:
            untracked_total += needed
            await db.stack_lot_movements.insert_one({
                "id": new_id(), "time": now, "loadId": load_id, "lotId": "", "lotCode": "",
                "movementType": "OUTBOUND_UNTRACKED", "productId": product_id,
                "sku": item.get("sku", ""), "product": item.get("name", ""), "stackCode": stack_code,
                "sourceDocument": item.get("documentNo") or load.get("ref", ""),
                "qty": -needed, "unit": item.get("unit", ""),
                "note": "Sisa pengeluaran berasal dari stok legacy/belum memiliki lot terlacak",
            })

    return {"tracked": tracked_total, "untracked": untracked_total}


@router.get("/stack-lots")
async def list_stack_lots(productId: str = "", stackCode: str = "", includeEmpty: bool = False, user: dict = Depends(get_current_user)):
    query = {}
    if productId.strip():
        query["productId"] = productId.strip()
    if stackCode.strip():
        query["stackCode"] = stackCode.strip().upper()
    if not includeEmpty:
        query["remainingQty"] = {"$gt": EPS}
    lots = await db.stack_lots.find(query, {"_id": 0}).to_list(20000)
    lots.sort(key=lot_sort_key)
    for lot in lots:
        lot["expiryStatus"] = expiry_status(lot.get("exp", ""))
    return lots


@router.get("/fefo-recommendations")
async def fefo_recommendations(user: dict = Depends(get_current_user)):
    lots = await db.stack_lots.find({"remainingQty": {"$gt": EPS}}, {"_id": 0}).to_list(50000)
    lots.sort(key=lot_sort_key)
    by_product: dict[str, list[dict]] = defaultdict(list)
    for lot in lots:
        lot["expiryStatus"] = expiry_status(lot.get("exp", ""))
        by_product[str(lot.get("productId") or "")].append(lot)

    allocations = await db.stack_allocations.find({}, {"_id": 0, "productId": 1, "primaryQty": 1}).to_list(50000)
    stack_totals = defaultdict(float)
    for allocation in allocations:
        stack_totals[str(allocation.get("productId") or "")] += _n(allocation.get("primaryQty"))

    result = []
    for product_id, product_lots in by_product.items():
        tracked = sum(_n(lot.get("remainingQty")) for lot in product_lots)
        stack_qty = stack_totals.get(product_id, 0.0)
        result.append({
            "productId": product_id,
            "sku": product_lots[0].get("sku", ""),
            "product": product_lots[0].get("product", ""),
            "unit": product_lots[0].get("unit", ""),
            "stackQty": stack_qty,
            "trackedQty": tracked,
            "untrackedQty": max(stack_qty - tracked, 0.0),
            "coveragePct": (tracked / stack_qty * 100) if stack_qty > EPS else 100.0,
            "nextLot": product_lots[0],
            "lots": product_lots[:20],
        })
    result.sort(key=lambda row: lot_sort_key(row.get("nextLot") or {}))
    return result
