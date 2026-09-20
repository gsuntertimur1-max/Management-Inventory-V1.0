import re
from typing import Literal, List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from pymongo import ReturnDocument

from backend.server import build_xlsx, db, get_current_user, new_id, now_iso, operational_now, normalize_channel
from backend.role_four_config import has_role_permission, role_destination

router = APIRouter(prefix="/api")

DESTINATIONS = {"Gudang Bazar", "Gudang E-commerce"}

from backend.consignment_locations import BAZAR as BAZAR_DESTINATION, consignment_stack_codes, normalize_consignment_stack_code


async def ensure_consignment_location_codes() -> None:
    """Migrate live virtual codes only; audit/history rows remain immutable."""
    layouts = await db.consignment_layouts.find(
        {"destination": {"$in": list(DESTINATIONS)}},
        {"_id": 0, "id": 1, "destination": 1, "stackCode": 1},
    ).to_list(5000)
    for row in layouts:
        try:
            canonical = normalize_consignment_stack_code(row.get("destination", ""), row.get("stackCode", ""))
        except HTTPException:
            continue
        if canonical != row.get("stackCode"):
            await db.consignment_layouts.update_one({"id": row.get("id")}, {"$set": {"stackCode": canonical}})

    trips = await db.bazar_trips.find({}, {"_id": 0, "id": 1, "items": 1, "resultItems": 1}).to_list(5000)
    for trip in trips:
        patch = {}
        for field in ("items", "resultItems"):
            source = trip.get(field)
            if not isinstance(source, list):
                continue
            changed = False
            normalized_rows = []
            for item in source:
                row = dict(item)
                try:
                    canonical = normalize_consignment_stack_code(BAZAR_DESTINATION, row.get("stackCode", ""))
                except HTTPException:
                    canonical = row.get("stackCode", "")
                if canonical and canonical != row.get("stackCode"):
                    row["stackCode"] = canonical
                    changed = True
                normalized_rows.append(row)
            if changed:
                patch[field] = normalized_rows
        if patch:
            await db.bazar_trips.update_one({"id": trip.get("id")}, {"$set": patch})

    # Once modules are fully imported, consignment_stock points to the adjusted
    # operational balance. Repair legacy/missing physical locations on every start.
    await reconcile_all_consignment_layouts(operator="Sistem (startup)")


def _layout_primary_qty(layout: dict) -> float:
    if "primaryQty" in layout:
        return float(layout.get("primaryQty", 0) or 0)
    secondary_qty = float(layout.get("secondaryQty", 0) or 0)
    secondary_count = sum(
        float(row.get("hamparan", 0) or 0) * float(row.get("kaki", 0) or 0) * float(row.get("height", 0) or 0)
        for row in (layout.get("arrangements") or [])
    ) + float(layout.get("extraSecondary", 0) or 0)
    return secondary_count * secondary_qty + float(layout.get("extraPrimary", 0) or 0)


