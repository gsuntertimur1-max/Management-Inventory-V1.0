from __future__ import annotations

from collections import defaultdict
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.server import db, get_current_user, new_id, next_sequence, normalize_channel, now_iso, operational_now
from backend.role_four_config import has_role_permission, role_destination
from backend.consignment_documents import next_bazar_document_numbers
import backend.consignment as consignment_module
import backend.consignment_operations as operations

router = APIRouter(prefix="/api")
BAZAR = operations.BAZAR
EPS = operations.EPS


def _n(value) -> float:
    return operations._n(value)


def _ensure_bazar(user: dict, write: bool = False) -> None:
    scoped = role_destination(user.get("role"))
    if scoped and scoped != BAZAR:
        raise HTTPException(status_code=403, detail=f"Akun ini hanya memiliki akses ke {scoped}")
    permission = "bazarOps" if write else "bazarView"
    if not has_role_permission(user.get("role"), permission):
        raise HTTPException(status_code=403, detail="Tidak memiliki akses ke operasional Bazar")


class PackageComponentInput(BaseModel):
    productId: str
    qty: float = Field(gt=0)


class PackageTemplateCreate(BaseModel):
    code: str
    name: str
    components: List[PackageComponentInput] = Field(min_length=1)
    note: str = ""


class PackageAssembleInput(BaseModel):
    templateId: str
    qty: float = Field(gt=0)
    note: str = ""


class PackageUnpackInput(BaseModel):
    qty: float = Field(gt=0)
    note: str = ""


class PackageLoadItem(BaseModel):
    templateId: str
    qty: float = Field(gt=0)


class PackageLoadCreate(BaseModel):
    date: str = ""
    destination: str
    vehicleNo: str
    driver: str = ""
    items: List[PackageLoadItem] = Field(min_length=1)
    note: str = ""


class PackageLoadCloseItem(BaseModel):
    templateId: str
    deliveredQty: float = Field(ge=0)
    returnedGoodQty: float = Field(ge=0)
    returnedDamagedQty: float = Field(default=0, ge=0)


class PackageLoadClose(BaseModel):
    items: List[PackageLoadCloseItem] = Field(min_length=1)
    note: str = ""


