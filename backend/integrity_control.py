from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from backend.server import db, require_master_write

router = APIRouter(prefix="/api")
EPS = 1e-9


def _number(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def product_integrity_row(
    product: dict,
    stack_qty: float,
    reserved_good: float,
    reserved_damaged: float,
) -> dict:
    stock = _number(product.get("stock"))
    damaged = _number(product.get("damaged"))
    channel_stock = product.get("channelStock") or {}
    channel_good = sum(_number((channel_stock.get(channel) or {}).get("stock")) for channel in ("PSO", "KOM"))
    channel_damaged = sum(_number((channel_stock.get(channel) or {}).get("damaged")) for channel in ("PSO", "KOM"))
    stack_diff = stock - _number(stack_qty)
    channel_good_diff = stock - channel_good
    channel_damaged_diff = damaged - channel_damaged

    issues: list[str] = []
    severity = "OK"

    def add_issue(message: str, level: str = "WARNING") -> None:
        nonlocal severity
        issues.append(message)
        if level == "ERROR" or severity == "OK":
            severity = level

    if stock < -EPS or damaged < -EPS:
        add_issue("Saldo master bernilai negatif", "ERROR")
    if stack_qty - stock > EPS:
        add_issue("Total tumpukan lebih besar daripada stok Baik master", "ERROR")
    elif stock - stack_qty > EPS:
        add_issue("Sebagian stok Baik belum teralokasi ke tumpukan")
    if abs(channel_good_diff) > EPS:
        add_issue("Total saldo PSO/KOM stok Baik tidak sama dengan master", "ERROR")
    if abs(channel_damaged_diff) > EPS:
        add_issue("Total saldo PSO/KOM stok Rusak tidak sama dengan master", "ERROR")
    if reserved_good - stock > EPS:
        add_issue("Reservasi outbound stok Baik melebihi saldo master", "ERROR")
    if reserved_damaged - damaged > EPS:
        add_issue("Reservasi outbound stok Rusak melebihi saldo rusak", "ERROR")

    return {
        "productId": product.get("id", ""),
        "sku": product.get("sku", ""),
        "name": product.get("name", ""),
        "unit": product.get("unit", ""),
        "masterGood": stock,
        "stackGood": _number(stack_qty),
        "stackDifference": stack_diff,
        "masterDamaged": damaged,
        "channelGood": channel_good,
        "channelGoodDifference": channel_good_diff,
        "channelDamaged": channel_damaged,
        "channelDamagedDifference": channel_damaged_diff,
        "reservedGood": _number(reserved_good),
        "reservedDamaged": _number(reserved_damaged),
        "availableGoodAfterReservation": stock - _number(reserved_good),
        "availableDamagedAfterReservation": damaged - _number(reserved_damaged),
        "severity": severity,
        "issues": issues,
    }


@router.get("/integrity-control")
async def integrity_control(user: dict = Depends(require_master_write)):
    products = await db.products.find({}, {"_id": 0}).sort("name", 1).to_list(20000)
    product_ids = {str(product.get("id") or "") for product in products if product.get("id")}

    stack_totals: dict[str, float] = defaultdict(float)
    orphan_allocations = []
    allocations = await db.stack_allocations.find({}, {"_id": 0}).to_list(50000)
    for allocation in allocations:
        product_id = str(allocation.get("productId") or "")
        stack_totals[product_id] += _number(allocation.get("primaryQty"))
        if product_id and product_id not in product_ids:
            orphan_allocations.append({
                "id": allocation.get("id", ""),
                "productId": product_id,
                "sku": allocation.get("sku", ""),
                "product": allocation.get("productName", ""),
                "stackCode": allocation.get("stackCode", ""),
                "qty": _number(allocation.get("primaryQty")),
            })

    reserved_good: dict[str, float] = defaultdict(float)
    reserved_damaged: dict[str, float] = defaultdict(float)
    active_loads = await db.outbound_loads.find(
        {"status": {"$in": ["Menunggu", "Sedang Dimuat"]}},
        {"_id": 0, "id": 1, "antrian": 1, "kondisi": 1, "items": 1},
    ).to_list(10000)
    for load in active_loads:
        target = reserved_damaged if str(load.get("kondisi") or "BAIK").upper() == "RUSAK" else reserved_good
        for item in load.get("items", []):
            product_id = str(item.get("productId") or "")
            if product_id:
                target[product_id] += _number(item.get("qty"))

    rows = [
        product_integrity_row(
            product,
            stack_totals.get(str(product.get("id") or ""), 0),
            reserved_good.get(str(product.get("id") or ""), 0),
            reserved_damaged.get(str(product.get("id") or ""), 0),
        )
        for product in products
    ]

    po_issues = []
    purchase_orders = await db.purchase_orders.find({}, {"_id": 0, "id": 1, "no": 1, "status": 1, "items": 1}).to_list(10000)
    for po in purchase_orders:
        for item in po.get("items", []):
            ordered = _number(item.get("qty"))
            received = _number(item.get("receivedQty", item.get("received_qty", 0)))
            if received - ordered > EPS:
                po_issues.append({
                    "poId": po.get("id", ""),
                    "poNo": po.get("no", ""),
                    "productId": item.get("productId", ""),
                    "product": item.get("name", ""),
                    "ordered": ordered,
                    "received": received,
                    "difference": received - ordered,
                    "issue": "Jumlah diterima melebihi jumlah PO",
                })

    missing_product_id_transactions = await db.transactions.count_documents({
        "type": {"$in": ["MASUK", "KELUAR", "PENYESUAIAN", "KOREKSI"]},
        "$or": [
            {"product_id": {"$exists": False}},
            {"product_id": ""},
            {"product_id": None},
        ],
    })

    errors = sum(1 for row in rows if row["severity"] == "ERROR")
    warnings = sum(1 for row in rows if row["severity"] == "WARNING")
    ok = sum(1 for row in rows if row["severity"] == "OK")

    system_issues = []
    if orphan_allocations:
        system_issues.append({"severity": "ERROR", "code": "ORPHAN_STACK", "message": f"Ada {len(orphan_allocations)} alokasi tumpukan tanpa master produk."})
    if po_issues:
        system_issues.append({"severity": "ERROR", "code": "PO_OVER_RECEIVED", "message": f"Ada {len(po_issues)} baris PO dengan penerimaan melebihi pesanan."})
    if missing_product_id_transactions:
        system_issues.append({"severity": "WARNING", "code": "MISSING_PRODUCT_ID", "message": f"Ada {missing_product_id_transactions} transaksi historis yang belum memiliki product_id permanen."})

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "products": len(rows),
            "ok": ok,
            "warnings": warnings,
            "errors": errors,
            "activeOutboundLoads": len(active_loads),
            "orphanAllocations": len(orphan_allocations),
            "poIssues": len(po_issues),
            "missingProductIdTransactions": missing_product_id_transactions,
        },
        "products": rows,
        "systemIssues": system_issues,
        "orphanAllocations": orphan_allocations[:200],
        "poIssues": po_issues[:500],
    }
