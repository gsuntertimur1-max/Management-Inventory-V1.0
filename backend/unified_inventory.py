from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.server import db, get_current_user, has_role_permission, new_id, now_iso

router = APIRouter(prefix="/api")


def _condition_field(condition: str) -> str:
    return {"BAIK": "stock", "RUSAK": "damaged", "ON_PROSES": "process"}.get(condition, "stock")


def _expiry_status(expired: str) -> str:
    if not expired:
        return "BELUM_DICATAT"
    try:
        expiry = datetime.fromisoformat(expired[:10]).replace(tzinfo=timezone.utc)
    except ValueError:
        return "TIDAK_VALID"
    days = (expiry - datetime.now(timezone.utc)).days
    if days < 0:
        return "EXPIRED"
    if days <= 90:
        return "MENDEKATI"
    return "AMAN"


async def _audit(user: dict, module: str, action: str, before=None, after=None, reason: str = ""):
    await db.audit_log.insert_one({
        "id": new_id(),
        "userId": user.get("id", ""),
        "userName": user.get("name", ""),
        "role": user.get("role", ""),
        "module": module,
        "action": action,
        "before": before,
        "after": after,
        "reason": reason,
        "created_at": now_iso(),
    })


class MutationBody(BaseModel):
    productId: str
    qty: float = Field(gt=0)
    fromCondition: Literal["BAIK", "RUSAK", "ON_PROSES"] = "BAIK"
    toCondition: Literal["BAIK", "RUSAK", "ON_PROSES"] = "BAIK"
    fromStackCode: str = ""
    toStackCode: str = ""
    reason: str


class RepackingBody(BaseModel):
    tmHasil: str
    sourceProductId: str
    sourceQty: float = Field(gt=0)
    resultProductId: str
    resultQty: float = Field(gt=0)
    batch: str = ""
    expired: str = ""
    operator: str = ""
    note: str = ""


class QCBody(BaseModel):
    repackingId: str
    status: Literal["LULUS", "TIDAK_LULUS", "PENDING"]
    inspector: str = ""
    reason: str = ""


@router.get("/monitoring-stock")
async def monitoring_stock(user: dict = Depends(get_current_user)):
    products = await db.products.find({}, {"_id": 0}).sort("name", 1).to_list(5000)
    allocations = await db.stack_allocations.find({}, {"_id": 0}).to_list(10000)
    allocated_by_product = {}
    for item in allocations:
        allocated_by_product[item.get("productId")] = allocated_by_product.get(item.get("productId"), 0) + float(item.get("primaryQty", 0) or 0)

    rows = []
    for product in products:
        stack_items = [item for item in allocations if item.get("productId") == product.get("id")]
        if stack_items:
            for item in stack_items:
                rows.append({
                    "productId": product.get("id"),
                    "sku": product.get("sku", ""),
                    "name": product.get("name", ""),
                    "saluran": product.get("saluran", product.get("category", "")),
                    "komoditi": product.get("komoditi", product.get("category", "")),
                    "warehouse": item.get("warehouse", ""),
                    "stackCode": item.get("stackCode", ""),
                    "condition": "BAIK",
                    "batch": item.get("batch", "") or "MASTER_STOCK",
                    "expired": item.get("expired", product.get("exp", "")) or "",
                    "qty": float(item.get("primaryQty", 0) or 0),
                    "kg": float(item.get("primaryQty", 0) or 0) * float(product.get("weight", 0) or 0),
                    "secondary": item.get("secondary", product.get("secondary", "")),
                    "updated_at": item.get("updated_at", item.get("time", "")),
                    "source": "stack_allocations",
                    "expiryStatus": _expiry_status(item.get("expired", product.get("exp", "")) or ""),
                })
        unallocated = max(float(product.get("stock", 0) or 0) - allocated_by_product.get(product.get("id"), 0), 0)
        if unallocated or not stack_items:
            rows.append({
                "productId": product.get("id"),
                "sku": product.get("sku", ""),
                "name": product.get("name", ""),
                "saluran": product.get("saluran", product.get("category", "")),
                "komoditi": product.get("komoditi", product.get("category", "")),
                "warehouse": "",
                "stackCode": product.get("location", "") or "BELUM_DICATAT",
                "condition": "BAIK",
                "batch": "MASTER_STOCK",
                "expired": product.get("exp", "") or "",
                "qty": unallocated if stack_items else float(product.get("stock", 0) or 0),
                "kg": (unallocated if stack_items else float(product.get("stock", 0) or 0)) * float(product.get("weight", 0) or 0),
                "secondary": product.get("secondary", ""),
                "updated_at": product.get("updated_at", ""),
                "source": "products",
                "expiryStatus": _expiry_status(product.get("exp", "") or ""),
            })
        if float(product.get("damaged", 0) or 0) > 0:
            rows.append({
                "productId": product.get("id"),
                "sku": product.get("sku", ""),
                "name": product.get("name", ""),
                "saluran": product.get("saluran", product.get("category", "")),
                "komoditi": product.get("komoditi", product.get("category", "")),
                "warehouse": "",
                "stackCode": product.get("location", "") or "BELUM_DICATAT",
                "condition": "RUSAK",
                "batch": "MASTER_STOCK",
                "expired": product.get("exp", "") or "",
                "qty": float(product.get("damaged", 0) or 0),
                "kg": float(product.get("damaged", 0) or 0) * float(product.get("weight", 0) or 0),
                "secondary": product.get("secondary", ""),
                "updated_at": product.get("updated_at", ""),
                "source": "products",
                "expiryStatus": _expiry_status(product.get("exp", "") or ""),
            })
    return sorted(rows, key=lambda row: (row["expired"] or "9999-12-31", row["name"], row["stackCode"]))


