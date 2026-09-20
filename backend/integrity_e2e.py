from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from backend.server import db

EPS = 1e-9
ACTIVE_STATUSES = {"Menunggu", "Sedang Dimuat"}
TERMINAL_STATUSES = {"Selesai", "Dibatalkan"}


def _n(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _stack(value) -> str:
    return str(value or "").strip().upper()


def _stage(status: str, message: str, **extra) -> dict:
    return {"status": status, "message": message, **extra}


def _sum_items(load: dict) -> float:
    return sum(_n(item.get("qty")) for item in load.get("items") or [])


def _parse_time(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _group_items(rows: list[dict], *, qty_field: str = "qty") -> dict[tuple[str, str], float]:
    grouped: dict[tuple[str, str], float] = defaultdict(float)
    for row in rows or []:
        product_id = str(row.get("productId") or row.get("product_id") or "")
        stack_code = _stack(row.get("stackCode"))
        if product_id:
            grouped[(product_id, stack_code)] += abs(_n(row.get(qty_field)))
    return dict(grouped)


async def analyze_main_warehouse_e2e(handling_cost_issues: list[dict] | None = None) -> dict:
    """Audit one complete operational chain for every main-warehouse outbound load.

    This is diagnostic only. It never mutates stock, documents, lots, reservations,
    or costs. The result points operators to the first broken stage while the
    existing correction/opname/repair endpoints remain the only mutation paths.
    """
    handling_cost_issues = handling_cost_issues or []

    loads = await db.outbound_loads.find({}, {"_id": 0}).sort("created_at", 1).to_list(30000)
    transactions = await db.transactions.find(
        {"type": "KELUAR"},
        {"_id": 0, "id": 1, "load_id": 1, "product_id": 1, "stackCode": 1, "change": 1, "bon_no": 1, "antrian": 1},
    ).to_list(100000)
    surat_jalan = await db.surat_jalan.find(
        {},
        {"_id": 0, "id": 1, "load_id": 1, "no": 1, "bon_no": 1, "antrian": 1},
    ).to_list(30000)
    allocations = await db.stack_allocations.find(
        {},
        {"_id": 0, "productId": 1, "stackCode": 1, "primaryQty": 1},
    ).to_list(50000)
    lot_movements = await db.stack_lot_movements.find(
        {"movementType": {"$in": ["OUTBOUND_FEFO", "OUTBOUND_UNTRACKED"]}},
        {"_id": 0, "loadId": 1, "movementType": 1, "productId": 1, "stackCode": 1, "qty": 1},
    ).to_list(100000)
    postcommit = await db.operational_postcommit_issues.find(
        {"operation": "OUTBOUND_COMPLETE", "status": "OPEN"},
        {"_id": 0, "loadId": 1, "stage": 1, "message": 1},
    ).to_list(10000)

    tx_by_load: dict[str, list[dict]] = defaultdict(list)
    for row in transactions:
        tx_by_load[str(row.get("load_id") or "")].append(row)

    sj_by_load: dict[str, list[dict]] = defaultdict(list)
    for row in surat_jalan:
        sj_by_load[str(row.get("load_id") or "")].append(row)

    lot_by_load: dict[str, list[dict]] = defaultdict(list)
    for row in lot_movements:
        lot_by_load[str(row.get("loadId") or "")].append(row)

    postcommit_by_load: dict[str, list[dict]] = defaultdict(list)
    for row in postcommit:
        postcommit_by_load[str(row.get("loadId") or "")].append(row)

    cost_by_load: dict[str, list[dict]] = defaultdict(list)
    for row in handling_cost_issues:
        load_id = str(row.get("loadId") or "")
        if load_id:
            cost_by_load[load_id].append(row)

    physical_by_stack: dict[tuple[str, str], float] = defaultdict(float)
    for row in allocations:
        key = (str(row.get("productId") or ""), _stack(row.get("stackCode")))
        if key[0] and key[1]:
            physical_by_stack[key] += _n(row.get("primaryQty"))

    reserved_by_stack: dict[tuple[str, str], float] = defaultdict(float)
    for load in loads:
        if str(load.get("status") or "") not in ACTIVE_STATUSES:
            continue
        if str(load.get("kondisi") or "BAIK").upper() != "BAIK":
            continue
        for item in load.get("items") or []:
            key = (str(item.get("productId") or ""), _stack(item.get("stackCode")))
            if key[0] and key[1]:
                reserved_by_stack[key] += _n(item.get("qty"))

    rows: list[dict] = []
    stage_error_counts: dict[str, int] = defaultdict(int)
    stage_warning_counts: dict[str, int] = defaultdict(int)

    stage_order = [
        "document", "queue", "reservation", "stack", "fefo",
        "transaction", "suratJalan", "cost", "postCommit",
    ]

    for load in loads:
        load_id = str(load.get("id") or "")
        status = str(load.get("status") or "")
        kondisi = str(load.get("kondisi") or "BAIK").upper()
        items = list(load.get("items") or [])
        documents = [str(value or "").strip() for value in (load.get("documents") or [load.get("ref", "")]) if str(value or "").strip()]
        stages: dict[str, dict] = {}

        # 1. Dokumen sumber.
        document_errors = []
        if not documents:
            document_errors.append("dokumen sumber kosong")
        doc_set = {value.upper() for value in documents}
        if not items:
            document_errors.append("barang pemuatan kosong")
        for item in items:
            item_doc = str(item.get("documentNo") or load.get("ref") or "").strip()
            if not item_doc or item_doc.upper() not in doc_set:
                document_errors.append(f"dokumen item {item_doc or '-'} tidak terdaftar")
            if not str(item.get("productId") or ""):
                document_errors.append("productId item kosong")
            if _n(item.get("qty")) <= EPS:
                document_errors.append("kuantitas item tidak positif")
        stages["document"] = _stage(
            "ERROR" if document_errors else "OK",
            "; ".join(dict.fromkeys(document_errors)) if document_errors else f"{len(documents)} dokumen sumber valid",
        )

        # 2. Antrean / lifecycle timestamp.
        queue_errors = []
        queue_warnings = []
        if status != "Dibatalkan":
            if not str(load.get("bon_no") or "").strip():
                queue_errors.append("nomor Bon Muat kosong")
            if not str(load.get("antrian") or "").strip():
                queue_errors.append("nomor antrean kosong")
            if not str(load.get("operational_date") or "").strip():
                queue_errors.append("tanggal operasional kosong")
        started = _parse_time(load.get("started_at"))
        completed = _parse_time(load.get("completed_at"))
        if status == "Menunggu":
            if started or completed:
                queue_errors.append("status Menunggu tetapi waktu mulai/selesai sudah terisi")
        elif status == "Sedang Dimuat":
            if not started:
                queue_errors.append("Sedang Dimuat tanpa waktu mulai")
            if completed:
                queue_errors.append("Sedang Dimuat tetapi waktu selesai sudah terisi")
        elif status == "Selesai":
            if not started:
                queue_errors.append("Selesai tanpa waktu mulai")
            if not completed:
                queue_errors.append("Selesai tanpa waktu selesai")
            if started and completed and completed < started:
                queue_errors.append("waktu selesai lebih awal daripada waktu mulai")
        elif status not in {"Dibatalkan"}:
            queue_warnings.append(f"status lifecycle tidak dikenal: {status or '-'}")
        queue_status = "ERROR" if queue_errors else ("WARNING" if queue_warnings else "OK")
        stages["queue"] = _stage(
            queue_status,
            "; ".join(queue_errors or queue_warnings) if (queue_errors or queue_warnings) else f"lifecycle {status} konsisten",
        )

        # 3-4. Reservasi dan keterlacakan tumpukan.
        stack_errors = []
        reservation_errors = []
        reservation_warnings = []
        for item in items:
            product_id = str(item.get("productId") or "")
            stack_code = _stack(item.get("stackCode"))
            qty = _n(item.get("qty"))
            if kondisi == "BAIK" and not stack_code:
                stack_errors.append(f"{item.get('sku') or item.get('name') or product_id}: tumpukan sumber kosong")
                continue
            if kondisi != "BAIK" or not product_id or not stack_code:
                continue
            key = (product_id, stack_code)
            if status in ACTIVE_STATUSES:
                physical = _n(physical_by_stack.get(key, 0))
                reserved = _n(reserved_by_stack.get(key, 0))
                if key not in physical_by_stack:
                    reservation_errors.append(f"{stack_code}: alokasi fisik tidak ditemukan")
                elif reserved - physical > EPS:
                    reservation_errors.append(f"{stack_code}: reservasi {reserved:g} melebihi fisik {physical:g}")
                elif qty - physical > EPS:
                    reservation_errors.append(f"{stack_code}: kebutuhan item {qty:g} melebihi fisik {physical:g}")

        if status in ACTIVE_STATUSES:
            stages["reservation"] = _stage(
                "ERROR" if reservation_errors else ("WARNING" if reservation_warnings else "OK"),
                "; ".join(reservation_errors or reservation_warnings)
                if (reservation_errors or reservation_warnings)
                else "reservasi aktif masih tertutup stok fisik",
            )
        else:
            stages["reservation"] = _stage("OK", "reservasi sudah dilepas pada status terminal")

        stages["stack"] = _stage(
            "ERROR" if stack_errors else "OK",
            "; ".join(dict.fromkeys(stack_errors)) if stack_errors else "seluruh item memiliki jejak tumpukan sumber",
        )

        # 5. FEFO/lot.
        lot_rows = lot_by_load.get(load_id, [])
        if kondisi != "BAIK":
            stages["fefo"] = _stage("OK", "tidak berlaku untuk stok rusak")
        elif status == "Selesai":
            expected_qty = _sum_items(load)
            moved_qty = sum(abs(_n(row.get("qty"))) for row in lot_rows)
            tracked_qty = sum(abs(_n(row.get("qty"))) for row in lot_rows if row.get("movementType") == "OUTBOUND_FEFO")
            untracked_qty = sum(abs(_n(row.get("qty"))) for row in lot_rows if row.get("movementType") == "OUTBOUND_UNTRACKED")
            fefo_errors = []
            if str(load.get("fefo_sync_status") or "") != "SYNCED":
                fefo_errors.append(f"FEFO {load.get('fefo_sync_status') or 'belum sinkron'}")
            if abs(moved_qty - expected_qty) > EPS:
                fefo_errors.append(f"movement lot {moved_qty:g} != kuantitas load {expected_qty:g}")
            if load.get("fefo_tracked_qty") is not None and abs(_n(load.get("fefo_tracked_qty")) - tracked_qty) > EPS:
                fefo_errors.append("tracked FEFO load berbeda dari movement")
            if load.get("fefo_untracked_qty") is not None and abs(_n(load.get("fefo_untracked_qty")) - untracked_qty) > EPS:
                fefo_errors.append("untracked FEFO load berbeda dari movement")
            stages["fefo"] = _stage(
                "ERROR" if fefo_errors else "OK",
                "; ".join(fefo_errors) if fefo_errors else f"SYNCED · tracked {tracked_qty:g} · legacy {untracked_qty:g}",
            )
        else:
            selection_missing = [
                item for item in items
                if kondisi == "BAIK" and not str(item.get("fefoSelectionStatus") or "").strip()
            ]
            stages["fefo"] = _stage(
                "WARNING" if selection_missing else "OK",
                f"{len(selection_missing)} item belum memiliki metadata pilihan FEFO"
                if selection_missing else "metadata pilihan FEFO tersedia; konsumsi lot dilakukan saat selesai",
            )

        # 6. Transaksi stok.
        tx_rows = tx_by_load.get(load_id, [])
        if status in ACTIVE_STATUSES:
            stages["transaction"] = _stage(
                "ERROR" if tx_rows else "OK",
                "stok sudah memiliki transaksi KELUAR sebelum pemuatan selesai"
                if tx_rows else "stok belum dipotong sebelum status Selesai",
            )
        elif status == "Selesai":
            expected = _group_items(items)
            actual_rows = [
                {
                    "product_id": row.get("product_id"),
                    "stackCode": row.get("stackCode"),
                    "change": row.get("change"),
                }
                for row in tx_rows
            ]
            actual = _group_items(actual_rows, qty_field="change")
            tx_errors = []
            if expected != actual:
                keys = set(expected) | set(actual)
                for key in keys:
                    if abs(_n(expected.get(key)) - _n(actual.get(key))) > EPS:
                        tx_errors.append(f"{key[1] or '-'}: load {_n(expected.get(key)):g} vs transaksi {_n(actual.get(key)):g}")
            load_bon = str(load.get("bon_no") or "")
            if any(str(row.get("bon_no") or "") != load_bon for row in tx_rows):
                tx_errors.append("nomor Bon pada transaksi berbeda")
            stages["transaction"] = _stage(
                "ERROR" if tx_errors else "OK",
                "; ".join(tx_errors) if tx_errors else f"{len(tx_rows)} transaksi KELUAR cocok dengan pemuatan",
            )
        else:
            stages["transaction"] = _stage("OK", "status dibatalkan tidak memerlukan transaksi KELUAR")

        # 7. Surat Jalan.
        sj_rows = sj_by_load.get(load_id, [])
        if status in ACTIVE_STATUSES:
            stages["suratJalan"] = _stage(
                "ERROR" if sj_rows else "OK",
                "Surat Jalan sudah terbit sebelum pemuatan selesai"
                if sj_rows else "Surat Jalan belum terbit sebelum selesai",
            )
        elif status == "Selesai":
            sj_errors = []
            if len(sj_rows) != 1:
                sj_errors.append(f"jumlah Surat Jalan {len(sj_rows)}, seharusnya 1")
            elif str(load.get("surat_jalan_id") or "") != str(sj_rows[0].get("id") or ""):
                sj_errors.append("surat_jalan_id pada load berbeda")
            elif str(load.get("surat_jalan_no") or "") != str(sj_rows[0].get("no") or ""):
                sj_errors.append("surat_jalan_no pada load berbeda")
            stages["suratJalan"] = _stage(
                "ERROR" if sj_errors else "OK",
                "; ".join(sj_errors) if sj_errors else str(sj_rows[0].get("no") or "Surat Jalan valid"),
            )
        else:
            stages["suratJalan"] = _stage("OK", "status dibatalkan tidak memerlukan Surat Jalan")

        # 8. Biaya muat.
        if status == "Selesai":
            cost_issues = cost_by_load.get(load_id, [])
            item_cost = sum(_n((item.get("loadingFee") or {}).get("total")) for item in items)
            load_cost = _n((load.get("loading_cost") or {}).get("total"))
            cost_errors = []
            if abs(item_cost - load_cost) > 1e-6:
                cost_errors.append(f"total item {item_cost:g} != rekap load {load_cost:g}")
            cost_errors.extend(str(row.get("issue") or row.get("code") or "") for row in cost_issues if row.get("severity") == "ERROR")
            cost_warnings = [str(row.get("issue") or row.get("code") or "") for row in cost_issues if row.get("severity") == "WARNING"]
            cost_status = "ERROR" if cost_errors else ("WARNING" if cost_warnings else "OK")
            stages["cost"] = _stage(
                cost_status,
                "; ".join(dict.fromkeys(cost_errors or cost_warnings))
                if (cost_errors or cost_warnings)
                else (f"rekap biaya {load_cost:g} konsisten" if load_cost > EPS else "pemuatan tanpa biaya aktif"),
            )
        else:
            stages["cost"] = _stage("OK", "biaya final dihitung saat pemuatan selesai")

        # 9. Post-commit enrichment.
        open_rows = postcommit_by_load.get(load_id, [])
        if status == "Selesai":
            stages["postCommit"] = _stage(
                "ERROR" if open_rows else "OK",
                "; ".join(f"{row.get('stage')}: {row.get('message')}" for row in open_rows)
                if open_rows else "metadata/SJ/FEFO post-commit bersih",
            )
        else:
            stages["postCommit"] = _stage("OK", "belum memerlukan enrichment final")

        overall = "OK"
        for stage_name in stage_order:
            stage_status = stages[stage_name]["status"]
            if stage_status == "ERROR":
                stage_error_counts[stage_name] += 1
                overall = "ERROR"
            elif stage_status == "WARNING":
                stage_warning_counts[stage_name] += 1
                if overall == "OK":
                    overall = "WARNING"

        broken_at = next(
            (stage_name for stage_name in stage_order if stages[stage_name]["status"] == "ERROR"),
            "",
        )
        warning_at = next(
            (stage_name for stage_name in stage_order if stages[stage_name]["status"] == "WARNING"),
            "",
        )
        rows.append({
            "loadId": load_id,
            "status": status,
            "severity": overall,
            "brokenAt": broken_at,
            "warningAt": warning_at,
            "bonNo": load.get("bon_no", ""),
            "queue": load.get("antrian", ""),
            "referenceNo": load.get("ref", ""),
            "documents": documents,
            "documentType": load.get("document_type", ""),
            "operationalDate": load.get("operational_date", ""),
            "party": load.get("party", ""),
            "itemCount": len(items),
            "qty": _sum_items(load),
            "stages": stages,
        })

    errors = sum(1 for row in rows if row["severity"] == "ERROR")
    warnings = sum(1 for row in rows if row["severity"] == "WARNING")
    healthy = sum(1 for row in rows if row["severity"] == "OK")

    return {
        "mainWarehouseE2E": rows,
        "summary": {
            "mainWarehouseE2ETotal": len(rows),
            "mainWarehouseE2EHealthy": healthy,
            "mainWarehouseE2EWarnings": warnings,
            "mainWarehouseE2EErrors": errors,
            "mainWarehouseE2EActive": sum(1 for row in rows if row.get("status") in ACTIVE_STATUSES),
            "mainWarehouseE2ECompleted": sum(1 for row in rows if row.get("status") == "Selesai"),
            "mainWarehouseE2ECancelled": sum(1 for row in rows if row.get("status") == "Dibatalkan"),
            "mainWarehouseE2EStageErrors": dict(stage_error_counts),
            "mainWarehouseE2EStageWarnings": dict(stage_warning_counts),
        },
    }
