from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.server import db, new_id, now_iso, normalize_channel, require_admin, ensure_channel_stock
from backend.inventory_flow import _po_status
from backend.stack_allocations import decrease_stack_allocation, reconcile_product_allocations
from backend.operational_guards import lock_keys, operation_guard, product_lock_keys
from backend.correction_receipts import product_maps, receipt_rows, recalculate_product_exp, txn_quantities
from backend.outbound_flow import _reserved_qty
from backend.stack_reservations import reserved_stack_qty

router = APIRouter(prefix="/api")
EPS = 1e-9


class CorrectionReasonInput(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


@router.post("/operational-corrections/receipts/{operation_id}/void")
async def void_receipt_operation(operation_id: str, body: CorrectionReasonInput, user: dict = Depends(require_admin)):
    initial_rows = await receipt_rows(operation_id)
    if not initial_rows:
        raise HTTPException(status_code=404, detail="Operasi penerimaan tidak ditemukan")

    by_id, by_sku = await product_maps()
    product_ids = []
    for row in initial_rows:
        product = by_id.get(str(row.get("product_id") or "")) or by_sku.get(str(row.get("sku") or ""))
        if product:
            product_ids.append(product["id"])
    po_id = str(initial_rows[0].get("po_id") or "")
    keys = lock_keys([f"receipt-correction:{operation_id}"], product_lock_keys(product_ids), [f"po:{po_id}"] if po_id else [])

    async with operation_guard(keys):
        rows = await receipt_rows(operation_id)
        if not rows:
            raise HTTPException(status_code=404, detail="Operasi penerimaan tidak ditemukan")
        if any(bool(row.get("voided")) for row in rows):
            raise HTTPException(status_code=409, detail="Penerimaan ini sudah pernah dikoreksi")
        if await db.supplier_returns.find_one({"source_damage_operation_id": operation_id}, {"_id": 1}):
            raise HTTPException(status_code=400, detail="Penerimaan tidak dapat dibatalkan karena barang rusaknya sudah memiliki Retur Pemasok")

        by_id, by_sku = await product_maps()
        tx_products: dict[str, dict] = {}
        global_totals = defaultdict(lambda: {"good": 0.0, "damaged": 0.0})
        channel_totals = defaultdict(lambda: {"good": 0.0, "damaged": 0.0})
        stack_totals = defaultdict(float)
        po_totals = defaultdict(float)

        for row in rows:
            product = by_id.get(str(row.get("product_id") or "")) or by_sku.get(str(row.get("sku") or ""))
            if not product:
                raise HTTPException(status_code=400, detail=f"Master produk {row.get('sku') or row.get('product')} tidak ditemukan")
            tx_products[row["id"]] = product
            good, damaged = txn_quantities(row)
            channel = normalize_channel(row.get("channel"), normalize_channel(product.get("channel")))
            global_totals[product["id"]]["good"] += good
            global_totals[product["id"]]["damaged"] += damaged
            channel_totals[(product["id"], channel)]["good"] += good
            channel_totals[(product["id"], channel)]["damaged"] += damaged
            po_totals[product["id"]] += good + damaged
            if good > 0:
                stack_code = str(row.get("stackCode") or "").strip().upper()
                if not stack_code:
                    raise HTTPException(status_code=400, detail="Penerimaan lama belum menyimpan tumpukan asal sehingga tidak aman dibatalkan otomatis")
                stack_totals[(product["id"], stack_code)] += good

        latest_products: dict[str, dict] = {}
        for product_id, totals in global_totals.items():
            product = await db.products.find_one({"id": product_id}, {"_id": 0})
            if not product:
                raise HTTPException(status_code=404, detail="Produk penerimaan tidak ditemukan")
            await ensure_channel_stock(product)
            product = await db.products.find_one({"id": product_id}, {"_id": 0}) or product
            latest_products[product_id] = product

            physical_good = float(product.get("stock", 0) or 0)
            reserved_good = await _reserved_qty(product_id, "BAIK")
            available_good = max(physical_good - reserved_good, 0.0)
            if totals["good"] > available_good + EPS:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Penerimaan {product.get('name', '')} tidak dapat dibatalkan karena stok Baik sudah terikat antrean outbound. "
                        f"Fisik {physical_good:g}, reservasi {reserved_good:g}, tersedia untuk koreksi {available_good:g}, akan dikurangi {totals['good']:g}."
                    ),
                )

            physical_damaged = float(product.get("damaged", 0) or 0)
            reserved_damaged = await _reserved_qty(product_id, "RUSAK")
            available_damaged = max(physical_damaged - reserved_damaged, 0.0)
            if totals["damaged"] > available_damaged + EPS:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Penerimaan {product.get('name', '')} tidak dapat dibatalkan karena stok Rusak sudah terikat antrean R-xxx. "
                        f"Fisik {physical_damaged:g}, reservasi {reserved_damaged:g}, tersedia untuk koreksi {available_damaged:g}, akan dikurangi {totals['damaged']:g}."
                    ),
                )

        for (product_id, channel), totals in channel_totals.items():
            bucket = (latest_products[product_id].get("channelStock") or {}).get(channel, {})
            good_balance = float(bucket.get("stock", 0) or 0)
            good_reserved = await _reserved_qty(product_id, "BAIK", channel=channel)
            good_available = max(good_balance - good_reserved, 0.0)
            if totals["good"] > good_available + EPS:
                raise HTTPException(
                    status_code=400,
                    detail=f"Stok Baik saluran {channel} sudah terikat reservasi outbound. Tersedia untuk koreksi hanya {good_available:g}.",
                )

            damaged_balance = float(bucket.get("damaged", 0) or 0)
            damaged_reserved = await _reserved_qty(product_id, "RUSAK", channel=channel)
            damaged_available = max(damaged_balance - damaged_reserved, 0.0)
            if totals["damaged"] > damaged_available + EPS:
                raise HTTPException(
                    status_code=400,
                    detail=f"Stok Rusak saluran {channel} sudah terikat antrean R-xxx. Tersedia untuk koreksi hanya {damaged_available:g}.",
                )

        stack_snapshots: dict[tuple[str, str], dict] = {}
        for (product_id, stack_code), qty in stack_totals.items():
            allocation = await db.stack_allocations.find_one({"productId": product_id, "stackCode": stack_code}, {"_id": 0})
            physical_stack = float((allocation or {}).get("primaryQty", 0) or 0)
            reserved_stack = await reserved_stack_qty(product_id, stack_code)
            available_stack = max(physical_stack - reserved_stack, 0.0)
            if not allocation or qty > available_stack + EPS:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Penerimaan tidak dapat dibatalkan dari tumpukan {stack_code} karena stok sudah berubah/direservasi outbound. "
                        f"Fisik {physical_stack:g}, reservasi {reserved_stack:g}, tersedia untuk koreksi {available_stack:g}, akan dikurangi {qty:g}."
                    ),
                )
            stack_snapshots[(product_id, stack_code)] = allocation

        po = None
        if po_id:
            po = await db.purchase_orders.find_one({"id": po_id}, {"_id": 0})
        elif rows[0].get("po_no"):
            po = await db.purchase_orders.find_one({"no": rows[0].get("po_no")}, {"_id": 0})

        updated_po_items = None
        if po:
            updated_po_items = []
            for item in po.get("items", []):
                revised = dict(item)
                product_id = str(revised.get("productId") or "")
                if not product_id and revised.get("sku"):
                    product_id = str((by_sku.get(str(revised.get("sku"))) or {}).get("id") or "")
                delta = po_totals.get(product_id, 0.0)
                if delta:
                    received = float(revised.get("receivedQty", revised.get("received_qty", 0)) or 0)
                    if received + EPS < delta:
                        raise HTTPException(status_code=409, detail="Jumlah penerimaan PO sudah berubah. Muat ulang lalu periksa dokumen.")
                    revised["receivedQty"] = max(received - delta, 0.0)
                updated_po_items.append(revised)

        correction_id = new_id()
        correction_time = now_iso()
        applied_products: list[str] = []
        decreased_stacks: list[tuple[str, str]] = []
        po_changed = False
        originals_marked = False

        try:
            for product_id, totals in global_totals.items():
                inc: dict[str, float] = {}
                query: dict = {"id": product_id}
                if totals["good"]:
                    inc["stock"] = -totals["good"]
                    query["stock"] = {"$gte": totals["good"]}
                if totals["damaged"]:
                    inc["damaged"] = -totals["damaged"]
                    query["damaged"] = {"$gte": totals["damaged"]}
                for (pid, channel), values in channel_totals.items():
                    if pid != product_id:
                        continue
                    if values["good"]:
                        inc[f"channelStock.{channel}.stock"] = -values["good"]
                        query[f"channelStock.{channel}.stock"] = {"$gte": values["good"]}
                    if values["damaged"]:
                        inc[f"channelStock.{channel}.damaged"] = -values["damaged"]
                        query[f"channelStock.{channel}.damaged"] = {"$gte": values["damaged"]}
                result = await db.products.update_one(query, {"$inc": inc})
                if result.matched_count == 0:
                    raise HTTPException(status_code=409, detail="Saldo stok berubah saat koreksi. Muat ulang lalu coba kembali.")
                applied_products.append(product_id)

            for (product_id, stack_code), qty in stack_totals.items():
                await decrease_stack_allocation(product_id, stack_code, qty, f"{user.get('name', 'Superadmin')} · Koreksi penerimaan")
                decreased_stacks.append((product_id, stack_code))

            if po and updated_po_items is not None:
                result = await db.purchase_orders.update_one({"id": po["id"]}, {"$set": {"items": updated_po_items, "status": _po_status(updated_po_items), "last_correction_at": correction_time, "last_correction_by": user.get("name", "")}})
                if result.matched_count == 0:
                    raise HTTPException(status_code=409, detail="PO berubah saat koreksi. Muat ulang lalu coba kembali.")
                po_changed = True

            reversal_rows = []
            for row in rows:
                good, damaged = txn_quantities(row)
                product = tx_products[row["id"]]
                reversal_rows.append({
                    "id": new_id(), "operation_id": correction_id, "parent_operation_id": operation_id,
                    "time": correction_time, "ref": f"KOR-{row.get('ref') or operation_id}",
                    "po_id": row.get("po_id", ""), "po_no": row.get("po_no", ""), "antrian": "",
                    "type": "KOREKSI", "kondisi": row.get("kondisi", ""), "document_type": "KOREKSI_PENERIMAAN",
                    "parent_document": row.get("ref", ""), "product_id": product.get("id", ""),
                    "product": row.get("product", product.get("name", "")), "sku": row.get("sku", product.get("sku", "")),
                    "change": -(good + damaged), "good_change": -good, "damaged_change": -damaged,
                    "unit": row.get("unit", product.get("unit", "")), "weight": float(row.get("weight", product.get("weight", 0)) or 0),
                    "total_weight": -abs(float(row.get("total_weight", 0) or 0)), "secondary": row.get("secondary", product.get("secondary", "")),
                    "secondaryQty": float(row.get("secondaryQty", product.get("secondaryQty", 0)) or 0),
                    "channel": row.get("channel", normalize_channel(product.get("channel"))), "exp": row.get("exp", ""),
                    "stackCode": row.get("stackCode", ""), "receipt_location": row.get("receipt_location", ""),
                    "penerima": row.get("penerima", ""), "operator": user.get("name", ""), "keterangan": body.reason.strip(),
                    "correction_reason": body.reason.strip(), "correction_for_operation": operation_id,
                })
            if reversal_rows:
                await db.transactions.insert_many(reversal_rows)

            mark = await db.transactions.update_many({"id": {"$in": [row["id"] for row in rows]}, "voided": {"$ne": True}}, {"$set": {"voided": True, "void_reason": body.reason.strip(), "voided_at": correction_time, "voided_by": user.get("name", ""), "correction_id": correction_id}})
            if mark.modified_count != len(rows):
                raise HTTPException(status_code=409, detail="Sebagian riwayat penerimaan berubah saat koreksi. Periksa ulang transaksi.")
            originals_marked = True
        except Exception:
            if originals_marked:
                await db.transactions.update_many({"id": {"$in": [row["id"] for row in rows]}, "correction_id": correction_id}, {"$unset": {"voided": "", "void_reason": "", "voided_at": "", "voided_by": "", "correction_id": ""}})
            await db.transactions.delete_many({"operation_id": correction_id})
            if po_changed and po:
                await db.purchase_orders.replace_one({"id": po["id"]}, po, upsert=False)
            for product_id, stack_code in reversed(decreased_stacks):
                snapshot = stack_snapshots[(product_id, stack_code)]
                await db.stack_allocations.replace_one({"id": snapshot["id"]}, snapshot, upsert=True)
            for product_id in reversed(applied_products):
                totals = global_totals[product_id]
                inc: dict[str, float] = {}
                if totals["good"]: inc["stock"] = totals["good"]
                if totals["damaged"]: inc["damaged"] = totals["damaged"]
                for (pid, channel), values in channel_totals.items():
                    if pid != product_id: continue
                    if values["good"]: inc[f"channelStock.{channel}.stock"] = values["good"]
                    if values["damaged"]: inc[f"channelStock.{channel}.damaged"] = values["damaged"]
                await db.products.update_one({"id": product_id}, {"$inc": inc})
            raise

        for product_id in global_totals:
            try:
                await reconcile_product_allocations(product_id)
                await recalculate_product_exp(latest_products[product_id])
            except Exception:
                pass

        # Jika penerimaan berasal dari satu kendaraan PO, sinkronkan jejak
        # kendaraan tanpa mengubah status historis "Selesai". Koreksi tetap
        # menjadi satu-satunya cara membatalkan penerimaan yang sudah selesai.
        try:
            reversal_event = {
                "time": correction_time,
                "status": "Direversal",
                "by": user.get("name", ""),
                "note": body.reason.strip(),
            }
            await db.inbound_loads.update_one(
                {"operationId": operation_id, "status": "Selesai"},
                {
                    "$set": {
                        "reversedAt": correction_time,
                        "reversedBy": user.get("name", ""),
                        "reversalReason": body.reason.strip(),
                        "correctionId": correction_id,
                    },
                    "$push": {"history": reversal_event},
                },
            )
        except Exception:
            # Reversal stok/PO sudah sah; metadata kendaraan bersifat audit
            # tambahan dan tidak boleh membuat koreksi inti tampak gagal.
            pass

        return {"correctionId": correction_id, "operationId": operation_id, "message": "Penerimaan berhasil dibatalkan melalui transaksi koreksi"}