@router.post("/stock-mutations")
async def create_stock_mutation(body: MutationBody, user: dict = Depends(get_current_user)):
    if not has_role_permission(user.get("role"), "mutasi"):
        raise HTTPException(status_code=403, detail="Peran ini tidak memiliki hak mutasi stok")
    product = await db.products.find_one({"id": body.productId}, {"_id": 0})
    if not product:
        raise HTTPException(status_code=404, detail="Produk tidak ditemukan")
    from_field = _condition_field(body.fromCondition)
    to_field = _condition_field(body.toCondition)
    if float(product.get(from_field, 0) or 0) < body.qty:
        raise HTTPException(status_code=400, detail="Saldo tidak cukup, mutasi ditolak")

    before = {from_field: product.get(from_field, 0), to_field: product.get(to_field, 0), "location": product.get("location", "")}
    update = {"$inc": {from_field: -body.qty, to_field: body.qty}}
    if body.toStackCode:
        update["$set"] = {"location": body.toStackCode.strip().upper(), "updated_at": now_iso()}
    result = await db.products.update_one({"id": body.productId, from_field: {"$gte": body.qty}}, update)
    if result.modified_count == 0:
        raise HTTPException(status_code=400, detail="Mutasi gagal karena saldo berubah. Coba muat ulang data.")

    transaction = {
        "id": new_id(),
        "time": now_iso(),
        "type": "MUTASI",
        "productId": product["id"],
        "product": product.get("name", ""),
        "sku": product.get("sku", ""),
        "qty": body.qty,
        "change": 0,
        "fromCondition": body.fromCondition,
        "toCondition": body.toCondition,
        "fromStackCode": body.fromStackCode.strip().upper(),
        "toStackCode": body.toStackCode.strip().upper(),
        "operator": user.get("name", ""),
        "keterangan": body.reason,
    }
    await db.transactions.insert_one(transaction)
    updated = await db.products.find_one({"id": body.productId}, {"_id": 0})
    await _audit(user, "Mutasi Stok", f"Mutasi {product.get('sku', '')}", before, updated, body.reason)
    return {"transaction": transaction, "product": updated}


@router.get("/audit-log")
async def list_audit_log(user: dict = Depends(get_current_user)):
    return await db.audit_log.find({}, {"_id": 0}).sort("created_at", -1).to_list(2000)


@router.get("/repacking-jobs")
async def list_repacking_jobs(user: dict = Depends(get_current_user)):
    return await db.repacking_jobs.find({}, {"_id": 0}).sort("created_at", -1).to_list(2000)


