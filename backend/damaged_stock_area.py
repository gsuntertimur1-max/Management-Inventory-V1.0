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


def _claim_replacement(claim: dict) -> float:
    return _n(claim.get("replacement_qty", claim.get("replacementQty", 0)))


def _claim_is_po_receipt(claim: dict) -> bool:
    source_type = str(claim.get("damage_source_type") or "").strip().upper()
    if source_type == "PO_RECEIPT":
        return True
    if source_type == "TEMUAN":
        return False
    return bool(str(claim.get("po_no") or "").strip())


@router.get("/damaged-stock-area")
async def damaged_stock_area(user: dict = Depends(get_current_user)):
    products = await db.products.find({}, {"_id": 0}).sort("name", 1).to_list(20000)
    claims = await db.supplier_returns.find({}, {"_id": 0}).sort("created_at", -1).to_list(10000)
    inbound_loads = await db.inbound_loads.find(
        {"operationId": {"$nin": ["", None]}},
        {"_id": 0, "operationId": 1, "loadNo": 1, "polisi": 1, "driver": 1, "completedAt": 1},
    ).to_list(10000)
    purchase_orders = await db.purchase_orders.find(
        {},
        {"_id": 0, "id": 1, "no": 1, "supplier": 1},
    ).to_list(10000)

    products_by_id = {str(row.get("id") or ""): row for row in products}
    products_by_sku = {str(row.get("sku") or ""): row for row in products if row.get("sku")}
    loads_by_operation = {str(row.get("operationId") or ""): row for row in inbound_loads if row.get("operationId")}
    po_by_no = {str(row.get("no") or ""): row for row in purchase_orders if row.get("no")}

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
            replacement = _claim_replacement(claim)
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

    # Buku pembantu 1: rusak yang memang sudah tercatat saat penerimaan PO.
    receipt_damage_rows = await db.transactions.find(
        {
            "type": "MASUK",
            "kondisi": "RUSAK",
            "po_no": {"$nin": ["", None]},
            "voided": {"$ne": True},
        },
        {"_id": 0},
    ).sort("time", 1).to_list(20000)

    po_item_buckets: dict[tuple[str, str], dict] = {}
    for txn in receipt_damage_rows:
        po_no = str(txn.get("po_no") or "").strip()
        product = (
            products_by_id.get(str(txn.get("product_id") or ""))
            or products_by_sku.get(str(txn.get("sku") or ""))
            or {}
        )
        product_id = str(product.get("id") or txn.get("product_id") or txn.get("sku") or txn.get("product") or "")
        if not po_no or not product_id:
            continue
        key = (po_no, product_id)
        bucket = po_item_buckets.setdefault(key, {
            "poNo": po_no,
            "poId": str(txn.get("po_id") or (po_by_no.get(po_no) or {}).get("id") or ""),
            "supplier": str((po_by_no.get(po_no) or {}).get("supplier") or txn.get("penerima") or ""),
            "productId": str(product.get("id") or txn.get("product_id") or ""),
            "sku": str(product.get("sku") or txn.get("sku") or ""),
            "product": str(product.get("name") or txn.get("product") or ""),
            "unit": str(product.get("unit") or txn.get("unit") or ""),
            "channel": str(txn.get("channel") or normalize_channel(product.get("channel"))),
            "totalDamaged": 0.0,
            "details": {},
            "claims": [],
        })
        qty = max(damaged_movement_qty(txn), 0.0)
        bucket["totalDamaged"] += qty
        operation_id = str(txn.get("operation_id") or "")
        load = loads_by_operation.get(operation_id) or {}
        detail = bucket["details"].setdefault(operation_id or str(txn.get("id") or ""), {
            "operationId": operation_id,
            "time": txn.get("time", ""),
            "loadNo": load.get("loadNo", ""),
            "polisi": load.get("polisi") or txn.get("polisi", ""),
            "driver": load.get("driver", ""),
            "qty": 0.0,
            "unit": bucket["unit"],
            "operator": txn.get("operator", ""),
        })
        detail["qty"] += qty

    for claim in claims:
        if not _claim_is_po_receipt(claim):
            continue
        po_no = str(claim.get("po_no") or "").strip()
        product_id = str(claim.get("product_id") or "")
        if not po_no or not product_id:
            continue
        key = (po_no, product_id)
        bucket = po_item_buckets.get(key)
        if not bucket:
            product = products_by_id.get(product_id) or {}
            bucket = po_item_buckets.setdefault(key, {
                "poNo": po_no,
                "poId": str(claim.get("po_id") or (po_by_no.get(po_no) or {}).get("id") or ""),
                "supplier": str(claim.get("supplier") or (po_by_no.get(po_no) or {}).get("supplier") or ""),
                "productId": product_id,
                "sku": str(product.get("sku") or claim.get("sku") or ""),
                "product": str(product.get("name") or claim.get("product") or ""),
                "unit": str(product.get("unit") or claim.get("unit") or ""),
                "channel": str(claim.get("channel") or normalize_channel(product.get("channel"))),
                "totalDamaged": 0.0,
                "details": {},
                "claims": [],
            })
        bucket["claims"].append(claim)

    po_groups: dict[str, dict] = {}
    for bucket in po_item_buckets.values():
        returned = sum(_n(claim.get("qty")) for claim in bucket["claims"])
        replacement = sum(_claim_replacement(claim) for claim in bucket["claims"])
        item = {
            **{key: value for key, value in bucket.items() if key not in {"details", "claims"}},
            "returnedQty": returned,
            "replacementQty": replacement,
            "availableForReturn": max(_n(bucket["totalDamaged"]) - returned, 0.0),
            "pendingReplacement": max(returned - replacement, 0.0),
            "details": sorted(bucket["details"].values(), key=lambda row: str(row.get("time") or "")),
            "claims": bucket["claims"],
        }
        group = po_groups.setdefault(bucket["poNo"], {
            "poNo": bucket["poNo"],
            "poId": bucket["poId"],
            "supplier": bucket["supplier"],
            "items": [],
        })
        if not group.get("supplier") and bucket.get("supplier"):
            group["supplier"] = bucket["supplier"]
        group["items"].append(item)

    po_damage_groups = []
    for group in po_groups.values():
        group["items"] = sorted(group["items"], key=lambda row: (str(row.get("product") or ""), str(row.get("sku") or "")))
        group["hasAvailableForReturn"] = any(_n(row.get("availableForReturn")) > EPS for row in group["items"])
        group["hasPendingReplacement"] = any(_n(row.get("pendingReplacement")) > EPS for row in group["items"])
        po_damage_groups.append(group)
    po_damage_groups.sort(key=lambda row: str(row.get("poNo") or ""), reverse=True)

    # Buku pembantu 2: temuan kerusakan setelah stok sudah tersimpan.
    discovery_rows = await db.transactions.find(
        {
            "document_type": "TEMUAN_RUSAK",
            "kondisi": "RUSAK",
            "voided": {"$ne": True},
        },
        {"_id": 0},
    ).sort("time", -1).to_list(10000)
    discovery_groups = []
    for txn in discovery_rows:
        operation_id = str(txn.get("operation_id") or "")
        product = (
            products_by_id.get(str(txn.get("product_id") or ""))
            or products_by_sku.get(str(txn.get("sku") or ""))
            or {}
        )
        product_id = str(product.get("id") or txn.get("product_id") or "")
        linked_claims = [
            claim for claim in claims
            if str(claim.get("source_damage_operation_id") or "") == operation_id
            and str(claim.get("product_id") or "") == product_id
            and not _claim_is_po_receipt(claim)
        ]
        damaged_qty = max(damaged_movement_qty(txn), 0.0)
        returned = sum(_n(claim.get("qty")) for claim in linked_claims)
        replacement = sum(_claim_replacement(claim) for claim in linked_claims)
        discovery_groups.append({
            "operationId": operation_id,
            "time": txn.get("time", ""),
            "referenceNo": txn.get("ref", ""),
            "productId": product_id,
            "sku": product.get("sku") or txn.get("sku", ""),
            "product": product.get("name") or txn.get("product", ""),
            "unit": product.get("unit") or txn.get("unit", ""),
            "channel": txn.get("channel") or normalize_channel(product.get("channel")),
            "stackCode": txn.get("stackCode", ""),
            "cause": txn.get("cause", ""),
            "note": txn.get("keterangan", ""),
            "totalDamaged": damaged_qty,
            "returnedQty": returned,
            "replacementQty": replacement,
            "availableForReturn": max(damaged_qty - returned, 0.0),
            "pendingReplacement": max(returned - replacement, 0.0),
            "claims": linked_claims,
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
            "poNo": txn.get("po_no", ""),
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
        "poDamageGroups": po_damage_groups,
        "discoveryDamageGroups": discovery_groups,
        "recentMovements": recent_movements,
        "summary": {
            "productsInArea": sum(1 for row in rows if _n(row.get("masterDamaged")) > EPS),
            "poGroups": len(po_damage_groups),
            "discoveryOpen": sum(1 for row in discovery_groups if _n(row.get("availableForReturn")) > EPS or _n(row.get("pendingReplacement")) > EPS),
            "openSupplierClaims": sum(int(row.get("openClaims") or 0) for row in rows),
            "productsWithChannelMismatch": sum(1 for row in rows if row.get("severity") == "ERROR"),
        },
    }
