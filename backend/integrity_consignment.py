from __future__ import annotations

from collections import defaultdict

from backend.server import db, normalize_channel
import backend.consignment as consignment_module
import backend.consignment_operations as operations
from backend.bazar_external_nd import summarize_external_nd

EPS = 1e-9
BAZAR = "Gudang Bazar"
ECOM = "Gudang E-commerce"
DESTINATIONS = (BAZAR, ECOM)


def _n(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _severity(issues: list[dict]) -> tuple[int, int]:
    return (
        sum(1 for row in issues if row.get("severity") == "ERROR"),
        sum(1 for row in issues if row.get("severity") == "WARNING"),
    )


async def analyze_consignment_integrity() -> dict:
    consignment_rows: list[dict] = []
    reservation_issues: list[dict] = []

    identities: dict[str, dict] = {}
    good_by_destination: dict[str, dict[str, float]] = {}
    for destination in DESTINATIONS:
        stock_rows = await operations.adjusted_consignment_stock(destination)
        good = defaultdict(float)
        for row in stock_rows:
            product_id = str(row.get("productId") or "")
            if not product_id:
                continue
            good[product_id] += _n(row.get("qty"))
            identities[product_id] = row
        good_by_destination[destination] = dict(good)

        layouts = await db.consignment_layouts.find(
            {"destination": destination},
            {"_id": 0},
        ).to_list(10000)
        layout_totals = defaultdict(float)
        negative_layouts = defaultdict(list)
        for layout in layouts:
            product_id = str(layout.get("productId") or "")
            qty = consignment_module._layout_primary_qty(layout)
            if product_id:
                layout_totals[product_id] += qty
                if qty < -EPS:
                    negative_layouts[product_id].append({
                        "stackCode": layout.get("stackCode", ""),
                        "qty": qty,
                    })
                identities.setdefault(product_id, {
                    "productId": product_id,
                    "sku": layout.get("sku", ""),
                    "name": layout.get("productName", ""),
                    "unit": layout.get("unit", ""),
                })

        product_ids = sorted(set(good) | set(layout_totals))
        for product_id in product_ids:
            meta = identities.get(product_id, {})
            ledger = _n(good.get(product_id))
            physical = _n(layout_totals.get(product_id))
            diff = physical - ledger
            issues = []
            severity = "OK"
            if negative_layouts.get(product_id):
                severity = "ERROR"
                issues.append("Ada lokasi fisik dengan saldo negatif")
            if abs(diff) > EPS:
                severity = "ERROR"
                issues.append("Total lokasi fisik tidak sama dengan saldo konsinyasi")
            consignment_rows.append({
                "destination": destination,
                "productId": product_id,
                "sku": meta.get("sku", ""),
                "name": meta.get("name", ""),
                "unit": meta.get("unit", ""),
                "ledgerQty": ledger,
                "layoutQty": physical,
                "difference": diff,
                "severity": severity,
                "issues": issues,
                "negativeLayouts": negative_layouts.get(product_id, []),
            })

    bazar_trip_reserved = defaultdict(float)
    trips = await db.bazar_trips.find(
        {"status": "BERJALAN"},
        {"_id": 0, "tripNo": 1, "items": 1},
    ).to_list(5000)
    for trip in trips:
        for item in trip.get("items", []):
            product_id = str(item.get("productId") or "")
            if product_id:
                bazar_trip_reserved[product_id] += _n(item.get("loadedQty"))

    package_batches = await db.bazar_package_batches.find({}, {"_id": 0}).to_list(10000)
    template_ids = sorted({str(row.get("templateId") or "") for row in package_batches if row.get("templateId")})
    templates = await db.bazar_package_templates.find(
        {"id": {"$in": template_ids}},
        {"_id": 0},
    ).to_list(10000) if template_ids else []
    template_map = {str(row.get("id") or ""): row for row in templates}

    package_component_hold = defaultdict(float)
    package_issues: list[dict] = []
    physical_packages = defaultdict(float)
    for batch in package_batches:
        template_id = str(batch.get("templateId") or "")
        remaining = _n(batch.get("remainingQty"))
        if remaining < -EPS:
            package_issues.append({
                "severity": "ERROR",
                "code": "PACKAGE_BATCH_NEGATIVE",
                "reference": batch.get("batchNo", ""),
                "templateId": template_id,
                "remainingQty": remaining,
                "issue": "Sisa Batch Paket Jadi bernilai negatif.",
            })
        if remaining > EPS:
            physical_packages[template_id] += remaining
        template = template_map.get(template_id)
        if not template:
            package_issues.append({
                "severity": "ERROR",
                "code": "PACKAGE_BATCH_ORPHAN_TEMPLATE",
                "reference": batch.get("batchNo", ""),
                "issue": "Batch Paket Jadi tidak memiliki master paket.",
            })
            continue
        if remaining > EPS:
            for component in template.get("components", []):
                product_id = str(component.get("productId") or "")
                if product_id:
                    package_component_hold[product_id] += remaining * _n(component.get("qty"))

    active_package_loads = await db.bazar_package_loads.find(
        {"status": "BERJALAN"},
        {"_id": 0, "loadNo": 1, "items": 1},
    ).to_list(5000)
    package_reserved = defaultdict(float)
    for load in active_package_loads:
        for item in load.get("items", []):
            template_id = str(item.get("templateId") or "")
            if template_id:
                package_reserved[template_id] += _n(item.get("loadedQty"))

    all_template_ids = sorted(set(physical_packages) | set(package_reserved))
    for template_id in all_template_ids:
        template = template_map.get(template_id) or await db.bazar_package_templates.find_one({"id": template_id}, {"_id": 0}) or {}
        physical = _n(physical_packages.get(template_id))
        reserved = _n(package_reserved.get(template_id))
        if reserved - physical > EPS:
            package_issues.append({
                "severity": "ERROR",
                "code": "PACKAGE_OVER_RESERVED",
                "templateId": template_id,
                "packageCode": template.get("code", ""),
                "packageName": template.get("name", ""),
                "physicalQty": physical,
                "reservedQty": reserved,
                "overBy": reserved - physical,
                "issue": "Reservasi pemuatan Paket melebihi Paket Jadi fisik.",
            })

    bazar_good = good_by_destination.get(BAZAR, {})
    for product_id in sorted(set(bazar_trip_reserved) | set(package_component_hold)):
        trip_qty = _n(bazar_trip_reserved.get(product_id))
        package_qty = _n(package_component_hold.get(product_id))
        bound = trip_qty + package_qty
        good = _n(bazar_good.get(product_id))
        if bound - good > EPS:
            meta = identities.get(product_id, {})
            reservation_issues.append({
                "severity": "ERROR",
                "destination": BAZAR,
                "productId": product_id,
                "sku": meta.get("sku", ""),
                "name": meta.get("name", ""),
                "unit": meta.get("unit", ""),
                "physicalQty": good,
                "tripReservedQty": trip_qty,
                "packageComponentQty": package_qty,
                "reservedQty": bound,
                "overBy": bound - good,
                "issue": "Stok Bazar yang terikat perjalanan + Paket melebihi saldo konsinyasi.",
            })

    ecom_orders = await db.ecom_orders.find({}, {"_id": 0}).to_list(20000)
    ecom_active_reserved = defaultdict(float)
    ecom_order_issues: list[dict] = []
    shipped_movements = await db.consignment_movements.find(
        {"destination": ECOM, "movementType": "ECOM_DIKIRIM"},
        {"_id": 0},
    ).to_list(50000)
    shipped_by_order_product = defaultdict(float)
    for movement in shipped_movements:
        shipped_by_order_product[(str(movement.get("referenceId") or ""), str(movement.get("productId") or ""))] += -_n(movement.get("delta"))

    for order in ecom_orders:
        status = str(order.get("status") or "RESERVED")
        expected = defaultdict(float)
        for item in order.get("items", []):
            product_id = str(item.get("productId") or "")
            if not product_id:
                continue
            qty = _n(item.get("qty"))
            expected[product_id] += qty
            if status in {"RESERVED", "PACKING"}:
                ecom_active_reserved[product_id] += qty

        for product_id, expected_qty in expected.items():
            shipped_qty = _n(shipped_by_order_product.get((str(order.get("id") or ""), product_id)))
            if status == "SHIPPED" and abs(shipped_qty - expected_qty) > EPS:
                ecom_order_issues.append({
                    "severity": "ERROR",
                    "code": "ECOM_SHIPMENT_MOVEMENT_MISMATCH",
                    "orderId": order.get("id", ""),
                    "orderNo": order.get("orderNo", ""),
                    "marketplace": order.get("marketplace", ""),
                    "productId": product_id,
                    "expectedQty": expected_qty,
                    "movementQty": shipped_qty,
                    "difference": shipped_qty - expected_qty,
                    "issue": "Order SHIPPED tidak cocok dengan movement ECOM_DIKIRIM.",
                })
            if status in {"RESERVED", "PACKING", "CANCELLED"} and shipped_qty > EPS:
                ecom_order_issues.append({
                    "severity": "ERROR",
                    "code": "ECOM_PRE_SHIP_HAS_MOVEMENT",
                    "orderId": order.get("id", ""),
                    "orderNo": order.get("orderNo", ""),
                    "marketplace": order.get("marketplace", ""),
                    "productId": product_id,
                    "status": status,
                    "movementQty": shipped_qty,
                    "issue": f"Order {status} sudah memiliki movement pengiriman.",
                })

    ecom_good = good_by_destination.get(ECOM, {})
    for product_id, reserved in ecom_active_reserved.items():
        good = _n(ecom_good.get(product_id))
        if reserved - good > EPS:
            meta = identities.get(product_id, {})
            reservation_issues.append({
                "severity": "ERROR",
                "destination": ECOM,
                "productId": product_id,
                "sku": meta.get("sku", ""),
                "name": meta.get("name", ""),
                "unit": meta.get("unit", ""),
                "physicalQty": good,
                "reservedQty": reserved,
                "overBy": reserved - good,
                "issue": "Reservasi order E-commerce melebihi saldo konsinyasi.",
            })

    damaged_balances = await db.consignment_damaged_balances.find({}, {"_id": 0}).to_list(20000)
    damaged_movements = await db.consignment_damaged_movements.find({}, {"_id": 0}).to_list(50000)
    damaged_ledger = defaultdict(float)
    for movement in damaged_movements:
        key = (
            str(movement.get("destination") or ""),
            str(movement.get("productId") or ""),
            normalize_channel(movement.get("channel"), "KOM"),
        )
        damaged_ledger[key] += _n(movement.get("delta"))
    balance_map = {}
    for balance in damaged_balances:
        key = (
            str(balance.get("destination") or ""),
            str(balance.get("productId") or ""),
            normalize_channel(balance.get("channel"), "KOM"),
        )
        balance_map[key] = balance

    damaged_issues: list[dict] = []
    for key in sorted(set(damaged_ledger) | set(balance_map)):
        balance = balance_map.get(key, {})
        current = _n(balance.get("qty"))
        ledger = _n(damaged_ledger.get(key))
        if current < -EPS or abs(current - ledger) > EPS:
            damaged_issues.append({
                "severity": "ERROR",
                "destination": key[0],
                "productId": key[1],
                "channel": key[2],
                "sku": balance.get("sku", ""),
                "name": balance.get("name", ""),
                "unit": balance.get("unit", ""),
                "balanceQty": current,
                "ledgerQty": ledger,
                "difference": current - ledger,
                "issue": "Saldo Area Barang Rusak negatif atau tidak sama dengan total movement.",
            })

    active_opnames = await db.consignment_opnames.find(
        {"status": {"$in": ["DRAFT", "SUBMITTED"]}},
        {"_id": 0},
    ).sort("createdAt", -1).to_list(1000)
    damaged_active_opnames = await db.consignment_damaged_opnames.find(
        {"status": {"$in": ["DRAFT", "SUBMITTED"]}},
        {"_id": 0},
    ).sort("createdAt", -1).to_list(1000)
    opname_issues = [{
        "severity": "WARNING",
        "code": "CONSIGNMENT_OPNAME_PENDING",
        "opnameId": row.get("id", ""),
        "opnameNo": row.get("no", ""),
        "destination": row.get("destination", ""),
        "status": row.get("status", ""),
        "stockType": "BAIK",
        "createdAt": row.get("createdAt", ""),
        "issue": "Stock opname konsinyasi stok Baik masih aktif; selesaikan atau tolak agar snapshot tidak tertinggal.",
    } for row in active_opnames]
    opname_issues.extend({
        "severity": "WARNING",
        "code": "CONSIGNMENT_DAMAGED_OPNAME_PENDING",
        "opnameId": row.get("id", ""),
        "opnameNo": row.get("no", ""),
        "destination": row.get("destination", ""),
        "status": row.get("status", ""),
        "stockType": "RUSAK",
        "createdAt": row.get("createdAt", ""),
        "issue": "Stock opname Area Barang Rusak masih aktif; selesaikan atau tolak agar snapshot tidak tertinggal.",
    } for row in damaged_active_opnames)

    external_nd_docs = await db.bazar_external_nd.find({}, {"_id": 0}).to_list(10000)
    nd_issues: list[dict] = []
    reference_usage = defaultdict(float)
    reference_meta = {}
    so_owners = defaultdict(set)

    for raw in external_nd_docs:
        doc = summarize_external_nd(raw)
        nd_no = str(doc.get("ndNo") or "")
        if doc.get("cancelledAt") and any(doc.get(field) for field in ("receipts", "returns", "realizations", "soDocuments")):
            nd_issues.append({
                "severity": "ERROR",
                "code": "EXTERNAL_ND_CANCELLED_WITH_ACTIVITY",
                "ndId": doc.get("id", ""),
                "ndNo": nd_no,
                "issue": "ND dibatalkan tetapi masih memiliki aktivitas turunan.",
            })

        for row in doc.get("summaryItems", []):
            ordered = _n(row.get("ordered"))
            good = _n(row.get("good"))
            damaged = _n(row.get("damaged"))
            returned = _n(row.get("returned"))
            realized = _n(row.get("realized"))
            settled = _n(row.get("settled"))
            if good + damaged - ordered > EPS:
                nd_issues.append({
                    "severity": "ERROR", "code": "EXTERNAL_ND_OVER_RECEIVED",
                    "ndId": doc.get("id", ""), "ndNo": nd_no, "productId": row.get("productId", ""),
                    "issue": "Penerimaan ND melebihi kuantum ND.",
                })
            if returned + realized - good > EPS:
                nd_issues.append({
                    "severity": "ERROR", "code": "EXTERNAL_ND_OVER_ALLOCATED",
                    "ndId": doc.get("id", ""), "ndNo": nd_no, "productId": row.get("productId", ""),
                    "issue": "Retur ke asal + realisasi melebihi penerimaan Baik ND.",
                })
            if settled - realized > EPS:
                nd_issues.append({
                    "severity": "ERROR", "code": "EXTERNAL_ND_SO_OVER_REALIZATION",
                    "ndId": doc.get("id", ""), "ndNo": nd_no, "productId": row.get("productId", ""),
                    "issue": "Kuantum SO melebihi realisasi Bazar/Paket.",
                })

        for realization in doc.get("realizations", []):
            activity_type = str(realization.get("activityType") or "")
            reference_no = str(realization.get("referenceNo") or "")
            for item in realization.get("items", []):
                product_id = str(item.get("productId") or "")
                reference_usage[(activity_type, reference_no, product_id)] += _n(item.get("qty"))
                reference_meta[(activity_type, reference_no)] = {
                    "ndNo": nd_no,
                    "ndId": doc.get("id", ""),
                }
        for so in doc.get("soDocuments", []):
            so_no = str(so.get("soNo") or "").strip().upper()
            if so_no:
                so_owners[so_no].add(str(doc.get("id") or ""))

    for so_no, owners in so_owners.items():
        if len(owners) > 1:
            nd_issues.append({
                "severity": "ERROR",
                "code": "EXTERNAL_ND_DUPLICATE_SO",
                "soNo": so_no,
                "ndIds": sorted(owners),
                "issue": "Nomor SO eksternal tertaut ke lebih dari satu ND.",
            })

    for (activity_type, reference_no, product_id), used in reference_usage.items():
        source = None
        capacity = 0.0
        if activity_type == "BAZAR":
            source = await db.bazar_trips.find_one({"tripNo": reference_no}, {"_id": 0})
            if source and source.get("status") == "SELESAI":
                for item in source.get("resultItems", []):
                    if str(item.get("productId") or "") == product_id:
                        capacity += _n(item.get("soldQty"))
        elif activity_type == "PAKET":
            source = await db.bazar_package_loads.find_one({"loadNo": reference_no}, {"_id": 0})
            if source and source.get("status") == "SELESAI":
                for loaded in source.get("resultItems", []):
                    delivered = _n(loaded.get("deliveredQty"))
                    for component in loaded.get("components", []):
                        if str(component.get("productId") or "") == product_id:
                            capacity += delivered * _n(component.get("qty"))

        meta = reference_meta.get((activity_type, reference_no), {})
        if not source or source.get("status") != "SELESAI":
            nd_issues.append({
                "severity": "ERROR",
                "code": "EXTERNAL_ND_REALIZATION_REFERENCE_INVALID",
                "ndId": meta.get("ndId", ""),
                "ndNo": meta.get("ndNo", ""),
                "referenceNo": reference_no,
                "activityType": activity_type,
                "productId": product_id,
                "usedQty": used,
                "issue": "Realisasi ND menunjuk kegiatan yang tidak ditemukan atau belum selesai.",
            })
        elif used - capacity > EPS:
            nd_issues.append({
                "severity": "ERROR",
                "code": "EXTERNAL_ND_REALIZATION_OVER_CAPACITY",
                "ndId": meta.get("ndId", ""),
                "ndNo": meta.get("ndNo", ""),
                "referenceNo": reference_no,
                "activityType": activity_type,
                "productId": product_id,
                "usedQty": used,
                "capacityQty": capacity,
                "overBy": used - capacity,
                "issue": "Akumulasi realisasi ND melebihi kapasitas kegiatan Bazar/Paket.",
            })

    all_issues = reservation_issues + package_issues + ecom_order_issues + damaged_issues + opname_issues + nd_issues
    consignment_errors = sum(1 for row in consignment_rows if row.get("severity") == "ERROR")
    errors, warnings = _severity(all_issues)
    errors += consignment_errors

    return {
        "consignmentStockIntegrity": consignment_rows,
        "consignmentReservationIssues": reservation_issues,
        "packageIntegrityIssues": package_issues,
        "ecomOrderIntegrityIssues": ecom_order_issues,
        "consignmentDamagedIntegrityIssues": damaged_issues,
        "consignmentOpnamePending": opname_issues,
        "externalNDIntegrityIssues": nd_issues,
        "summary": {
            "consignmentRows": len(consignment_rows),
            "consignmentLayoutMismatches": consignment_errors,
            "consignmentReservationIssues": len(reservation_issues),
            "packageIntegrityIssues": len(package_issues),
            "ecomOrderIntegrityIssues": len(ecom_order_issues),
            "consignmentDamagedIntegrityIssues": len(damaged_issues),
            "consignmentOpnamePending": len(opname_issues),
            "externalNDIntegrityIssues": len(nd_issues),
            "consignmentIntegrityErrors": errors,
            "consignmentIntegrityWarnings": warnings,
        },
    }