async def _template(template_id: str) -> dict:
    doc = await db.bazar_package_templates.find_one({"id": template_id, "active": {"$ne": False}}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Master paket tidak ditemukan")
    return doc


async def _package_reserved(template_id: str, exclude_load_id: str = "") -> float:
    reserved = 0.0
    loads = await db.bazar_package_loads.find({"status": "BERJALAN"}, {"_id": 0, "id": 1, "items": 1}).to_list(5000)
    for load in loads:
        if exclude_load_id and load.get("id") == exclude_load_id:
            continue
        for item in load.get("items", []):
            if item.get("templateId") == template_id:
                reserved += _n(item.get("loadedQty"))
    return reserved


async def _package_remaining(template_id: str) -> float:
    batches = await db.bazar_package_batches.find(
        {"templateId": template_id, "remainingQty": {"$gt": EPS}},
        {"_id": 0, "remainingQty": 1},
    ).to_list(10000)
    return sum(_n(row.get("remainingQty")) for row in batches)


async def package_availability(template_id: str, exclude_load_id: str = "") -> tuple[float, float, float]:
    physical = await _package_remaining(template_id)
    reserved = await _package_reserved(template_id, exclude_load_id)
    return physical, reserved, max(physical - reserved, 0.0)


async def component_package_hold(product_id: str) -> float:
    """Jumlah komponen yang sudah dirakit menjadi Paket Jadi dan belum tersalurkan/dibongkar."""
    hold = 0.0
    batches = await db.bazar_package_batches.find({"remainingQty": {"$gt": EPS}}, {"_id": 0}).to_list(10000)
    template_cache: dict[str, dict] = {}
    for batch in batches:
        template_id = str(batch.get("templateId") or "")
        if not template_id:
            continue
        template = template_cache.get(template_id)
        if template is None:
            template = await db.bazar_package_templates.find_one({"id": template_id}, {"_id": 0}) or {}
            template_cache[template_id] = template
        component = next((x for x in template.get("components", []) if x.get("productId") == product_id), None)
        if component:
            hold += _n(batch.get("remainingQty")) * _n(component.get("qty"))
    return hold


_base_available = operations._available


async def _available_with_packages(destination: str, product_id: str, exclude_kind: str = "", exclude_id: str = "") -> tuple[float, float, float]:
    physical, reserved, _ = await _base_available(destination, product_id, exclude_kind, exclude_id)
    if destination == BAZAR:
        reserved += await component_package_hold(product_id)
    return physical, reserved, max(physical - reserved, 0.0)


# Existing Bazar trip and availability routes resolve this module variable at request time,
# so loose stock automatically excludes components already assembled into packages.
operations._available = _available_with_packages


async def _consume_package_batches(template_id: str, qty: float, reference_id: str, operator: str) -> list[dict]:
    remaining = float(qty)
    consumed = []
    batches = await db.bazar_package_batches.find(
        {"templateId": template_id, "remainingQty": {"$gt": EPS}},
        {"_id": 0},
    ).sort("createdAt", 1).to_list(10000)
    for batch in batches:
        if remaining <= EPS:
            break
        take = min(_n(batch.get("remainingQty")), remaining)
        if take <= EPS:
            continue
        result = await db.bazar_package_batches.update_one(
            {"id": batch["id"], "remainingQty": {"$gte": take}},
            {"$inc": {"remainingQty": -take}, "$set": {"updatedAt": now_iso(), "updatedBy": operator}},
        )
        if result.matched_count == 0:
            raise HTTPException(status_code=409, detail="Stok Paket Jadi berubah. Muat ulang lalu coba kembali.")
        consumed.append({"batchId": batch["id"], "batchNo": batch.get("batchNo", ""), "qty": take})
        remaining -= take
    if remaining > EPS:
        raise HTTPException(status_code=409, detail="Stok Paket Jadi tidak mencukupi")
    return consumed


@router.get("/bazar/package-templates")
async def list_package_templates(user: dict = Depends(get_current_user)):
    _ensure_bazar(user, write=False)
    return await db.bazar_package_templates.find({"active": {"$ne": False}}, {"_id": 0}).sort("name", 1).to_list(5000)


@router.post("/bazar/package-templates")
async def create_package_template(body: PackageTemplateCreate, user: dict = Depends(get_current_user)):
    _ensure_bazar(user, write=True)
    code = body.code.strip().upper()
    name = body.name.strip()
    if not code or not name:
        raise HTTPException(status_code=400, detail="Kode dan nama paket wajib diisi")
    if await db.bazar_package_templates.find_one({"code": code, "active": {"$ne": False}}):
        raise HTTPException(status_code=409, detail="Kode paket sudah digunakan")
    grouped = defaultdict(float)
    for component in body.components:
        grouped[component.productId] += float(component.qty)
    components = []
    for product_id, qty in grouped.items():
        identity = await operations._identity(BAZAR, product_id)
        components.append({
            "productId": product_id, "sku": identity.get("sku", ""), "name": identity.get("name", ""),
            "unit": identity.get("unit", ""), "channel": normalize_channel(identity.get("channel"), "KOM"),
            "qty": qty,
        })
    doc = {
        "id": new_id(), "code": code, "name": name, "components": components, "note": body.note.strip(),
        "active": True, "createdAt": now_iso(), "createdBy": user.get("name", ""),
    }
    await db.bazar_package_templates.insert_one(dict(doc))
    await operations._history(BAZAR, "PAKET_MASTER_DIBUAT", doc["id"], code, user.get("name", ""), components, body.note,
                              {"packageName": name})
    return doc


@router.get("/bazar/package-stock")
async def list_package_stock(user: dict = Depends(get_current_user)):
    _ensure_bazar(user, write=False)
    result = []
    templates = await db.bazar_package_templates.find({"active": {"$ne": False}}, {"_id": 0}).sort("name", 1).to_list(5000)
    for template in templates:
        physical, reserved, available = await package_availability(template["id"])
        result.append({**template, "assembledQty": physical, "reservedQty": reserved, "availableQty": available})
    return result


@router.post("/bazar/packages/assemble")
async def assemble_package(body: PackageAssembleInput, user: dict = Depends(get_current_user)):
    _ensure_bazar(user, write=True)
    template = await _template(body.templateId)
    package_qty = float(body.qty)
    requirements = []
    for component in template.get("components", []):
        required = package_qty * _n(component.get("qty"))
        _, _, available = await operations._available(BAZAR, component["productId"])
        if required > available + EPS:
            raise HTTPException(
                status_code=409,
                detail=f"Stok loose {component.get('name', '')} hanya {available:g} {component.get('unit', '')}; kebutuhan paket {required:g}",
            )
        requirements.append({**component, "requiredQty": required})

    today = operational_now().strftime("%Y%m%d")
    seq = await next_sequence(f"bazar-package-batch:{today}")
    batch_no = f"PKT-{today}-{seq:03d}"
    now = now_iso()
    doc = {
        "id": new_id(), "batchNo": batch_no, "templateId": template["id"], "packageCode": template.get("code", ""),
        "packageName": template.get("name", ""), "components": template.get("components", []),
        "assembledQty": package_qty, "remainingQty": package_qty, "note": body.note.strip(),
        "createdAt": now, "createdBy": user.get("name", ""),
    }
    await db.bazar_package_batches.insert_one(dict(doc))
    await operations._history(BAZAR, "PAKET_DIRAKIT", doc["id"], batch_no, user.get("name", ""), requirements, body.note,
                              {"packageCode": template.get("code", ""), "packageName": template.get("name", ""), "packageQty": package_qty})
    return doc


@router.get("/bazar/package-batches")
async def list_package_batches(user: dict = Depends(get_current_user)):
    _ensure_bazar(user, write=False)
    return await db.bazar_package_batches.find({}, {"_id": 0}).sort("createdAt", -1).to_list(10000)


@router.post("/bazar/package-batches/{batch_id}/unpack")
async def unpack_package(batch_id: str, body: PackageUnpackInput, user: dict = Depends(get_current_user)):
    _ensure_bazar(user, write=True)
    batch = await db.bazar_package_batches.find_one({"id": batch_id}, {"_id": 0})
    if not batch:
        raise HTTPException(status_code=404, detail="Batch paket tidak ditemukan")
    qty = float(body.qty)
    template_id = batch.get("templateId", "")
    physical, reserved, available = await package_availability(template_id)
    batch_remaining = _n(batch.get("remainingQty"))
    max_unpack = min(batch_remaining, available)
    if qty > max_unpack + EPS:
        raise HTTPException(status_code=409, detail=f"Paket yang bebas dibongkar pada batch ini maksimal {max_unpack:g}")
    result = await db.bazar_package_batches.update_one(
        {"id": batch_id, "remainingQty": {"$gte": qty}},
        {"$inc": {"remainingQty": -qty}, "$set": {"updatedAt": now_iso(), "updatedBy": user.get("name", "")}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=409, detail="Stok paket berubah. Muat ulang lalu coba kembali.")
    await operations._history(BAZAR, "PAKET_DIBONGKAR", batch_id, batch.get("batchNo", ""), user.get("name", ""),
                              batch.get("components", []), body.note, {"packageQty": qty, "packageName": batch.get("packageName", "")})
    return await db.bazar_package_batches.find_one({"id": batch_id}, {"_id": 0})


@router.get("/bazar/package-loads")
async def list_package_loads(user: dict = Depends(get_current_user)):
    _ensure_bazar(user, write=False)
    return await db.bazar_package_loads.find({}, {"_id": 0}).sort("createdAt", -1).to_list(5000)


@router.post("/bazar/package-loads")
async def create_package_load(body: PackageLoadCreate, user: dict = Depends(get_current_user)):
    _ensure_bazar(user, write=True)
    if not body.destination.strip() or not body.vehicleNo.strip():
        raise HTTPException(status_code=400, detail="Tujuan dan nomor kendaraan wajib diisi")
    grouped = defaultdict(float)
    for item in body.items:
        grouped[item.templateId] += float(item.qty)
    items = []
    for template_id, qty in grouped.items():
        template = await _template(template_id)
        _, _, available = await package_availability(template_id)
        if qty > available + EPS:
            raise HTTPException(status_code=409, detail=f"Paket {template.get('name', '')} tersedia hanya {available:g}")
        items.append({
            "templateId": template_id,
            "packageCode": template.get("code", ""),
            "packageName": template.get("name", ""),
            "components": template.get("components", []),
            "loadedQty": qty,
        })

    today = operational_now().strftime("%Y%m%d")
    seq = await next_sequence(f"bazar-package-load:{today}")
    load_no = f"PKL-{today}-{seq:03d}"
    event_date = body.date or operational_now().strftime("%Y-%m-%d")
    document_numbers = await next_bazar_document_numbers("PAKET", event_date)

    flattened = defaultdict(float)
    for loaded in items:
        for component in loaded.get("components", []):
            flattened[component["productId"]] += _n(loaded.get("loadedQty")) * _n(component.get("qty"))
    document_items = []
    for product_id, qty in flattened.items():
        identity = await operations._identity(BAZAR, product_id)
        document_items.append({
            "productId": product_id,
            "sku": identity.get("sku", ""),
            "name": identity.get("name", ""),
            "unit": identity.get("unit", ""),
            "channel": normalize_channel(identity.get("channel"), "KOM"),
            "weight": _n(identity.get("weight")),
            "measureUnit": identity.get("measureUnit", "kg") or "kg",
            "secondary": identity.get("secondary", ""),
            "secondaryQty": _n(identity.get("secondaryQty")),
            "stackCode": "AREA PAKET BAZAR",
            "qty": qty,
            "documentNo": load_no,
        })

    now = now_iso()
    doc = {
        "id": new_id(),
        "loadNo": load_no,
        "date": event_date,
        "destination": body.destination.strip(),
        "vehicleNo": body.vehicleNo.strip().upper(),
        "driver": body.driver.strip(),
        "items": items,
        "documentItems": document_items,
        "status": "BERJALAN",
        "bonNo": document_numbers["bonNo"],
        "suratJalanNo": document_numbers["suratJalanNo"],
        "note": body.note.strip(),
        "createdAt": now,
        "createdBy": user.get("name", ""),
    }
    await db.bazar_package_loads.insert_one(dict(doc))
    await operations._history(
        BAZAR,
        "PAKET_DIMUAT",
        doc["id"],
        load_no,
        user.get("name", ""),
        items,
        body.note,
        {
            "destinationName": doc["destination"],
            "vehicleNo": doc["vehicleNo"],
            "bonNo": doc["bonNo"],
            "suratJalanNo": doc["suratJalanNo"],
        },
    )
    return doc


@router.post("/bazar/package-loads/{load_id}/close")
async def close_package_load(load_id: str, body: PackageLoadClose, user: dict = Depends(get_current_user)):
    _ensure_bazar(user, write=True)
    load = await db.bazar_package_loads.find_one({"id": load_id}, {"_id": 0})
    if not load:
        raise HTTPException(status_code=404, detail="Pemuatan paket tidak ditemukan")
    if load.get("status") == "SELESAI":
        return load
    if load.get("status") != "BERJALAN":
        raise HTTPException(status_code=409, detail="Pemuatan paket tidak dapat diselesaikan dari status saat ini")

    result_map = {item.templateId: item for item in body.items}
    expected = {item.get("templateId") for item in load.get("items", [])}
    if set(result_map) != expected:
        raise HTTPException(status_code=400, detail="Rekonsiliasi harus mencakup seluruh jenis paket yang dimuat")

    now = now_iso()
    final_items = []
    for loaded in load.get("items", []):
        result = result_map[loaded["templateId"]]
        delivered = float(result.deliveredQty)
        returned_good = float(result.returnedGoodQty)
        returned_damaged = float(result.returnedDamagedQty)
        loaded_qty = _n(loaded.get("loadedQty"))
        if abs((delivered + returned_good + returned_damaged) - loaded_qty) > EPS:
            raise HTTPException(
                status_code=400,
                detail=f"{loaded.get('packageName', '')}: Disalurkan + Retur Baik + Retur Rusak harus sama dengan jumlah muat {loaded_qty:g}",
            )
        consumed_packages = delivered + returned_damaged
        consumed_batches = []
        if consumed_packages > EPS:
            consumed_batches = await _consume_package_batches(loaded["templateId"], consumed_packages, load_id, user.get("name", ""))
            for component in loaded.get("components", []):
                qty_component = consumed_packages * _n(component.get("qty"))
                event_key = f"package-load-close:{load_id}:{loaded['templateId']}:{component['productId']}"
                movement = {
                    "id": new_id(), "eventKey": event_key, "time": now, "destination": BAZAR,
                    "movementType": "PAKET_DISALURKAN", "referenceId": load_id, "referenceNo": load.get("loadNo", ""),
                    "productId": component["productId"], "sku": component.get("sku", ""), "name": component.get("name", ""),
                    "unit": component.get("unit", ""), "channel": component.get("channel", "KOM"), "delta": -qty_component,
                    "packageTemplateId": loaded["templateId"], "packageQty": consumed_packages,
                    "deliveredPackageQty": delivered, "damagedPackageQty": returned_damaged,
                    "operator": user.get("name", ""),
                }
                await db.consignment_movements.update_one({"eventKey": event_key}, {"$setOnInsert": movement}, upsert=True)
                await consignment_module.decrease_consignment_layouts(
                    BAZAR,
                    component["productId"],
                    qty_component,
                    user.get("name", ""),
                    operation_key=event_key,
                )
        final_items.append({
            **loaded, "deliveredQty": delivered, "returnedGoodQty": returned_good,
            "returnedDamagedQty": returned_damaged, "consumedBatches": consumed_batches,
        })

    await db.bazar_package_loads.update_one({"id": load_id, "status": "BERJALAN"}, {"$set": {
        "status": "SELESAI", "resultItems": final_items, "closedAt": now,
        "closedBy": user.get("name", ""), "closeNote": body.note.strip(),
    }})
    await operations._history(BAZAR, "PAKET_SELESAI", load_id, load.get("loadNo", ""), user.get("name", ""), final_items, body.note,
                              {"destinationName": load.get("destination", ""), "vehicleNo": load.get("vehicleNo", "")})
    return await db.bazar_package_loads.find_one({"id": load_id}, {"_id": 0})


async def ensure_bazar_package_indexes() -> None:
    await db.bazar_package_templates.create_index("code", unique=True, sparse=True, name="bazar_package_code_unique")
    await db.bazar_package_batches.create_index([("templateId", 1), ("createdAt", 1)], name="bazar_package_batch_fifo")
    await db.bazar_package_loads.create_index([("status", 1), ("createdAt", -1)], name="bazar_package_load_status")
