from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from backend.server import db
from backend.work_time_costs import normalize_unloading_group

EPS = 1e-6


def _n(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _loading_group(value: str) -> str:
    text = str(value or "").strip().upper()
    if not text:
        return ""
    if "RTR" in text:
        return "GRUP 3 - RTR"
    if "GRUP 2" in text or "MP1" in text or "21-24" in text:
        return "GRUP 2 - MP1/21-24"
    if "GRUP 1" in text or "17-20" in text:
        return "GRUP 1 - GBB 17-20"
    return ""


def _sum_components(cost: dict) -> float:
    return _n(cost.get("labor")) + _n(cost.get("daily")) + _n(cost.get("warehouse"))


def _expected_payment_status(chargeable: float, collected: float) -> str:
    if chargeable <= EPS:
        return "TIDAK_DITAGIH"
    if collected + EPS >= chargeable:
        return "LUNAS"
    if collected > EPS:
        return "SEBAGIAN"
    return "BELUM_DIBAYAR"


def _valid_time_order(started: str, completed: str) -> bool:
    if not started or not completed:
        return True
    try:
        return datetime.fromisoformat(str(started).replace("Z", "+00:00")) <= datetime.fromisoformat(str(completed).replace("Z", "+00:00"))
    except ValueError:
        return False


async def analyze_handling_cost_integrity() -> dict:
    issues: list[dict] = []

    loads = await db.outbound_loads.find(
        {"status": "Selesai"},
        {"_id": 0},
    ).to_list(30000)

    loading_accrual: dict[tuple[str, str, str], float] = defaultdict(float)

    for load in loads:
        load_id = str(load.get("id") or "")
        cost = dict(load.get("loading_cost") or {})
        item_fees = [dict(item.get("loadingFee") or {}) for item in load.get("items", [])]

        has_cost = _n(cost.get("total")) > EPS or any(_n(fee.get("total")) > EPS for fee in item_fees)
        if not has_cost:
            continue

        component_sum = _sum_components(cost)
        if abs(component_sum - _n(cost.get("total"))) > EPS:
            issues.append({
                "severity": "ERROR",
                "code": "LOADING_COST_COMPONENT_MISMATCH",
                "loadId": load_id,
                "referenceNo": load.get("ref", ""),
                "bonNo": load.get("bon_no", ""),
                "componentTotal": component_sum,
                "recordedTotal": _n(cost.get("total")),
                "difference": _n(cost.get("total")) - component_sum,
                "issue": "Total biaya muat tidak sama dengan Buruh + Harian + Gudang.",
            })

        for key in ("labor", "daily", "warehouse", "total", "chargeable"):
            item_total = sum(_n(fee.get(key)) for fee in item_fees)
            if abs(item_total - _n(cost.get(key))) > EPS:
                issues.append({
                    "severity": "ERROR",
                    "code": "LOADING_ITEM_COST_MISMATCH",
                    "loadId": load_id,
                    "referenceNo": load.get("ref", ""),
                    "bonNo": load.get("bon_no", ""),
                    "component": key,
                    "itemTotal": item_total,
                    "loadTotal": _n(cost.get(key)),
                    "difference": _n(cost.get(key)) - item_total,
                    "issue": f"Rekap biaya muat {key} tidak sama dengan penjumlahan biaya per komoditi.",
                })

        if not _valid_time_order(load.get("started_at", ""), load.get("completed_at", "")):
            issues.append({
                "severity": "ERROR",
                "code": "LOADING_WORK_TIME_INVALID",
                "loadId": load_id,
                "referenceNo": load.get("ref", ""),
                "startedAt": load.get("started_at", ""),
                "completedAt": load.get("completed_at", ""),
                "issue": "Waktu selesai muat lebih awal daripada waktu mulai muat atau format waktunya tidak valid.",
            })

        for index, item in enumerate(load.get("items", [])):
            work = dict(item.get("loadingWork") or {})
            fee = dict(item.get("loadingFee") or {})
            qty = _n(item.get("qty"))
            if work:
                split_qty = _n(work.get("regularQty")) + _n(work.get("overtimeQty"))
                if abs(split_qty - qty) > EPS:
                    issues.append({
                        "severity": "ERROR",
                        "code": "LOADING_WORK_SPLIT_MISMATCH",
                        "loadId": load_id,
                        "referenceNo": load.get("ref", ""),
                        "productId": item.get("productId", ""),
                        "name": item.get("name", ""),
                        "qty": qty,
                        "splitQty": split_qty,
                        "difference": split_qty - qty,
                        "issue": "Kuantum normal + lembur pemuatan tidak sama dengan kuantum barang.",
                    })
                if abs(_n(fee.get("regularQty")) - _n(work.get("regularQty"))) > EPS or abs(_n(fee.get("overtimeQty")) - _n(work.get("overtimeQty"))) > EPS:
                    issues.append({
                        "severity": "ERROR",
                        "code": "LOADING_FEE_WORK_SPLIT_MISMATCH",
                        "loadId": load_id,
                        "referenceNo": load.get("ref", ""),
                        "productId": item.get("productId", ""),
                        "name": item.get("name", ""),
                        "issue": "Kuantum dasar perhitungan biaya muat berbeda dari catatan waktu kerja.",
                    })

            breakdown = fee.get("breakdown") or {}
            if breakdown:
                for component in ("labor", "daily", "warehouse"):
                    row = breakdown.get(component) or {}
                    if abs(_n(row.get("total")) - (_n(row.get("base")) + _n(row.get("overtime")) + _n(row.get("holiday")) + _n(row.get("holidayOvertime")))) > EPS:
                        issues.append({
                            "severity": "ERROR",
                            "code": "LOADING_FEE_BREAKDOWN_MISMATCH",
                            "loadId": load_id,
                            "referenceNo": load.get("ref", ""),
                            "productId": item.get("productId", ""),
                            "name": item.get("name", ""),
                            "component": component,
                            "issue": "Breakdown dasar/lembur/libur biaya muat tidak menjumlah ke total komponennya.",
                        })

            group = _loading_group(item.get("crewGroup") or item.get("stackCode") or item.get("location") or load.get("unit_loading"))
            if _n(fee.get("total")) > EPS and not group:
                issues.append({
                    "severity": "ERROR",
                    "code": "LOADING_COST_GROUP_MISSING",
                    "loadId": load_id,
                    "referenceNo": load.get("ref", ""),
                    "productId": item.get("productId", ""),
                    "name": item.get("name", ""),
                    "issue": "Biaya muat tercatat tetapi grup mandor pemuatan tidak dapat ditentukan.",
                })
            if group:
                op_date = str(load.get("operational_date") or str(load.get("completed_at") or "")[:10])
                loading_accrual[(op_date, "BURUH", group)] += _n(fee.get("labor"))
                loading_accrual[(op_date, "HARIAN", group)] += _n(fee.get("daily"))

        payments = load.get("loading_fee_payments") or []
        payment_sum = sum(_n(row.get("amount")) for row in payments)
        recorded_collected = _n(load.get("loading_fee_payment_total"))
        chargeable = _n(cost.get("chargeable"))
        if abs(payment_sum - recorded_collected) > EPS:
            issues.append({
                "severity": "ERROR",
                "code": "LOADING_PAYMENT_TOTAL_MISMATCH",
                "loadId": load_id,
                "referenceNo": load.get("ref", ""),
                "paymentRowsTotal": payment_sum,
                "recordedCollected": recorded_collected,
                "difference": recorded_collected - payment_sum,
                "issue": "Total pembayaran biaya muat tidak sama dengan akumulasi riwayat pembayaran.",
            })
        if recorded_collected - chargeable > EPS:
            issues.append({
                "severity": "ERROR",
                "code": "LOADING_PAYMENT_OVERPAID",
                "loadId": load_id,
                "referenceNo": load.get("ref", ""),
                "chargeable": chargeable,
                "collected": recorded_collected,
                "overBy": recorded_collected - chargeable,
                "issue": "Pembayaran biaya muat melebihi tagihan kepada pengambil.",
            })
        expected_status = _expected_payment_status(chargeable, recorded_collected)
        actual_status = str(load.get("loading_fee_payment_status") or expected_status)
        if actual_status != expected_status:
            issues.append({
                "severity": "ERROR",
                "code": "LOADING_PAYMENT_STATUS_MISMATCH",
                "loadId": load_id,
                "referenceNo": load.get("ref", ""),
                "paymentStatus": actual_status,
                "expectedStatus": expected_status,
                "issue": "Status pembayaran biaya muat tidak sesuai nominal tagihan/pembayaran.",
            })

    txns = await db.transactions.find(
        {"type": "MASUK", "voided": {"$ne": True}},
        {"_id": 0},
    ).to_list(100000)
    cost_bearing_by_operation: dict[tuple[str, str], list[dict]] = defaultdict(list)
    unloading_accrual: dict[tuple[str, str, str], float] = defaultdict(float)

    for txn in txns:
        fee = dict(txn.get("unloading_cost") or {})
        if _n(fee.get("total")) <= EPS:
            continue
        operation_id = str(txn.get("operation_id") or "")
        product_key = str(txn.get("product_id") or txn.get("sku") or txn.get("product") or "")
        cost_bearing_by_operation[(operation_id, product_key)].append(txn)

        component_sum = _sum_components(fee)
        if abs(component_sum - _n(fee.get("total"))) > EPS:
            issues.append({
                "severity": "ERROR",
                "code": "UNLOADING_COST_COMPONENT_MISMATCH",
                "operationId": operation_id,
                "referenceNo": txn.get("ref", ""),
                "productId": txn.get("product_id", ""),
                "name": txn.get("product", ""),
                "componentTotal": component_sum,
                "recordedTotal": _n(fee.get("total")),
                "difference": _n(fee.get("total")) - component_sum,
                "issue": "Total biaya bongkar tidak sama dengan Buruh + Harian + Gudang.",
            })

        basis_qty = _n(txn.get("unloading_cost_basis_qty")) or (_n(fee.get("regularQty")) + _n(fee.get("overtimeQty")))
        if basis_qty > EPS:
            split_qty = _n(fee.get("regularQty")) + _n(fee.get("overtimeQty"))
            if split_qty > EPS and abs(split_qty - basis_qty) > EPS:
                issues.append({
                    "severity": "ERROR",
                    "code": "UNLOADING_WORK_SPLIT_MISMATCH",
                    "operationId": operation_id,
                    "referenceNo": txn.get("ref", ""),
                    "productId": txn.get("product_id", ""),
                    "name": txn.get("product", ""),
                    "basisQty": basis_qty,
                    "splitQty": split_qty,
                    "difference": split_qty - basis_qty,
                    "issue": "Kuantum normal + lembur bongkar tidak sama dengan basis kuantum bongkar.",
                })

        started = fee.get("startedAt") or (txn.get("unloading_work") or {}).get("startedAt")
        completed = fee.get("completedAt") or (txn.get("unloading_work") or {}).get("completedAt")
        if started or completed:
            if not _valid_time_order(started, completed):
                issues.append({
                    "severity": "ERROR",
                    "code": "UNLOADING_WORK_TIME_INVALID",
                    "operationId": operation_id,
                    "referenceNo": txn.get("ref", ""),
                    "startedAt": started or "",
                    "completedAt": completed or "",
                    "issue": "Waktu selesai bongkar lebih awal daripada waktu mulai bongkar atau format waktunya tidak valid.",
                })

        group = normalize_unloading_group(txn.get("unloading_group", ""))
        if not group:
            issues.append({
                "severity": "ERROR",
                "code": "UNLOADING_COST_GROUP_INVALID",
                "operationId": operation_id,
                "referenceNo": txn.get("ref", ""),
                "productId": txn.get("product_id", ""),
                "name": txn.get("product", ""),
                "rawGroup": txn.get("unloading_group", ""),
                "issue": "Biaya bongkar tercatat tetapi tidak masuk Mandor 1 atau Mandor 2.",
            })
        else:
            op_date = str(txn.get("operational_date") or str(txn.get("time") or "")[:10])
            unloading_accrual[(op_date, "BURUH", group)] += _n(fee.get("labor"))
            unloading_accrual[(op_date, "HARIAN", group)] += _n(fee.get("daily"))

        breakdown = fee.get("breakdown") or {}
        if breakdown:
            for component in ("labor", "daily", "warehouse"):
                row = breakdown.get(component) or {}
                if abs(_n(row.get("total")) - (_n(row.get("base")) + _n(row.get("overtime")) + _n(row.get("holiday")) + _n(row.get("holidayOvertime")))) > EPS:
                    issues.append({
                        "severity": "ERROR",
                        "code": "UNLOADING_FEE_BREAKDOWN_MISMATCH",
                        "operationId": operation_id,
                        "referenceNo": txn.get("ref", ""),
                        "productId": txn.get("product_id", ""),
                        "name": txn.get("product", ""),
                        "component": component,
                        "issue": "Breakdown dasar/lembur/libur biaya bongkar tidak menjumlah ke total komponennya.",
                    })

    for (operation_id, product_key), rows in cost_bearing_by_operation.items():
        if operation_id and len(rows) > 1:
            issues.append({
                "severity": "ERROR",
                "code": "UNLOADING_COST_DUPLICATE_PRODUCT",
                "operationId": operation_id,
                "productKey": product_key,
                "transactionIds": [row.get("id", "") for row in rows],
                "issue": "Satu produk pada satu operasi penerimaan memiliki lebih dari satu baris biaya bongkar dan berisiko dihitung ganda.",
            })

    loading_settlements = await db.loading_cost_settlements.find({}, {"_id": 0}).to_list(20000)
    unloading_settlements = await db.unloading_cost_settlements.find({}, {"_id": 0}).to_list(20000)

    for kind, rows, accrual in (
        ("LOADING", loading_settlements, loading_accrual),
        ("UNLOADING", unloading_settlements, unloading_accrual),
    ):
        for row in rows:
            date = str(row.get("date") or "")
            recipient = str(row.get("recipient") or "")
            group = _loading_group(row.get("group", "")) if kind == "LOADING" else normalize_unloading_group(row.get("group", ""))
            paid = _n(row.get("amount"))
            accrued = _n(accrual.get((date, recipient, group)))
            if paid - accrued > EPS:
                issues.append({
                    "severity": "ERROR",
                    "code": f"{kind}_SETTLEMENT_OVER_ACCRUAL",
                    "date": date,
                    "recipient": recipient,
                    "group": group,
                    "settledAmount": paid,
                    "accruedAmount": accrued,
                    "overBy": paid - accrued,
                    "issue": "Nilai yang ditandai sudah dibayar melebihi biaya aktif yang tercatat untuk tanggal/grup tersebut.",
                })

    errors = sum(1 for row in issues if row.get("severity") == "ERROR")
    warnings = sum(1 for row in issues if row.get("severity") == "WARNING")
    return {
        "handlingCostIntegrityIssues": issues,
        "summary": {
            "handlingCostIntegrityIssues": len(issues),
            "handlingCostIntegrityErrors": errors,
            "handlingCostIntegrityWarnings": warnings,
            "loadingCostRecords": sum(1 for load in loads if _n((load.get("loading_cost") or {}).get("total")) > EPS),
            "unloadingCostRecords": sum(1 for txn in txns if _n((txn.get("unloading_cost") or {}).get("total")) > EPS),
        },
    }
