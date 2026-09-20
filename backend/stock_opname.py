from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.server import (
    ROLE_SUPERADMIN,
    canonical_role,
    db,
    ensure_channel_stock,
    get_current_user,
    has_role_permission,
    new_id,
    next_sequence,
    normalize_channel,
    operational_now,
    require_write,
    now_iso,
)
from backend.operational_guards import operation_guard, product_lock_keys
from backend.stack_allocations import record_stack_history

router = APIRouter(prefix="/api")
EPS = 1e-9


class OpnameCreateInput(BaseModel):
    warehouse: str = Field(min_length=1, max_length=20)
    note: str = Field(default="", max_length=1000)


class OpnameLineInput(BaseModel):
    allocationId: str
    physicalQty: float = Field(ge=0)
    channel: Literal["PSO", "KOM"] = "KOM"
    note: str = Field(default="", max_length=500)


class OpnameUpdateInput(BaseModel):
    lines: List[OpnameLineInput] = Field(min_length=1, max_length=2000)
    note: str = Field(default="", max_length=1000)


class OpnameDecisionInput(BaseModel):
    note: str = Field(default="", max_length=1000)


async def require_opname_approval(user: dict = Depends(get_current_user)) -> dict:
    if canonical_role(user.get("role")) == ROLE_SUPERADMIN or has_role_permission(user.get("role"), "warehouseApprove"):
        return user
    raise HTTPException(status_code=403, detail="Hanya Superadmin atau Kepala Gudang yang dapat menyetujui stock opname")