async def sync_consignment_layout_balance(
    destination: str,
    product_id: str,
    operator: str = "Sistem",
    preferred_stack: str = "",
    operation_key: str = "",
    note: str = "Sinkronisasi otomatis saldo konsinyasi dan lokasi fisik",
) -> dict:
    """Keep live Bazar/E-commerce locations equal to the physical consignment balance.

    primaryQty is authoritative after an automatic adjustment. Existing manual
    arrangements are retained for audit/display and marked arrangementAdjusted.
    """
    destination = str(destination or "").strip()
    if destination not in DESTINATIONS:
        raise HTTPException(status_code=400, detail="Lokasi konsinyasi tidak valid")

    stock_rows = await consignment_stock(destination)
    matching = [row for row in stock_rows if row.get("productId") == product_id]
    target_qty = sum(float(row.get("qty", 0) or 0) for row in matching)

    identity = matching[0] if matching else await db.products.find_one({"id": product_id}, {"_id": 0})
    if not identity:
        raise HTTPException(status_code=404, detail="Produk konsinyasi tidak ditemukan")

    allowed = consignment_stack_codes(destination)
    if not allowed:
        raise HTTPException(status_code=400, detail="Lokasi konsinyasi tidak memiliki master tumpukan")
    try:
        preferred = normalize_consignment_stack_code(destination, preferred_stack) if preferred_stack else allowed[0]
    except HTTPException:
        preferred = allowed[0]

    layouts = await db.consignment_layouts.find(
        {"destination": destination, "productId": product_id},
        {"_id": 0},
    ).sort("stackCode", 1).to_list(5000)

    # Hydrate legacy rows that pre-date primaryQty/secondaryQty so old multiplication
    # remains meaningful instead of being read as zero.
    secondary_qty = float(identity.get("secondaryQty", 0) or 0)
    hydrated = []
    for layout in layouts:
        row = dict(layout)
        patch = {}
        secondary_count = sum(
            float(item.get("hamparan", 0) or 0)
            * float(item.get("kaki", 0) or 0)
            * float(item.get("height", 0) or 0)
            for item in (row.get("arrangements") or [])
        ) + float(row.get("extraSecondary", 0) or 0)
        if "secondaryQty" not in row:
            patch["secondaryQty"] = secondary_qty
        if "secondaryCount" not in row:
            patch["secondaryCount"] = secondary_count
        if "primaryQty" not in row:
            patch["primaryQty"] = secondary_count * secondary_qty + float(row.get("extraPrimary", 0) or 0)
        for field, value in (
            ("sku", identity.get("sku", "")),
            ("productName", identity.get("name", identity.get("productName", ""))),
            ("unit", identity.get("unit", "")),
            ("weight", float(identity.get("weight", 0) or 0)),
            ("measureUnit", identity.get("measureUnit", "kg") or "kg"),
            ("secondary", identity.get("secondary", "")),
        ):
            if field not in row:
                patch[field] = value
        if patch:
            patch.update({"updatedAt": now_iso(), "updatedBy": operator})
            await db.consignment_layouts.update_one({"id": row["id"]}, {"$set": patch})
            row.update(patch)
        hydrated.append(row)
    layouts = hydrated

    current_qty = sum(_layout_primary_qty(row) for row in layouts)
    difference = target_qty - current_qty
    if abs(difference) <= 1e-9:
        return {
            "destination": destination,
            "productId": product_id,
            "targetQty": target_qty,
            "layoutQty": current_qty,
            "difference": 0.0,
            "adjusted": False,
        }

    now = now_iso()
    if difference > 1e-9:
        target_layout = next((row for row in layouts if row.get("stackCode") == preferred), None)
        if not target_layout:
            target_layout = {
                "id": new_id(),
                "destination": destination,
                "productId": product_id,
                "stackCode": preferred,
                "sku": identity.get("sku", ""),
                "productName": identity.get("name", identity.get("productName", "")),
                "unit": identity.get("unit", ""),
                "weight": float(identity.get("weight", 0) or 0),
                "measureUnit": identity.get("measureUnit", "kg") or "kg",
                "secondary": identity.get("secondary", ""),
                "secondaryQty": secondary_qty,
                "arrangements": [],
                "extraSecondary": 0,
                "extraPrimary": difference,
                "secondaryCount": 0,
                "primaryQty": difference,
                "arrangementAdjusted": True,
                "note": "Saldo ditempatkan otomatis; atur perkalian fisik bila diperlukan.",
                "createdAt": now,
                "updatedAt": now,
                "updatedBy": operator,
                "appliedOperations": [],
            }
            await db.consignment_layouts.insert_one(dict(target_layout))
            before = {}
            after = target_layout
            action = "SINKRON_OTOMATIS_DIBUAT"
        else:
            before = dict(target_layout)
            next_qty = _layout_primary_qty(target_layout) + difference
            patch = {
                "primaryQty": next_qty,
                "arrangementAdjusted": True,
                "updatedAt": now,
                "updatedBy": operator,
            }
            await db.consignment_layouts.update_one({"id": target_layout["id"]}, {"$set": patch})
            after = {**target_layout, **patch}
            action = "SINKRON_OTOMATIS_TAMBAH"

        await db.consignment_layout_history.insert_one({
            "id": new_id(),
            "time": now,
            "destination": destination,
            "productId": product_id,
            "stackCode": preferred,
            "action": action,
            "before": before,
            "after": after,
            "operator": operator,
            "operationKey": operation_key,
            "note": note,
        })
    else:
        excess = -difference
        ordered = sorted(layouts, key=lambda row: (row.get("stackCode") != preferred, row.get("stackCode", "")))
        for layout in ordered:
            if excess <= 1e-9:
                break
            current = _layout_primary_qty(layout)
            if current <= 1e-9:
                continue
            take = min(current, excess)
            next_qty = current - take
            patch = {
                "primaryQty": next_qty,
                "arrangementAdjusted": True,
                "updatedAt": now,
                "updatedBy": operator,
            }
            await db.consignment_layouts.update_one({"id": layout["id"]}, {"$set": patch})
            after = {**layout, **patch}
            await db.consignment_layout_history.insert_one({
                "id": new_id(),
                "time": now,
                "destination": destination,
                "productId": product_id,
                "stackCode": layout.get("stackCode", ""),
                "action": "SINKRON_OTOMATIS_KURANG",
                "before": layout,
                "after": after,
                "operator": operator,
                "operationKey": operation_key,
                "note": note,
            })
            excess -= take
        if excess > 1e-9:
            raise HTTPException(status_code=409, detail="Saldo lokasi konsinyasi tidak dapat direkonsiliasi penuh")

    final_rows = await db.consignment_layouts.find(
        {"destination": destination, "productId": product_id},
        {"_id": 0},
    ).to_list(5000)
    final_qty = sum(_layout_primary_qty(row) for row in final_rows)
    if abs(final_qty - target_qty) > 1e-9:
        raise HTTPException(
            status_code=409,
            detail=f"Sinkronisasi lokasi belum seimbang. Saldo {target_qty:g}, lokasi {final_qty:g}",
        )
    return {
        "destination": destination,
        "productId": product_id,
        "targetQty": target_qty,
        "layoutQty": final_qty,
        "difference": target_qty - final_qty,
        "adjusted": True,
    }


