from __future__ import annotations

from collections import defaultdict
from datetime import date

from fastapi import APIRouter, Depends

from backend.server import db, operational_now, require_cost_view

router = APIRouter(prefix="/api")
EPS = 1e-9
ACTIVE_LOAD_STATUSES = {"Menunggu", "Sedang Dimuat"}
COUNTED_LOAD_STATUSES = {"Menunggu", "Sedang Dimuat", "Selesai"}


def _n(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _doc_key(value: str) -> str:
    return str(value or "").strip().upper()


def _load_so_refs(load: dict) -> set[str]:
    refs: set[str] = set()
    if str(load.get("document_type") or "").upper() != "SO":
        return refs

    for value in [load.get("ref"), *(load.get("documents") or [])]:
        key = _doc_key(value)
        if key:
            refs.add(key)
    fallback = _doc_key(load.get("ref"))
    for item in load.get("items", []):
        key = _doc_key(item.get("documentNo") or fallback)
        if key:
            refs.add(key)
    for event in load.get("cancellation_history", []):
        for value in event.get("documents", []):
            key = _doc_key(value)
            if key:
                refs.add(key)
        for item in event.get("items", []):
            key = _doc_key(item.get("documentNo") or fallback)
            if key:
                refs.add(key)
    return refs


def _current_items_for_so(load: dict, so_no: str) -> list[dict]:
    target = _doc_key(so_no)
    fallback = _doc_key(load.get("ref"))
    return [
        item for item in load.get("items", [])
        if _doc_key(item.get("documentNo") or fallback) == target
    ]


def _cancelled_items_for_so(load: dict, so_no: str) -> list[dict]:
    target = _doc_key(so_no)
    fallback = _doc_key(load.get("ref"))
    rows: list[dict] = []
    for event in load.get("cancellation_history", []):
        event_docs = {_doc_key(value) for value in event.get("documents", [])}
        for item in event.get("items", []):
            item_doc = _doc_key(item.get("documentNo") or fallback)
            if item_doc == target or target in event_docs:
                rows.append({**item, "cancelledAt": event.get("cancelledAt", ""), "cancelledBy": event.get("cancelledBy", ""), "cancelReason": event.get("reason", "")})
    return rows


def _group_items(items: list[dict]) -> list[dict]:
    grouped: dict[str, dict] = {}
    for item in items:
        product_id = str(item.get("productId") or "")
        if not product_id:
            continue
        current = grouped.setdefault(product_id, {
            "productId": product_id,
            "sku": item.get("sku", ""),
            "name": item.get("name", ""),
            "unit": item.get("unit", ""),
            "channel": item.get("channel", ""),
            "qty": 0.0,
        })
        current["qty"] += _n(item.get("qty"))
    return list(grouped.values())


def _latest_value(values: list[str]) -> str:
    present = [str(value or "") for value in values if str(value or "")]
    return max(present) if present else ""


async def build_so_monitoring() -> dict:
    masters = await db.outbound_documents.find(
        {"documentType": "SO"},
        {"_id": 0},
    ).to_list(20000)
    loads = await db.outbound_loads.find(
        {"document_type": "SO"},
        {"_id": 0},
    ).to_list(30000)
    load_ids = [str(load.get("id") or "") for load in loads if str(load.get("id") or "")]
    surat_jalan = await db.surat_jalan.find(
        {"load_id": {"$in": load_ids}},
        {"_id": 0},
    ).to_list(30000) if load_ids else []

    masters_by_no = {_doc_key(row.get("documentNo")): row for row in masters if _doc_key(row.get("documentNo"))}
    sj_by_load: dict[str, list[dict]] = defaultdict(list)
    for sj in surat_jalan:
        sj_by_load[str(sj.get("load_id") or "")].append(sj)

    document_numbers = set(masters_by_no)
    for load in loads:
        document_numbers.update(_load_so_refs(load))

    today_text = operational_now().strftime("%Y-%m-%d")
    records: list[dict] = []

    for so_no in sorted(document_numbers):
        master = masters_by_no.get(so_no)
        related_loads = [load for load in loads if so_no in _load_so_refs(load)]
        usage: dict[str, dict] = defaultdict(lambda: {"completedQty": 0.0, "reservedQty": 0.0, "cancelledQty": 0.0, "identity": {}})
        history_rows: list[dict] = []
        issues: list[dict] = []
        parties = set()

        for load in related_loads:
            load_id = str(load.get("id") or "")
            current_items = _current_items_for_so(load, so_no)
            cancelled_items = _cancelled_items_for_so(load, so_no)
            status = str(load.get("status") or "")
            if load.get("party"):
                parties.add(str(load.get("party")))

            for item in current_items:
                product_id = str(item.get("productId") or "")
                if not product_id:
                    continue
                usage[product_id]["identity"] = {
                    "productId": product_id,
                    "sku": item.get("sku", ""),
                    "name": item.get("name", ""),
                    "unit": item.get("unit", ""),
                    "channel": item.get("channel", ""),
                }
                qty = _n(item.get("qty"))
                if status == "Selesai":
                    usage[product_id]["completedQty"] += qty
                elif status in ACTIVE_LOAD_STATUSES:
                    usage[product_id]["reservedQty"] += qty

            for item in cancelled_items:
                product_id = str(item.get("productId") or "")
                if not product_id:
                    continue
                if not usage[product_id]["identity"]:
                    usage[product_id]["identity"] = {
                        "productId": product_id,
                        "sku": item.get("sku", ""),
                        "name": item.get("name", ""),
                        "unit": item.get("unit", ""),
                        "channel": item.get("channel", ""),
                    }
                usage[product_id]["cancelledQty"] += _n(item.get("qty"))

            sj_rows = sj_by_load.get(load_id, [])
            item_rows = current_items if current_items else cancelled_items
            doc_status = status if current_items else ("Dibatalkan" if cancelled_items else status)
            history_rows.append({
                "loadId": load_id,
                "status": doc_status,
                "loadStatus": status,
                "bonNo": load.get("bon_no", ""),
                "queue": load.get("antrian", ""),
                "operationalDate": load.get("operational_date", ""),
                "createdAt": load.get("created_at", ""),
                "startedAt": load.get("started_at", ""),
                "completedAt": load.get("completed_at", ""),
                "party": load.get("party", ""),
                "vehicleNo": load.get("polisi", ""),
                "driver": load.get("pengambil", ""),
                "suratJalan": [{"id": sj.get("id", ""), "no": sj.get("no", ""), "time": sj.get("time", "")} for sj in sj_rows],
                "items": _group_items(item_rows),
                "cancelled": bool(cancelled_items and not current_items),
            })

            if status == "Selesai" and current_items and not sj_rows:
                issues.append({
                    "severity": "ERROR",
                    "code": "SO_COMPLETED_LOAD_MISSING_SJ",
                    "loadId": load_id,
                    "bonNo": load.get("bon_no", ""),
                    "issue": "Pemuatan SO selesai tetapi Surat Jalan tidak ditemukan.",
                })
            if len(sj_rows) > 1 and current_items:
                issues.append({
                    "severity": "ERROR",
                    "code": "SO_LOAD_MULTIPLE_SJ",
                    "loadId": load_id,
                    "bonNo": load.get("bon_no", ""),
                    "suratJalan": [row.get("no", "") for row in sj_rows],
                    "issue": "Satu pemuatan SO memiliki lebih dari satu Surat Jalan.",
                })
            if status in ACTIVE_LOAD_STATUSES and current_items:
                op_date = str(load.get("operational_date") or "")
                if op_date and op_date < today_text:
                    issues.append({
                        "severity": "WARNING",
                        "code": "SO_STALE_ACTIVE_LOAD",
                        "loadId": load_id,
                        "bonNo": load.get("bon_no", ""),
                        "queue": load.get("antrian", ""),
                        "operationalDate": op_date,
                        "issue": "Antrean SO masih aktif melewati tanggal operasional pembuatannya.",
                    })

        master_items = {
            str(item.get("productId") or ""): item
            for item in (master or {}).get("items", [])
            if str(item.get("productId") or "")
        }
        item_rows: list[dict] = []
        all_product_ids = sorted(set(master_items) | set(usage))
        for product_id in all_product_ids:
            source = master_items.get(product_id) or usage[product_id]["identity"]
            used = usage.get(product_id, {})
            ordered = _n((master_items.get(product_id) or {}).get("orderedQty"))
            completed = _n(used.get("completedQty"))
            reserved = _n(used.get("reservedQty"))
            cancelled = _n(used.get("cancelledQty"))
            committed = completed + reserved
            if master:
                available = max(ordered - committed, 0.0)
                outstanding = max(ordered - completed, 0.0)
                if committed - ordered > EPS:
                    issues.append({
                        "severity": "ERROR",
                        "code": "SO_OVER_ALLOCATED",
                        "productId": product_id,
                        "name": source.get("name", ""),
                        "orderedQty": ordered,
                        "completedQty": completed,
                        "reservedQty": reserved,
                        "overBy": committed - ordered,
                        "issue": "Pemuatan selesai + reservasi aktif melebihi kuantum induk SO.",
                    })
                if product_id not in master_items and committed > EPS:
                    issues.append({
                        "severity": "ERROR",
                        "code": "SO_PRODUCT_NOT_IN_MASTER",
                        "productId": product_id,
                        "name": source.get("name", ""),
                        "issue": "Ada pengambilan produk yang tidak tercantum pada master SO.",
                    })
            else:
                available = None
                outstanding = None
            item_rows.append({
                "productId": product_id,
                "sku": source.get("sku", ""),
                "name": source.get("name", ""),
                "unit": source.get("unit", ""),
                "channel": source.get("channel", ""),
                "orderedQty": ordered if master else None,
                "completedQty": completed,
                "reservedQty": reserved,
                "committedQty": committed,
                "remainingQty": available,
                "outstandingQty": outstanding,
                "cancelledQty": cancelled,
            })

        master_party = str((master or {}).get("party") or "").strip()
        if master_party and any(party != master_party for party in parties):
            issues.append({
                "severity": "WARNING",
                "code": "SO_PARTY_MISMATCH",
                "masterParty": master_party,
                "loadParties": sorted(parties),
                "issue": "Nama penerima pada pemuatan tidak konsisten dengan master SO.",
            })

        if not master:
            active_exists = any(str(load.get("status") or "") in ACTIVE_LOAD_STATUSES and _current_items_for_so(load, so_no) for load in related_loads)
            status = "PERLU_KUANTUM_SO" if active_exists else "ARSIP_LEGACY"
            if active_exists:
                issues.append({
                    "severity": "WARNING",
                    "code": "SO_MASTER_MISSING",
                    "issue": "SO aktif belum memiliki master kuantum. Isi Kuantum SO total sebelum menambah pengambilan berikutnya.",
                })
        else:
            has_over = any(issue.get("code") in {"SO_OVER_ALLOCATED", "SO_PRODUCT_NOT_IN_MASTER"} for issue in issues)
            completed_any = any(_n(row.get("completedQty")) > EPS for row in item_rows)
            reserved_any = any(_n(row.get("reservedQty")) > EPS for row in item_rows)
            all_complete = bool(item_rows) and all(
                _n(row.get("completedQty")) + EPS >= _n(row.get("orderedQty"))
                for row in item_rows
            )
            if has_over:
                status = "BERMASALAH"
            elif all_complete:
                status = "SELESAI"
            elif completed_any:
                status = "SEBAGIAN"
            elif reserved_any:
                status = "DALAM_ANTREAN"
            else:
                status = "BELUM_DIAMBIL"

        history_rows.sort(key=lambda row: row.get("completedAt") or row.get("createdAt") or "", reverse=True)
        last_activity = _latest_value([
            *((row.get("completedAt") or row.get("createdAt") or "") for row in history_rows),
            str((master or {}).get("updatedAt") or ""),
            str((master or {}).get("createdAt") or ""),
        ])

        records.append({
            "documentNo": so_no,
            "masterId": (master or {}).get("id", ""),
            "hasMaster": bool(master),
            "party": master_party or (sorted(parties)[0] if parties else ""),
            "status": status,
            "items": item_rows,
            "loads": history_rows,
            "issues": issues,
            "lastActivity": last_activity,
            "createdAt": (master or {}).get("createdAt", ""),
            "updatedAt": (master or {}).get("updatedAt", ""),
            "loadCount": len(history_rows),
            "completedLoadCount": sum(1 for row in history_rows if row.get("status") == "Selesai"),
            "activeLoadCount": sum(1 for row in history_rows if row.get("status") in ACTIVE_LOAD_STATUSES),
            "cancelledLoadCount": sum(1 for row in history_rows if row.get("status") == "Dibatalkan"),
        })

    records.sort(key=lambda row: row.get("lastActivity") or row.get("documentNo") or "", reverse=True)

    summary = {
        "total": len(records),
        "completed": sum(1 for row in records if row.get("status") == "SELESAI"),
        "partial": sum(1 for row in records if row.get("status") == "SEBAGIAN"),
        "queued": sum(1 for row in records if row.get("status") == "DALAM_ANTREAN"),
        "notStarted": sum(1 for row in records if row.get("status") == "BELUM_DIAMBIL"),
        "problem": sum(1 for row in records if row.get("status") == "BERMASALAH"),
        "legacy": sum(1 for row in records if row.get("status") == "ARSIP_LEGACY"),
        "needsMaster": sum(1 for row in records if row.get("status") == "PERLU_KUANTUM_SO"),
        "outstanding": sum(1 for row in records if row.get("status") in {"BELUM_DIAMBIL", "DALAM_ANTREAN", "SEBAGIAN", "BERMASALAH", "PERLU_KUANTUM_SO"}),
        "errors": sum(1 for row in records for issue in row.get("issues", []) if issue.get("severity") == "ERROR"),
        "warnings": sum(1 for row in records for issue in row.get("issues", []) if issue.get("severity") == "WARNING"),
    }
    return {
        "generatedAt": operational_now().isoformat(),
        "summary": summary,
        "records": records,
    }


def fulfillment_integrity_issues(monitoring: dict) -> list[dict]:
    rows: list[dict] = []
    for record in monitoring.get("records", []):
        for issue in record.get("issues", []):
            rows.append({
                **issue,
                "documentNo": record.get("documentNo", ""),
                "soStatus": record.get("status", ""),
            })
    return rows


@router.get("/so-monitoring")
async def so_monitoring(user: dict = Depends(require_cost_view)):
    return await build_so_monitoring()
