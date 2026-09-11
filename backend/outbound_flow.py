from collections import defaultdict
import re
from typing import List, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.server import (
    db,
    get_current_user,
    max_suffix,
    new_id,
    next_sequence,
    now_iso,
    operational_now,
    require_write,
)
from backend.stack_allocations import reconcile_product_allocations

router = APIRouter(prefix="/api")


def _validate_pack_qty(product: dict, qty: float) -> None:
    if float(product.get("secondaryQty", 0) or 0) > 0 and abs(qty - round(qty)) > 1e-6:
        raise HTTPException(
            status_code=400,
            detail=f"Jumlah {product.get('name', 'produk')} harus berupa kemasan primer/pack utuh",
        )


class OutboundItemInput(BaseModel):
    productId: str
    qty: float = Field(gt=0)


class OutboundCreateInput(BaseModel):
    items: List[OutboundItemInput] = Field(min_length=1)
    party: str
    ref: str = ""
    polisi: str = ""
    pengambil: str = ""
    kondisi: Literal["BAIK", "RUSAK"] = "BAIK"
    keterangan: str = ""


async def _reserved_qty(product_id: str, kondisi: str, exclude_id: str = "") -> float:
    query = {"status": {"$in": ["Menunggu", "Sedang Dimuat"]}}
    if exclude_id:
        query["id"] = {"$ne": exclude_id}
    docs = await db.outbound_loads.find(query, {"_id": 0, "items": 1, "kondisi": 1}).to_list(5000)
    total = 0.0
    for doc in docs:
        if doc.get("kondisi", "BAIK") != kondisi:
            continue
        for item in doc.get("items", []):
            if item.get("productId") == product_id:
                total += float(item.get("qty", 0) or 0)
    return total


def _loading_unit_from_products(products: List[dict]) -> tuple[str, str]:
    """Bentuk label unit pemuatan dan prefix antrean, contoh: Unit 17 / 17."""
    labels = []
    queue_prefix = ""
    for product in products:
        location = str(product.get("location") or "").strip()
        if not location:
            continue
        match = re.search(r"unit\s*0*(\d+)", location, re.IGNORECASE)
        if not match:
            match = re.search(r"\b(\d{1,3})\b", location)
        if match:
            number = str(int(match.group(1)))
            label = f"Unit {number}"
            if not queue_prefix:
                queue_prefix = number
        else:
            label = location
        if label not in labels:
            labels.append(label)
    return " / ".join(labels) if labels else "-", queue_prefix or "A"


@router.get("/outbound-loads")
async def list_outbound_loads(user: dict = Depends(get_current_user)):
    return await db.outbound_loads.find({}, {"_id": 0}).sort("created_at", -1).to_list(2000)


