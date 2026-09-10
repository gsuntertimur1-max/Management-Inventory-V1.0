from collections import defaultdict
from datetime import datetime
from typing import List, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.server import (
    db,
    new_id,
    now_iso,
    operational_now,
    next_sequence,
    max_suffix,
    require_write,
)

router = APIRouter(prefix="/api")


class POItemInput(BaseModel):
    productId: str
    qty: float = Field(gt=0)


class PurchaseOrderInput(BaseModel):
    supplier: str
    items: List[POItemInput] = Field(min_length=1)
    date: str = ""


class ReceiptItemInput(BaseModel):
    productId: str
    qty: float = Field(gt=0)
    exp: str = ""


class ReceiptInput(BaseModel):
    poId: str = ""
    items: List[ReceiptItemInput] = Field(min_length=1)
    party: str = ""
    ref: str = ""
    polisi: str = ""
    kondisi: Literal["BAIK", "RUSAK"] = "BAIK"
    keterangan: str = ""


def _validate_exp(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Format tanggal kedaluwarsa harus YYYY-MM-DD") from exc
    return value


def _po_status(items: list[dict]) -> str:
    ordered = sum(float(item.get("qty", 0) or 0) for item in items)
    received = sum(float(item.get("receivedQty", item.get("received_qty", 0)) or 0) for item in items)
    if ordered <= 0 or received <= 0:
        return "Belum Diterima"
    if received + 1e-9 < ordered:
        return "Sebagian"
    return "Selesai"


def _normalize_po(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    normalized_items = []
    for item in doc.get("items", []):
        normalized = dict(item)
        normalized["receivedQty"] = float(
            normalized.get("receivedQty", normalized.get("received_qty", 0)) or 0
        )
        normalized.setdefault("unit", "")
        normalized.setdefault("sku", "")
        normalized.setdefault("productId", "")
        normalized_items.append(normalized)
    doc["items"] = normalized_items
    doc["status"] = _po_status(normalized_items)
    return doc


@router.get("/purchase-orders-v2")
async def list_purchase_orders(user: dict = Depends(require_write)):
    docs = await db.purchase_orders.find({}, {"_id": 0}).sort("date", -1).to_list(1000)
    return [_normalize_po(doc) for doc in docs]


@router.post("/purchase-orders-v2")
async def create_purchase_order(body: PurchaseOrderInput, user: dict = Depends(require_write)):
    supplier = body.supplier.strip()
    if not supplier:
        raise HTTPException(status_code=400, detail="Supplier wajib dipilih")

    if not await db.suppliers.find_one({"name": supplier}):
        raise HTTPException(status_code=404, detail="Supplier tidak ditemukan")

    seen = set()
    items = []
    for item in body.items:
        if item.productId in seen:
            raise HTTPException(status_code=400, detail="Produk yang sama tidak boleh muncul dua kali dalam satu PO")
        seen.add(item.productId)

        product = await db.products.find_one({"id": item.productId}, {"_id": 0})
        if not product:
            raise HTTPException(status_code=404, detail="Produk pada PO tidak ditemukan")

        items.append({
            "productId": product["id"],
            "sku": product.get("sku", ""),
            "name": product.get("name", ""),
            "qty": float(item.qty),
            "receivedQty": 0.0,
            "unit": product.get("unit", ""),
            "cost": float(product.get("cost", 0) or 0),
        })

    year = operational_now().strftime("%Y")
    prefix = f"PO-{year}-"
    floor = await max_suffix(db.purchase_orders, "no", prefix)
    number = await next_sequence(f"purchase-order:{year}", floor)

    doc = {
        "id": new_id(),
        "no": f"{prefix}{number:03d}",
        "supplier": supplier,
        "date": body.date or now_iso(),
        "status": "Belum Diterima",
        "items": items,
        "total": sum(item["qty"] * item["cost"] for item in items),
        "created_by": user.get("name", ""),
        "created_at": now_iso(),
    }
    await db.purchase_orders.insert_one(dict(doc))
    return doc


@router.post("/receipts")
async def receive_stock(body: ReceiptInput, user: dict = Depends(require_write)):
    po = None
    if body.poId:
        po = await db.purchase_orders.find_one({"id": body.poId}, {"_id": 0})
        if not po:
            raise HTTPException(status_code=404, detail="Purchase Order tidak ditemukan")
        po = _normalize_po(po)
        if po["status"] == "Selesai":
            raise HTTPException(status_code=400, detail="PO sudah selesai diterima")

    products = []
    requested_by_product = defaultdict(float)
    for item in body.items:
        product = await db.products.find_one({"id": item.productId}, {"_id": 0})
        if not product:
            raise HTTPException(status_code=404, detail="Produk penerimaan tidak ditemukan")
        products.append(product)
        requested_by_product[item.productId] += float(item.qty)
        _validate_exp(item.exp)

    party = (po.get("supplier") if po else body.party).strip() if (po or body.party) else ""
    if not party:
        raise HTTPException(status_code=400, detail="Supplier pengirim wajib dipilih")

    po_item_map = {}
    if po:
        for item in po.get("items", []):
            product_id = item.get("productId", "")
            if product_id:
                po_item_map[product_id] = item

        for product_id, qty in requested_by_product.items():
            po_item = po_item_map.get(product_id)
            if not po_item:
                raise HTTPException(status_code=400, detail="Produk penerimaan tidak tercantum pada PO")
            ordered = float(po_item.get("qty", 0) or 0)
            received = float(po_item.get("receivedQty", 0) or 0)
            remaining = max(ordered - received, 0)
            if qty > remaining + 1e-9:
                raise HTTPException(
                    status_code=400,
                    detail=f"Jumlah diterima untuk {po_item.get('name', 'produk')} melebihi sisa PO ({remaining:g} {po_item.get('unit', '')})",
                )

    op_now = operational_now()
    operation_id = new_id()
    transaction_ref = po.get("no") if po else (body.ref.strip() or f"IN-{op_now.strftime('%Y%m%d%H%M%S%f')}")
    time = now_iso()
    stock_changes = []
    txns = []

    try:
        for item, product in zip(body.items, products):
            field = "damaged" if body.kondisi == "RUSAK" else "stock"
            exp = _validate_exp(item.exp)
            previous_exp = product.get("exp", "") or ""
            update_doc = {"$inc": {field: float(item.qty)}}

            # Produk tetap menyimpan tanggal kedaluwarsa terdekat sebagai ringkasan.
            # Tanggal aktual setiap penerimaan juga dicatat di transaksi di bawah.
            if body.kondisi == "BAIK" and exp and (not previous_exp or exp < previous_exp):
                update_doc["$set"] = {"exp": exp}

            result = await db.products.update_one({"id": product["id"]}, update_doc)
            if result.matched_count == 0:
                raise HTTPException(status_code=409, detail=f"Produk {product.get('name', '')} berubah. Muat ulang lalu coba lagi.")

            stock_changes.append({
                "productId": product["id"],
                "field": field,
                "qty": float(item.qty),
                "previousExp": previous_exp,
                "expChanged": bool(update_doc.get("$set")),
            })

            txns.append({
                "id": new_id(),
                "operation_id": operation_id,
                "time": time,
                "ref": transaction_ref,
                "po_id": po.get("id", "") if po else "",
                "po_no": po.get("no", "") if po else "",
                "antrian": "",
                "type": "MASUK",
                "kondisi": body.kondisi,
                "product": product.get("name", ""),
                "sku": product.get("sku", ""),
                "change": float(item.qty),
                "exp": exp,
                "penerima": party,
                "polisi": body.polisi,
                "operator": user.get("name", ""),
                "keterangan": body.keterangan,
            })

        if txns:
            await db.transactions.insert_many([dict(txn) for txn in txns])

        updated_po = None
        if po:
            increments = requested_by_product
            updated_items = []
            for item in po["items"]:
                updated = dict(item)
                product_id = updated.get("productId", "")
                if product_id in increments:
                    updated["receivedQty"] = float(updated.get("receivedQty", 0) or 0) + increments[product_id]
                updated_items.append(updated)

            new_status = _po_status(updated_items)
            result = await db.purchase_orders.update_one(
                {"id": po["id"]},
                {"$set": {
                    "items": updated_items,
                    "status": new_status,
                    "last_received_at": time,
                    "last_received_by": user.get("name", ""),
                }},
            )
            if result.matched_count == 0:
                raise HTTPException(status_code=409, detail="PO berubah. Muat ulang lalu coba kembali.")
            updated_po = {**po, "items": updated_items, "status": new_status}

    except Exception:
        await db.transactions.delete_many({"operation_id": operation_id})
        for change in reversed(stock_changes):
            rollback = {"$inc": {change["field"]: -change["qty"]}}
            if change["expChanged"]:
                rollback["$set"] = {"exp": change["previousExp"]}
            await db.products.update_one({"id": change["productId"]}, rollback)
        raise

    return {
        "transactions": txns,
        "purchaseOrder": updated_po,
        "message": "Penerimaan stok berhasil disimpan",
    }
