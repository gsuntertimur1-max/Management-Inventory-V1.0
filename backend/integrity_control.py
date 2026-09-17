from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from backend.server import db, require_master_write

router = APIRouter(prefix="/api")
EPS = 1e-9
ACTIVE_OUTBOUND_STATUSES = {"Menunggu", "Sedang Dimuat"}


def _number(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _stack_code(value) -> str:
    return str(value or "").strip().upper()


def build_stack_reservation_integrity(
    allocations: list[dict],
    active_loads: list[dict],
    products: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Bangun kontrol reservasi per produk+tumpukan untuk stok BAIK aktif.

    Tersedia sengaja tidak di-clamp ke nol agar kondisi over-reserved dapat
    terlihat sebagai angka negatif pada Kontrol Integritas.
    """
    product_map = {str(product.get("id") or ""): product for product in products if product.get("id")}
    physical: dict[tuple[str, str], float] = defaultdict(float)
    for allocation in allocations:
        product_id = str(allocation.get("productId") or "")
        code = _stack_code(allocation.get("stackCode"))
        if product_id and code:
            physical[(product_id, code)] += _number(allocation.get("primaryQty"))

    reserved: dict[tuple[str, str], float] = defaultdict(float)
    queue_refs: dict[tuple[str, str], list[str]] = defaultdict(list)
    item_meta: dict[tuple[str, str], dict] = {}
    unassigned: list[dict] = []

    for load in active_loads:
        if str(load.get("kondisi") or "BAIK").upper() != "BAIK":
            continue
        queue_ref = str(load.get("antrian") or load.get("ref") or load.get("id") or "").strip()
        for item in load.get("items", []):
            product_id = str(item.get("productId") or "")
            qty = _number(item.get("qty"))
            if not product_id or qty <= EPS:
                continue
            code = _stack_code(item.get("stackCode"))
            product = product_map.get(product_id) or {}
            if not code:
                unassigned.append({
                    "loadId": load.get("id", ""),
                    "queue": load.get("antrian", ""),
                    "ref": load.get("ref", ""),
                    "productId": product_id,
                    "sku": item.get("sku") or product.get("sku", ""),
                    "name": item.get("name") or product.get("name", ""),
                    "unit": item.get("unit") or product.get("unit", ""),
                    "qty": qty,
                    "issue": "Reservasi outbound aktif belum memiliki tumpukan sumber",
                })
                continue

            key = (product_id, code)
            reserved[key] += qty
            item_meta[key] = {
                "sku": item.get("sku") or product.get("sku", ""),
                "name": item.get("name") or product.get("name", ""),
                "unit": item.get("unit") or product.get("unit", ""),
            }
            if queue_ref and queue_ref not in queue_refs[key]:
                queue_refs[key].append(queue_ref)

    rows = []
    for product_id, code in sorted(reserved, key=lambda key: (key[1], item_meta.get(key, {}).get("name", ""), key[0])):
        key = (product_id, code)
        physical_qty = _number(physical.get(key, 0))
        reserved_qty = _number(reserved.get(key, 0))
        available = physical_qty - reserved_qty
        over_by = max(reserved_qty - physical_qty, 0.0)
        meta = item_meta.get(key, {})
        rows.append({
            "productId": product_id,
            "sku": meta.get("sku", ""),
            "name": meta.get("name", ""),
            "unit": meta.get("unit", ""),
            "stackCode": code,
            "physical": physical_qty,
            "reserved": reserved_qty,
            "available": available,
            "overReserved": over_by > EPS,
            "overBy": over_by,
            "queues": queue_refs.get(key, []),
        })

    return rows, unassigned


def product_integrity_row(
    product: dict,
    stack_qty: float,
    reserved_good: float,
    reserved_damaged: float,
    over_reserved_stack_count: int = 0,
    unassigned_stack_reservation_count: int = 0,
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
    if over_reserved_stack_count:
        add_issue(f"{over_reserved_stack_count} tumpukan over-reserved", "ERROR")
    if unassigned_stack_reservation_count:
        add_issue(f"{unassigned_stack_reservation_count} reservasi aktif belum memiliki tumpukan sumber", "ERROR")

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
        "overReservedStackCount": int(over_reserved_stack_count or 0),
        "unassignedStackReservationCount": int(unassigned_stack_reservation_count or 0),
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
        {"status": {"$in": list(ACTIVE_OUTBOUND_STATUSES)}},
        {"_id": 0, "id": 1, "antrian": 1, "ref": 1, "kondisi": 1, "items": 1},
    ).to_list(10000)
    for load in active_loads:
        target = reserved_damaged if str(load.get("kondisi") or "BAIK").upper() == "RUSAK" else reserved_good
        for item in load.get("items", []):
            product_id = str(item.get("productId") or "")
            if product_id:
                target[product_id] += _number(item.get("qty"))

    stack_reservations, unassigned_stack_reservations = build_stack_reservation_integrity(
        allocations, active_loads, products
    )
    over_reserved_by_product: dict[str, int] = defaultdict(int)
    for reservation in stack_reservations:
        if reservation.get("overReserved"):
            over_reserved_by_product[str(reservation.get("productId") or "")] += 1
    unassigned_by_product: dict[str, int] = defaultdict(int)
    for reservation in unassigned_stack_reservations:
        unassigned_by_product[str(reservation.get("productId") or "")] += 1

    rows = [
        product_integrity_row(
            product,
            stack_totals.get(str(product.get("id") or ""), 0),
            reserved_good.get(str(product.get("id") or ""), 0),
            reserved_damaged.get(str(product.get("id") or ""), 0),
            over_reserved_by_product.get(str(product.get("id") or ""), 0),
            unassigned_by_product.get(str(product.get("id") or ""), 0),
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
    over_reserved_stacks = [row for row in stack_reservations if row.get("overReserved")]

    system_issues = []
    if orphan_allocations:
        system_issues.append({"severity": "ERROR", "code": "ORPHAN_STACK", "message": f"Ada {len(orphan_allocations)} alokasi tumpukan tanpa master produk."})
    if over_reserved_stacks:
        system_issues.append({"severity": "ERROR", "code": "STACK_OVER_RESERVED", "message": f"Ada {len(over_reserved_stacks)} tumpukan dengan reservasi outbound melebihi stok fisik."})
    if unassigned_stack_reservations:
        system_issues.append({"severity": "ERROR", "code": "OUTBOUND_STACK_MISSING", "message": f"Ada {len(unassigned_stack_reservations)} baris reservasi outbound aktif yang belum memiliki tumpukan sumber."})
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
            "reservedStacks": len(stack_reservations),
            "overReservedStacks": len(over_reserved_stacks),
            "unassignedStackReservations": len(unassigned_stack_reservations),
            "orphanAllocations": len(orphan_allocations),
            "poIssues": len(po_issues),
            "missingProductIdTransactions": missing_product_id_transactions,
        },
        "products": rows,
        "stackReservations": stack_reservations,
        "unassignedStackReservations": unassigned_stack_reservations[:500],
        "systemIssues": system_issues,
        "orphanAllocations": orphan_allocations[:200],
        "poIssues": po_issues[:500],
    }