async def reconcile_all_consignment_layouts(operator: str = "Sistem") -> list[dict]:
    """Repair live location balances for every product currently or historically located in Bazar/E-commerce."""
    stock_rows = await consignment_stock()
    keys = {
        (str(row.get("destination") or ""), str(row.get("productId") or ""))
        for row in stock_rows
        if row.get("destination") in DESTINATIONS and row.get("productId")
    }
    existing = await db.consignment_layouts.find(
        {"destination": {"$in": list(DESTINATIONS)}},
        {"_id": 0, "destination": 1, "productId": 1},
    ).to_list(10000)
    keys.update(
        (str(row.get("destination") or ""), str(row.get("productId") or ""))
        for row in existing
        if row.get("destination") in DESTINATIONS and row.get("productId")
    )
    results = []
    for destination, product_id in sorted(keys):
        results.append(await sync_consignment_layout_balance(
            destination,
            product_id,
            operator=operator,
            operation_key=f"consignment-layout-reconcile:{destination}:{product_id}",
            note="Rekonsiliasi otomatis agar saldo konsinyasi sama dengan jumlah lokasi fisik.",
        ))
    return results


class Arrangement(BaseModel):
    hamparan: int = Field(ge=1, le=1000)
    kaki: int = Field(ge=1, le=1000)
    height: int = Field(ge=1, le=1000)


class ConsignmentLayoutInput(BaseModel):
    destination: Literal["Gudang Bazar", "Gudang E-commerce"]
    productId: str
    stackCode: str
    arrangements: List[Arrangement] = Field(default_factory=list, max_length=10)
    extraSecondary: int = Field(default=0, ge=0, le=1000000)
    extraPrimary: int = Field(default=0, ge=0, le=1000000)
    note: str = ""


class OpnameItemInput(BaseModel):
    productId: str
    actualQty: float = Field(ge=0)
    note: str = ""


class ConsignmentOpnameInput(BaseModel):
    destination: Literal["Gudang Bazar", "Gudang E-commerce"]
    items: List[OpnameItemInput] = Field(min_length=1)
    note: str = ""


def _scope_for_user(user: dict) -> str:
    return role_destination(user.get("role"))


def _ensure_destination_access(user: dict, destination: str, write: bool = False) -> str:
    destination = str(destination or "").strip()
    if destination not in DESTINATIONS:
        raise HTTPException(status_code=400, detail="Lokasi konsinyasi tidak valid")
    scope = _scope_for_user(user)
    if scope and scope != destination:
        raise HTTPException(status_code=403, detail=f"Akun ini hanya memiliki akses ke {scope}")
    permission = "bazarOps" if destination == "Gudang Bazar" else "ecomOps"
    view_permission = "bazarView" if destination == "Gudang Bazar" else "ecomView"
    required = permission if write else view_permission
    if not has_role_permission(user.get("role"), required):
        raise HTTPException(status_code=403, detail=f"Tidak memiliki akses ke {destination}")
    return destination


