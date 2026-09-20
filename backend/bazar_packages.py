from __future__ import annotations

from collections import defaultdict
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend.server import db, get_current_user, new_id, next_sequence, normalize_channel, now_iso, operational_now
from backend.role_four_config import has_role_permission, role_destination
from backend.consignment_documents import next_bazar_document_numbers
from backend.consignment_damaged import credit_consignment_damaged
from backend.operational_guards import idempotent_operation, lock_keys
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


async def _restore_package_batches(consumed: list[dict], operator: str) -> None:
    for row in reversed(consumed):
        await db.bazar_package_batches.update_one(
            {"id": row.get("batchId", "")},
            {"$inc": {"remainingQty": _n(row.get("qty"))}, "$set": {"updatedAt": now_iso(), "updatedBy": operator}},
        )


async def _consume_package_batches(template_id: str, qty: float, reference_id: str, operator: str) -> list[dict]:
    remaining = float(qty)
    consumed = []
    batches = await db.bazar_package_batches.find(
        {"templateId": template_id, "remainingQty": {"$gt": EPS}},
        {"_id": 0},
    ).sort("createdAt", 1).to_list(10000)
    try:
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
    except Exception:
        if consumed:
            await _restore_package_batches(consumed, "Sistem (rollback Paket)")
        raise