@router.post("/outbound-loads")
async def create_outbound_load(body: OutboundCreateInput, user: dict = Depends(require_write)):
    party = body.party.strip()
    if not party:
        raise HTTPException(status_code=400, detail="Penerima barang wajib diisi")

    requested = defaultdict(float)
    item_order = []
    for item in body.items:
        if item.productId not in requested:
            item_order.append(item.productId)
        requested[item.productId] += float(item.qty)

    products = {}
    load_items = []
    for product_id in item_order:
        qty = requested[product_id]
        product = await db.products.find_one({"id": product_id}, {"_id": 0})
        if not product:
            raise HTTPException(status_code=404, detail="Produk pengeluaran tidak ditemukan")
        _validate_pack_qty(product, qty)
        products[product_id] = product

        field = "damaged" if body.kondisi == "RUSAK" else "stock"
        physical = float(product.get(field, 0) or 0)
        reserved = await _reserved_qty(product_id, body.kondisi)
        available = max(physical - reserved, 0)
        if qty > available + 1e-9:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Stok tersedia untuk {product.get('name', 'produk')} tidak mencukupi. "
                    f"Fisik {physical:g}, sudah dialokasikan {reserved:g}, tersedia {available:g} {product.get('unit', '')}"
                ),
            )

        weight = float(product.get("weight", 0) or 0)
        load_items.append({
            "productId": product_id,
            "sku": product.get("sku", ""),
            "name": product.get("name", ""),
            "qty": qty,
            "unit": product.get("unit", ""),
            "weight": weight,
            "berat": weight * qty,
            "secondary": product.get("secondary", ""),
            "secondaryQty": float(product.get("secondaryQty", 0) or 0),
            "location": product.get("location", ""),
        })

    ordered_products = [products[product_id] for product_id in item_order]
    unit_loading, queue_prefix = _loading_unit_from_products(ordered_products)

    op_now = operational_now()
    operational_date = op_now.strftime("%Y-%m-%d")

    queue_floor = await max_suffix(
        db.outbound_loads,
        "antrian",
        f"{queue_prefix}-",
        {"operational_date": operational_date},
    )
    queue_number = await next_sequence(
        f"loading-queue:{operational_date}:{queue_prefix}",
        queue_floor,
    )

    bon_prefix = f"BM-{op_now.strftime('%Y%m%d')}-"
    bon_floor = await max_suffix(
        db.outbound_loads,
        "bon_no",
        bon_prefix,
        {"operational_date": operational_date},
    )
    bon_number = await next_sequence(f"bon-muat:{operational_date}", bon_floor)

    total_unit = sum(float(item["qty"]) for item in load_items)
    total_berat = sum(float(item["berat"]) for item in load_items)
    created_at = now_iso()
    doc = {
        "id": new_id(),
        "bon_no": f"{bon_prefix}{bon_number:03d}",
        "antrian": f"{queue_prefix}-{queue_number:03d}",
        "operational_date": operational_date,
        "created_at": created_at,
        "started_at": "",
        "completed_at": "",
        "party": party,
        "penerima": party,
        "ref": body.ref.strip(),
        "polisi": body.polisi.strip(),
        "pengambil": body.pengambil.strip(),
        "unit_loading": unit_loading,
        "kondisi": body.kondisi,
        "keterangan": body.keterangan.strip(),
        "items": load_items,
        "total_unit": total_unit,
        "total_berat": total_berat,
        "status": "Menunggu",
        "created_by": user.get("name", ""),
        "started_by": "",
        "completed_by": "",
        "surat_jalan_id": "",
        "surat_jalan_no": "",
    }
    await db.outbound_loads.insert_one(dict(doc))
    return doc


@router.post("/outbound-loads/{load_id}/start")
async def start_outbound_load(load_id: str, user: dict = Depends(require_write)):
    load = await db.outbound_loads.find_one({"id": load_id}, {"_id": 0})
    if not load:
        raise HTTPException(status_code=404, detail="Data pemuatan tidak ditemukan")
    if load.get("status") == "Selesai":
        raise HTTPException(status_code=400, detail="Pemuatan sudah selesai")
    if load.get("status") == "Sedang Dimuat":
        return load

    now = now_iso()
    await db.outbound_loads.update_one(
        {"id": load_id, "status": "Menunggu"},
        {"$set": {"status": "Sedang Dimuat", "started_at": now, "started_by": user.get("name", "")}},
    )
    return await db.outbound_loads.find_one({"id": load_id}, {"_id": 0})


