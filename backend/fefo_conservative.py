from __future__ import annotations

from collections import defaultdict

from backend.server import db, new_id, now_iso
from backend.operational_guards import operation_guard, product_lock_keys
from backend.stack_lots import EPS, _n, lot_sort_key


def conservative_outbound_split(physical_before: float, tracked_before: float, requested: float) -> tuple[float, float]:
    """Protect identified lots while legacy/untracked stock still exists.

    The subledger must not pretend an outbound came from a named batch when the
    physical stack still contains stock whose batch/expiry identity is unknown.
    Unknown stock is therefore consumed first for accounting purposes. Once the
    unknown balance is exhausted, the remaining request is consumed from
    tracked lots in FEFO order.
    """
    request_qty = max(_n(requested), 0.0)
    untracked_before = max(_n(physical_before) - _n(tracked_before), 0.0)
    untracked = min(request_qty, untracked_before)
    tracked = max(request_qty - untracked, 0.0)
    return untracked, tracked


async def _stack_qty(product_id: str, stack_code: str) -> float:
    rows = await db.stack_allocations.find(
        {"productId": product_id, "stackCode": stack_code},
        {"_id": 0, "primaryQty": 1},
    ).to_list(10000)
    return sum(_n(row.get("primaryQty")) for row in rows)


async def _active_lots(product_id: str, stack_code: str) -> list[dict]:
    lots = await db.stack_lots.find(
        {
            "productId": product_id,
            "stackCode": stack_code,
            "remainingQty": {"$gt": EPS},
            "status": {"$nin": ["DIBATALKAN"]},
        },
        {"_id": 0},
    ).to_list(10000)
    lots.sort(key=lot_sort_key)
    return lots


async def _record_untracked(load: dict, group: dict, qty: float, note: str) -> float:
    if qty <= EPS:
        return 0.0
    await db.stack_lot_movements.insert_one({
        "id": new_id(),
        "time": now_iso(),
        "loadId": str(load.get("id") or ""),
        "lotId": "",
        "lotCode": "",
        "movementType": "OUTBOUND_UNTRACKED",
        "productId": str(group.get("productId") or ""),
        "sku": group.get("sku", ""),
        "product": group.get("product", ""),
        "stackCode": str(group.get("stackCode") or "").strip().upper(),
        "sourceDocument": str(group.get("sourceDocument") or ""),
        "qty": -qty,
        "unit": group.get("unit", ""),
        "note": note,
    })
    return qty


async def _consume_tracked_fefo(load: dict, group: dict, qty: float) -> tuple[float, float]:
    needed = max(_n(qty), 0.0)
    if needed <= EPS:
        return 0.0, 0.0

    product_id = str(group.get("productId") or "")
    stack_code = str(group.get("stackCode") or "").strip().upper()
    if not product_id or not stack_code:
        return 0.0, needed

    tracked = 0.0
    lots = await _active_lots(product_id, stack_code)
    for lot in lots:
        if needed <= EPS:
            break
        available = _n(lot.get("remainingQty"))
        if available <= EPS:
            continue
        take = min(available, needed)
        result = await db.stack_lots.update_one(
            {"id": lot.get("id"), "remainingQty": {"$gte": take - EPS}},
            {"$inc": {"remainingQty": -take}, "$set": {"updatedAt": now_iso()}},
        )
        if result.matched_count == 0:
            continue
        after = max(available - take, 0.0)
        if after <= EPS:
            await db.stack_lots.update_one(
                {"id": lot.get("id")},
                {"$set": {"remainingQty": 0.0, "status": "HABIS", "updatedAt": now_iso()}},
            )
        await db.stack_lot_movements.insert_one({
            "id": new_id(),
            "time": now_iso(),
            "loadId": str(load.get("id") or ""),
            "lotId": lot.get("id", ""),
            "lotCode": lot.get("lotCode", ""),
            "movementType": "OUTBOUND_FEFO",
            "productId": product_id,
            "sku": group.get("sku", ""),
            "product": group.get("product", ""),
            "stackCode": stack_code,
            "sourceDocument": str(group.get("sourceDocument") or ""),
            "qty": -take,
            "unit": group.get("unit", ""),
            "exp": lot.get("exp", ""),
            "note": "FEFO diterapkan setelah saldo legacy/untracked pada tumpukan dianggap habis.",
        })
        tracked += take
        needed -= take
    return tracked, max(needed, 0.0)


def _movement_key(row: dict) -> tuple[str, str, str]:
    return (
        str(row.get("productId") or ""),
        str(row.get("stackCode") or "").strip().upper(),
        str(row.get("sourceDocument") or ""),
    )


