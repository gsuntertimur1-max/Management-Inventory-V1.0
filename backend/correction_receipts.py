from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from backend.server import db, require_admin, require_write
from backend.inventory_flow import ReceiptInput, receipt_condition_quantities
from backend.operational_guards import guarded_receive_stock

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)
DAMAGED_HOLDING = "AREA BARANG RUSAK"


def normal_receipt_query(operation_id: str | None = None) -> dict:
    query: dict = {
        "type": "MASUK",
        "operation_id": {"$nin": ["", None]},
        "$or": [{"document_type": {"$exists": False}}, {"document_type": ""}],
    }
    if operation_id:
        query["operation_id"] = operation_id
    return query


def txn_quantities(txn: dict) -> tuple[float, float]:
    change = max(float(txn.get("change", 0) or 0), 0.0)
    good = float(txn.get("good_change", 0) or 0)
    damaged = float(txn.get("damaged_change", 0) or 0)
    if good <= 0 and damaged <= 0:
        if str(txn.get("kondisi") or "").upper() == "RUSAK":
            damaged = change
        else:
            good = change
    return max(good, 0.0), max(damaged, 0.0)


def receipt_item_metadata(body: ReceiptInput, transactions: list[dict]) -> list[tuple[str, dict]]:
    result: list[tuple[str, dict]] = []
    cursor = 0
    for item in body.items:
        good_qty, damaged_qty = receipt_condition_quantities(item, body.kondisi)
        stack_code = str(item.stackCode or "").strip().upper()
        if good_qty > 0 and cursor < len(transactions):
            result.append((transactions[cursor]["id"], {
                "product_id": item.productId,
                "stackCode": stack_code,
                "receipt_location": stack_code,
                "location_type": "STACK",
            }))
            cursor += 1
        if damaged_qty > 0 and cursor < len(transactions):
            result.append((transactions[cursor]["id"], {
                "product_id": item.productId,
                "stackCode": "",
                "receipt_location": DAMAGED_HOLDING,
                "damaged_location": DAMAGED_HOLDING,
                "location_type": "DAMAGED_HOLDING",
            }))
            cursor += 1
    return result


async def enrich_receipt_result(body: ReceiptInput, result: dict) -> dict:
    txns = [dict(row) for row in (result.get("transactions") or [])]
    by_id = {txn.get("id"): txn for txn in txns}
    for txn_id, patch in receipt_item_metadata(body, txns):
        try:
            await db.transactions.update_one({"id": txn_id}, {"$set": patch})
            if txn_id in by_id:
                by_id[txn_id].update(patch)
        except Exception:
            logger.exception("Gagal menambahkan metadata penerimaan %s", txn_id)
    result["transactions"] = txns
    return result


@router.post("/receipts")
async def guarded_receive_stock_with_metadata(body: ReceiptInput, user: dict = Depends(require_write)):
    from backend.stack_allocations import valid_stack_codes

    valid_stacks = None
    for item in body.items:
        good_qty, _ = receipt_condition_quantities(item, body.kondisi)
        if good_qty <= 0:
            continue
        stack_code = str(item.stackCode or "").strip().upper()
        if not stack_code:
            raise HTTPException(status_code=400, detail="Tumpukan penerimaan wajib dipilih untuk setiap stok Baik")
        if valid_stacks is None:
            valid_stacks = await valid_stack_codes()
        if stack_code not in valid_stacks:
            raise HTTPException(status_code=400, detail="Lokasi tumpukan penerimaan tidak valid")

    result = await guarded_receive_stock(body, user)
    return await enrich_receipt_result(body, result)


async def product_maps() -> tuple[dict[str, dict], dict[str, dict]]:
    products = await db.products.find({}, {"_id": 0}).to_list(20000)
    return (
        {str(p.get("id") or ""): p for p in products if p.get("id")},
        {str(p.get("sku") or ""): p for p in products if p.get("sku")},
    )


async def receipt_rows(operation_id: str) -> list[dict]:
    return await db.transactions.find(normal_receipt_query(operation_id), {"_id": 0}).sort("time", 1).to_list(100)