@router.post("/repacking-jobs")
async def create_repacking_job(body: RepackingBody, user: dict = Depends(get_current_user)):
    if not has_role_permission(user.get("role"), "rebagging"):
        raise HTTPException(status_code=403, detail="Peran ini tidak memiliki hak repacking")
    source = await db.products.find_one({"id": body.sourceProductId}, {"_id": 0})
    result = await db.products.find_one({"id": body.resultProductId}, {"_id": 0})
    if not source or not result:
        raise HTTPException(status_code=404, detail="Produk asal atau hasil tidak ditemukan")
    if float(source.get("stock", 0) or 0) < body.sourceQty:
        raise HTTPException(status_code=400, detail="Stok bahan baku tidak cukup")

    now = now_iso()
    job = {
        "id": new_id(),
        "tmHasil": body.tmHasil.strip(),
        "sourceProductId": source["id"],
        "sourceProductName": source.get("name", ""),
        "sourceSku": source.get("sku", ""),
        "sourceQty": body.sourceQty,
        "resultProductId": result["id"],
        "resultProductName": result.get("name", ""),
        "resultSku": result.get("sku", ""),
        "resultQty": body.resultQty,
        "shrinkage": body.sourceQty - body.resultQty,
        "batch": body.batch.strip(),
        "expired": body.expired,
        "operator": body.operator.strip() or user.get("name", ""),
        "note": body.note.strip(),
        "qcStatus": "PENDING",
        "created_at": now,
        "updated_at": now,
        "created_by": user.get("name", ""),
    }
    await db.products.update_one({"id": source["id"], "stock": {"$gte": body.sourceQty}}, {"$inc": {"stock": -body.sourceQty}, "$set": {"updated_at": now}})
    await db.products.update_one({"id": result["id"]}, {"$inc": {"process": body.resultQty}, "$set": {"updated_at": now}})
    await db.repacking_jobs.insert_one(job)
    await db.transactions.insert_many([
        {"id": new_id(), "time": now, "type": "REPACKING_BAHAN", "productId": source["id"], "product": source.get("name", ""), "sku": source.get("sku", ""), "qty": body.sourceQty, "change": -body.sourceQty, "operator": user.get("name", ""), "ref": job["tmHasil"], "keterangan": "Bahan baku repacking"},
        {"id": new_id(), "time": now, "type": "REPACKING_HASIL", "productId": result["id"], "product": result.get("name", ""), "sku": result.get("sku", ""), "qty": body.resultQty, "change": body.resultQty, "operator": user.get("name", ""), "ref": job["tmHasil"], "keterangan": "Hasil repacking menunggu QC"},
    ])
    await _audit(user, "Repacking", f"Input {job['tmHasil'] or job['id']}", {"sourceStock": source.get("stock", 0)}, job, body.note)
    return job


@router.post("/qc-inspections")
async def create_qc_inspection(body: QCBody, user: dict = Depends(get_current_user)):
    if not has_role_permission(user.get("role"), "qc"):
        raise HTTPException(status_code=403, detail="Peran ini tidak memiliki hak QC")
    job = await db.repacking_jobs.find_one({"id": body.repackingId}, {"_id": 0})
    if not job:
        raise HTTPException(status_code=404, detail="Repacking tidak ditemukan")
    if job.get("qcStatus") == "LULUS":
        raise HTTPException(status_code=400, detail="Repacking ini sudah lulus QC")

    now = now_iso()
    inspection = {
        "id": new_id(),
        "repackingId": job["id"],
        "tmHasil": job.get("tmHasil", ""),
        "status": body.status,
        "inspector": body.inspector.strip() or user.get("name", ""),
        "reason": body.reason.strip(),
        "created_at": now,
        "created_by": user.get("name", ""),
    }
    update = {"$set": {"qcStatus": body.status, "qcReason": inspection["reason"], "qcInspector": inspection["inspector"], "updated_at": now}}
    await db.repacking_jobs.update_one({"id": job["id"]}, update)
    if body.status == "LULUS":
        await db.products.update_one({"id": job["resultProductId"]}, {"$inc": {"process": -float(job.get("resultQty", 0) or 0), "stock": float(job.get("resultQty", 0) or 0)}, "$set": {"updated_at": now}})
    elif body.status == "TIDAK_LULUS":
        await db.products.update_one({"id": job["resultProductId"]}, {"$inc": {"process": -float(job.get("resultQty", 0) or 0), "damaged": float(job.get("resultQty", 0) or 0)}, "$set": {"updated_at": now}})
    await db.qc_inspections.insert_one(inspection)
    await _audit(user, "QC", f"QC {job.get('tmHasil', job['id'])}", job, {**job, "qcStatus": body.status}, body.reason)
    return inspection
