from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.server import db, new_id, now_iso, require_master_write

router = APIRouter(prefix="/api")


class MasterProductBody(BaseModel):
    name: str
    sku: str
    category: str = ""
    cost: float = Field(default=0, ge=0)
    location: str = ""
    supplier: str = ""
    min: float = Field(default=0, ge=0)
    unit: str = "Pcs"
    weight: float = Field(default=0, ge=0)
    measureUnit: str = "kg"
    secondary: str = ""
    secondaryQty: float = Field(default=0, ge=0)
    channel: str = "KOM"
    loadingFeeLabor: float = Field(default=0, ge=0)
    loadingFeeDaily: float = Field(default=0, ge=0)
    loadingFeeWarehouse: float = Field(default=0, ge=0)
    loadingFeeChargeMode: str = "TIDAK_ADA"
    unloadingFeeLabor: float = Field(default=0, ge=0)
    unloadingFeeDaily: float = Field(default=0, ge=0)
    unloadingFeeWarehouse: float = Field(default=0, ge=0)
    unloadingFeeChargeMode: str = "TIDAK_ADA"
    loadingOvertimeLabor: float = Field(default=0, ge=0)
    loadingOvertimeDaily: float = Field(default=0, ge=0)
    loadingOvertimeWarehouse: float = Field(default=0, ge=0)
    loadingHolidayLabor: float = Field(default=0, ge=0)
    loadingHolidayDaily: float = Field(default=0, ge=0)
    loadingHolidayWarehouse: float = Field(default=0, ge=0)
    loadingHolidayOvertimeLabor: float = Field(default=0, ge=0)
    loadingHolidayOvertimeDaily: float = Field(default=0, ge=0)
    loadingHolidayOvertimeWarehouse: float = Field(default=0, ge=0)
    unloadingOvertimeLabor: float = Field(default=0, ge=0)
    unloadingOvertimeDaily: float = Field(default=0, ge=0)
    unloadingOvertimeWarehouse: float = Field(default=0, ge=0)
    unloadingHolidayLabor: float = Field(default=0, ge=0)
    unloadingHolidayDaily: float = Field(default=0, ge=0)
    unloadingHolidayWarehouse: float = Field(default=0, ge=0)
    unloadingHolidayOvertimeLabor: float = Field(default=0, ge=0)
    unloadingHolidayOvertimeDaily: float = Field(default=0, ge=0)
    unloadingHolidayOvertimeWarehouse: float = Field(default=0, ge=0)


