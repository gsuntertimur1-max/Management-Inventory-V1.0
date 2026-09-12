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
from backend.stack_allocations import VALID_STACK_CODES, allocate_stock_to_stack, reconcile_product_allocations

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
    documentNo: str = ""


class OutboundCreateInput(BaseModel):
    items: List[OutboundItemInput] = Field(min_length=1)
    party: str
    ref: str = ""
    polisi: str = ""
    pengambil: str = ""
    kondisi: Literal["BAIK", "RUSAK"] = "BAIK"
    keterangan: str = ""
    documentType: Literal["SO", "TM", "CT", "MEMO"] = "SO"
    transferScope: Literal["", "LOKAL", "REGIONAL", "NASIONAL"] = ""
    documents: List[str] = Field(default_factory=list, max_length=20)
    requestDocument: str = ""
    consignmentDestination: str = ""
    consignmentZone: str = ""


class ReturnItemInput(BaseModel):
    productId: str
    goodQty: float = Field(default=0, ge=0)
    damagedQty: float = Field(default=0, ge=0)
    stackCode: str = ""


class ConsignmentReturnInput(BaseModel):
    documentNo: str
    items: List[ReturnItemInput] = Field(min_length=1)
    note: str = ""
    returnType: Literal["CR", "RETUR"] = "CR"


class SettlementItemInput(BaseModel):
    productId: str
    qty: float = Field(gt=0)