def _resolved_destination(user: dict, requested: str = "") -> str:
    scope = _scope_for_user(user)
    requested = str(requested or "").strip()
    if scope:
        if requested and requested != scope:
            raise HTTPException(status_code=403, detail=f"Akun ini hanya memiliki akses ke {scope}")
        return scope
    if requested:
        return _ensure_destination_access(user, requested, write=False)
    return ""


def _source_document(load: dict, item: dict) -> str:
    return str(item.get("documentNo") or load.get("ref") or "").strip()


def _settled_qty(load: dict, product_id: str, source_document_no: str = "") -> float:
    target = str(source_document_no or load.get("ref") or "").strip()
    settled = 0.0
    for link in load.get("document_links", []):
        link_source = str(link.get("sourceDocumentNo") or load.get("ref") or "").strip()
        if target and link_source != target:
            continue
        for item in link.get("items", []):
            if item.get("productId") != product_id:
                continue
            if link.get("type") in {"CR", "RETUR"}:
                # CR/RETUR physically returns goods to the main warehouse.
                settled += float(item.get("goodQty", 0) or 0) + float(item.get("damagedQty", 0) or 0)
            # SO is administrative settlement only. Physical Bazar/E-commerce
            # reductions are recorded by their operational movements, so counting
            # SO here would deduct the same goods twice.
    return settled


async def consignment_stock(destination: str = "") -> list[dict]:
    query = {"document_type": {"$in": ["MEMO", "ND"]}, "status": "Selesai", "consignment_destination": {"$in": list(DESTINATIONS)}}
    if destination:
        if destination not in DESTINATIONS:
            raise HTTPException(status_code=400, detail="Lokasi konsinyasi tidak valid")
        query["consignment_destination"] = destination
    loads = await db.outbound_loads.find(query, {"_id": 0}).to_list(5000)
    result: dict[tuple[str, str, str], dict] = {}
    for load in loads:
        source_rows: dict[tuple[str, str, str], dict] = {}
        for item in load.get("items", []):
            product_id = item.get("productId", "")
            if not product_id:
                continue
            source_document = _source_document(load, item)
            channel = normalize_channel(item.get("channel"), "KOM")
            source_key = (source_document, product_id, channel)
            row = source_rows.setdefault(source_key, {**item, "qty": 0.0})
            row["qty"] += float(item.get("qty", 0) or 0)
        for (source_document, product_id, channel), item in source_rows.items():
            qty = max(float(item.get("qty", 0) or 0) - _settled_qty(load, product_id, source_document), 0)
            if qty <= 0:
                continue
            key = (load.get("consignment_destination", ""), product_id, channel)
            row = result.setdefault(key, {
                "destination": key[0], "productId": product_id, "channel": channel, "sku": item.get("sku", ""),
                "name": item.get("name", ""), "unit": item.get("unit", ""), "weight": float(item.get("weight", 0) or 0),
                "measureUnit": item.get("measureUnit", "kg") or "kg", "secondary": item.get("secondary", ""),
                "secondaryQty": float(item.get("secondaryQty", 0) or 0), "qty": 0.0, "totalWeight": 0.0,
                "documents": [], "requestDocuments": [],
            })
            row["qty"] += qty
            row["totalWeight"] += qty * float(item.get("weight", 0) or 0)
            if source_document and source_document not in row["documents"]:
                row["documents"].append(source_document)
            if load.get("request_document") and load["request_document"] not in row["requestDocuments"]:
                row["requestDocuments"].append(load["request_document"])
    return sorted(result.values(), key=lambda row: (row["destination"] != "Gudang Bazar", row["name"].lower(), row["channel"], row["sku"]))


@router.get("/consignment-stock")
async def list_consignment_stock(destination: str = "", user: dict = Depends(get_current_user)):
    resolved = _resolved_destination(user, destination)
    if not resolved and not has_role_permission(user.get("role"), "consignmentView"):
        raise HTTPException(status_code=403, detail="Tidak memiliki akses stok Bazar/E-commerce")
    return await consignment_stock(resolved)


