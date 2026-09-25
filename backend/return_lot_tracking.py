from __future__ import annotations

from backend.server import db, new_id, now_iso

EPS = 1e-9


def _n(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


async def _outbound_provenance(load_id: str, product_id: str, source_document: str) -> tuple[float, float]:
    """Return qty originally consumed from legacy/untracked vs tracked FEFO lots."""
    rows = await db.stack_lot_movements.find(
        {
            "loadId": load_id,
            "productId": product_id,
            "sourceDocument": source_document,
            "movementType": {"$in": ["OUTBOUND_UNTRACKED", "OUTBOUND_FEFO"]},
        },
        {"_id": 0, "movementType": 1, "qty": 1},
    ).to_list(10000)
    legacy = sum(abs(_n(row.get("qty"))) for row in rows if row.get("movementType") == "OUTBOUND_UNTRACKED")
    tracked = sum(abs(_n(row.get("qty"))) for row in rows if row.get("movementType") == "OUTBOUND_FEFO")
    return legacy, tracked


async def _legacy_returned_qty(load_id: str, product_id: str, source_document: str) -> float:
    rows = await db.stack_lot_movements.find(
        {
            "loadId": load_id,
            "productId": product_id,
            "sourceDocument": source_document,
            "movementType": "RETURN_LEGACY",
        },
        {"_id": 0, "qty": 1},
    ).to_list(10000)
    return sum(abs(_n(row.get("qty"))) for row in rows)


async def record_return_untracked_movements(load_id: str, link: dict) -> int:
    """Record returned good stock without inventing lot identity.

    If the original outbound quantity is proven to have come from legacy/untracked
    stock, the matching returned quantity remains legacy and is immediately complete
    (RETURN_LEGACY). Only the remainder whose source lot cannot be restored safely is
    marked RETURN_UNTRACKED and shown in the reconciliation queue.
    """
    document_no = str(link.get("no") or "").strip()
    source_document = str(link.get("sourceDocumentNo") or "").strip()
    written = 0
    timestamp = str(link.get("time") or now_iso())

    for item_index, item in enumerate(link.get("items", [])):
        product_id = str(item.get("productId") or "")
        if not product_id:
            continue

        outbound_legacy, outbound_tracked = await _outbound_provenance(load_id, product_id, source_document)
        already_legacy_returned = await _legacy_returned_qty(load_id, product_id, source_document)
        legacy_remaining = max(outbound_legacy - already_legacy_returned, 0.0)

        placements = list(item.get("placements") or [])
        if not placements and _n(item.get("goodQty")) > EPS and item.get("stackCode"):
            placements = [{"goodQty": _n(item.get("goodQty")), "stackCode": item.get("stackCode")}]

        for placement_index, placement in enumerate(placements):
            qty = _n(placement.get("goodQty"))
            stack_code = str(placement.get("stackCode") or "").strip().upper()
            if qty <= EPS or not stack_code:
                continue

            legacy_qty = min(qty, legacy_remaining)
            pending_qty = max(qty - legacy_qty, 0.0)

            if legacy_qty > EPS:
                movement_id = f"return-legacy:{load_id}:{document_no}:{product_id}:{item_index}:{placement_index}"
                doc = {
                    "id": movement_id,
                    "time": timestamp,
                    "loadId": load_id,
                    "lotId": "",
                    "lotCode": "",
                    "movementType": "RETURN_LEGACY",
                    "productId": product_id,
                    "sku": item.get("sku", ""),
                    "product": item.get("name", ""),
                    "stackCode": stack_code,
                    "sourceDocument": source_document,
                    "returnDocument": document_no,
                    "qty": legacy_qty,
                    "unit": item.get("unit", ""),
                    "exp": "",
                    "provenance": "OUTBOUND_UNTRACKED",
                    "note": "Retur berasal dari stok legacy/untracked; dikembalikan sebagai legacy tanpa membuat lot baru dan tidak memerlukan rekonsiliasi.",
                }
                result = await db.stack_lot_movements.update_one(
                    {"id": movement_id},
                    {"$setOnInsert": doc},
                    upsert=True,
                )
                if result.upserted_id is not None:
                    written += 1
                legacy_remaining = max(legacy_remaining - legacy_qty, 0.0)

            if pending_qty > EPS:
                movement_id = f"return-untracked:{load_id}:{document_no}:{product_id}:{item_index}:{placement_index}"
                doc = {
                    "id": movement_id,
                    "time": timestamp,
                    "loadId": load_id,
                    "lotId": "",
                    "lotCode": "",
                    "movementType": "RETURN_UNTRACKED",
                    "productId": product_id,
                    "sku": item.get("sku", ""),
                    "product": item.get("name", ""),
                    "stackCode": stack_code,
                    "sourceDocument": source_document,
                    "returnDocument": document_no,
                    "qty": pending_qty,
                    "unit": item.get("unit", ""),
                    "exp": "",
                    "provenance": "TRACKED_OR_UNKNOWN",
                    "note": (
                        "Retur belum dapat dikembalikan ke lot asal secara aman; "
                        "perlu verifikasi lot/expired sebelum direkonsiliasi."
                    ),
                }
                result = await db.stack_lot_movements.update_one(
                    {"id": movement_id},
                    {"$setOnInsert": doc},
                    upsert=True,
                )
                if result.upserted_id is not None:
                    written += 1

    return written