@router.post("/outbound-loads/{load_id}/complete")
async def complete_outbound_load(load_id: str, user: dict = Depends(require_write)):
    load = await db.outbound_loads.find_one({"id": load_id}, {"_id": 0})
    if not load:
        raise HTTPException(status_code=404, detail="Data pemuatan tidak ditemukan")

    if load.get("status") == "Selesai":
        sj = None
        if load.get("surat_jalan_id"):
            sj = await db.surat_jalan.find_one({"id": load["surat_jalan_id"]}, {"_id": 0})
        return {"load": load, "suratJalan": sj}

    if load.get("status") != "Sedang Dimuat":
        raise HTTPException(status_code=400, detail="Pemuatan harus dimulai sebelum dapat diselesaikan")

    operation_id = new_id()
    completed_at = now_iso()
    stock_changes = []
    transactions = []
    kondisi = load.get("kondisi", "BAIK")
    field = "damaged" if kondisi == "RUSAK" else "stock"

    try:
        for item in load.get("items", []):
            qty = float(item.get("qty", 0) or 0)
            if qty <= 0:
                continue
            product = await db.products.find_one({"id": item.get("productId")}, {"_id": 0})
            if not product:
                raise HTTPException(status_code=404, detail=f"Produk {item.get('name', '')} tidak ditemukan")

            result = await db.products.update_one(
                {"id": product["id"], field: {"$gte": qty}},
                {"$inc": {field: -qty}},
            )
            if result.matched_count == 0:
                raise HTTPException(
                    status_code=409,
                    detail=f"Stok {product.get('name', '')} berubah atau tidak mencukupi. Periksa stok lalu coba lagi.",
                )
            stock_changes.append((product["id"], qty))

            transactions.append({
                "id": new_id(),
                "operation_id": operation_id,
                "load_id": load["id"],
                "time": completed_at,
                "ref": load.get("ref") or load.get("antrian", ""),
                "bon_no": load.get("bon_no", ""),
                "antrian": load.get("antrian", ""),
                "type": "KELUAR",
                "kondisi": kondisi,
                "product": product.get("name", ""),
                "sku": product.get("sku", ""),
                "change": -qty,
                "unit": product.get("unit", ""),
                "weight": float(product.get("weight", 0) or 0),
                "total_weight": float(product.get("weight", 0) or 0) * qty,
                "secondary": product.get("secondary", ""),
                "secondaryQty": float(product.get("secondaryQty", 0) or 0),
                "penerima": load.get("party", "-"),
                "pengambil": load.get("pengambil", ""),
                "polisi": load.get("polisi", ""),
                "operator": user.get("name", ""),
                "keterangan": load.get("keterangan", ""),
            })

        op_now = operational_now()
        month_prefix = op_now.strftime("SJ-%Y%m")
        sj_floor = await max_suffix(db.surat_jalan, "no", f"{month_prefix}-")
        sj_number = await next_sequence(f"surat-jalan:{op_now.strftime('%Y%m')}", sj_floor)
        sj_id = new_id()
        sj_no = f"{month_prefix}-{sj_number:03d}"
        sj = {
            "id": sj_id,
            "operation_id": operation_id,
            "load_id": load["id"],
            "no": sj_no,
            "bon_no": load.get("bon_no", ""),
            "antrian": load.get("antrian", ""),
            "operational_date": load.get("operational_date", op_now.strftime("%Y-%m-%d")),
            "time": completed_at,
            "penerima": load.get("party", "-"),
            "pengambil": load.get("pengambil", ""),
            "polisi": load.get("polisi", ""),
            "unit_loading": load.get("unit_loading", ""),
            "operator": user.get("name", ""),
            "status": "Selesai",
            "ref": load.get("ref", ""),
            "items": [
                {
                    "name": item.get("name", ""),
                    "sku": item.get("sku", ""),
                    "qty": float(item.get("qty", 0) or 0),
                    "unit": item.get("unit", ""),
                    "berat": float(item.get("berat", 0) or 0),
                    "location": item.get("location", ""),
                    "secondary": item.get("secondary", ""),
                    "secondaryQty": float(item.get("secondaryQty", 0) or 0),
                    "sec": (
                        f"{int(float(item.get('qty', 0) or 0) // float(item.get('secondaryQty', 0) or 1))} "
                        f"{item.get('secondary', '')} + "
                        f"{int(float(item.get('qty', 0) or 0) % float(item.get('secondaryQty', 0) or 1))} "
                        f"{item.get('unit', '')}"
                        if float(item.get("secondaryQty", 0) or 0) > 0
                        else ""
                    ),
                }
                for item in load.get("items", [])
            ],
            "berat": float(load.get("total_berat", 0) or 0),
            "unit": float(load.get("total_unit", 0) or 0),
            "issued_at": completed_at,
        }

        if transactions:
            await db.transactions.insert_many([dict(txn) for txn in transactions])
        await db.surat_jalan.insert_one(dict(sj))
        await db.outbound_loads.update_one(
            {"id": load_id},
            {"$set": {
                "status": "Selesai",
                "completed_at": completed_at,
                "completed_by": user.get("name", ""),
                "surat_jalan_id": sj_id,
                "surat_jalan_no": sj_no,
            }},
        )

    except Exception:
        await db.transactions.delete_many({"operation_id": operation_id})
        await db.surat_jalan.delete_many({"operation_id": operation_id})
        for product_id, qty in reversed(stock_changes):
            await db.products.update_one({"id": product_id}, {"$inc": {field: qty}})
        raise

    for product_id in {item.get("productId") for item in load.get("items", []) if item.get("productId")}:
        await reconcile_product_allocations(product_id)

    updated = await db.outbound_loads.find_one({"id": load_id}, {"_id": 0})
    return {"load": updated, "suratJalan": sj}
