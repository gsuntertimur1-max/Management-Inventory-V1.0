from __future__ import annotations

from backend.server import db, new_id, now_iso

EPS = 1e-9


def _n(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


async def record_return_untracked_movements(load_id: str, link: dict) -> int:
    """Record good returns placed back on stacks without inventing expiry/lot identity.

    Return documents do not currently capture a verified source lot/expiry.  The physical
    stock therefore remains valid, but the returned quantity must stay legacy/untracked
    until an operator reconciles it to a real lot.  Deterministic movement ids make retries
    idempotent.
    """
    document_no = str(link.get("no") or "").strip()
    source_document = str(link.get("sourceDocumentNo") or "").strip()
    movement_type = "RETURN_UNTRACKED"
    written = 0
    timestamp = str(link.get("time") or now_iso())

    for item_index, item in enumerate(link.get("items", [])):
        product_id = str(item.get("productId") or "")
        if not product_id:
            continue
        placements = list(item.get("placements") or [])
        if not placements and _n(item.get("goodQty")) > EPS and item.get("stackCode"):
            placements = [{"goodQty": _n(item.get("goodQty")), "stackCode": item.get("stackCode")}]

        for placement_index, placement in enumerate(placements):
            qty = _n(placement.get("goodQty"))
            stack_code = str(placement.get("stackCode") or "").strip().upper()
            if qty <= EPS or not stack_code:
                continue
            movement_id = f"return-untracked:{load_id}:{document_no}:{product_id}:{item_index}:{placement_index}"
            doc = {
                "id": movement_id,
                "time": timestamp,
                "loadId": load_id,
                "lotId": "",
                "lotCode": "",
                "movementType": movement_type,
                "productId": product_id,
                "sku": item.get("sku", ""),
                "product": item.get("name", ""),
                "stackCode": stack_code,
                "sourceDocument": source_document,
                "returnDocument": document_no,
                "qty": qty,
                "unit": item.get("unit", ""),
                "exp": "",
                "note": "Retur barang Baik kembali ke tumpukan tanpa identitas lot/expired terverifikasi; diperlakukan sebagai stok legacy sampai rekonsiliasi lot.",
            }
            result = await db.stack_lot_movements.update_one(
                {"id": movement_id},
                {"$setOnInsert": doc},
                upsert=True,
            )
            if result.upserted_id is not None:
                written += 1
    return written
