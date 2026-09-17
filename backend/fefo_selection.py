from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException

from backend.server import db, get_current_user
from backend.stack_lots import EPS, _n, expiry_status, lot_sort_key

router = APIRouter(prefix="/api")


def build_fefo_pick_guide(product_id: str, allocations: list[dict], lots: list[dict]) -> dict:
    stack_qty = defaultdict(float)
    stack_meta = {}
    for allocation in allocations:
        code = str(allocation.get("stackCode") or "").strip().upper()
        if not code:
            continue
        qty = _n(allocation.get("primaryQty"))
        if qty <= EPS:
            continue
        stack_qty[code] += qty
        stack_meta.setdefault(code, {
            "stackCode": code,
            "unit": allocation.get("unit", ""),
            "product": allocation.get("productName", ""),
            "sku": allocation.get("sku", ""),
        })

    lots_by_stack: dict[str, list[dict]] = defaultdict(list)
    for raw in lots:
        code = str(raw.get("stackCode") or "").strip().upper()
        if not code or _n(raw.get("remainingQty")) <= EPS or str(raw.get("status") or "").upper() == "DIBATALKAN":
            continue
        lot = dict(raw)
        lot["stackCode"] = code
        lot["expiryStatus"] = expiry_status(lot.get("exp", ""))
        lots_by_stack[code].append(lot)

    rows = []
    for code in sorted(stack_qty):
        stack_lots = sorted(lots_by_stack.get(code, []), key=lot_sort_key)
        tracked = sum(_n(lot.get("remainingQty")) for lot in stack_lots)
        physical = stack_qty[code]
        row = {
            **stack_meta.get(code, {}),
            "stackCode": code,
            "stackQty": physical,
            "trackedQty": tracked,
            "untrackedQty": max(physical - tracked, 0.0),
            "overtrackedQty": max(tracked - physical, 0.0),
            "coveragePct": (tracked / physical * 100) if physical > EPS else 100.0,
            "nextLot": stack_lots[0] if stack_lots else None,
            "activeLotCount": len(stack_lots),
        }
        rows.append(row)

    integrity_error = any(row["overtrackedQty"] > EPS for row in rows)
    legacy_rows = [row for row in rows if row["untrackedQty"] > EPS]
    tracked_rows = [row for row in rows if row.get("nextLot")]

    if integrity_error:
        recommended = []
        mode = "INTEGRITY_ERROR"
        reason = "Coverage lot melebihi stok tumpukan. Perbaiki Kontrol Integritas sebelum menjadikan FEFO sebagai acuan wajib."
    elif legacy_rows:
        recommended = [row["stackCode"] for row in sorted(legacy_rows, key=lambda row: row["stackCode"])]
        mode = "LEGACY_FIRST"
        reason = "Stok legacy/untracked diprioritaskan untuk verifikasi/pengeluaran sebelum lot bernama dikurangi."
    elif tracked_rows:
        ordered = sorted(tracked_rows, key=lambda row: (lot_sort_key(row["nextLot"]), row["stackCode"]))
        recommended = [ordered[0]["stackCode"]]
        mode = "FEFO_TRACKED"
        reason = "Semua stok telah terlacak lot; pilih tumpukan dengan lot kedaluwarsa terdekat."
    else:
        recommended = [row["stackCode"] for row in rows]
        mode = "LEGACY_ONLY" if rows else "NO_STOCK"
        reason = "Belum ada lot terlacak; pilih tumpukan stok fisik yang tersedia."

    priority = {code: index for index, code in enumerate(recommended)}
    rows.sort(key=lambda row: (
        0 if row["stackCode"] in priority else 1,
        priority.get(row["stackCode"], 9999),
        lot_sort_key(row.get("nextLot") or {}),
        row["stackCode"],
    ))
    return {
        "productId": product_id,
        "policy": "CONSERVATIVE_LEGACY_FIRST",
        "mode": mode,
        "reason": reason,
        "recommendedStacks": recommended,
        "requiresManualVerification": mode in {"LEGACY_FIRST", "LEGACY_ONLY", "INTEGRITY_ERROR"},
        "stacks": rows,
    }


def selection_requires_reason(guide: dict, stack_code: str) -> bool:
    selected = str(stack_code or "").strip().upper()
    recommended = [str(code or "").strip().upper() for code in guide.get("recommendedStacks", []) if str(code or "").strip()]
    return bool(selected and recommended and selected not in recommended)


async def get_fefo_pick_guide(product_id: str) -> dict:
    product = await db.products.find_one({"id": product_id}, {"_id": 0, "id": 1})
    if not product:
        raise HTTPException(status_code=404, detail="Produk tidak ditemukan")
    allocations = await db.stack_allocations.find(
        {"productId": product_id, "primaryQty": {"$gt": EPS}},
        {"_id": 0},
    ).to_list(10000)
    lots = await db.stack_lots.find(
        {"productId": product_id, "remainingQty": {"$gt": EPS}, "status": {"$ne": "DIBATALKAN"}},
        {"_id": 0},
    ).to_list(10000)
    return build_fefo_pick_guide(product_id, allocations, lots)


@router.get("/fefo-pick-guide/{product_id}")
async def fefo_pick_guide(product_id: str, user: dict = Depends(get_current_user)):
    return await get_fefo_pick_guide(product_id)
