from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends

from backend.server import db, get_current_user, normalize_channel

router = APIRouter(prefix="/api")
DAMAGED_AREA = "AREA BARANG RUSAK"
EPS = 1e-9


def _n(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def damaged_movement_qty(txn: dict) -> float:
    if "damaged_change" in txn and txn.get("damaged_change") is not None:
        return _n(txn.get("damaged_change"))
    if str(txn.get("kondisi") or "").upper() == "RUSAK":
        return _n(txn.get("change"))
    return 0.0


@router.get("/damaged-stock-area")
async def damaged_stock_area(user: dict = Depends(get_current_user)):
    products = await db.products.find({}, {"_id": 0}).sort("name", 1).to_list(20000)
    claims = await db.supplier_returns.find({}, {"_id": 0}).sort("created_at", -1).to_list(10000)

    claims_by_product: dict[str, list[dict]] = defaultdict(list)
    for claim in claims:
        product_id = str(claim.get("product_id") or claim.get("productId") or "")
        if product_id:
            claims_by_product[product_id].append(claim)

    rows = []
    totals_by_unit: dict[str, float] = defaultdict(float)
    for product in products:
        product_id = str(product.get("id") or "")
        master_damaged = _n(product.get("damaged"))
        channel_stock = product.get("channelStock") or {}
        channel_damaged = sum(_n((channel_stock.get(channel) or {}).get("damaged")) for channel in ("PSO", "KOM"))
        product_claims = claims_by_product.get(product_id, [])
        pending_replacement = 0.0
        returned_to_supplier = 0.0
        for claim in product_claims:
            qty = _n(claim.get("qty"))
            replacement = _n(claim.get("replacement_qty", claim.get("replacementQty", 0)))
            returned_to_supplier += qty
            pending_replacement += max(qty - replacement, 0.0)

        if master_damaged <= EPS and not product_claims:
            continue
        unit = str(product.get("unit") or "")
        totals_by_unit[unit or "Unit"] += master_damaged
        rows.append({
            "productId": product_id,
            "sku": product.get("sku", ""),
            "product": product.get("name", ""),
            "unit": unit,
            "location": DAMAGED_AREA,
            "masterDamaged": master_damaged,
            "channelDamaged": channel_damaged,
            "channelDifference": master_damaged - channel_damaged,
            "defaultChannel": normalize_channel(product.get("channel")),
            "openClaims": sum(1 for claim in product_claims if str(claim.get("status") or "") != "SELESAI_DIGANTI"),
            "returnedToSupplier": returned_to_supplier,
            "pendingReplacement": pending_replacement,
            "claims": product_claims[:20],
            "severity": "ERROR" if abs(master_damaged - channel_damaged) > EPS else "OK",
        })

    recent = await db.transactions.find(
        {"$or": [{"kondisi": "RUSAK"}, {"damaged_change": {"$ne": 0}}]},
        {"_id": 0},
    ).sort("time", -1).to_list(500)
    recent_movements = []
    for txn in recent:
        qty = damaged_movement_qty(txn)
        if abs(qty) <= EPS:
            continue
        recent_movements.append({
            "id": txn.get("id", ""),
            "time": txn.get("time", ""),
            "productId": txn.get("product_id", ""),
            "sku": txn.get("sku", ""),
            "product": txn.get("product", ""),
            "type": txn.get("type", ""),
            "documentType": txn.get("document_type", ""),
            "ref": txn.get("ref", ""),
            "qty": qty,
            "unit": txn.get("unit", ""),
            "sourceStackCode": txn.get("sourceStackCode") or txn.get("stackCode", ""),
            "operator": txn.get("operator", ""),
            "note": txn.get("keterangan", ""),
            "location": txn.get("damaged_location") or txn.get("receipt_location") or DAMAGED_AREA,
        })
        if len(recent_movements) >= 100:
            break

    return {
        "location": DAMAGED_AREA,
        "summaryByUnit": [{"unit": unit, "qty": qty} for unit, qty in sorted(totals_by_unit.items())],
        "products": rows,
        "recentMovements": recent_movements,
        "summary": {
            "productsInArea": sum(1 for row in rows if _n(row.get("masterDamaged")) > EPS),
            "openSupplierClaims": sum(int(row.get("openClaims") or 0) for row in rows),
            "productsWithChannelMismatch": sum(1 for row in rows if row.get("severity") == "ERROR"),
        },
    }