def _physical_key(row: dict) -> tuple[str, str]:
    return (
        str(row.get("productId") or ""),
        str(row.get("stackCode") or "").strip().upper(),
    )


async def consume_stack_lots_conservative(load: dict) -> dict:
    """Retry-safe FEFO accounting that preserves identified lots in mixed legacy stacks."""
    if str(load.get("kondisi") or "BAIK").upper() != "BAIK":
        return {"tracked": 0.0, "untracked": 0.0, "legacyProtected": 0.0, "policy": "NOT_APPLICABLE"}

    load_id = str(load.get("id") or "")
    if not load_id:
        return {"tracked": 0.0, "untracked": 0.0, "legacyProtected": 0.0, "policy": "NO_LOAD_ID"}

    grouped: dict[tuple[str, str, str], dict] = {}
    physical_requested: dict[tuple[str, str], float] = defaultdict(float)
    for item in load.get("items", []):
        product_id = str(item.get("productId") or "")
        stack_code = str(item.get("stackCode") or "").strip().upper()
        source_document = str(item.get("documentNo") or load.get("ref") or "")
        key = (product_id, stack_code, source_document)
        row = grouped.setdefault(key, {
            "productId": product_id,
            "stackCode": stack_code,
            "sourceDocument": source_document,
            "sku": item.get("sku", ""),
            "product": item.get("name", ""),
            "unit": item.get("unit", ""),
            "qty": 0.0,
        })
        qty = _n(item.get("qty"))
        row["qty"] += qty
        physical_requested[(product_id, stack_code)] += qty

    previous = await db.stack_lot_movements.find({"loadId": load_id}, {"_id": 0}).to_list(50000)
    processed_exact: dict[tuple[str, str, str], float] = defaultdict(float)
    tracked_done: dict[tuple[str, str], float] = defaultdict(float)
    untracked_done: dict[tuple[str, str], float] = defaultdict(float)
    tracked_total = untracked_total = 0.0
    for movement in previous:
        qty = abs(_n(movement.get("qty")))
        processed_exact[_movement_key(movement)] += qty
        pkey = _physical_key(movement)
        if movement.get("movementType") == "OUTBOUND_FEFO":
            tracked_done[pkey] += qty
            tracked_total += qty
        elif movement.get("movementType") == "OUTBOUND_UNTRACKED":
            untracked_done[pkey] += qty
            untracked_total += qty

    product_ids = sorted({key[0] for key in physical_requested if key[0]})
    legacy_budget: dict[tuple[str, str], float] = {}
    legacy_protected = 0.0

    async with operation_guard(product_lock_keys(product_ids)):
        for pkey, requested in physical_requested.items():
            product_id, stack_code = pkey
            if not product_id or not stack_code:
                legacy_budget[pkey] = max(requested - untracked_done.get(pkey, 0.0), 0.0)
                continue
            current_stack = await _stack_qty(product_id, stack_code)
            lots = await _active_lots(product_id, stack_code)
            tracked_current = sum(_n(lot.get("remainingQty")) for lot in lots)
            tracked_before = tracked_current + tracked_done.get(pkey, 0.0)
            physical_before = current_stack + requested
            untracked_before, _ = conservative_outbound_split(physical_before, tracked_before, requested)
            remaining_budget = max(untracked_before - untracked_done.get(pkey, 0.0), 0.0)
            legacy_budget[pkey] = remaining_budget
            legacy_protected += remaining_budget

        for key, group in grouped.items():
            requested = _n(group.get("qty"))
            already = processed_exact.get(key, 0.0)
            needed = max(requested - already, 0.0)
            if needed <= EPS:
                continue

            pkey = (key[0], key[1])
            legacy_take = min(needed, legacy_budget.get(pkey, 0.0))
            if legacy_take > EPS:
                added = await _record_untracked(
                    load,
                    group,
                    legacy_take,
                    "Stok legacy/untracked diprioritaskan pada subledger agar sistem tidak menebak lot/batch yang keluar.",
                )
                untracked_total += added
                legacy_budget[pkey] = max(legacy_budget.get(pkey, 0.0) - added, 0.0)
                needed -= added

            if needed > EPS:
                tracked, remainder = await _consume_tracked_fefo(load, group, needed)
                tracked_total += tracked
                needed = remainder

            if needed > EPS:
                added = await _record_untracked(
                    load,
                    group,
                    needed,
                    "Saldo lot terlacak tidak mencukupi; sisa pengeluaran dicatat sebagai legacy/untracked untuk menjaga integritas subledger.",
                )
                untracked_total += added

    return {
        "tracked": tracked_total,
        "untracked": untracked_total,
        "legacyProtected": legacy_protected,
        "policy": "CONSERVATIVE_LEGACY_FIRST",
    }