async def monitoring_stock(destination_scope: str = "", include_main: bool = True) -> list[dict]:
    rows = []
    if include_main:
        products = await db.products.find({}, {"_id": 0}).sort("name", 1).to_list(5000)
        for product in products:
            balances = product.get("channelStock") if isinstance(product.get("channelStock"), dict) else {}
            if not balances:
                channel = normalize_channel(product.get("channel"), "KOM")
                balances = {channel: {"stock": float(product.get("stock", 0) or 0), "damaged": float(product.get("damaged", 0) or 0)}}
            for channel in ("PSO", "KOM"):
                balance = balances.get(channel) or {}
                qty = float(balance.get("stock", 0) or 0)
                damaged = float(balance.get("damaged", 0) or 0)
                if qty <= 0 and damaged <= 0:
                    continue
                weight = float(product.get("weight", 0) or 0)
                rows.append({
                    "channel": channel, "location": product.get("location") or "Gudang Utama",
                    "locationType": "GUDANG", "productId": product.get("id", ""), "sku": product.get("sku", ""),
                    "name": product.get("name", ""), "unit": product.get("unit", ""), "qty": qty,
                    "damaged": damaged, "weight": weight, "measureUnit": product.get("measureUnit", "kg") or "kg", "totalWeight": qty * weight,
                    "secondary": product.get("secondary", ""), "secondaryQty": float(product.get("secondaryQty", 0) or 0), "documents": [],
                })
    damaged_query = {"destination": destination_scope} if destination_scope else {}
    damaged_rows = await db.consignment_damaged_balances.find(damaged_query, {"_id": 0}).to_list(10000)
    damaged_map = {
        (row.get("destination", ""), row.get("productId", ""), normalize_channel(row.get("channel"), "KOM")): float(row.get("qty", 0) or 0)
        for row in damaged_rows
    }
    seen_consignment = set()
    for item in await consignment_stock(destination_scope):
        key = (item["destination"], item["productId"], normalize_channel(item.get("channel"), "KOM"))
        seen_consignment.add(key)
        rows.append({
            "channel": key[2], "location": item["destination"],
            "locationType": "KONSINYASI", "productId": item["productId"], "sku": item.get("sku", ""),
            "name": item.get("name", ""), "unit": item.get("unit", ""), "qty": float(item.get("qty", 0) or 0),
            "damaged": damaged_map.get(key, 0.0), "weight": float(item.get("weight", 0) or 0), "measureUnit": item.get("measureUnit", "kg") or "kg", "totalWeight": float(item.get("totalWeight", 0) or 0),
            "secondary": item.get("secondary", ""), "secondaryQty": float(item.get("secondaryQty", 0) or 0), "documents": item.get("documents", []),
        })
    for damaged in damaged_rows:
        key = (damaged.get("destination", ""), damaged.get("productId", ""), normalize_channel(damaged.get("channel"), "KOM"))
        if key in seen_consignment or float(damaged.get("qty", 0) or 0) <= 0:
            continue
        weight = float(damaged.get("weight", 0) or 0)
        rows.append({
            "channel": key[2], "location": damaged.get("destination", ""),
            "locationType": "KONSINYASI", "productId": damaged.get("productId", ""), "sku": damaged.get("sku", ""),
            "name": damaged.get("name", ""), "unit": damaged.get("unit", ""), "qty": 0.0,
            "damaged": float(damaged.get("qty", 0) or 0), "weight": weight, "measureUnit": damaged.get("measureUnit", "kg") or "kg",
            "totalWeight": 0.0, "secondary": "", "secondaryQty": 0.0, "documents": [],
        })
    return sorted(rows, key=lambda row: (row["location"] not in {"Gudang Bazar", "Gudang E-commerce"}, row["location"], row["channel"], row["name"].lower(), row["sku"]))


@router.get("/monitoring-stock")
async def list_monitoring_stock(user: dict = Depends(get_current_user)):
    scope = _scope_for_user(user)
    if scope:
        _ensure_destination_access(user, scope, write=False)
        return await monitoring_stock(scope, include_main=False)
    return await monitoring_stock()


