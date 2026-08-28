from datetime import datetime, timezone
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException

from lib.auth import principal
from lib.db import db
from models.inventory import Transaction
from models.shipment import (
    Shipment,
    ShipmentCreate,
    ShipmentItem,
    ShipmentStatusUpdate,
)

router = APIRouter()


async def _next_doc_no() -> str:
    prefix = f"SJ-{datetime.now(timezone.utc).strftime('%Y%m')}-"
    count = await db.shipments.count_documents({"doc_no": {"$regex": f"^{prefix}"}})
    return f"{prefix}{count + 1:03d}"


async def _next_queue_no(day: str) -> str:
    count = await db.shipments.count_documents({"date": day})
    return f"A-{count + 1:03d}"


@router.get("/shipments", response_model=List[Shipment])
async def list_shipments():
    docs = await db.shipments.find().sort("created_at", -1).to_list(1000)
    return [Shipment(**d) for d in docs]


@router.get("/shipments/queue", response_model=List[Shipment])
async def queue_board():
    """Antrian pemuatan: semua pengeluaran yang belum SELESAI, urut paling lama dulu."""
    docs = await db.shipments.find({"status": {"$ne": "SELESAI"}}).sort("created_at", 1).to_list(200)
    return [Shipment(**d) for d in docs]


@router.get("/shipments/by-ids", response_model=List[Shipment])
async def shipments_by_ids(ids: str):
    wanted = [i for i in ids.split(",") if i]
    docs = await db.shipments.find({"id": {"$in": wanted}}).to_list(200)
    by_id = {d["id"]: d for d in docs}
    return [Shipment(**by_id[i]) for i in wanted if i in by_id]


@router.get("/shipments/{shipment_id}", response_model=Shipment)
async def get_shipment(shipment_id: str):
    doc = await db.shipments.find_one({"id": shipment_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Surat jalan tidak ditemukan")
    return Shipment(**doc)


@router.post("/shipments", response_model=Shipment)
async def create_shipment(payload: ShipmentCreate, caller=Depends(principal)):
    """One outbound document with many product lines; stock drops per line atomically."""
    if not payload.items:
        raise HTTPException(status_code=400, detail="Minimal satu item barang harus ditambahkan")

    merged: Dict[str, int] = {}
    for line in payload.items:
        merged[line.product_id] = merged.get(line.product_id, 0) + line.quantity

    products: Dict[str, dict] = {}
    for product_id, qty in merged.items():
        product = await db.products.find_one({"id": product_id})
        if not product:
            raise HTTPException(status_code=404, detail="Produk pada item pengeluaran tidak ditemukan")
        stock = int(product.get("current_stock", 0))
        if qty > stock:
            raise HTTPException(
                status_code=400,
                detail=f"Stok {product['name']} tidak cukup. Tersedia {stock}, diminta {qty}",
            )
        products[product_id] = product

    day = payload.date or datetime.now(timezone.utc).date().isoformat()
    doc_no = await _next_doc_no()
    queue_no = await _next_queue_no(day)

    items: List[ShipmentItem] = []
    for product_id, qty in merged.items():
        product = products[product_id]
        after = int(product.get("current_stock", 0)) - qty
        items.append(ShipmentItem(
            product_id=product_id,
            product_name=product["name"],
            product_sku=product["sku"],
            unit=product.get("unit", "Pcs"),
            quantity=qty,
            stock_after=after,
        ))

    shipment = Shipment(
        doc_no=doc_no,
        queue_no=queue_no,
        party=payload.party,
        reference_no=payload.reference_no or doc_no,
        notes=payload.notes,
        date=day,
        items=items,
        total_quantity=sum(i.quantity for i in items),
        created_by=caller.id if caller else None,
        created_by_name=(caller.full_name or caller.username) if caller else "",
    )
    await db.shipments.insert_one(shipment.model_dump())

    # One stock transaction per line keeps per-product history and stats intact.
    for item in items:
        product = products[item.product_id]
        tx = Transaction(
            product_id=item.product_id,
            product_name=item.product_name,
            product_sku=item.product_sku,
            category=product.get("category", "Lainnya"),
            type="KELUAR",
            quantity=item.quantity,
            stock_after=item.stock_after,
            party=shipment.party,
            reference_no=shipment.reference_no,
            queue_no=queue_no,
            shipment_id=shipment.id,
            created_by=shipment.created_by,
            created_by_name=shipment.created_by_name,
            notes=shipment.notes,
            date=day,
        )
        await db.transactions.insert_one(tx.model_dump())
        await db.products.update_one(
            {"id": item.product_id}, {"$set": {"current_stock": item.stock_after}}
        )

    return shipment


@router.patch("/shipments/{shipment_id}/status", response_model=Shipment)
async def update_shipment_status(shipment_id: str, payload: ShipmentStatusUpdate):
    doc = await db.shipments.find_one({"id": shipment_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Surat jalan tidak ditemukan")
    await db.shipments.update_one({"id": shipment_id}, {"$set": {"status": payload.status}})
    doc["status"] = payload.status
    return Shipment(**doc)
