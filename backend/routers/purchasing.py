from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from lib.auth import principal
from lib.db import db
from models.inventory import Transaction
from models.purchasing import PurchaseOrder, PurchaseOrderCreate, POItem, Settings

router = APIRouter()

SETTINGS_ID = "app"


# ---------- Settings ----------
@router.get("/settings", response_model=Settings)
async def get_settings():
    doc = await db.settings.find_one({"id": SETTINGS_ID})
    if not doc:
        return Settings()
    doc.pop("_id", None)
    doc.pop("id", None)
    return Settings(**doc)


@router.put("/settings", response_model=Settings)
async def update_settings(payload: Settings):
    await db.settings.update_one(
        {"id": SETTINGS_ID}, {"$set": {**payload.model_dump(), "id": SETTINGS_ID}}, upsert=True
    )
    return payload


# ---------- Purchase Orders ----------
async def _next_po_number() -> str:
    prefix = f"PO-{datetime.now(timezone.utc).strftime('%Y%m')}-"
    count = await db.purchase_orders.count_documents({"po_number": {"$regex": f"^{prefix}"}})
    return f"{prefix}{count + 1:03d}"


@router.get("/purchase-orders", response_model=List[PurchaseOrder])
async def list_purchase_orders():
    docs = await db.purchase_orders.find().sort("created_at", -1).to_list(500)
    return [PurchaseOrder(**d) for d in docs]


@router.get("/purchase-orders/{po_id}", response_model=PurchaseOrder)
async def get_purchase_order(po_id: str):
    doc = await db.purchase_orders.find_one({"id": po_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Purchase Order tidak ditemukan")
    return PurchaseOrder(**doc)


@router.post("/purchase-orders", response_model=PurchaseOrder)
async def create_purchase_order(payload: PurchaseOrderCreate):
    supplier = await db.suppliers.find_one({"id": payload.supplier_id})
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier tidak ditemukan")
    if not payload.items:
        raise HTTPException(status_code=400, detail="Minimal satu item produk harus ditambahkan")

    items: List[POItem] = []
    for line in payload.items:
        product = await db.products.find_one({"id": line.product_id})
        if not product:
            raise HTTPException(status_code=404, detail="Produk pada item PO tidak ditemukan")
        price = line.unit_price if line.unit_price > 0 else float(product.get("purchase_price", 0))
        items.append(POItem(
            product_id=product["id"],
            product_name=product["name"],
            product_sku=product["sku"],
            unit=product.get("unit", "Pcs"),
            quantity=line.quantity,
            unit_price=price,
            subtotal=price * line.quantity,
        ))

    po = PurchaseOrder(
        po_number=await _next_po_number(),
        supplier_id=supplier["id"],
        supplier_name=supplier["name"],
        items=items,
        total=sum(i.subtotal for i in items),
        notes=payload.notes,
        order_date=datetime.now(timezone.utc).date().isoformat(),
        expected_date=payload.expected_date,
    )
    await db.purchase_orders.insert_one(po.model_dump())
    return po


class ReceiveRequest(BaseModel):
    vehicle_plate: str = ""


@router.post("/purchase-orders/{po_id}/receive", response_model=PurchaseOrder)
async def receive_purchase_order(po_id: str, payload: Optional[ReceiveRequest] = None, caller=Depends(principal)):
    doc = await db.purchase_orders.find_one({"id": po_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Purchase Order tidak ditemukan")
    po = PurchaseOrder(**doc)
    if po.status != "MENUNGGU":
        raise HTTPException(status_code=400, detail=f"PO sudah berstatus {po.status}")

    plate = (payload.vehicle_plate.strip().upper() if payload else "")
    today = datetime.now(timezone.utc).date().isoformat()
    for item in po.items:
        product = await db.products.find_one({"id": item.product_id})
        if not product:
            continue
        after = int(product.get("current_stock", 0)) + item.quantity
        tx = Transaction(
            product_id=product["id"],
            product_name=product["name"],
            product_sku=product["sku"],
            category=product.get("category", "Lainnya"),
            type="MASUK",
            quantity=item.quantity,
            stock_after=after,
            party=po.supplier_name,
            reference_no=po.po_number,
            vehicle_plate=plate,
            created_by=caller.id if caller else None,
            created_by_name=(caller.full_name or caller.username) if caller else "",
            notes=f"Penerimaan barang dari {po.po_number}",
            date=today,
        )
        await db.transactions.insert_one(tx.model_dump())
        await db.products.update_one({"id": product["id"]}, {"$set": {"current_stock": after}})

    received = datetime.now(timezone.utc)
    await db.purchase_orders.update_one(
        {"id": po_id}, {"$set": {"status": "DITERIMA", "received_at": received}}
    )
    po.status = "DITERIMA"
    po.received_at = received
    return po


@router.post("/purchase-orders/{po_id}/cancel", response_model=PurchaseOrder)
async def cancel_purchase_order(po_id: str):
    doc = await db.purchase_orders.find_one({"id": po_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Purchase Order tidak ditemukan")
    po = PurchaseOrder(**doc)
    if po.status == "DITERIMA":
        raise HTTPException(status_code=400, detail="PO yang sudah diterima tidak dapat dibatalkan")
    await db.purchase_orders.update_one({"id": po_id}, {"$set": {"status": "DIBATALKAN"}})
    po.status = "DIBATALKAN"
    return po


@router.delete("/purchase-orders/{po_id}")
async def delete_purchase_order(po_id: str):
    res = await db.purchase_orders.delete_one({"id": po_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Purchase Order tidak ditemukan")
    return {"ok": True}