class SettlementInput(BaseModel):
    documentNo: str
    items: List[SettlementItemInput] = Field(min_length=1)
    note: str = ""


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
    refs = []
    for candidate in [body.ref, *body.documents]:
        value = str(candidate or "").strip()
        if value and value not in refs:
            refs.append(value)
    if not refs:
        raise HTTPException(status_code=400, detail=f"Nomor dokumen {body.documentType} wajib diisi")
    expected = {"SO": "SO/", "TM": "TM", "CT": "CT", "MEMO": "MEMO"}[body.documentType]
    if any(not ref.upper().startswith(expected) for ref in refs):
        raise HTTPException(status_code=400, detail=f"Nomor dokumen tidak sesuai jenis {body.documentType}")
    if body.documentType == "TM" and not body.transferScope:
        raise HTTPException(status_code=400, detail="Pilih cakupan Transfer Move")
    for ref in refs:
        if await db.outbound_loads.find_one({"$or": [{"ref": ref}, {"documents": ref}, {"document_links.no": ref}]}):
            raise HTTPException(status_code=409, detail=f"Nomor dokumen {ref} sudah digunakan")

    requested = defaultdict(float)
    item_order = []
    for item in body.items:
        if item.productId not in requested:
            item_order.append(item.productId)
        requested[item.productId] += float(item.qty)

    products = {}
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

    load_items = []
    for item in body.items:
        product = products[item.productId]
        item_ref = item.documentNo.strip() or refs[0]
        if item_ref not in refs:
            raise HTTPException(status_code=400, detail=f"Dokumen komoditas {item_ref} belum didaftarkan")
        qty = float(item.qty)
        weight = float(product.get("weight", 0) or 0)
        load_items.append({"productId": item.productId, "documentNo": item_ref, "sku": product.get("sku", ""), "name": product.get("name", ""), "qty": qty, "unit": product.get("unit", ""), "weight": weight, "berat": weight * qty, "secondary": product.get("secondary", ""), "secondaryQty": float(product.get("secondaryQty", 0) or 0), "location": product.get("location", "")})

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
        "ref": refs[0],
        "documents": refs,
        "polisi": body.polisi.strip(),
        "pengambil": body.pengambil.strip(),
        "unit_loading": unit_loading,
        "kondisi": body.kondisi,
        "keterangan": body.keterangan.strip(),
        "document_type": body.documentType,
        "transfer_scope": body.transferScope if body.documentType == "TM" else "",
        "request_document": body.requestDocument.strip(),
        "consignment_destination": body.consignmentDestination.strip(),
        "consignment_zone": body.consignmentZone.strip(),
        "document_links": [],
        "document_status": "Menunggu Pemuatan",
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
                "document_type": load.get("document_type", "SO"),
                "parent_document": "",
                "request_document": load.get("request_document", ""),
                "consignment_destination": load.get("consignment_destination", ""),
                "consignment_zone": load.get("consignment_zone", ""),
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
            "document_type": load.get("document_type", "SO"),
            "transfer_scope": load.get("transfer_scope", ""),
            "request_document": load.get("request_document", ""),
            "consignment_destination": load.get("consignment_destination", ""),
            "consignment_zone": load.get("consignment_zone", ""),
            "documents": load.get("documents", [load.get("ref", "")]),
            "items": [
                {
                    "name": item.get("name", ""),
                    "sku": item.get("sku", ""),
                    "qty": float(item.get("qty", 0) or 0),
                    "unit": item.get("unit", ""),
                    "berat": float(item.get("berat", 0) or 0),
                    "location": item.get("location", ""),
                    "documentNo": item.get("documentNo", load.get("ref", "")),
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
                "document_status": "Menunggu CR/SO" if load.get("document_type") == "CT" else "Menunggu SO/Retur" if load.get("document_type") == "MEMO" else "Selesai",
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


def _linked_totals(load: dict, product_id: str) -> tuple[float, float]:
    returned = sold = 0.0
    for link in load.get("document_links", []):
        for item in link.get("items", []):
            if item.get("productId") != product_id:
                continue
            if link.get("type") in {"CR", "RETUR"}:
                returned += float(item.get("goodQty", 0) or 0) + float(item.get("damagedQty", 0) or 0)
            elif link.get("type") == "SO":
                sold += float(item.get("qty", 0) or 0)
    return returned, sold


@router.post("/outbound-loads/{load_id}/return")
async def create_consignment_return(load_id: str, body: ConsignmentReturnInput, user: dict = Depends(require_write)):
    load = await db.outbound_loads.find_one({"id": load_id}, {"_id": 0})
    if not load or load.get("document_type") not in {"CT", "MEMO"} or load.get("status") != "Selesai":
        raise HTTPException(status_code=400, detail="Pengembalian hanya dapat dibuat dari CT atau Memo yang sudah selesai dimuat")
    expected_return = "CR" if load.get("document_type") == "CT" else "RETUR"
    if body.returnType != expected_return:
        raise HTTPException(status_code=400, detail=f"Dokumen {load.get('document_type')} harus menggunakan {expected_return}")
    document_no = body.documentNo.strip()
    valid_prefix = ("CR",) if body.returnType == "CR" else ("RT", "RET", "RM")
    if not document_no.upper().startswith(valid_prefix):
        raise HTTPException(status_code=400, detail=f"Nomor pengembalian harus berupa dokumen {body.returnType}")
    if await db.outbound_loads.find_one({"$or": [{"ref": document_no}, {"document_links.no": document_no}]}):
        raise HTTPException(status_code=409, detail="Nomor CR sudah digunakan")
    if len({item.productId for item in body.items}) != len(body.items):
        raise HTTPException(status_code=400, detail="Produk retur tidak boleh dicatat lebih dari satu baris")

    original = {item.get("productId"): item for item in load.get("items", [])}
    link_items, stock_changes = [], []
    try:
        for item in body.items:
            source = original.get(item.productId)
            if not source:
                raise HTTPException(status_code=400, detail="Produk retur tidak terdapat pada dokumen induk")
            qty = float(item.goodQty) + float(item.damagedQty)
            if qty <= 0:
                continue
            returned, sold = _linked_totals(load, item.productId)
            if qty > float(source.get("qty", 0) or 0) - returned - sold + 1e-9:
                raise HTTPException(status_code=400, detail=f"Jumlah retur {source.get('name', '')} melebihi sisa dokumen")
            product = await db.products.find_one({"id": item.productId}, {"_id": 0})
            if not product:
                raise HTTPException(status_code=404, detail="Produk pengembalian tidak ditemukan")
            if item.goodQty and item.stackCode.strip().upper() not in VALID_STACK_CODES:
                raise HTTPException(status_code=400, detail=f"Pilih lokasi tumpukan untuk barang Good {source.get('name', '')}")
            if item.goodQty:
                await db.products.update_one({"id": item.productId}, {"$inc": {"stock": float(item.goodQty)}})
                stock_changes.append((item.productId, "stock", float(item.goodQty)))
                if item.stackCode.strip():
                    await allocate_stock_to_stack(product, item.stackCode, float(item.goodQty), user.get("name", ""))
            if item.damagedQty:
                await db.products.update_one({"id": item.productId}, {"$inc": {"damaged": float(item.damagedQty)}})
                stock_changes.append((item.productId, "damaged", float(item.damagedQty)))
            link_items.append({"productId": item.productId, "name": source.get("name", ""), "unit": source.get("unit", ""), "goodQty": float(item.goodQty), "damagedQty": float(item.damagedQty), "stackCode": item.stackCode.strip().upper()})
        if not link_items:
            raise HTTPException(status_code=400, detail="Isi jumlah barang yang dikembalikan")
        link = {"id": new_id(), "type": body.returnType, "no": document_no, "time": now_iso(), "items": link_items, "note": body.note.strip(), "operator": user.get("name", "")}
        prospective = {**load, "document_links": [*load.get("document_links", []), link]}
        complete = all(sum(_linked_totals(prospective, product_id)) >= float(source.get("qty", 0) or 0) - 1e-9 for product_id, source in original.items())
        status = "Selesai Dokumen" if complete else f"{body.returnType} Tercatat · Menunggu SO"
        await db.outbound_loads.update_one({"id": load_id}, {"$push": {"document_links": link}, "$set": {"document_status": status}})
        txns = [{"id": new_id(), "load_id": load_id, "time": link["time"], "ref": document_no, "type": "MASUK", "kondisi": "PENGEMBALIAN", "document_type": body.returnType, "parent_document": load.get("ref", ""), "product": x["name"], "change": x["goodQty"] + x["damagedQty"], "good_change": x["goodQty"], "damaged_change": x["damagedQty"], "unit": x["unit"], "penerima": load.get("party", ""), "operator": user.get("name", ""), "keterangan": body.note.strip()} for x in link_items]
        await db.transactions.insert_many(txns)
        return link
    except Exception:
        for product_id, field, qty in reversed(stock_changes):
            await db.products.update_one({"id": product_id}, {"$inc": {field: -qty}})
        raise


@router.post("/outbound-loads/{load_id}/settle")
async def settle_outbound_document(load_id: str, body: SettlementInput, user: dict = Depends(require_write)):
    load = await db.outbound_loads.find_one({"id": load_id}, {"_id": 0})
    if not load or load.get("document_type") not in {"CT", "MEMO"} or load.get("status") != "Selesai":
        raise HTTPException(status_code=400, detail="SO lanjutan hanya dapat dibuat dari CT atau Memo yang selesai")
    document_no = body.documentNo.strip()
    if not document_no.upper().startswith("SO/"):
        raise HTTPException(status_code=400, detail="Nomor penyelesaian harus berupa dokumen SO")
    if await db.outbound_loads.find_one({"$or": [{"ref": document_no}, {"document_links.no": document_no}]}):
        raise HTTPException(status_code=409, detail="Nomor SO sudah digunakan")
    if len({item.productId for item in body.items}) != len(body.items):
        raise HTTPException(status_code=400, detail="Produk SO tidak boleh dicatat lebih dari satu baris")
    original = {item.get("productId"): item for item in load.get("items", [])}
    items = []
    for item in body.items:
        source = original.get(item.productId)
        if not source:
            raise HTTPException(status_code=400, detail="Produk SO tidak terdapat pada dokumen induk")
        returned, sold = _linked_totals(load, item.productId)
        if float(item.qty) > float(source.get("qty", 0) or 0) - returned - sold + 1e-9:
            raise HTTPException(status_code=400, detail=f"Jumlah SO {source.get('name', '')} melebihi sisa dokumen")
        items.append({"productId": item.productId, "name": source.get("name", ""), "unit": source.get("unit", ""), "qty": float(item.qty)})
    link = {"id": new_id(), "type": "SO", "no": document_no, "time": now_iso(), "items": items, "note": body.note.strip(), "operator": user.get("name", "")}
    prospective = {**load, "document_links": [*load.get("document_links", []), link]}
    complete = all(sum(_linked_totals(prospective, pid)) >= float(source.get("qty", 0) or 0) - 1e-9 for pid, source in original.items())
    await db.outbound_loads.update_one({"id": load_id}, {"$push": {"document_links": link}, "$set": {"document_status": "Selesai Dokumen" if complete else "SO Sebagian · Belum Selesai"}})
    await db.transactions.insert_many([{"id": new_id(), "load_id": load_id, "time": link["time"], "ref": document_no, "type": "DOKUMEN", "kondisi": "—", "document_type": "SO", "parent_document": load.get("ref", ""), "product": item["name"], "change": 0, "settled_qty": item["qty"], "unit": item["unit"], "penerima": load.get("party", ""), "operator": user.get("name", ""), "keterangan": body.note.strip()} for item in items])
    return link
