from __future__ import annotations

import logging
from typing import Callable, Awaitable

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from backend.server import build_xlsx, db, get_current_user, normalize_channel, operational_now

logger = logging.getLogger(__name__)


def blocks_legacy_product_mutation(method: str, path: str) -> bool:
    method = str(method or "").upper()
    normalized = str(path or "").rstrip("/")
    return method in {"POST", "PUT", "PATCH", "DELETE"} and (
        normalized == "/api/products" or normalized.startswith("/api/products/")
    )


def blocks_legacy_direct_transaction(method: str, path: str) -> bool:
    return str(method or "").upper() == "POST" and str(path or "").rstrip("/") == "/api/transactions"


def measure_unit(value: str | None) -> str:
    candidate = str(value or "kg").strip().lower()
    return candidate if candidate in {"kg", "liter", "pcs"} else "kg"


async def ensure_performance_indexes() -> None:
    indexes = (
        (db.outbound_loads, [("status", 1), ("created_at", -1)], "queue_status_created"),
        (db.outbound_loads, [("operational_date", 1), ("antrian", 1)], "queue_operational_date"),
        (db.outbound_loads, [("operational_date", 1), ("bon_no", 1)], "bon_operational_date"),
        (db.outbound_loads, [("documents", 1)], "outbound_documents"),
        (db.transactions, [("time", -1)], "transactions_time"),
        (db.transactions, [("operation_id", 1), ("time", -1)], "transactions_operation"),
        (db.transactions, [("product_id", 1), ("time", -1)], "transactions_product_time"),
        (db.surat_jalan, [("time", -1)], "surat_jalan_time"),
        (db.stack_allocations, [("stackCode", 1), ("productName", 1)], "stack_location_product"),
        (db.stack_treatments, [("warehouse", 1), ("stackCode", 1), ("startDate", -1)], "treatment_location_date"),
        (db.stock_opnames, [("warehouse", 1), ("status", 1), ("createdAt", -1)], "stock_opname_warehouse_status"),
        (db.stock_opnames, [("createdAt", -1)], "stock_opname_created"),
    )
    for collection, keys, name in indexes:
        try:
            await collection.create_index(keys, name=name)
        except Exception as exc:
            logger.warning("Index %s gagal dibuat: %s", name, exc)


async def _export_products_xlsx(request: Request):
    try:
        await get_current_user(request)
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    products = await db.products.find({}, {"_id": 0}).sort("name", 1).to_list(5000)
    headers = [
        "Nama Produk", "SKU", "Saluran", "Kategori", "Stok Baik", "Stok Rusak", "Satuan",
        "Harga Modal", "Nilai Total", "Supplier", "Lokasi", "Stok Minimum",
        "Kuantum/Unit", "Satuan Kuantum", "Kemasan Sekunder", "Isi/Kemasan Sekunder",
        "Kuantum/Kemasan Sekunder", "Kedaluwarsa",
    ]
    rows = []
    for product in products:
        weight = float(product.get("weight", 0) or 0)
        secondary_qty = float(product.get("secondaryQty", 0) or 0)
        unit = measure_unit(product.get("measureUnit"))
        rows.append([
            product.get("name", ""), product.get("sku", ""), normalize_channel(product.get("channel")),
            product.get("category", ""), product.get("stock", 0), product.get("damaged", 0), product.get("unit", ""),
            product.get("cost", 0), (product.get("stock", 0) or 0) * (product.get("cost", 0) or 0),
            product.get("supplier", ""), product.get("location", ""), product.get("min", 0),
            weight, unit, product.get("secondary", ""), secondary_qty, weight * secondary_qty, product.get("exp", ""),
        ])
    output = build_xlsx(headers, rows, "Daftar Produk")
    filename = f"daftar_produk_{operational_now().strftime('%Y%m%d_%H%M')}.xlsx"
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def _cleanup_new_operational_collections() -> None:
    for collection in (
        db.stock_opnames,
        db.stack_lots,
        db.stack_lot_movements,
        db.operation_requests,
        db.operation_locks,
    ):
        await collection.delete_many({})


async def hardening_middleware(request: Request, call_next: Callable[[Request], Awaitable]):
    if blocks_legacy_product_mutation(request.method, request.url.path):
        return JSONResponse(status_code=409, content={"detail": "Endpoint master produk lama dinonaktifkan untuk mencegah perubahan stok langsung. Gunakan /api/products-master dan transaksi stok."})
    if blocks_legacy_direct_transaction(request.method, request.url.path):
        return JSONResponse(status_code=409, content={"detail": "Transaksi stok langsung versi lama dinonaktifkan. Gunakan penerimaan /api/receipts atau proses pemuatan /api/outbound-loads agar tumpukan, saluran, Bon Muat, dan antrian tetap konsisten."})
    if request.method.upper() == "GET" and request.url.path.rstrip("/") == "/api/export/products.xlsx":
        return await _export_products_xlsx(request)

    response = await call_next(request)
    if request.method.upper() == "POST" and request.url.path.rstrip("/") == "/api/admin/reset-data" and 200 <= response.status_code < 300:
        try:
            await _cleanup_new_operational_collections()
        except Exception as exc:
            logger.exception("Reset utama berhasil tetapi cleanup modul baru gagal: %s", exc)
    return response
