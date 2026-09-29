from __future__ import annotations

import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.server import db, get_operational_location, new_id, now_iso, require_admin
from backend.operational_guards import operation_guard, surat_jalan_with_exact_locations
from backend.outbound_flow import _crew_group, loading_units_from_items
from backend.stack_allocations import record_stack_history, valid_stack_codes
from backend.stack_reservations import available_stack_qty
from backend.fefo_conservative import consume_stack_lots_conservative

router = APIRouter(prefix="/api")


class OutboundMetadataCorrectionInput(BaseModel):
    reason: str = Field(min_length=3, max_length=500)
    party: Optional[str] = Field(default=None, max_length=200)
    polisi: Optional[str] = Field(default=None, max_length=50)
    pengambil: Optional[str] = Field(default=None, max_length=200)
    keterangan: Optional[str] = Field(default=None, max_length=1000)


class OutboundStackCorrectionInput(BaseModel):
    itemIndex: int = Field(ge=0, le=199)
    stackCode: str = Field(min_length=3, max_length=50)
    reason: str = Field(min_length=3, max_length=500)


EPS = 1e-9


def _qty(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


async def _write_stack_qty(product: dict, stack_code: str, qty: float, *, note: str) -> dict | None:
    """Set one product/stack physical balance without changing product.stock."""
    code = str(stack_code or "").strip().upper()
    current = await db.stack_allocations.find_one({"productId": product["id"], "stackCode": code}, {"_id": 0})
    qty = max(float(qty or 0), 0.0)
    if qty <= EPS:
        if current:
            await db.stack_allocations.delete_one({"id": current["id"]})
        return None

    per_secondary = float(product.get("secondaryQty", 0) or 0)
    if per_secondary <= 0:
        raise HTTPException(status_code=400, detail=f"Kemasan sekunder {product.get('name', '')} belum diatur")

    base = dict(current or {})
    row = {
        **base,
        "id": base.get("id") or new_id(),
        "productId": product["id"],
        "sku": product.get("sku", ""),
        "productName": product.get("name", ""),
        "unit": product.get("unit", ""),
        "weight": float(product.get("weight", 0) or 0),
        "measureUnit": product.get("measureUnit", "kg") or "kg",
        "secondary": product.get("secondary", ""),
        "secondaryQty": per_secondary,
        "stackCode": code,
        "warehouse": code.split("/", 1)[0],
        "zone": re.sub(r"\d", "", code.split("/", 1)[1]) if "/" in code else "",
        "length": 0,
        "width": 0,
        "height": 0,
        "secondaryCount": int(qty // per_secondary),
        "primaryRemainder": qty % per_secondary,
        "primaryQty": qty,
        "note": base.get("note") or note,
        "arrangementAdjusted": True,
        "createdAt": base.get("createdAt") or now_iso(),
        "updatedAt": now_iso(),
    }
    await db.stack_allocations.replace_one(
        {"id": row["id"]},
        row,
        upsert=True,
    )
    return row


async def _restore_outbound_lot_usage(load: dict, item: dict, qty: float) -> None:
    """Undo only the selected item's old lot consumption before re-consuming from the corrected stack."""
    load_id = str(load.get("id") or "")
    product_id = str(item.get("productId") or "")
    old_stack = str(item.get("stackCode") or "").strip().upper()
    source_document = str(item.get("documentNo") or load.get("ref") or "")
    movements = await db.stack_lot_movements.find(
        {
            "loadId": load_id,
            "productId": product_id,
            "stackCode": old_stack,
            "sourceDocument": source_document,
            "movementType": {"$in": ["OUTBOUND_FEFO", "OUTBOUND_UNTRACKED"]},
        },
        {"_id": 0},
    ).sort("time", -1).to_list(5000)

    available = sum(abs(_qty(row.get("qty"))) for row in movements)
    if available + EPS < qty:
        raise HTTPException(
            status_code=409,
            detail="Jejak lot pengeluaran tidak cukup untuk memindahkan tumpukan secara aman. Gunakan Kontrol Integritas sebelum koreksi.",
        )

    remaining = qty
    for movement in movements:
        if remaining <= EPS:
            break
        moved = abs(_qty(movement.get("qty")))
        if moved <= EPS:
            continue
        take = min(moved, remaining)
        if movement.get("movementType") == "OUTBOUND_FEFO" and movement.get("lotId"):
            lot = await db.stack_lots.find_one({"id": movement["lotId"]}, {"_id": 0})
            if not lot:
                raise HTTPException(status_code=409, detail="Lot asal pengeluaran tidak ditemukan; koreksi tumpukan dibatalkan.")
            restored = _qty(lot.get("remainingQty")) + take
            original = _qty(lot.get("originalQty"))
            if original > EPS and restored > original + EPS:
                raise HTTPException(status_code=409, detail="Saldo lot asal akan melebihi kuantum awal; koreksi tumpukan dibatalkan.")
            await db.stack_lots.update_one(
                {"id": lot["id"]},
                {"$set": {"remainingQty": restored, "status": "AKTIF", "updatedAt": now_iso()}},
            )

        left = moved - take
        if left <= EPS:
            await db.stack_lot_movements.delete_one({"id": movement["id"]})
        else:
            await db.stack_lot_movements.update_one(
                {"id": movement["id"]},
                {"$set": {"qty": -left, "updatedAt": now_iso()}},
            )
        remaining -= take


async def _restore_allocation_snapshot(product_id: str, stack_code: str, snapshot: dict | None) -> None:
    if snapshot:
        await db.stack_allocations.replace_one({"id": snapshot["id"]}, snapshot, upsert=True)
    else:
        await db.stack_allocations.delete_many({"productId": product_id, "stackCode": stack_code})


@router.get("/operational-corrections/outbound")
async def list_completed_outbound_for_correction(user: dict = Depends(require_admin)):
    loads = await db.outbound_loads.find({"status": "Selesai"}, {"_id": 0}).sort("completed_at", -1).to_list(500)
    return [{
        "id": load.get("id", ""), "bonNo": load.get("bon_no", ""), "antrian": load.get("antrian", ""),
        "documents": load.get("documents") or [load.get("ref", "")], "party": load.get("party", ""),
        "polisi": load.get("polisi", ""), "pengambil": load.get("pengambil", ""), "keterangan": load.get("keterangan", ""),
        "suratJalanNo": load.get("surat_jalan_no", ""), "completedAt": load.get("completed_at", ""),
        "correctionHistory": load.get("correction_history", []),
        "items": [{"name": item.get("name", ""), "sku": item.get("sku", ""), "qty": item.get("qty", 0), "unit": item.get("unit", ""), "stackCode": item.get("stackCode", ""), "documentNo": item.get("documentNo", "")} for item in load.get("items", [])],
    } for load in loads]


@router.put("/operational-corrections/outbound/{load_id}/stack")
async def correct_completed_outbound_stack(load_id: str, body: OutboundStackCorrectionInput, user: dict = Depends(require_admin)):
    """Move a completed outbound item's physical source stack without changing total product stock."""
    load = await db.outbound_loads.find_one({"id": load_id}, {"_id": 0})
    if not load:
        raise HTTPException(status_code=404, detail="Data pengeluaran tidak ditemukan")
    if load.get("status") != "Selesai":
        raise HTTPException(status_code=400, detail="Koreksi tumpukan ini hanya untuk pengeluaran yang sudah Selesai Muat")
    if str(load.get("kondisi") or "BAIK").upper() != "BAIK":
        raise HTTPException(status_code=400, detail="Koreksi tumpukan hanya tersedia untuk stok baik")

    items = [dict(row) for row in (load.get("items") or [])]
    if body.itemIndex >= len(items):
        raise HTTPException(status_code=400, detail="Baris komoditas yang dipilih tidak ditemukan")
    item = items[body.itemIndex]
    product_id = str(item.get("productId") or "")
    qty = _qty(item.get("qty"))
    old_stack = str(item.get("stackCode") or "").strip().upper()
    new_stack = str(body.stackCode or "").strip().upper()
    source_document = str(item.get("documentNo") or load.get("ref") or "")

    if not product_id or qty <= EPS or not old_stack:
        raise HTTPException(status_code=400, detail="Data tumpukan asal pengeluaran tidak lengkap")
    if new_stack == old_stack:
        raise HTTPException(status_code=400, detail="Tumpukan baru sama dengan tumpukan saat ini")
    if new_stack not in await valid_stack_codes():
        raise HTTPException(status_code=400, detail="Tumpukan tujuan koreksi tidak valid")

    async with operation_guard([f"outbound-correction:{load_id}", f"product:{product_id}"]):
        # Reload after acquiring locks so the correction always works from current truth.
        load = await db.outbound_loads.find_one({"id": load_id}, {"_id": 0})
        if not load or load.get("status") != "Selesai":
            raise HTTPException(status_code=409, detail="Data pengeluaran berubah. Muat ulang lalu coba kembali.")
        items = [dict(row) for row in (load.get("items") or [])]
        if body.itemIndex >= len(items):
            raise HTTPException(status_code=409, detail="Baris komoditas berubah. Muat ulang lalu coba kembali.")
        item = items[body.itemIndex]
        if str(item.get("productId") or "") != product_id or str(item.get("stackCode") or "").strip().upper() != old_stack or abs(_qty(item.get("qty")) - qty) > EPS:
            raise HTTPException(status_code=409, detail="Data komoditas berubah. Muat ulang lalu coba kembali.")

        product = await db.products.find_one({"id": product_id}, {"_id": 0})
        if not product:
            raise HTTPException(status_code=404, detail="Produk pengeluaran tidak ditemukan")

        target_allocation = await db.stack_allocations.find_one(
            {"productId": product_id, "stackCode": new_stack},
            {"_id": 0},
        )
        target_physical = _qty((target_allocation or {}).get("primaryQty"))
        reserved, available = await available_stack_qty(product_id, new_stack, target_physical)
        if qty > available + EPS:
            raise HTTPException(
                status_code=400,
                detail=f"Stok {new_stack} tidak cukup untuk koreksi. Fisik {target_physical:g}, direservasi antrean lain {reserved:g}, tersedia {available:g} {product.get('unit', '')}.",
            )

        source_allocation = await db.stack_allocations.find_one(
            {"productId": product_id, "stackCode": old_stack},
            {"_id": 0},
        )
        # Validate lot trace before mutating physical balances.
        old_movements = await db.stack_lot_movements.find(
            {
                "loadId": load_id,
                "productId": product_id,
                "stackCode": old_stack,
                "sourceDocument": source_document,
                "movementType": {"$in": ["OUTBOUND_FEFO", "OUTBOUND_UNTRACKED"]},
            },
            {"_id": 0},
        ).to_list(5000)
        if sum(abs(_qty(row.get("qty"))) for row in old_movements) + EPS < qty:
            raise HTTPException(
                status_code=409,
                detail="Jejak lot pengeluaran belum lengkap. Koreksi tumpukan tidak dijalankan agar saldo FEFO tidak rusak.",
            )

        sj = None
        if load.get("surat_jalan_id"):
            sj = await db.surat_jalan.find_one({"id": load["surat_jalan_id"]}, {"_id": 0})
        if not sj:
            sj = await db.surat_jalan.find_one({"load_id": load_id}, {"_id": 0})

        transaction = await db.transactions.find_one(
            {
                "load_id": load_id,
                "type": "KELUAR",
                "product_id": product_id,
                "stackCode": old_stack,
                "$or": [{"source_document": source_document}, {"ref": source_document}],
                "change": {"$lte": -qty + EPS, "$gte": -qty - EPS},
            },
            {"_id": 0},
        )
        if not transaction:
            raise HTTPException(status_code=409, detail="Transaksi stok keluar untuk baris ini tidak ditemukan")

        lot_snapshots = await db.stack_lots.find(
            {"productId": product_id, "stackCode": {"$in": [old_stack, new_stack]}},
            {"_id": 0},
        ).to_list(10000)
        movement_snapshots = await db.stack_lot_movements.find(
            {"loadId": load_id, "productId": product_id},
            {"_id": 0},
        ).to_list(10000)

        source_before = _qty((source_allocation or {}).get("primaryQty"))
        target_before = target_physical
        time = now_iso()
        location_config = await get_operational_location(new_stack, "outbound")
        crew_group = _crew_group((location_config or {}).get("loadingGroup", "") or new_stack)
        corrected_item = {
            **item,
            "stackCode": new_stack,
            "location": new_stack,
            "locationCode": (location_config or {}).get("code", new_stack.split("/", 1)[0]),
            "locationName": (location_config or {}).get("name", new_stack.split("/", 1)[0]),
            "crewGroup": crew_group,
        }
        recommended = [str(value or "").strip().upper() for value in corrected_item.get("fefoRecommendedStacks", [])]
        if recommended:
            corrected_item["fefoSelectionStatus"] = "PRIORITY" if new_stack in recommended else "EXCEPTION"
            corrected_item["fefoExceptionReason"] = "" if new_stack in recommended else body.reason.strip()
        items[body.itemIndex] = corrected_item
        unit_loading, _ = loading_units_from_items(items)
        crew_groups = sorted({str(row.get("crewGroup") or "") for row in items if str(row.get("crewGroup") or "")})
        loading_cost = dict(load.get("loading_cost") or {})
        loading_cost["group"] = crew_groups[0] if len(crew_groups) == 1 else ""

        event = {
            "id": new_id(),
            "time": time,
            "by": user.get("name", ""),
            "reason": body.reason.strip(),
            "type": "KOREKSI_TUMPUKAN_PENGAMBILAN",
            "itemIndex": body.itemIndex,
            "productId": product_id,
            "product": item.get("name", ""),
            "qty": qty,
            "unit": item.get("unit", ""),
            "documentNo": source_document,
            "before": {"stackCode": old_stack, "unitLoading": load.get("unit_loading", "")},
            "after": {"stackCode": new_stack, "unitLoading": unit_loading},
        }
        updated_load = {
            **load,
            "items": items,
            "unit_loading": unit_loading,
            "crew_groups": crew_groups,
            "loading_cost": loading_cost,
            "correction_history": list(load.get("correction_history") or []) + [event],
            "last_correction_at": time,
            "last_correction_by": user.get("name", ""),
        }

        load_updated = False
        try:
            # Physical relocation only: total product.stock remains untouched.
            source_after_row = await _write_stack_qty(
                product, old_stack, source_before + qty,
                note=f"Koreksi pengeluaran {load.get('bon_no', '')}: dikembalikan ke tumpukan asal pencatatan",
            )
            target_after_row = await _write_stack_qty(
                product, new_stack, target_before - qty,
                note=f"Koreksi pengeluaran {load.get('bon_no', '')}: sumber fisik sebenarnya",
            )

            # Undo old lot attribution, then let the conservative FEFO engine consume
            # the same quantity from the corrected physical stack.
            await _restore_outbound_lot_usage(load, item, qty)

            result = await db.outbound_loads.replace_one(
                {"id": load_id, "status": "Selesai"},
                updated_load,
                upsert=False,
            )
            if result.matched_count == 0:
                raise HTTPException(status_code=409, detail="Data pengeluaran berubah saat koreksi")
            load_updated = True

            fefo = await consume_stack_lots_conservative(updated_load, lock_products=False)
            updated_load["fefo_tracked_qty"] = fefo.get("tracked", 0)
            updated_load["fefo_untracked_qty"] = fefo.get("untracked", 0)
            updated_load["fefo_legacy_protected_qty"] = fefo.get("legacyProtected", 0)
            updated_load["fefo_policy"] = fefo.get("policy", "CONSERVATIVE_LEGACY_FIRST")
            await db.outbound_loads.update_one(
                {"id": load_id},
                {"$set": {
                    "fefo_tracked_qty": updated_load["fefo_tracked_qty"],
                    "fefo_untracked_qty": updated_load["fefo_untracked_qty"],
                    "fefo_legacy_protected_qty": updated_load["fefo_legacy_protected_qty"],
                    "fefo_policy": updated_load["fefo_policy"],
                }},
            )

            await db.transactions.update_one(
                {"id": transaction["id"]},
                {"$set": {
                    "stackCode": new_stack,
                    "correction_reason": body.reason.strip(),
                    "corrected_stack_from": old_stack,
                    "corrected_stack_at": time,
                    "corrected_stack_by": user.get("name", ""),
                }},
            )

            if sj:
                corrected_sj = surat_jalan_with_exact_locations(updated_load, sj)
                await db.surat_jalan.update_one(
                    {"id": sj["id"]},
                    {"$set": {
                        "items": corrected_sj.get("items", []),
                        "unit_loading": corrected_sj.get("unit_loading", ""),
                        "last_correction_at": time,
                        "last_correction_by": user.get("name", ""),
                    }},
                )

            audit_id = new_id()
            await db.transactions.insert_one({
                "id": audit_id,
                "operation_id": audit_id,
                "load_id": load_id,
                "time": time,
                "ref": source_document,
                "bon_no": load.get("bon_no", ""),
                "antrian": load.get("antrian", ""),
                "type": "KOREKSI",
                "kondisi": "LOKASI",
                "document_type": "KOREKSI_TUMPUKAN_PENGELUARAN",
                "product": item.get("name", ""),
                "sku": item.get("sku", ""),
                "product_id": product_id,
                "change": 0,
                "unit": item.get("unit", ""),
                "stackCode": new_stack,
                "source_stack": old_stack,
                "target_stack": new_stack,
                "operator": user.get("name", ""),
                "keterangan": body.reason.strip(),
                "correction_reason": body.reason.strip(),
                "correction_event_id": event["id"],
            })

            if source_after_row:
                await record_stack_history("KOREKSI_PENGELUARAN_KEMBALI", source_after_row, user.get("name", ""))
            if target_after_row:
                await record_stack_history("KOREKSI_PENGELUARAN_AMBIL", target_after_row, user.get("name", ""))

        except Exception:
            # Compensating rollback keeps physical, lot, document, and transaction
            # snapshots aligned if any part of the correction cannot finish.
            await _restore_allocation_snapshot(product_id, old_stack, source_allocation)
            await _restore_allocation_snapshot(product_id, new_stack, target_allocation)

            current_lots = await db.stack_lots.find(
                {"productId": product_id, "stackCode": {"$in": [old_stack, new_stack]}},
                {"_id": 0, "id": 1},
            ).to_list(10000)
            snapshot_ids = {row["id"] for row in lot_snapshots}
            for row in current_lots:
                if row.get("id") not in snapshot_ids:
                    await db.stack_lots.delete_one({"id": row["id"]})
            for row in lot_snapshots:
                await db.stack_lots.replace_one({"id": row["id"]}, row, upsert=True)

            await db.stack_lot_movements.delete_many({"loadId": load_id, "productId": product_id})
            if movement_snapshots:
                await db.stack_lot_movements.insert_many([dict(row) for row in movement_snapshots])

            if load_updated:
                await db.outbound_loads.replace_one({"id": load_id}, load, upsert=False)
            await db.transactions.replace_one({"id": transaction["id"]}, transaction, upsert=True)
            await db.transactions.delete_many({
                "load_id": load_id,
                "type": "KOREKSI",
                "document_type": "KOREKSI_TUMPUKAN_PENGELUARAN",
                "correction_event_id": event["id"],
            })
            if sj:
                await db.surat_jalan.replace_one({"id": sj["id"]}, sj, upsert=True)
            raise

        return await db.outbound_loads.find_one({"id": load_id}, {"_id": 0})


@router.put("/operational-corrections/outbound/{load_id}")
async def correct_completed_outbound_metadata(load_id: str, body: OutboundMetadataCorrectionInput, user: dict = Depends(require_admin)):
    async with operation_guard([f"outbound-correction:{load_id}"]):
        load = await db.outbound_loads.find_one({"id": load_id}, {"_id": 0})
        if not load:
            raise HTTPException(status_code=404, detail="Data pengeluaran tidak ditemukan")
        if load.get("status") != "Selesai":
            raise HTTPException(status_code=400, detail="Koreksi dokumen selesai hanya tersedia setelah pemuatan selesai")

        changes = {}
        if body.party is not None:
            party = body.party.strip()
            if not party:
                raise HTTPException(status_code=400, detail="Penerima barang tidak boleh dikosongkan")
            changes["party"] = party
            changes["penerima"] = party
        if body.polisi is not None: changes["polisi"] = body.polisi.strip()
        if body.pengambil is not None: changes["pengambil"] = body.pengambil.strip()
        if body.keterangan is not None: changes["keterangan"] = body.keterangan.strip()
        if not changes:
            raise HTTPException(status_code=400, detail="Tidak ada metadata dokumen yang berubah")

        before = {"party": load.get("party", ""), "penerima": load.get("penerima", ""), "polisi": load.get("polisi", ""), "pengambil": load.get("pengambil", ""), "keterangan": load.get("keterangan", "")}
        after = {**before, **changes}
        if all(str(after.get(key, "")) == str(before.get(key, "")) for key in before):
            raise HTTPException(status_code=400, detail="Tidak ada perubahan dibanding data saat ini")

        time = now_iso()
        event = {"id": new_id(), "time": time, "by": user.get("name", ""), "reason": body.reason.strip(), "before": before, "after": after}
        sj = None
        if load.get("surat_jalan_id"):
            sj = await db.surat_jalan.find_one({"id": load["surat_jalan_id"]}, {"_id": 0})
        if not sj:
            sj = await db.surat_jalan.find_one({"load_id": load_id}, {"_id": 0})
        txns = await db.transactions.find({"load_id": load_id, "type": "KELUAR"}, {"_id": 0, "id": 1, "penerima": 1, "polisi": 1, "pengambil": 1, "keterangan": 1}).to_list(5000)

        audit_id = new_id()
        load_updated = sj_updated = tx_updated = False
        try:
            result = await db.outbound_loads.update_one({"id": load_id, "status": "Selesai"}, {"$set": {**changes, "last_correction_at": time, "last_correction_by": user.get("name", "")}, "$push": {"correction_history": event}})
            if result.matched_count == 0:
                raise HTTPException(status_code=409, detail="Data pengeluaran berubah saat koreksi. Muat ulang lalu coba kembali.")
            load_updated = True

            if sj:
                sj_changes = {}
                if "party" in changes or "penerima" in changes: sj_changes["penerima"] = after["party"]
                for key in ("polisi", "pengambil", "keterangan"):
                    if key in changes: sj_changes[key] = changes[key]
                if sj_changes:
                    await db.surat_jalan.update_one({"id": sj["id"]}, {"$set": sj_changes})
                    sj_updated = True

            txn_changes = {}
            if "party" in changes or "penerima" in changes: txn_changes["penerima"] = after["party"]
            for key in ("polisi", "pengambil", "keterangan"):
                if key in changes: txn_changes[key] = changes[key]
            if txn_changes:
                await db.transactions.update_many({"load_id": load_id, "type": "KELUAR"}, {"$set": txn_changes})
                tx_updated = True

            await db.transactions.insert_one({"id": audit_id, "operation_id": audit_id, "load_id": load_id, "time": time, "ref": load.get("ref", ""), "bon_no": load.get("bon_no", ""), "antrian": load.get("antrian", ""), "type": "KOREKSI", "kondisi": "DOKUMEN", "document_type": "KOREKSI_DOKUMEN_KELUAR", "product": "Metadata pengeluaran", "sku": "", "change": 0, "unit": "", "penerima": after.get("party", ""), "polisi": after.get("polisi", ""), "pengambil": after.get("pengambil", ""), "operator": user.get("name", ""), "keterangan": body.reason.strip(), "correction_reason": body.reason.strip(), "correction_event_id": event["id"]})
        except Exception:
            await db.transactions.delete_one({"id": audit_id})
            if tx_updated:
                for txn in txns:
                    await db.transactions.update_one({"id": txn["id"]}, {"$set": {"penerima": txn.get("penerima", ""), "polisi": txn.get("polisi", ""), "pengambil": txn.get("pengambil", ""), "keterangan": txn.get("keterangan", "")}})
            if sj_updated and sj:
                await db.surat_jalan.update_one({"id": sj["id"]}, {"$set": {"penerima": sj.get("penerima", ""), "polisi": sj.get("polisi", ""), "pengambil": sj.get("pengambil", ""), "keterangan": sj.get("keterangan", "")}})
            if load_updated:
                await db.outbound_loads.update_one({"id": load_id}, {"$set": {**before, "correction_history": list(load.get("correction_history") or [])}, "$unset": {"last_correction_at": "", "last_correction_by": ""}})
            raise

        return await db.outbound_loads.find_one({"id": load_id}, {"_id": 0})