def clean_master(body: MasterProductBody) -> dict:
    doc = body.model_dump()
    doc["name"] = doc["name"].strip()
    doc["sku"] = doc["sku"].strip()
    doc["unit"] = doc["unit"].strip() or "Pcs"
    doc["secondary"] = doc["secondary"].strip()
    doc["measureUnit"] = str(doc.get("measureUnit") or "kg").strip().lower()
    if doc["measureUnit"] not in {"kg", "liter", "pcs"}:
        raise HTTPException(status_code=400, detail="Satuan kuantum harus kg, liter, atau pcs")
    doc["channel"] = doc.get("channel", "KOM").strip().upper()
    if doc["channel"] not in {"PSO", "KOM"}:
        raise HTTPException(status_code=400, detail="Saluran produk harus PSO atau KOM")
    doc["loadingFeeChargeMode"] = str(doc.get("loadingFeeChargeMode") or "TIDAK_ADA").strip().upper()
    if doc["loadingFeeChargeMode"] == "0":
        doc["loadingFeeChargeMode"] = "TIDAK_ADA"
    if doc["loadingFeeChargeMode"] not in {"PENGAMBIL", "TERMASUK", "TIDAK_ADA"}:
        raise HTTPException(status_code=400, detail="Status biaya muat tidak valid")
    fee_keys = [key for key in doc if key.startswith(("loadingFee", "unloadingFee", "loadingOvertime", "loadingHoliday", "unloadingOvertime", "unloadingHoliday")) and key.endswith(("Labor", "Daily", "Warehouse"))]
    for key in fee_keys:
        doc[key] = float(doc.get(key, 0) or 0)
    doc["unloadingFeeChargeMode"] = str(doc.get("unloadingFeeChargeMode") or "TIDAK_ADA").strip().upper()
    if doc["unloadingFeeChargeMode"] == "0":
        doc["unloadingFeeChargeMode"] = "TIDAK_ADA"
    if doc["unloadingFeeChargeMode"] not in {"PENGIRIM", "TERMASUK", "TIDAK_ADA"}:
        raise HTTPException(status_code=400, detail="Status biaya bongkar tidak valid")
    if doc["loadingFeeChargeMode"] == "TIDAK_ADA" and sum(doc[key] for key in ("loadingFeeLabor", "loadingFeeDaily", "loadingFeeWarehouse")) > 0:
        raise HTTPException(status_code=400, detail="Pilih Ditagihkan atau Termasuk Harga bila tarif biaya muat diisi")
    if doc["unloadingFeeChargeMode"] == "TIDAK_ADA" and sum(doc[key] for key in ("unloadingFeeLabor", "unloadingFeeDaily", "unloadingFeeWarehouse")) > 0:
        raise HTTPException(status_code=400, detail="Pilih Ditagihkan atau Termasuk Harga bila tarif biaya bongkar diisi")
    if doc["secondary"] and doc["secondaryQty"] <= 0:
        raise HTTPException(status_code=400, detail="Isi kemasan sekunder harus lebih dari 0")
    if doc["secondaryQty"] > 0 and not doc["secondary"]:
        raise HTTPException(status_code=400, detail="Nama kemasan sekunder wajib diisi")
    if doc["secondaryQty"] > 0 and abs(doc["secondaryQty"] - round(doc["secondaryQty"])) > 1e-6:
        raise HTTPException(status_code=400, detail="Isi kemasan sekunder harus berupa jumlah pack utuh")
    if not doc["name"]:
        raise HTTPException(status_code=400, detail="Nama produk wajib diisi")
    if not doc["sku"]:
        raise HTTPException(status_code=400, detail="SKU wajib diisi")
    return doc


@router.post("/products-master")
async def create_master_product(body: MasterProductBody, user: dict = Depends(require_master_write)):
    master = clean_master(body)
    if await db.products.find_one({"sku": master["sku"]}):
        raise HTTPException(status_code=409, detail="SKU sudah digunakan")

    doc = {
        **master,
        "id": new_id(),
        "stock": 0,
        "damaged": 0,
        "exp": "",
    }
    await db.products.insert_one(dict(doc))
    return doc


