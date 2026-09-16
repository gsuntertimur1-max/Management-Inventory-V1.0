from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.server import (
    channel_balance,
    db,
    ensure_channel_stock,
    max_suffix,
    new_id,
    next_sequence,
    normalize_channel,
    now_iso,
    operational_now,
    require_write,
)
from backend.outbound_flow import (
    OutboundCreateInput,
    _crew_group,
    _loading_fee,
    _reserved_qty,
    _validate_pack_qty,
    _weighing_entries,
)
from backend.operational_guards import (
    document_lock_keys,
    guarded_create_outbound as base_guarded_create_outbound,
    idempotent_operation,
    lock_keys,
    product_lock_keys,
)

router = APIRouter(prefix="/api")
DAMAGED_AREA = "AREA BARANG RUSAK"
DAMAGED_QUEUE_PREFIX = "R"


def damaged_loading_context() -> tuple[str, str]:
    return DAMAGED_AREA, DAMAGED_QUEUE_PREFIX


async def create_damaged_outbound_load(body: OutboundCreateInput, user: dict) -> dict:
    if body.kondisi != "RUSAK":
        raise HTTPException(status_code=400, detail="Jalur Area Barang Rusak hanya untuk stok kondisi RUSAK")

    party = body.party.strip()
    if not party:
        raise HTTPException(status_code=400, detail="Penerima barang wajib diisi")
    if body.weighingForm and (body.grossWeight <= 0 or body.grossMin <= 0 or body.grossMax <= 0):
        raise HTTPException(status_code=400, detail="Rata-rata bruto serta rentang timbang harus diisi")
    if body.weighingForm and not body.grossMin <= body.grossWeight <= body.grossMax:
        raise HTTPException(status_code=400, detail="Rata-rata bruto harus berada di dalam rentang timbang")

    refs: list[str] = []
    for candidate in [body.ref, *body.documents]:
        value = str(candidate or "").strip()
        if value and value not in refs:
            refs.append(value)
    if not refs:
        raise HTTPException(status_code=400, detail=f"Nomor dokumen {body.documentType} wajib diisi")
    expected = {"SO": "SO/", "TM": "TM", "CT": "CT", "ND": "ND", "MEMO": "MEMO"}[body.documentType]
    if any(not ref.upper().startswith(expected) for ref in refs):
        raise HTTPException(status_code=400, detail=f"Nomor dokumen tidak sesuai jenis {body.documentType}")
    if body.documentType == "TM" and not body.transferScope:
        raise HTTPException(status_code=400, detail="Pilih cakupan Transfer Move")
    if body.consignmentDestination and body.documentType not in {"MEMO", "ND"}:
        raise HTTPException(status_code=400, detail="Stok Gudang Bazar/E-commerce harus dicatat menggunakan Memo atau ND")
    if body.consignmentDestination and body.consignmentDestination not in {"Gudang Bazar", "Gudang E-commerce"}:
        raise HTTPException(status_code=400, detail="Tujuan konsinyasi tidak valid")

    item_document_refs = [str(item.documentNo or "").strip() for item in body.items]
    if len(refs) > 1:
        if any(not item_ref for item_ref in item_document_refs):
            raise HTTPException(status_code=400, detail="Pilih nomor dokumen pada setiap komoditas untuk pemuatan multi-dokumen")
        unknown_refs = sorted({item_ref for item_ref in item_document_refs if item_ref not in refs})
        if unknown_refs:
            raise HTTPException(status_code=400, detail=f"Dokumen komoditas belum didaftarkan: {', '.join(unknown_refs)}")
        unassigned_refs = [ref for ref in refs if ref not in item_document_refs]
        if unassigned_refs:
            raise HTTPException(status_code=400, detail=f"Dokumen belum memiliki komoditas: {', '.join(unassigned_refs)}")
    elif any(item_ref and item_ref not in refs for item_ref in item_document_refs):
        raise HTTPException(status_code=400, detail="Dokumen komoditas belum didaftarkan")

    for ref in refs:
        if await db.outbound_loads.find_one({"$or": [{"ref": ref}, {"documents": ref}, {"document_links.no": ref}]}):
            raise HTTPException(status_code=409, detail=f"Nomor dokumen {ref} sudah digunakan")

    requested: dict[str, float] = defaultdict(float)
    item_order: list[str] = []
    for item in body.items:
        if item.productId not in requested:
            item_order.append(item.productId)
        requested[item.productId] += float(item.qty)

    products: dict[str, dict] = {}
    for product_id in item_order:
        qty = requested[product_id]
        product = await db.products.find_one({"id": product_id}, {"_id": 0})
        if not product:
            raise HTTPException(status_code=404, detail="Produk pengeluaran tidak ditemukan")
        _validate_pack_qty(product, qty)
        products[product_id] = product
        physical = float(product.get("damaged", 0) or 0)
        reserved = await _reserved_qty(product_id, "RUSAK")
        available = max(physical - reserved, 0)
        if qty > available + 1e-9:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Stok rusak tersedia untuk {product.get('name', 'produk')} tidak mencukupi. "
                    f"Fisik {physical:g}, sudah dialokasikan {reserved:g}, tersedia {available:g} {product.get('unit', '')}"
                ),
            )

    channel_requested: dict[tuple[str, str], float] = defaultdict(float)
    for item in body.items:
        channel = normalize_channel(item.channel, normalize_channel(products[item.productId].get("channel")))
        channel_requested[(item.productId, channel)] += float(item.qty)
    for (product_id, channel), qty in channel_requested.items():
        product = products[product_id]
        await ensure_channel_stock(product)
        reserved = await _reserved_qty(product_id, "RUSAK", channel=channel)
        available = max(channel_balance(product, channel, "damaged") - reserved, 0)
        if qty > available + 1e-9:
            raise HTTPException(status_code=400, detail=f"Stok rusak {channel} untuk {product.get('name', 'produk')} tidak mencukupi. Tersedia {available:g} {product.get('unit', '')}")

    load_items = []
    for item in body.items:
        product = products[item.productId]
        item_ref = item.documentNo.strip() or refs[0]
        if item_ref not in refs:
            raise HTTPException(status_code=400, detail=f"Dokumen komoditas {item_ref} belum didaftarkan")
        qty = float(item.qty)
        weight = float(product.get("weight", 0) or 0)
        channel = normalize_channel(item.channel, normalize_channel(product.get("channel")))
        load_items.append({
            "productId": item.productId,
            "documentNo": item_ref,
            "sku": product.get("sku", ""),
            "name": product.get("name", ""),
            "channel": channel,
            "qty": qty,
            "unit": product.get("unit", ""),
            "weight": weight,
            "measureUnit": product.get("measureUnit", "kg") or "kg",
            "berat": weight * qty,
            "secondary": product.get("secondary", ""),
            "secondaryQty": float(product.get("secondaryQty", 0) or 0),
            "location": DAMAGED_AREA,
            "stackCode": "",
            "crewGroup": DAMAGED_AREA,
            "loadingFee": _loading_fee(product, qty, charge_mode_override=body.loadingFeeChargeMode),
        })

    unit_loading, queue_prefix = damaged_loading_context()
    op_now = operational_now()
    operational_date = op_now.strftime("%Y-%m-%d")
    queue_floor = await max_suffix(db.outbound_loads, "antrian", f"{queue_prefix}-", {"operational_date": operational_date})
    queue_number = await next_sequence(f"loading-queue:{operational_date}:{queue_prefix}", queue_floor)
    bon_prefix = f"BM-{op_now.strftime('%Y%m%d')}-"
    bon_floor = await max_suffix(db.outbound_loads, "bon_no", bon_prefix, {"operational_date": operational_date})
    bon_number = await next_sequence(f"bon-muat:{operational_date}", bon_floor)

    total_unit = sum(float(item["qty"]) for item in load_items)
    total_berat = sum(float(item["berat"]) for item in load_items)
    loading_cost = {key: sum(float(item.get("loadingFee", {}).get(key, 0) or 0) for item in load_items) for key in ("labor", "daily", "warehouse", "total", "chargeable")}
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
        "crew_groups": [DAMAGED_AREA],
        "kondisi": "RUSAK",
        "keterangan": body.keterangan.strip(),
        "document_type": body.documentType,
        "transfer_scope": body.transferScope if body.documentType == "TM" else "",
        "request_document": body.requestDocument.strip(),
        "dispatch_purpose": body.dispatchPurpose if body.documentType in {"MEMO", "ND"} else "",
        "consignment_destination": body.consignmentDestination.strip(),
        "consignment_zone": body.consignmentZone.strip(),
        "weighing_form": body.weighingForm,
        "gross_weight": float(body.grossWeight) if body.weighingForm else 0,
        "gross_min": float(body.grossMin) if body.weighingForm else 0,
        "gross_max": float(body.grossMax) if body.weighingForm else 0,
        "weighing_entries": _weighing_entries(float(body.grossWeight), float(body.grossMin), float(body.grossMax)) if body.weighingForm else [],
        "document_links": [],
        "document_status": "Menunggu Pemuatan",
        "loading_cost": loading_cost,
        "loading_fee_payments": [],
        "loading_fee_payment_total": 0.0,
        "loading_fee_payment_status": "TIDAK_DITAGIH" if loading_cost["chargeable"] <= 0 else "BELUM_DIBAYAR",
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


@router.post("/outbound-loads")
async def guarded_create_outbound(body: OutboundCreateInput, request: Request, user: dict = Depends(require_write)):
    if body.kondisi != "RUSAK":
        return await base_guarded_create_outbound(body, request, user)
    refs = [body.ref, *body.documents]
    keys = lock_keys(product_lock_keys(item.productId for item in body.items), document_lock_keys(refs))
    return await idempotent_operation(
        request,
        user,
        "outbound-create",
        keys,
        lambda: create_damaged_outbound_load(body, user),
    )