@router.get("/export/monitoring-stock.xlsx")
async def export_monitoring_stock(user: dict = Depends(get_current_user)):
    scope = _scope_for_user(user)
    if scope:
        _ensure_destination_access(user, scope, write=False)
    rows = await monitoring_stock(scope, include_main=not bool(scope))
    headers = ["Saluran", "Lokasi", "Jenis Lokasi", "SKU", "Nama Komoditi", "Kuantum Pack/PCS", "Satuan", "Kuantum Fisik", "Stok Rusak", "Dokumen Memo/ND"]
    values = [[row["channel"], row["location"], row["locationType"], row["sku"], row["name"], row["qty"], row["unit"], f"{row['totalWeight']:g} {row.get('measureUnit', 'kg')}", row["damaged"], ", ".join(row.get("documents", []))] for row in rows]
    output = build_xlsx(headers, values, "Monitoring Stok")
    filename = f"monitoring_stok_{operational_now().strftime('%Y%m%d_%H%M')}.xlsx"
    return StreamingResponse(output, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/consignment-layouts")
async def list_consignment_layouts(user: dict = Depends(get_current_user)):
    scope = _scope_for_user(user)
    if scope:
        _ensure_destination_access(user, scope, write=False)
        return await db.consignment_layouts.find({"destination": scope}, {"_id": 0}).to_list(5000)
    if not has_role_permission(user.get("role"), "consignmentView"):
        raise HTTPException(status_code=403, detail="Tidak memiliki akses layout Bazar/E-commerce")
    return await db.consignment_layouts.find({}, {"_id": 0}).to_list(5000)


@router.get("/consignment-layout-history")
async def list_consignment_layout_history(destination: str = "", user: dict = Depends(get_current_user)):
    resolved = _resolved_destination(user, destination)
    query = {"destination": resolved} if resolved else {}
    return await db.consignment_layout_history.find(query, {"_id": 0}).sort("time", -1).to_list(5000)


@router.get("/consignment-opnames")
async def list_consignment_opnames(destination: str = "", user: dict = Depends(get_current_user)):
    resolved = _resolved_destination(user, destination)
    query = {"destination": resolved} if resolved else {}
    return await db.consignment_opnames.find(query, {"_id": 0}).sort("time", -1).to_list(5000)


@router.put("/consignment-layouts")
async def save_consignment_layout(body: ConsignmentLayoutInput, user: dict = Depends(get_current_user)):
    _ensure_destination_access(user, body.destination, write=True)
    stack_code = normalize_consignment_stack_code(body.destination, body.stackCode)
    rows = await consignment_stock(body.destination)
    stock = next((row for row in rows if row["productId"] == body.productId), None)
    if not stock:
        raise HTTPException(status_code=400, detail="Produk tidak memiliki stok konsinyasi aktif pada lokasi ini")

    secondary_qty = float(stock.get("secondaryQty", 0) or 0)
    secondary_count = sum(row.hamparan * row.kaki * row.height for row in body.arrangements) + body.extraSecondary
    calculated = secondary_count * secondary_qty + body.extraPrimary
    if calculated <= 0:
        raise HTTPException(status_code=400, detail="Isi minimal satu perkalian tumpukan atau jumlah tambahan")
    if secondary_count > 0 and secondary_qty <= 0:
        raise HTTPException(status_code=400, detail="Kemasan sekunder produk belum diatur")

    existing_same = await db.consignment_layouts.find_one(
        {"destination": body.destination, "productId": body.productId, "stackCode": stack_code},
        {"_id": 0},
    )
    allocated_elsewhere = 0.0
    query = {"destination": body.destination, "productId": body.productId}
    async for row in db.consignment_layouts.find(query, {"_id": 0}):
        if existing_same and row.get("id") == existing_same.get("id"):
            continue
        allocated_elsewhere += _layout_primary_qty(row)

    stock_qty = float(stock.get("qty", 0) or 0)
    if body.destination == "Gudang Bazar":
        reserved_on_stack = 0.0
        active_trips = await db.bazar_trips.find(
            {"status": "BERJALAN"},
            {"_id": 0, "items": 1},
        ).to_list(5000)
        for trip in active_trips:
            for trip_item in trip.get("items", []):
                if (
                    trip_item.get("productId") == body.productId
                    and str(trip_item.get("stackCode") or "").strip().upper() == stack_code
                ):
                    reserved_on_stack += float(trip_item.get("loadedQty", 0) or 0)
        if calculated + 1e-9 < reserved_on_stack:
            raise HTTPException(
                status_code=409,
                detail=f"Tumpukan {stack_code} sedang mereservasi {reserved_on_stack:g} {stock.get('unit', '')} untuk perjalanan Bazar aktif",
            )
    if allocated_elsewhere + calculated > stock_qty + 1e-9:
        available = max(stock_qty - allocated_elsewhere, 0)
        raise HTTPException(
            status_code=400,
            detail=f"Perkalian melebihi saldo {stock.get('name', '')}. Tersedia untuk tumpukan ini {available:g} {stock.get('unit', '')}",
        )

    now = now_iso()
    doc = {
        "destination": body.destination,
        "productId": body.productId,
        "stackCode": stack_code,
        "sku": stock.get("sku", ""),
        "productName": stock.get("name", ""),
        "unit": stock.get("unit", ""),
        "weight": float(stock.get("weight", 0) or 0),
        "measureUnit": stock.get("measureUnit", "kg") or "kg",
        "secondary": stock.get("secondary", ""),
        "secondaryQty": secondary_qty,
        "arrangements": [row.model_dump() for row in body.arrangements],
        "extraSecondary": body.extraSecondary,
        "extraPrimary": body.extraPrimary,
        "secondaryCount": secondary_count,
        "primaryQty": calculated,
        "arrangementAdjusted": False,
        "note": body.note.strip(),
        "updatedAt": now,
        "updatedBy": user.get("name", ""),
    }
    before = existing_same or {}
    saved = await db.consignment_layouts.find_one_and_update(
        {"destination": body.destination, "productId": body.productId, "stackCode": stack_code},
        {"$set": doc, "$setOnInsert": {"id": new_id(), "createdAt": now}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    result = {k: v for k, v in saved.items() if k != "_id"}
    await db.consignment_layout_history.insert_one({
        "id": new_id(),
        "time": now,
        "destination": body.destination,
        "productId": body.productId,
        "stackCode": stack_code,
        "action": "DIUBAH" if before else "DIBUAT",
        "before": before,
        "after": result,
        "operator": user.get("name", ""),
        "note": body.note.strip(),
    })
    return result


@router.delete("/consignment-layouts/{layout_id}")
async def delete_consignment_layout(layout_id: str, user: dict = Depends(get_current_user)):
    existing = await db.consignment_layouts.find_one({"id": layout_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Perkalian tumpukan tidak ditemukan")
    _ensure_destination_access(user, existing.get("destination", ""), write=True)
    if existing.get("destination") == "Gudang Bazar":
        active_trip = await db.bazar_trips.find_one(
            {
                "status": "BERJALAN",
                "items": {
                    "$elemMatch": {
                        "productId": existing.get("productId", ""),
                        "stackCode": existing.get("stackCode", ""),
                    }
                },
            },
            {"_id": 0, "tripNo": 1},
        )
        if active_trip:
            raise HTTPException(
                status_code=409,
                detail=f"Tumpukan sedang dipakai perjalanan Bazar aktif {active_trip.get('tripNo', '')}; selesaikan perjalanan terlebih dahulu",
            )
    await db.consignment_layouts.delete_one({"id": layout_id})
    await db.consignment_layout_history.insert_one({
        "id": new_id(),
        "time": now_iso(),
        "destination": existing.get("destination", ""),
        "productId": existing.get("productId", ""),
        "stackCode": existing.get("stackCode", ""),
        "action": "DIHAPUS",
        "before": existing,
        "after": {},
        "operator": user.get("name", ""),
        "note": "Perkalian tumpukan dihapus",
    })
    return {"ok": True}


async def decrease_consignment_layouts(
    destination: str,
    product_id: str,
    qty: float,
    operator: str,
    preferred_stack: str = "",
    strict_preferred: bool = False,
    operation_key: str = "",
) -> None:
    remaining = max(float(qty or 0), 0.0)
    if remaining <= 1e-9:
        return
    query = {"destination": destination, "productId": product_id}
    layouts = await db.consignment_layouts.find(query, {"_id": 0}).sort([("updatedAt", 1), ("stackCode", 1)]).to_list(5000)
    if preferred_stack:
        normalized = normalize_consignment_stack_code(destination, preferred_stack)
        preferred_rows = [row for row in layouts if row.get("stackCode") == normalized]
        if strict_preferred and layouts:
            available_on_stack = sum(_layout_primary_qty(row) for row in preferred_rows)
            if available_on_stack + 1e-9 < remaining:
                raise HTTPException(
                    status_code=409,
                    detail=f"Saldo tumpukan {normalized} berubah dan hanya tersisa {available_on_stack:g}. Periksa perjalanan aktif/perkalian sebelum menyelesaikan.",
                )
            layouts = preferred_rows
        else:
            layouts.sort(key=lambda row: (row.get("stackCode") != normalized, row.get("stackCode", "")))
    for layout in layouts:
        if remaining <= 1e-9:
            break
        if operation_key:
            applied = next((row for row in (layout.get("appliedOperations") or []) if row.get("key") == operation_key), None)
            if applied:
                remaining = max(remaining - float(applied.get("qty", 0) or 0), 0.0)
                continue
        current = _layout_primary_qty(layout)
        if current <= 1e-9:
            continue
        take = min(current, remaining)
        next_qty = current - take
        now = now_iso()
        patch = {"primaryQty": next_qty, "arrangementAdjusted": True, "updatedAt": now, "updatedBy": operator}
        if operation_key:
            result = await db.consignment_layouts.update_one(
                {"id": layout["id"], "appliedOperations.key": {"$ne": operation_key}},
                {"$set": patch, "$push": {"appliedOperations": {"$each": [{"key": operation_key, "qty": take, "time": now}], "$slice": -500}}},
            )
            if result.matched_count == 0:
                refreshed = await db.consignment_layouts.find_one({"id": layout["id"]}, {"_id": 0}) or {}
                applied = next((row for row in (refreshed.get("appliedOperations") or []) if row.get("key") == operation_key), None)
                if applied:
                    remaining = max(remaining - float(applied.get("qty", 0) or 0), 0.0)
                    continue
                raise HTTPException(status_code=409, detail="Perkalian tumpukan berubah. Muat ulang lalu coba kembali.")
            after = {**layout, **patch}
            action = "PENGELUARAN_HABIS" if next_qty <= 1e-9 else "PENGELUARAN_OTOMATIS"
        elif next_qty <= 1e-9:
            await db.consignment_layouts.delete_one({"id": layout["id"]})
            after = {**layout, "primaryQty": 0, "arrangementAdjusted": True, "updatedAt": now}
            action = "PENGELUARAN_HABIS"
        else:
            await db.consignment_layouts.update_one({"id": layout["id"]}, {"$set": patch})
            after = {**layout, **patch}
            action = "PENGELUARAN_OTOMATIS"
        await db.consignment_layout_history.insert_one({
            "id": new_id(),
            "time": now,
            "destination": destination,
            "productId": product_id,
            "stackCode": layout.get("stackCode", ""),
            "action": action,
            "before": layout,
            "after": after,
            "operator": operator,
            "operationKey": operation_key,
            "note": f"Pengurangan otomatis {take:g} {layout.get('unit', '')}",
        })
        remaining -= take

    if remaining > 1e-9:
        raise HTTPException(
            status_code=409,
            detail=f"Saldo lokasi {destination} tidak cukup untuk mengurangi {qty:g}. Jalankan sinkronisasi lokasi terlebih dahulu.",
        )


@router.post("/consignment-opnames")
async def create_consignment_opname(body: ConsignmentOpnameInput, user: dict = Depends(get_current_user)):
    _ensure_destination_access(user, body.destination, write=True)
    stock_by_product = {row["productId"]: row for row in await consignment_stock(body.destination)}
    items = []
    for item in body.items:
        system = stock_by_product.get(item.productId)
        if not system:
            raise HTTPException(status_code=400, detail="Produk opname tidak memiliki saldo konsinyasi aktif")
        actual = float(item.actualQty)
        items.append({"productId": item.productId, "sku": system.get("sku", ""), "name": system.get("name", ""), "unit": system.get("unit", ""), "systemQty": float(system["qty"]), "actualQty": actual, "difference": actual - float(system["qty"]), "note": item.note.strip()})
    doc = {"id": new_id(), "time": now_iso(), "destination": body.destination, "items": items, "note": body.note.strip(), "operator": user.get("name", "")}
    await db.consignment_opnames.insert_one(dict(doc))
    return doc