@router.put("/products-master/{product_id}")
async def update_master_product(product_id: str, body: MasterProductBody, user: dict = Depends(require_master_write)):
    master = clean_master(body)
    current = await db.products.find_one({"id": product_id}, {"_id": 0})
    if not current:
        raise HTTPException(status_code=404, detail="Produk tidak ditemukan")
    if master["channel"] != (current.get("channel") or "KOM").upper() and (float(current.get("stock", 0) or 0) > 0 or float(current.get("damaged", 0) or 0) > 0):
        raise HTTPException(status_code=400, detail="Saluran default tidak dapat diubah selama masih ada saldo stok. Gunakan koreksi transaksi bila diperlukan.")

    packaging_changed = (
        float(current.get("secondaryQty", 0) or 0) != float(master.get("secondaryQty", 0) or 0)
        or str(current.get("secondary", "") or "").strip() != master.get("secondary", "")
    )
    allocations = []
    if packaging_changed:
        allocations = await db.stack_allocations.find({"productId": product_id}, {"_id": 0}).to_list(5000)
        if allocations and (float(master.get("secondaryQty", 0) or 0) <= 0 or not str(master.get("secondary") or "").strip()):
            raise HTTPException(
                status_code=400,
                detail="Produk yang masih berada di tumpukan wajib memiliki kemasan sekunder dan isi per kemasan lebih dari 0",
            )

    duplicate = await db.products.find_one({"sku": master["sku"], "id": {"$ne": product_id}})
    if duplicate:
        raise HTTPException(status_code=409, detail="SKU sudah digunakan")

    timestamp = now_iso()
    updated_allocations = []
    audit_id = ""
    try:
        result = await db.products.update_one({"id": product_id}, {"$set": master})
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Produk tidak ditemukan")

        if packaging_changed and allocations:
            per_secondary = float(master.get("secondaryQty", 0) or 0)
            secondary_name = str(master.get("secondary") or "").strip()
            for allocation in allocations:
                primary_qty = float(allocation.get("primaryQty", 0) or 0)
                secondary_count = int(primary_qty // per_secondary)
                primary_remainder = primary_qty - (secondary_count * per_secondary)
                changes = {
                    "secondary": secondary_name,
                    "secondaryQty": per_secondary,
                    "secondaryCount": secondary_count,
                    "primaryRemainder": primary_remainder,
                    "length": 0,
                    "width": 0,
                    "height": 0,
                    "arrangements": [],
                    "extraSecondary": 0,
                    "extraPrimary": primary_remainder,
                    "arrangementAdjusted": True,
                    "updatedAt": timestamp,
                    "packagingConversionUpdatedAt": timestamp,
                    "packagingConversionUpdatedBy": user.get("name", ""),
                }
                allocation_result = await db.stack_allocations.update_one({"id": allocation["id"]}, {"$set": changes})
                if allocation_result.matched_count == 0:
                    raise RuntimeError("Alokasi tumpukan berubah saat konversi kemasan")
                updated_allocations.append(allocation)

            audit_id = new_id()
            await db.transactions.insert_one({
                "id": audit_id,
                "operation_id": audit_id,
                "time": timestamp,
                "ref": master.get("sku", ""),
                "type": "KOREKSI",
                "kondisi": "MASTER",
                "document_type": "KOREKSI_KONVERSI_KEMASAN",
                "product": master.get("name", ""),
                "product_id": product_id,
                "change": 0,
                "unit": master.get("unit", ""),
                "operator": user.get("name", ""),
                "old_secondary": str(current.get("secondary") or ""),
                "old_secondary_qty": float(current.get("secondaryQty", 0) or 0),
                "new_secondary": master.get("secondary", ""),
                "new_secondary_qty": float(master.get("secondaryQty", 0) or 0),
                "affected_stack_ids": [row.get("id") for row in allocations if row.get("id")],
                "keterangan": "Konversi kemasan diubah; stok primer tetap dan representasi dus/karung pada tumpukan dihitung ulang.",
            })
    except Exception:
        if audit_id:
            await db.transactions.delete_one({"id": audit_id})
        for allocation in updated_allocations:
            await db.stack_allocations.replace_one({"id": allocation["id"]}, allocation, upsert=True)
        await db.products.replace_one({"id": product_id}, current, upsert=True)
        raise

    return await db.products.find_one({"id": product_id}, {"_id": 0})


@router.delete("/products-master/{product_id}")
async def delete_master_product(product_id: str, user: dict = Depends(require_master_write)):
    product = await db.products.find_one({"id": product_id}, {"_id": 0})
    if not product:
        raise HTTPException(status_code=404, detail="Produk tidak ditemukan")

    if float(product.get("stock", 0) or 0) > 0 or float(product.get("damaged", 0) or 0) > 0:
        raise HTTPException(status_code=400, detail="Master produk tidak dapat dihapus karena stok fisik masih tersedia")

    if await db.stack_allocations.find_one({"productId": product_id}):
        raise HTTPException(status_code=400, detail="Master produk masih digunakan pada tumpukan stok")

    open_po = await db.purchase_orders.find_one({
        "items.productId": product_id,
        "status": {"$nin": ["Selesai", "Diterima"]},
    })
    if open_po:
        raise HTTPException(status_code=400, detail="Master produk masih digunakan pada Purchase Order yang belum selesai")

    await db.products.delete_one({"id": product_id})
    return {"ok": True}