async def _rollback_damaged_component(event_key: str, product_id: str, channel: str, qty: float) -> None:
    movement = await db.consignment_damaged_movements.find_one({"eventKey": event_key}, {"_id": 0})
    if not movement:
        return
    await db.consignment_damaged_movements.delete_one({"eventKey": event_key})
    await db.consignment_damaged_balances.update_one(
        {"destination": BAZAR, "productId": product_id, "channel": normalize_channel(channel, "KOM")},
        {"$inc": {"qty": -float(qty)}, "$set": {"updatedAt": now_iso()}},
    )


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
async def close_package_load(
    load_id: str,
    body: PackageLoadClose,
    request: Request,
    user: dict = Depends(get_current_user),
):
    _ensure_bazar(user, write=True)
    initial = await db.bazar_package_loads.find_one({"id": load_id}, {"_id": 0})
    if not initial:
        raise HTTPException(status_code=404, detail="Pemuatan paket tidak ditemukan")
    if initial.get("status") == "SELESAI":
        return initial

    product_ids = sorted({
        str(component.get("productId") or "")
        for loaded in initial.get("items", [])
        for component in loaded.get("components", [])
        if str(component.get("productId") or "")
    })
    template_ids = sorted({
        str(item.get("templateId") or "")
        for item in initial.get("items", [])
        if str(item.get("templateId") or "")
    })

    async def action():
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

        # Validate every row before mutating any balance.
        prepared = []
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
            physical = await _package_remaining(loaded["templateId"])
            if consumed_packages > physical + EPS:
                raise HTTPException(
                    status_code=409,
                    detail=f"Stok Paket Jadi {loaded.get('packageName', '')} tinggal {physical:g}",
                )
            prepared.append((loaded, delivered, returned_good, returned_damaged, consumed_packages))

        now = now_iso()
        final_items = []
        batch_rollbacks: list[dict] = []
        movement_events: list[dict] = []
        damaged_events: list[dict] = []
        affected_products: dict[str, str] = {}
        status_saved = False
        history_saved = False

        try:
            for loaded, delivered, returned_good, returned_damaged, consumed_packages in prepared:
                consumed_batches = []
                if consumed_packages > EPS:
                    consumed_batches = await _consume_package_batches(
                        loaded["templateId"],
                        consumed_packages,
                        load_id,
                        user.get("name", ""),
                    )
                    batch_rollbacks.extend(consumed_batches)

                    for component in loaded.get("components", []):
                        per_package = _n(component.get("qty"))
                        qty_component = consumed_packages * per_package
                        damaged_component_qty = returned_damaged * per_package
                        if qty_component <= EPS:
                            continue

                        product_id = component["productId"]
                        event_key = f"package-load-close:{load_id}:{loaded['templateId']}:{product_id}"
                        movement = {
                            "id": new_id(),
                            "eventKey": event_key,
                            "time": now,
                            "destination": BAZAR,
                            "movementType": "PAKET_KELUAR",
                            "referenceId": load_id,
                            "referenceNo": load.get("loadNo", ""),
                            "productId": product_id,
                            "sku": component.get("sku", ""),
                            "name": component.get("name", ""),
                            "unit": component.get("unit", ""),
                            "channel": normalize_channel(component.get("channel"), "KOM"),
                            "delta": -qty_component,
                            "packageTemplateId": loaded["templateId"],
                            "packageQty": consumed_packages,
                            "deliveredPackageQty": delivered,
                            "damagedPackageQty": returned_damaged,
                            "deliveredComponentQty": delivered * per_package,
                            "damagedComponentQty": damaged_component_qty,
                            "operator": user.get("name", ""),
                        }
                        await db.consignment_movements.insert_one(dict(movement))
                        movement_events.append(movement)
                        affected_products[product_id] = component.get("channel", "KOM")

                        await consignment_module.decrease_consignment_layouts(
                            BAZAR,
                            product_id,
                            qty_component,
                            user.get("name", ""),
                            operation_key=event_key,
                        )

                        if damaged_component_qty > EPS:
                            identity = await operations._identity(BAZAR, product_id)
                            damaged_key = f"package-damaged-return:{load_id}:{loaded['templateId']}:{product_id}"
                            await credit_consignment_damaged(
                                BAZAR,
                                {**identity, "productId": product_id, "channel": component.get("channel", "KOM")},
                                damaged_component_qty,
                                damaged_key,
                                "PAKET_RETUR_RUSAK",
                                load_id,
                                load.get("loadNo", ""),
                                user.get("name", ""),
                                body.note,
                            )
                            damaged_events.append({
                                "eventKey": damaged_key,
                                "productId": product_id,
                                "channel": component.get("channel", "KOM"),
                                "qty": damaged_component_qty,
                            })

                final_items.append({
                    **loaded,
                    "deliveredQty": delivered,
                    "returnedGoodQty": returned_good,
                    "returnedDamagedQty": returned_damaged,
                    "consumedBatches": consumed_batches,
                    "damagedComponents": [
                        {
                            **component,
                            "damagedQty": returned_damaged * _n(component.get("qty")),
                        }
                        for component in loaded.get("components", [])
                        if returned_damaged * _n(component.get("qty")) > EPS
                    ],
                })

            result = await db.bazar_package_loads.update_one(
                {"id": load_id, "status": "BERJALAN"},
                {"$set": {
                    "status": "SELESAI",
                    "resultItems": final_items,
                    "closedAt": now,
                    "closedBy": user.get("name", ""),
                    "closeNote": body.note.strip(),
                }},
            )
            if result.matched_count == 0:
                raise HTTPException(status_code=409, detail="Pemuatan Paket berubah saat diselesaikan. Muat ulang lalu coba kembali.")
            status_saved = True

            await operations._history(
                BAZAR,
                "PAKET_SELESAI",
                load_id,
                load.get("loadNo", ""),
                user.get("name", ""),
                final_items,
                body.note,
                {
                    "destinationName": load.get("destination", ""),
                    "vehicleNo": load.get("vehicleNo", ""),
                    "damagedArea": "Area Barang Rusak Bazar",
                    "operationId": f"package-close:{load_id}",
                },
            )
            history_saved = True
            return await db.bazar_package_loads.find_one({"id": load_id}, {"_id": 0})

        except Exception:
            if history_saved:
                await db.consignment_operation_history.delete_many({"operationId": f"package-close:{load_id}"})
            if status_saved:
                await db.bazar_package_loads.update_one(
                    {"id": load_id, "status": "SELESAI"},
                    {"$set": {"status": "BERJALAN"}, "$unset": {
                        "resultItems": "",
                        "closedAt": "",
                        "closedBy": "",
                        "closeNote": "",
                    }},
                )

            for row in reversed(damaged_events):
                await _rollback_damaged_component(
                    row["eventKey"],
                    row["productId"],
                    row["channel"],
                    row["qty"],
                )

            for movement in reversed(movement_events):
                await db.consignment_movements.delete_one({"eventKey": movement["eventKey"]})

            if batch_rollbacks:
                await _restore_package_batches(batch_rollbacks, "Sistem (rollback Paket)")

            # Recompute physical locations from the authoritative movement balance.
            for product_id, channel in affected_products.items():
                try:
                    await consignment_module.sync_consignment_layout_balance(
                        BAZAR,
                        product_id,
                        operator="Sistem (rollback Paket)",
                        operation_key=f"package-close:{load_id}:{product_id}:rollback",
                        note="Rollback penutupan Paket yang tidak selesai.",
                    )
                except Exception:
                    pass
            raise

    keys = lock_keys(
        [f"package-load:{load_id}"],
        (f"package-template:{template_id}" for template_id in template_ids),
        (f"consignment:{BAZAR}:{product_id}" for product_id in product_ids),
        (f"consignment-damaged:{BAZAR}:{product_id}" for product_id in product_ids),
    )
    return await idempotent_operation(
        request,
        user,
        f"package-load-close:{load_id}",
        keys,
        action,
    )

async def ensure_bazar_package_indexes() -> None:
    await db.bazar_package_templates.create_index("code", unique=True, sparse=True, name="bazar_package_code_unique")
    await db.bazar_package_batches.create_index([("templateId", 1), ("createdAt", 1)], name="bazar_package_batch_fifo")
    await db.bazar_package_loads.create_index([("status", 1), ("createdAt", -1)], name="bazar_package_load_status")