def receipt_summary(
    operation_id: str,
    rows: list[dict],
    products_by_id: dict[str, dict],
    products_by_sku: dict[str, dict],
    linked_return_operations: set[str],
) -> dict:
    items = []
    correctable = True
    reason = ""
    flags = [bool(row.get("voided")) for row in rows]
    voided = bool(rows) and all(flags)
    if voided:
        correctable, reason = False, "Penerimaan sudah dibatalkan melalui koreksi."
    elif any(flags):
        correctable, reason = False, "Riwayat penerimaan terkoreksi sebagian; periksa audit trail."
    elif operation_id in linked_return_operations:
        correctable, reason = False, "Barang rusak dari penerimaan ini sudah memiliki Retur Pemasok."

    for row in rows:
        good, damaged = txn_quantities(row)
        product = products_by_id.get(str(row.get("product_id") or "")) or products_by_sku.get(str(row.get("sku") or ""))
        stack_code = str(row.get("stackCode") or row.get("receipt_stack_code") or "").strip().upper()
        if not product and correctable:
            correctable, reason = False, "Master produk penerimaan tidak ditemukan."
        if good > 0 and not stack_code and correctable:
            correctable, reason = False, "Penerimaan lama belum menyimpan tumpukan asal sehingga tidak aman dibatalkan otomatis."
        items.append({
            "transactionId": row.get("id", ""),
            "productId": (product or {}).get("id", row.get("product_id", "")),
            "product": row.get("product", ""),
            "sku": row.get("sku", ""),
            "goodQty": good,
            "damagedQty": damaged,
            "unit": row.get("unit", ""),
            "channel": row.get("channel", "KOM"),
            "stackCode": stack_code,
            "receiptLocation": row.get("receipt_location") or stack_code or row.get("damaged_location", ""),
            "exp": row.get("exp", ""),
        })

    first = rows[0] if rows else {}
    return {
        "operationId": operation_id,
        "time": first.get("time", ""),
        "ref": first.get("ref", ""),
        "poId": first.get("po_id", ""),
        "poNo": first.get("po_no", ""),
        "party": first.get("penerima", ""),
        "items": items,
        "status": "DIBATALKAN" if voided else "AKTIF",
        "correctable": correctable,
        "reason": reason,
        "correctionId": first.get("correction_id", ""),
        "voidReason": first.get("void_reason", ""),
        "voidedAt": first.get("voided_at", ""),
        "voidedBy": first.get("voided_by", ""),
    }


@router.get("/operational-corrections/receipts")
async def list_receipt_corrections(user: dict = Depends(require_admin)):
    rows = await db.transactions.find(normal_receipt_query(), {"_id": 0}).sort("time", -1).to_list(3000)
    grouped: dict[str, list[dict]] = {}
    order: list[str] = []
    for row in rows:
        op_id = str(row.get("operation_id") or "")
        if op_id not in grouped:
            grouped[op_id] = []
            order.append(op_id)
        grouped[op_id].append(row)

    linked_returns = {
        str(row.get("source_damage_operation_id") or "")
        for row in await db.supplier_returns.find(
            {"source_damage_operation_id": {"$nin": ["", None]}},
            {"_id": 0, "source_damage_operation_id": 1},
        ).to_list(5000)
    }
    by_id, by_sku = await product_maps()
    return [receipt_summary(op_id, grouped[op_id], by_id, by_sku, linked_returns) for op_id in order[:500]]


async def recalculate_product_exp(product: dict) -> None:
    # Penerimaan lama tidak selalu memiliki good_change. Ambil semua penerimaan
    # aktif produk lalu gunakan txn_quantities agar data legacy tetap dihitung.
    query = {
        "type": "MASUK",
        "operation_id": {"$nin": ["", None]},
        "voided": {"$ne": True},
        "exp": {"$nin": ["", None]},
        "$and": [
            {"$or": [{"document_type": {"$exists": False}}, {"document_type": ""}]},
            {"$or": [{"product_id": product.get("id", "")}, {"sku": product.get("sku", "")}]},
        ],
    }
    rows = await db.transactions.find(
        query,
        {"_id": 0, "exp": 1, "change": 1, "kondisi": 1, "good_change": 1, "damaged_change": 1},
    ).to_list(10000)
    expiries = sorted(
        str(row.get("exp") or "")
        for row in rows
        if row.get("exp") and txn_quantities(row)[0] > 0
    )
    await db.products.update_one({"id": product["id"]}, {"$set": {"exp": expiries[0] if expiries else ""}})
