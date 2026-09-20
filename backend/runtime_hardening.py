from __future__ import annotations

import logging
import uuid
from typing import Callable, Awaitable

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from backend.server import build_xlsx, create_unique_index_safely, db, get_current_user, normalize_channel, operational_now

logger = logging.getLogger(__name__)


def blocks_legacy_product_mutation(method: str, path: str) -> bool:
    method = str(method or "").upper()
    normalized = str(path or "").rstrip("/")
    return method in {"POST", "PUT", "PATCH", "DELETE"} and (
        normalized == "/api/products" or normalized.startswith("/api/products/")
    )


def blocks_legacy_direct_transaction(method: str, path: str) -> bool:
    return str(method or "").upper() == "POST" and str(path or "").rstrip("/") == "/api/transactions"


def blocks_legacy_po_or_import(method: str, path: str) -> bool:
    method = str(method or "").upper()
    normalized = str(path or "").rstrip("/")
    return method == "POST" and normalized in {"/api/purchase-orders", "/api/import/csv"}


def scoped_role_blocks_main_read(role: str | None, path: str) -> bool:
    if str(role or "").strip() not in {"Operator", "Petugas Bazar", "QC", "Petugas E-commerce", "Petugas Ecom"}:
        return False
    normalized = str(path or "").rstrip("/")
    prefixes = (
        "/api/products", "/api/suppliers", "/api/transactions", "/api/surat-jalan", "/api/purchase-orders",
        "/api/outbound-loads", "/api/stack-allocations", "/api/stack-treatments",
        "/api/stock-opnames", "/api/integrity-control", "/api/operational-corrections",
        "/api/supplier-returns", "/api/damaged-stock-area", "/api/stock-transfers",
        "/api/loading-costs", "/api/unloading-costs", "/api/cost-settlements",
    )
    return any(normalized == prefix or normalized.startswith(prefix + "/") for prefix in prefixes)


def measure_unit(value: str | None) -> str:
    candidate = str(value or "kg").strip().lower()
    return candidate if candidate in {"kg", "liter", "pcs"} else "kg"


async def ensure_performance_indexes() -> None:
    # Bon Muat sudah unik melalui ensure_operational_guard_indexes().
    # Nomor SJ sendiri unik dari initialize_app; indeks ini menutup relasi 1 load = 1 SJ.
    await create_unique_index_safely(
        db.surat_jalan,
        "load_id",
        sparse=True,
        name="surat_jalan_load_unique",
    )

    indexes = (
        (db.outbound_loads, [("status", 1), ("created_at", -1)], "queue_status_created"),
        (db.outbound_loads, [("operational_date", 1), ("antrian", 1)], "queue_operational_date"),
        (db.outbound_loads, [("operational_date", 1), ("bon_no", 1)], "bon_operational_date"),
        (db.outbound_loads, [("documents", 1)], "outbound_documents"),
        (db.transactions, [("time", -1)], "transactions_time"),
        (db.transactions, [("operation_id", 1), ("time", -1)], "transactions_operation"),
        (db.transactions, [("product_id", 1), ("time", -1)], "transactions_product_time"),
        (db.transactions, [("load_id", 1), ("time", -1)], "transactions_load_time"),
        (db.surat_jalan, [("time", -1)], "surat_jalan_time"),
        (db.stack_history, [("time", -1)], "stack_history_time"),
        (db.stack_history, [("stackCode", 1), ("time", -1)], "stack_history_stack_time"),
        (db.consignment_movements, [("time", -1)], "consignment_movement_time"),
        (db.consignment_operation_history, [("time", -1)], "consignment_operation_history_time"),
        (db.purchase_orders, [("date", -1), ("status", 1)], "purchase_order_date_status"),
        (db.outbound_documents, [("updatedAt", -1)], "outbound_document_updated"),
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
        db.stock_opnames, db.stack_lots, db.stack_lot_movements,
        db.operation_requests, db.operation_locks,
        db.consignment_movements, db.consignment_operation_history,
        db.consignment_damaged_balances, db.consignment_damaged_movements,
        db.bazar_trips, db.ecom_orders,
        db.bazar_package_templates, db.bazar_package_batches, db.bazar_package_loads,
        db.unloading_cost_settlements,
        db.marketplace_sync_logs, db.marketplace_auth_sessions, db.marketplace_webhook_events,
    ):
        await collection.delete_many({})


async def hardening_middleware(request: Request, call_next: Callable[[Request], Awaitable]):
    request_id = str(request.headers.get("X-Request-ID") or uuid.uuid4().hex)[:100]
    method = request.method.upper()
    path = request.url.path.rstrip("/")

    if method in {"POST", "PUT", "PATCH", "DELETE"} and not (
        path.startswith("/api/auth/")
        or path.startswith("/api/admin/backups/")
        or path == "/api/admin/maintenance"
    ):
        settings = await db.settings.find_one({"_id": "app"}, {"_id": 0, "maintenanceMode": 1}) or {}
        if settings.get("maintenanceMode"):
            return JSONResponse(
                status_code=503,
                content={"detail": "PEPEG sedang Maintenance Mode. Transaksi sementara dikunci.", "requestId": request_id},
                headers={"X-Request-ID": request_id},
            )

    if blocks_legacy_product_mutation(request.method, request.url.path):
        return JSONResponse(status_code=409, content={"detail": "Endpoint master produk lama dinonaktifkan untuk mencegah perubahan stok langsung. Gunakan /api/products-master dan transaksi stok."})
    if blocks_legacy_direct_transaction(request.method, request.url.path):
        return JSONResponse(status_code=409, content={"detail": "Transaksi stok langsung versi lama dinonaktifkan. Gunakan penerimaan /api/receipts atau proses pemuatan /api/outbound-loads agar tumpukan, saluran, Bon Muat, dan antrian tetap konsisten."})
    if blocks_legacy_po_or_import(request.method, request.url.path):
        return JSONResponse(status_code=409, content={"detail": "Endpoint versi lama dinonaktifkan. Gunakan Purchase Order V2 dan alur import master PEPEG terbaru."})
    if request.method.upper() == "GET":
        try:
            scoped_user = await get_current_user(request)
        except HTTPException:
            scoped_user = None
        if scoped_user and scoped_role_blocks_main_read(scoped_user.get("role"), request.url.path):
            return JSONResponse(status_code=403, content={"detail": "Peran ini hanya dapat mengakses data Bazar/E-commerce sesuai ruang lingkupnya."})
    if request.method.upper() == "GET" and request.url.path.rstrip("/") == "/api/export/products.xlsx":
        return await _export_products_xlsx(request)

    try:
        response = await call_next(request)
    except Exception:
        logger.exception("Unhandled request error requestId=%s method=%s path=%s", request_id, method, path)
        return JSONResponse(
            status_code=500,
            content={"detail": "Terjadi kesalahan server. Gunakan Request ID saat melaporkan masalah.", "requestId": request_id},
            headers={"X-Request-ID": request_id},
        )
    response.headers["X-Request-ID"] = request_id
    if method == "POST" and path == "/api/admin/reset-data" and 200 <= response.status_code < 300:
        try:
            await _cleanup_new_operational_collections()
        except Exception as exc:
            logger.exception("Reset utama berhasil tetapi cleanup modul baru gagal: %s", exc)
    return response