def _n(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


async def _warehouse_codes() -> set[str]:
    settings = await db.settings.find_one({"_id": "app"}, {"_id": 0, "warehouses": 1}) or {}
    warehouses = settings.get("warehouses") or [
        *[{"code": str(unit)} for unit in range(17, 25)],
        {"code": "MP1"},
    ]
    return {str(item.get("code") or "").strip().upper() for item in warehouses if str(item.get("code") or "").strip()}


async def _allocation_snapshot(warehouse: str) -> list[dict]:
    allocations = await db.stack_allocations.find(
        {"$or": [{"warehouse": warehouse}, {"stackCode": {"$regex": f"^{warehouse}/"}}]},
        {"_id": 0},
    ).sort("stackCode", 1).to_list(10000)
    if not allocations:
        return []
    product_ids = list({str(item.get("productId") or "") for item in allocations if item.get("productId")})
    products = await db.products.find({"id": {"$in": product_ids}}, {"_id": 0}).to_list(10000)
    by_id = {str(product.get("id") or ""): product for product in products}
    result = []
    for allocation in allocations:
        product = by_id.get(str(allocation.get("productId") or ""), {})
        qty = _n(allocation.get("primaryQty"))
        result.append({
            "allocationId": allocation.get("id", ""),
            "productId": allocation.get("productId", ""),
            "sku": allocation.get("sku") or product.get("sku", ""),
            "product": allocation.get("productName") or product.get("name", ""),
            "stackCode": allocation.get("stackCode", ""),
            "unit": allocation.get("unit") or product.get("unit", ""),
            "systemQty": qty,
            "physicalQty": qty,
            "difference": 0.0,
            "channel": normalize_channel(product.get("channel")),
            "note": "",
        })
    return result


@router.get("/stock-opnames")
async def list_stock_opnames(user: dict = Depends(get_current_user)):
    rows = await db.stock_opnames.find({}, {"_id": 0}).sort("createdAt", -1).to_list(1000)
    for row in rows:
        row["snapshotStale"] = False
        row["staleLines"] = []
        if row.get("status") not in {"DRAFT", "SUBMITTED"}:
            continue
        allocation_ids = [str(line.get("allocationId") or "") for line in row.get("lines", []) if line.get("allocationId")]
        current_rows = await db.stack_allocations.find(
            {"id": {"$in": allocation_ids}},
            {"_id": 0, "id": 1, "primaryQty": 1},
        ).to_list(10000) if allocation_ids else []
        current_by_id = {str(item.get("id") or ""): _n(item.get("primaryQty")) for item in current_rows}
        stale_lines = []
        for line in row.get("lines", []):
            allocation_id = str(line.get("allocationId") or "")
            if allocation_id not in current_by_id:
                stale_lines.append({
                    "allocationId": allocation_id,
                    "stackCode": line.get("stackCode", ""),
                    "snapshotQty": _n(line.get("systemQty")),
                    "currentQty": None,
                })
                continue
            current_qty = current_by_id[allocation_id]
            if abs(current_qty - _n(line.get("systemQty"))) > EPS:
                stale_lines.append({
                    "allocationId": allocation_id,
                    "stackCode": line.get("stackCode", ""),
                    "snapshotQty": _n(line.get("systemQty")),
                    "currentQty": current_qty,
                })
        row["snapshotStale"] = bool(stale_lines)
        row["staleLines"] = stale_lines
    return rows


@router.post("/stock-opnames")
async def create_stock_opname(body: OpnameCreateInput, user: dict = Depends(require_write)):
    warehouse = body.warehouse.strip().upper()
    if warehouse not in await _warehouse_codes():
        raise HTTPException(status_code=400, detail="GBB/warehouse tidak valid")
    existing = await db.stock_opnames.find_one({"warehouse": warehouse, "status": {"$in": ["DRAFT", "SUBMITTED"]}}, {"_id": 0, "no": 1})
    if existing:
        raise HTTPException(status_code=409, detail=f"Masih ada stock opname aktif untuk {warehouse}: {existing.get('no', '')}")

    lines = await _allocation_snapshot(warehouse)
    if not lines:
        raise HTTPException(status_code=400, detail=f"Tidak ada stok tumpukan yang dapat diopname pada {warehouse}")

    op_now = operational_now()
    date_text = op_now.strftime("%Y%m%d")
    sequence = await next_sequence(f"stock-opname:{date_text}", 0)
    now = now_iso()
    doc = {
        "id": new_id(),
        "no": f"OPN-{date_text}-{sequence:03d}",
        "warehouse": warehouse,
        "status": "DRAFT",
        "lines": lines,
        "note": body.note.strip(),
        "createdAt": now,
        "createdBy": user.get("name", ""),
        "updatedAt": now,
        "updatedBy": user.get("name", ""),
        "submittedAt": "",
        "submittedBy": "",
        "approvedAt": "",
        "approvedBy": "",
        "approvalNote": "",
    }
    await db.stock_opnames.insert_one(dict(doc))
    return doc


@router.put("/stock-opnames/{opname_id}")
async def update_stock_opname(opname_id: str, body: OpnameUpdateInput, user: dict = Depends(require_write)):
    opname = await db.stock_opnames.find_one({"id": opname_id}, {"_id": 0})
    if not opname:
        raise HTTPException(status_code=404, detail="Stock opname tidak ditemukan")
    if opname.get("status") != "DRAFT":
        raise HTTPException(status_code=400, detail="Hanya stock opname berstatus DRAFT yang dapat diubah")

    submitted = {line.allocationId: line for line in body.lines}
    lines = []
    for original in opname.get("lines", []):
        patch = submitted.get(original.get("allocationId", ""))
        revised = dict(original)
        if patch:
            revised["physicalQty"] = float(patch.physicalQty)
            revised["channel"] = patch.channel
            revised["note"] = patch.note.strip()
        revised["difference"] = _n(revised.get("physicalQty")) - _n(revised.get("systemQty"))
        lines.append(revised)

    now = now_iso()
    await db.stock_opnames.update_one(
        {"id": opname_id, "status": "DRAFT"},
        {"$set": {
            "lines": lines,
            "note": body.note.strip(),
            "updatedAt": now,
            "updatedBy": user.get("name", ""),
        }},
    )
    return await db.stock_opnames.find_one({"id": opname_id}, {"_id": 0})


@router.post("/stock-opnames/{opname_id}/cancel")
async def cancel_stock_opname(opname_id: str, body: OpnameDecisionInput, user: dict = Depends(require_write)):
    opname = await db.stock_opnames.find_one({"id": opname_id}, {"_id": 0})
    if not opname:
        raise HTTPException(status_code=404, detail="Stock opname tidak ditemukan")
    if opname.get("status") != "DRAFT":
        raise HTTPException(status_code=409, detail="Hanya stock opname DRAFT yang dapat dibatalkan langsung")
    now = now_iso()
    result = await db.stock_opnames.update_one(
        {"id": opname_id, "status": "DRAFT"},
        {"$set": {
            "status": "CANCELLED",
            "cancelledAt": now,
            "cancelledBy": user.get("name", ""),
            "cancellationNote": body.note.strip(),
            "updatedAt": now,
            "updatedBy": user.get("name", ""),
        }},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=409, detail="Status stock opname berubah. Muat ulang halaman.")
    return await db.stock_opnames.find_one({"id": opname_id}, {"_id": 0})


@router.post("/stock-opnames/{opname_id}/submit")
async def submit_stock_opname(opname_id: str, body: OpnameDecisionInput, user: dict = Depends(require_write)):
    opname = await db.stock_opnames.find_one({"id": opname_id}, {"_id": 0})
    if not opname:
        raise HTTPException(status_code=404, detail="Stock opname tidak ditemukan")
    if opname.get("status") != "DRAFT":
        raise HTTPException(status_code=400, detail="Hanya stock opname DRAFT yang dapat diajukan")
    if not opname.get("lines"):
        raise HTTPException(status_code=400, detail="Stock opname tidak memiliki baris stok")
    now = now_iso()
    await db.stock_opnames.update_one(
        {"id": opname_id, "status": "DRAFT"},
        {"$set": {
            "status": "SUBMITTED",
            "submittedAt": now,
            "submittedBy": user.get("name", ""),
            "submissionNote": body.note.strip(),
            "updatedAt": now,
        }},
    )
    return await db.stock_opnames.find_one({"id": opname_id}, {"_id": 0})


async def _active_reserved_qty(product_id: str, stack_code: str) -> float:
    loads = await db.outbound_loads.find(
        {"status": {"$in": ["Menunggu", "Sedang Dimuat"]}, "kondisi": "BAIK"},
        {"_id": 0, "items": 1},
    ).to_list(10000)
    return sum(
        _n(item.get("qty"))
        for load in loads
        for item in load.get("items", [])
        if item.get("productId") == product_id and str(item.get("stackCode") or "").upper() == stack_code.upper()
    )


@router.post("/stock-opnames/{opname_id}/approve")
async def approve_stock_opname(opname_id: str, body: OpnameDecisionInput, user: dict = Depends(require_opname_approval)):
    initial = await db.stock_opnames.find_one({"id": opname_id}, {"_id": 0})
    if not initial:
        raise HTTPException(status_code=404, detail="Stock opname tidak ditemukan")
    product_ids = [line.get("productId", "") for line in initial.get("lines", []) if abs(_n(line.get("difference"))) > EPS]

    async with operation_guard(product_lock_keys(product_ids)):
        opname = await db.stock_opnames.find_one({"id": opname_id}, {"_id": 0})
        if not opname or opname.get("status") != "SUBMITTED":
            raise HTTPException(status_code=409, detail="Stock opname sudah berubah atau tidak lagi menunggu persetujuan")

        allocation_snapshots: dict[str, dict] = {}
        product_snapshots: dict[str, dict] = {}
        changed_allocations: list[tuple[dict, dict]] = []
        transaction_rows = []
        operation_id = new_id()
        approved_at = now_iso()

        # Validate every snapshot before mutating anything.
        for line in opname.get("lines", []):
            allocation_id = str(line.get("allocationId") or "")
            current = await db.stack_allocations.find_one({"id": allocation_id}, {"_id": 0})
            if not current:
                raise HTTPException(status_code=409, detail=f"Tumpukan {line.get('stackCode', '')} sudah berubah/habis sejak opname dibuat. Buat opname baru.")
            if abs(_n(current.get("primaryQty")) - _n(line.get("systemQty"))) > EPS:
                raise HTTPException(status_code=409, detail=f"Stok sistem {line.get('stackCode', '')} berubah sejak snapshot. Buat ulang stock opname agar tidak menimpa transaksi terbaru.")
            allocation_snapshots[allocation_id] = current
            reserved = await _active_reserved_qty(str(line.get("productId") or ""), str(line.get("stackCode") or ""))
            if _n(line.get("physicalQty")) + EPS < reserved:
                raise HTTPException(status_code=400, detail=f"Fisik {line.get('stackCode', '')} lebih kecil daripada stok yang sudah direservasi outbound ({reserved:g}). Selesaikan/batalkan antrean terlebih dahulu.")

        affected_ids = list({str(line.get("productId") or "") for line in opname.get("lines", []) if abs(_n(line.get("difference"))) > EPS})
        products = await db.products.find({"id": {"$in": affected_ids}}, {"_id": 0}).to_list(10000)
        product_snapshots = {str(product.get("id") or ""): product for product in products}
        if len(product_snapshots) != len(affected_ids):
            raise HTTPException(status_code=409, detail="Ada master produk opname yang tidak ditemukan")

        for product in product_snapshots.values():
            await ensure_channel_stock(product)
        refreshed = await db.products.find({"id": {"$in": affected_ids}}, {"_id": 0}).to_list(10000)
        current_products = {str(product.get("id") or ""): product for product in refreshed}

        try:
            for line in opname.get("lines", []):
                difference = _n(line.get("physicalQty")) - _n(line.get("systemQty"))
                if abs(difference) <= EPS:
                    continue
                product_id = str(line.get("productId") or "")
                product = current_products[product_id]
                channel = normalize_channel(line.get("channel"), normalize_channel(product.get("channel")))
                query = {"id": product_id}
                if difference < 0:
                    required = -difference
                    query["stock"] = {"$gte": required}
                    query[f"channelStock.{channel}.stock"] = {"$gte": required}
                result = await db.products.update_one(
                    query,
                    {"$inc": {"stock": difference, f"channelStock.{channel}.stock": difference}},
                )
                if result.matched_count == 0:
                    raise HTTPException(status_code=409, detail=f"Saldo {product.get('name', '')} berubah/tidak mencukupi untuk adjustment opname")

                allocation = allocation_snapshots[line["allocationId"]]
                physical = _n(line.get("physicalQty"))
                if physical <= EPS:
                    await db.stack_allocations.delete_one({"id": allocation["id"]})
                    updated_allocation = {**allocation, "primaryQty": 0.0, "secondaryCount": 0, "primaryRemainder": 0.0, "updatedAt": approved_at}
                else:
                    per_secondary = _n(allocation.get("secondaryQty"))
                    update = {
                        "primaryQty": physical,
                        "secondaryCount": int(physical // per_secondary) if per_secondary > 0 else 0,
                        "primaryRemainder": physical % per_secondary if per_secondary > 0 else physical,
                        "length": 0,
                        "width": 0,
                        "height": 0,
                        "arrangementAdjusted": True,
                        "updatedAt": approved_at,
                    }
                    await db.stack_allocations.update_one({"id": allocation["id"]}, {"$set": update})
                    updated_allocation = {**allocation, **update}
                changed_allocations.append((allocation, updated_allocation))

                transaction_rows.append({
                    "id": new_id(),
                    "operation_id": operation_id,
                    "time": approved_at,
                    "ref": opname.get("no", ""),
                    "type": "PENYESUAIAN",
                    "kondisi": "BAIK",
                    "document_type": "OPNAME",
                    "product_id": product_id,
                    "product": line.get("product", product.get("name", "")),
                    "sku": line.get("sku", product.get("sku", "")),
                    "change": difference,
                    "good_change": difference,
                    "damaged_change": 0,
                    "unit": line.get("unit", product.get("unit", "")),
                    "channel": channel,
                    "stackCode": line.get("stackCode", ""),
                    "operator": user.get("name", ""),
                    "keterangan": line.get("note", "") or body.note.strip(),
                    "opname_id": opname_id,
                })

            if transaction_rows:
                await db.transactions.insert_many([dict(row) for row in transaction_rows])

            result = await db.stock_opnames.update_one(
                {"id": opname_id, "status": "SUBMITTED"},
                {"$set": {
                    "status": "APPROVED",
                    "approvedAt": approved_at,
                    "approvedBy": user.get("name", ""),
                    "approvalNote": body.note.strip(),
                    "adjustmentOperationId": operation_id,
                    "updatedAt": approved_at,
                }},
            )
            if result.matched_count == 0:
                raise HTTPException(status_code=409, detail="Status opname berubah saat persetujuan")
        except Exception:
            await db.transactions.delete_many({"operation_id": operation_id})
            for allocation_id, snapshot in allocation_snapshots.items():
                await db.stack_allocations.replace_one({"id": allocation_id}, dict(snapshot), upsert=True)
            for product_id, snapshot in product_snapshots.items():
                await db.products.replace_one({"id": product_id}, dict(snapshot), upsert=False)
            raise

        for before, after in changed_allocations:
            try:
                await record_stack_history("OPNAME_ADJUSTMENT", after, user.get("name", ""))
            except Exception:
                pass

        return await db.stock_opnames.find_one({"id": opname_id}, {"_id": 0})


@router.post("/stock-opnames/{opname_id}/reject")
async def reject_stock_opname(opname_id: str, body: OpnameDecisionInput, user: dict = Depends(require_opname_approval)):
    opname = await db.stock_opnames.find_one({"id": opname_id}, {"_id": 0})
    if not opname:
        raise HTTPException(status_code=404, detail="Stock opname tidak ditemukan")
    if opname.get("status") != "SUBMITTED":
        raise HTTPException(status_code=400, detail="Hanya stock opname yang diajukan yang dapat ditolak")
    now = now_iso()
    await db.stock_opnames.update_one(
        {"id": opname_id, "status": "SUBMITTED"},
        {"$set": {
            "status": "REJECTED",
            "rejectedAt": now,
            "rejectedBy": user.get("name", ""),
            "rejectionNote": body.note.strip(),
            "updatedAt": now,
        }},
    )
    return await db.stock_opnames.find_one({"id": opname_id}, {"_id": 0})
