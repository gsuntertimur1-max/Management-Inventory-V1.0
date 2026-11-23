from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.server import (
    channel_balance,
    db,
    ensure_channel_stock,
    get_current_user,
    new_id,
    next_sequence,
    normalize_channel,
    now_iso,
    operational_now,
    require_write,
)
from backend.operational_guards import lock_keys, operation_guard, product_lock_keys
from backend.stack_allocations import (
    allocate_stock_to_stack,
    decrease_stack_allocation,
    valid_stack_codes,
)
from backend.stack_lots import lot_sort_key, record_receipt_lots

router = APIRouter(prefix="/api")
EPS = 1e-9
COLLECTION = "partner_variance_settlements"


class PartnerVarianceActionInput(BaseModel):
    method: str
    qty: float = Field(gt=0)
    stackCode: str = ""
    referenceNo: str = ""
    note: str = Field(default="", max_length=500)


class PartnerVarianceCompensationInput(BaseModel):
    excessKey: str
    shortageKey: str
    qty: float = Field(gt=0)
    referenceNo: str = ""
    note: str = Field(default="", max_length=500)


async def ensure_partner_variance_indexes() -> None:
    collection = db[COLLECTION]
    await collection.create_index("id", unique=True, name="partner_variance_settlement_id_unique")
    await collection.create_index("settlementNo", unique=True, sparse=True, name="partner_variance_settlement_no_unique")
    await collection.create_index([("excessKey", 1), ("status", 1)], name="partner_variance_excess_status")
    await collection.create_index([("shortageKey", 1), ("status", 1)], name="partner_variance_shortage_status")
    await collection.create_index([("supplierKey", 1), ("productId", 1), ("time", -1)], name="partner_variance_supplier_product")


def _n(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _party_key(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _source_key(load_id: str, product_id: str) -> str:
    return f"{str(load_id or '').strip()}:{str(product_id or '').strip()}"


def _variance_kind(value: float) -> str:
    if value > EPS:
        return "EXCESS"
    if value < -EPS:
        return "SHORTAGE"
    return ""


def _tm_label(plotting: dict | None, fallback: str) -> str:
    if plotting:
        values = []
        for row in plotting.get("documentAllocations", []) or []:
            if str(row.get("documentType") or "").strip().upper() != "TM":
                continue
            number = str(row.get("documentNo") or "").strip()
            if number and number not in values:
                values.append(number)
        if values:
            return " / ".join(values)
    return str(fallback or "").strip()


async def _load_completed_move_in_rows(product_id: str = "") -> list[dict]:
    query: dict = {
        "status": "Selesai",
        "$or": [
            {"sourceType": "MOVE_IN"},
            {"historicalImportSource": {"$exists": True}},
        ],
    }
    if str(product_id or "").strip():
        query["actualItems.productId"] = str(product_id).strip()
    return await db.inbound_loads.find(query, {"_id": 0}).sort("completedAt", -1).to_list(20000)


async def _build_sources(product_id: str = "") -> list[dict]:
    loads = await _load_completed_move_in_rows(product_id)
    if not loads:
        return []

    product_ids = sorted({
        str(item.get("productId") or "")
        for load in loads
        for item in (load.get("actualItems") or [])
        if str(item.get("productId") or "")
    })
    po_ids = sorted({str(load.get("poId") or "") for load in loads if str(load.get("poId") or "")})

    products = await db.products.find({"id": {"$in": product_ids}}, {"_id": 0}).to_list(max(len(product_ids), 1))
    product_map = {str(row.get("id") or ""): row for row in products}
    pos = await db.purchase_orders.find({"id": {"$in": po_ids}}, {"_id": 0}).to_list(max(len(po_ids), 1))
    po_map = {str(row.get("id") or ""): row for row in pos}

    plotting_ids = sorted({
        str(row.get("moveInPlottingId") or "")
        for row in pos
        if str(row.get("moveInPlottingId") or "")
    })
    plottings = await db.move_in_plottings.find({"id": {"$in": plotting_ids}}, {"_id": 0}).to_list(max(len(plotting_ids), 1))
    plotting_map = {str(row.get("id") or ""): row for row in plottings}

    keys: list[str] = []
    raw_sources: list[dict] = []
    for load in loads:
        load_id = str(load.get("id") or "")
        po = po_map.get(str(load.get("poId") or ""), {})
        plotting = plotting_map.get(str(po.get("moveInPlottingId") or ""), {})
        supplier = str(load.get("party") or po.get("supplier") or "").strip()
        document_no = _tm_label(plotting, str(load.get("poNo") or po.get("no") or ""))
        for item in load.get("actualItems") or []:
            pid = str(item.get("productId") or "")
            if product_id and pid != product_id:
                continue
            variance_qty = _n(item.get("varianceQty"))
            if abs(variance_qty) <= EPS:
                planned = _n(item.get("plannedQty"))
                actual = _n(item.get("documentActualQty", item.get("actualQty")))
                variance_qty = actual - planned
            kind = _variance_kind(variance_qty)
            if not kind:
                continue

            product = product_map.get(pid, {})
            key = _source_key(load_id, pid)
            keys.append(key)
            weight = _n(item.get("weight", product.get("weight")))
            channel = normalize_channel(item.get("channel"), normalize_channel(product.get("channel")))
            raw_sources.append({
                "key": key,
                "kind": kind,
                "loadId": load_id,
                "loadNo": str(load.get("loadNo") or ""),
                "poId": str(load.get("poId") or ""),
                "poNo": str(load.get("poNo") or po.get("no") or ""),
                "plottingId": str(po.get("moveInPlottingId") or ""),
                "documentNo": document_no,
                "supplier": supplier,
                "supplierKey": _party_key(supplier),
                "polisi": str(load.get("polisi") or "").strip().upper(),
                "operationalDate": str(load.get("completedAt") or load.get("createdAt") or "")[:10],
                "completedAt": str(load.get("completedAt") or ""),
                "productId": pid,
                "sku": str(item.get("sku") or product.get("sku") or ""),
                "product": str(item.get("name") or product.get("name") or ""),
                "unit": str(item.get("unit") or product.get("unit") or ""),
                "weightKgPerUnit": weight,
                "channel": channel,
                "stackCode": str(item.get("stackCode") or "").strip().upper(),
                "exp": str(item.get("exp") or "").strip(),
                "plannedQty": _n(item.get("plannedQty")),
                "actualQty": _n(item.get("documentActualQty", item.get("actualQty"))),
                "varianceQty": variance_qty,
                "originalQty": abs(variance_qty),
                "originalWeightKg": abs(variance_qty) * weight,
                "reason": str(item.get("discrepancyReason") or "").strip(),
                "historicalImportAlias": str(load.get("historicalImportAlias") or ""),
            })

    if not raw_sources:
        return []

    settlements = await db[COLLECTION].find(
        {
            "status": "SELESAI",
            "$or": [
                {"excessKey": {"$in": keys}},
                {"shortageKey": {"$in": keys}},
            ],
        },
        {"_id": 0},
    ).sort("time", -1).to_list(50000)

    used_by_key: dict[str, float] = defaultdict(float)
    history_by_key: dict[str, list[dict]] = defaultdict(list)
    for row in settlements:
        qty = _n(row.get("qty"))
        excess_key = str(row.get("excessKey") or "")
        shortage_key = str(row.get("shortageKey") or "")
        if excess_key:
            used_by_key[excess_key] += qty
            history_by_key[excess_key].append(row)
        if shortage_key:
            used_by_key[shortage_key] += qty
            history_by_key[shortage_key].append(row)

    result = []
    for source in raw_sources:
        used = min(used_by_key.get(source["key"], 0.0), source["originalQty"])
        remaining = max(source["originalQty"] - used, 0.0)
        if remaining <= EPS:
            status = "SELESAI"
        elif used > EPS:
            status = "SEBAGIAN"
        else:
            status = "AKTIF"
        source["settledQty"] = round(used, 6)
        source["remainingQty"] = round(remaining, 6)
        source["remainingWeightKg"] = round(remaining * source["weightKgPerUnit"], 6)
        source["status"] = status
        source["history"] = history_by_key.get(source["key"], [])
        result.append(source)

    result.sort(key=lambda row: (row.get("operationalDate", ""), row.get("completedAt", ""), row.get("loadNo", "")), reverse=True)
    return result


async def _source_by_key(source_key: str) -> dict:
    source_key = str(source_key or "").strip()
    if not source_key or ":" not in source_key:
        raise HTTPException(status_code=400, detail="Identitas selisih mitra tidak valid")
    load_id, product_id = source_key.rsplit(":", 1)
    sources = await _build_sources(product_id)
    source = next((row for row in sources if row["key"] == source_key and row["loadId"] == load_id), None)
    if not source:
        raise HTTPException(status_code=404, detail="Selisih mitra tidak ditemukan")
    return source


async def reserved_partner_excess_qty(product_id: str, stack_code: str = "", channel: str = "") -> float:
    """Saldo lebih kirim tetap fisik di gudang tetapi tidak boleh dipakai outbound sebelum diselesaikan."""
    product_id = str(product_id or "").strip()
    if not product_id:
        return 0.0
    loads = await _load_completed_move_in_rows(product_id)
    candidates: list[dict] = []
    keys: list[str] = []
    target_stack = str(stack_code or "").strip().upper()
    target_channel = str(channel or "").strip().upper()

    for load in loads:
        load_id = str(load.get("id") or "")
        for item in load.get("actualItems") or []:
            if str(item.get("productId") or "") != product_id:
                continue
            variance = _n(item.get("varianceQty"))
            if variance <= EPS:
                continue
            item_stack = str(item.get("stackCode") or "").strip().upper()
            item_channel = str(item.get("channel") or "").strip().upper()
            if target_stack and item_stack != target_stack:
                continue
            if target_channel and item_channel and item_channel != target_channel:
                continue
            key = _source_key(load_id, product_id)
            keys.append(key)
            candidates.append({"key": key, "qty": variance})

    if not candidates:
        return 0.0

    settlements = await db[COLLECTION].find(
        {"status": "SELESAI", "excessKey": {"$in": keys}},
        {"_id": 0, "excessKey": 1, "qty": 1},
    ).to_list(50000)
    used: dict[str, float] = defaultdict(float)
    for row in settlements:
        used[str(row.get("excessKey") or "")] += _n(row.get("qty"))
    return round(sum(max(row["qty"] - used.get(row["key"], 0.0), 0.0) for row in candidates), 6)


async def _new_settlement_no(reference_no: str) -> str:
    reference_no = str(reference_no or "").strip().upper()
    if reference_no:
        exists = await db[COLLECTION].find_one({"settlementNo": reference_no}, {"_id": 1})
        if exists:
            raise HTTPException(status_code=409, detail="Nomor referensi penyelesaian sudah digunakan")
        return reference_no
    now = operational_now()
    return f"SM-{now.strftime('%Y%m%d')}-{await next_sequence('partner-variance-settlement', 0):04d}"


async def _consume_lots_for_partner_withdrawal(
    product_id: str,
    stack_code: str,
    qty: float,
    settlement_id: str,
    settlement_no: str,
    source: dict,
) -> list[dict]:
    lots = await db.stack_lots.find(
        {"productId": product_id, "stackCode": stack_code, "remainingQty": {"$gt": EPS}},
        {"_id": 0},
    ).to_list(10000)
    lots.sort(key=lot_sort_key)
    remaining = qty
    changes: list[dict] = []
    time = now_iso()

    for lot in lots:
        if remaining <= EPS:
            break
        available = _n(lot.get("remainingQty"))
        if available <= EPS:
            continue
        take = min(available, remaining)
        new_remaining = max(available - take, 0.0)
        result = await db.stack_lots.update_one(
            {"id": lot["id"], "remainingQty": {"$gte": take - EPS}},
            {"$set": {
                "remainingQty": new_remaining,
                "status": "HABIS" if new_remaining <= EPS else str(lot.get("status") or "AKTIF"),
                "updatedAt": time,
            }},
        )
        if result.matched_count == 0:
            raise HTTPException(status_code=409, detail="Lot tumpukan berubah. Muat ulang lalu coba kembali.")
        changes.append({
            "id": lot["id"],
            "oldRemainingQty": available,
            "oldStatus": str(lot.get("status") or "AKTIF"),
            "oldUpdatedAt": lot.get("updatedAt"),
        })
        await db.stack_lot_movements.insert_one({
            "id": new_id(),
            "time": time,
            "loadId": "",
            "lotId": lot["id"],
            "lotCode": lot.get("lotCode", ""),
            "movementType": "PARTNER_EXCESS_WITHDRAWAL",
            "productId": product_id,
            "sku": source.get("sku", ""),
            "product": source.get("product", ""),
            "stackCode": stack_code,
            "sourceDocument": source.get("documentNo", ""),
            "qty": -take,
            "unit": source.get("unit", ""),
            "exp": lot.get("exp", ""),
            "varianceSettlementId": settlement_id,
            "varianceSettlementNo": settlement_no,
        })
        remaining -= take

    if remaining > EPS:
        await db.stack_lot_movements.insert_one({
            "id": new_id(),
            "time": time,
            "loadId": "",
            "lotId": "",
            "lotCode": "",
            "movementType": "PARTNER_EXCESS_WITHDRAWAL_UNTRACKED",
            "productId": product_id,
            "sku": source.get("sku", ""),
            "product": source.get("product", ""),
            "stackCode": stack_code,
            "sourceDocument": source.get("documentNo", ""),
            "qty": -remaining,
            "unit": source.get("unit", ""),
            "varianceSettlementId": settlement_id,
            "varianceSettlementNo": settlement_no,
            "note": "Saldo kelebihan berasal dari stok legacy/belum memiliki lot terlacak",
        })
    return changes


async def _rollback_lot_withdrawal(settlement_id: str, changes: list[dict]) -> None:
    await db.stack_lot_movements.delete_many({"varianceSettlementId": settlement_id})
    for row in reversed(changes):
        update = {
            "remainingQty": row["oldRemainingQty"],
            "status": row["oldStatus"],
        }
        if row.get("oldUpdatedAt") is not None:
            update["updatedAt"] = row["oldUpdatedAt"]
        else:
            update["updatedAt"] = now_iso()
        await db.stack_lots.update_one({"id": row["id"]}, {"$set": update})


@router.get("/partner-variances")
async def list_partner_variances(user: dict = Depends(get_current_user)):
    rows = await _build_sources()
    active_excess = [row for row in rows if row["kind"] == "EXCESS" and row["remainingQty"] > EPS]
    active_shortage = [row for row in rows if row["kind"] == "SHORTAGE" and row["remainingQty"] > EPS]
    return {
        "items": rows,
        "summary": {
            "activeExcessCount": len(active_excess),
            "activeShortageCount": len(active_shortage),
            "activeExcessWeightKg": round(sum(row["remainingWeightKg"] for row in active_excess), 6),
            "activeShortageWeightKg": round(sum(row["remainingWeightKg"] for row in active_shortage), 6),
            "completedCount": sum(1 for row in rows if row["status"] == "SELESAI"),
        },
    }


@router.post("/partner-variances/compensate")
async def compensate_partner_variances(body: PartnerVarianceCompensationInput, user: dict = Depends(require_write)):
    preliminary_excess = await _source_by_key(body.excessKey)
    preliminary_shortage = await _source_by_key(body.shortageKey)
    product_id = preliminary_excess.get("productId", "")
    guard_keys = lock_keys(
        [f"partner-variance:{body.excessKey}", f"partner-variance:{body.shortageKey}"],
        product_lock_keys([product_id]),
    )
    async with operation_guard(guard_keys):
        excess = await _source_by_key(body.excessKey)
        shortage = await _source_by_key(body.shortageKey)
        qty = float(body.qty)

        if excess["kind"] != "EXCESS" or shortage["kind"] != "SHORTAGE":
            raise HTTPException(status_code=400, detail="Kompensasi harus memasangkan satu kelebihan dengan satu kekurangan")
        if excess["supplierKey"] != shortage["supplierKey"]:
            raise HTTPException(status_code=400, detail="Kelebihan dan kekurangan harus berasal dari mitra yang sama")
        if excess["productId"] != shortage["productId"]:
            raise HTTPException(status_code=400, detail="Kelebihan dan kekurangan harus untuk komoditi yang sama")
        if excess["channel"] != shortage["channel"]:
            raise HTTPException(status_code=400, detail="Kelebihan dan kekurangan harus berada pada saluran stok yang sama")
        if qty > excess["remainingQty"] + EPS:
            raise HTTPException(status_code=400, detail=f"Saldo kelebihan hanya {excess['remainingQty']:g} {excess['unit']}")
        if qty > shortage["remainingQty"] + EPS:
            raise HTTPException(status_code=400, detail=f"Sisa kekurangan hanya {shortage['remainingQty']:g} {shortage['unit']}")

        settlement_no = await _new_settlement_no(body.referenceNo)
        time = now_iso()
        weight = _n(excess.get("weightKgPerUnit"))
        doc = {
            "id": new_id(),
            "settlementNo": settlement_no,
            "method": "KOMPENSASI",
            "status": "SELESAI",
            "time": time,
            "operationalDate": operational_now().strftime("%Y-%m-%d"),
            "qty": qty,
            "weightKg": qty * weight,
            "excessKey": excess["key"],
            "shortageKey": shortage["key"],
            "supplier": excess["supplier"],
            "supplierKey": excess["supplierKey"],
            "productId": excess["productId"],
            "sku": excess["sku"],
            "product": excess["product"],
            "unit": excess["unit"],
            "channel": excess["channel"],
            "excessDocumentNo": excess["documentNo"],
            "shortageDocumentNo": shortage["documentNo"],
            "excessLoadNo": excess["loadNo"],
            "shortageLoadNo": shortage["loadNo"],
            "note": str(body.note or "").strip(),
            "operator": user.get("name", ""),
        }
        await db[COLLECTION].insert_one(dict(doc))
        return doc


@router.post("/partner-variances/{source_key}/settle")
async def settle_partner_variance(
    source_key: str,
    body: PartnerVarianceActionInput,
    user: dict = Depends(require_write),
):
    preliminary = await _source_by_key(source_key)
    product_id = preliminary.get("productId", "")
    guard_keys = lock_keys([f"partner-variance:{source_key}"], product_lock_keys([product_id]))

    async with operation_guard(guard_keys):
        source = await _source_by_key(source_key)
        method = str(body.method or "").strip().upper()
        qty = float(body.qty)
        if qty > source["remainingQty"] + EPS:
            raise HTTPException(status_code=400, detail=f"Sisa selisih hanya {source['remainingQty']:g} {source['unit']}")

        if method == "PENGAMBILAN_KELEBIHAN" and source["kind"] != "EXCESS":
            raise HTTPException(status_code=400, detail="Pengambilan mitra hanya berlaku untuk saldo kelebihan")
        if method == "PEMENUHAN_KEKURANGAN" and source["kind"] != "SHORTAGE":
            raise HTTPException(status_code=400, detail="Kiriman susulan hanya berlaku untuk saldo kekurangan")
        if method not in {"PENGAMBILAN_KELEBIHAN", "PEMENUHAN_KEKURANGAN"}:
            raise HTTPException(status_code=400, detail="Metode penyelesaian selisih mitra tidak dikenal")

        product = await db.products.find_one({"id": source["productId"]}, {"_id": 0})
        if not product:
            raise HTTPException(status_code=404, detail="Produk sumber selisih tidak ditemukan")
        product = await ensure_channel_stock(product)
        channel = normalize_channel(source.get("channel"), normalize_channel(product.get("channel")))
        stack_code = str(body.stackCode or source.get("stackCode") or "").strip().upper()
        valid_stacks = await valid_stack_codes()
        if not stack_code or stack_code not in valid_stacks:
            raise HTTPException(status_code=400, detail="Pilih tumpukan fisik yang valid untuk penyelesaian selisih")

        if method == "PENGAMBILAN_KELEBIHAN":
            source_stack = str(source.get("stackCode") or "").strip().upper()
            if source_stack and stack_code != source_stack:
                raise HTTPException(status_code=400, detail=f"Saldo kelebihan terikat ke tumpukan sumber {source_stack}")
            if _n(product.get("stock")) + EPS < qty or channel_balance(product, channel, "stock") + EPS < qty:
                raise HTTPException(status_code=409, detail="Stok baik tidak mencukupi untuk pengambilan kembali kelebihan")
            allocation = await db.stack_allocations.find_one(
                {"productId": source["productId"], "stackCode": stack_code},
                {"_id": 0, "primaryQty": 1},
            )
            if not allocation or _n(allocation.get("primaryQty")) + EPS < qty:
                raise HTTPException(status_code=409, detail=f"Stok tumpukan {stack_code} tidak mencukupi untuk pengambilan kelebihan")

        settlement_no = await _new_settlement_no(body.referenceNo)
        settlement_id = new_id()
        operation_id = new_id()
        transaction_id = new_id()
        op_now = operational_now()
        time = now_iso()
        operator = user.get("name", "")
        weight = _n(source.get("weightKgPerUnit"))
        transaction = {
            "id": transaction_id,
            "operation_id": operation_id,
            "time": time,
            "operational_date": op_now.strftime("%Y-%m-%d"),
            "ref": settlement_no,
            "parent_document": source.get("documentNo", ""),
            "po_no": source.get("poNo", ""),
            "type": "KELUAR" if method == "PENGAMBILAN_KELEBIHAN" else "MASUK",
            "document_type": method,
            "kondisi": "BAIK",
            "product_id": source["productId"],
            "product": source.get("product", ""),
            "sku": source.get("sku", ""),
            "change": -qty if method == "PENGAMBILAN_KELEBIHAN" else qty,
            "good_change": -qty if method == "PENGAMBILAN_KELEBIHAN" else qty,
            "damaged_change": 0,
            "unit": source.get("unit", ""),
            "weight": weight,
            "total_weight": qty * weight,
            "channel": channel,
            "exp": source.get("exp", ""),
            "stackCode": stack_code,
            "receipt_location": stack_code if method == "PEMENUHAN_KEKURANGAN" else "",
            "penerima": source.get("supplier", ""),
            "tujuan": source.get("supplier", "") if method == "PENGAMBILAN_KELEBIHAN" else "",
            "polisi": source.get("polisi", ""),
            "operator": operator,
            "partner_variance_key": source["key"],
            "keterangan": str(body.note or "").strip(),
        }

        product_changed = False
        stack_changed = False
        transaction_inserted = False
        lot_changes: list[dict] = []
        receipt_lot_created = False

        try:
            delta = -qty if method == "PENGAMBILAN_KELEBIHAN" else qty
            result = await db.products.update_one(
                {"id": source["productId"]},
                {"$inc": {
                    "stock": delta,
                    f"channelStock.{channel}.stock": delta,
                }},
            )
            if result.matched_count == 0:
                raise HTTPException(status_code=409, detail="Master produk berubah. Muat ulang lalu coba kembali.")
            product_changed = True

            if method == "PENGAMBILAN_KELEBIHAN":
                await decrease_stack_allocation(source["productId"], stack_code, qty, operator)
                stack_changed = True
                lot_changes = await _consume_lots_for_partner_withdrawal(
                    source["productId"], stack_code, qty, settlement_id, settlement_no, source
                )
            else:
                refreshed_product = await db.products.find_one({"id": source["productId"]}, {"_id": 0}) or product
                await allocate_stock_to_stack(refreshed_product, stack_code, qty, operator)
                stack_changed = True

            await db.transactions.insert_one(dict(transaction))
            transaction_inserted = True

            if method == "PEMENUHAN_KEKURANGAN":
                await record_receipt_lots(None, {"transactions": [transaction]})
                receipt_lot_created = True

            settlement = {
                "id": settlement_id,
                "settlementNo": settlement_no,
                "method": method,
                "status": "SELESAI",
                "time": time,
                "operationalDate": op_now.strftime("%Y-%m-%d"),
                "qty": qty,
                "weightKg": qty * weight,
                "excessKey": source["key"] if source["kind"] == "EXCESS" else "",
                "shortageKey": source["key"] if source["kind"] == "SHORTAGE" else "",
                "supplier": source["supplier"],
                "supplierKey": source["supplierKey"],
                "productId": source["productId"],
                "sku": source["sku"],
                "product": source["product"],
                "unit": source["unit"],
                "channel": channel,
                "stackCode": stack_code,
                "sourceDocumentNo": source["documentNo"],
                "sourceLoadNo": source["loadNo"],
                "sourcePolisi": source["polisi"],
                "transactionId": transaction_id,
                "operationId": operation_id,
                "note": str(body.note or "").strip(),
                "operator": operator,
            }
            await db[COLLECTION].insert_one(dict(settlement))
            return settlement
        except Exception:
            if receipt_lot_created:
                await db.stack_lots.delete_many({"sourceTransactionId": transaction_id})
            if transaction_inserted:
                await db.transactions.delete_one({"id": transaction_id})
            if method == "PENGAMBILAN_KELEBIHAN":
                if lot_changes:
                    await _rollback_lot_withdrawal(settlement_id, lot_changes)
                if stack_changed:
                    rollback_product = await db.products.find_one({"id": source["productId"]}, {"_id": 0}) or product
                    rollback_product["stock"] = _n(rollback_product.get("stock")) + qty
                    await allocate_stock_to_stack(rollback_product, stack_code, qty, "Sistem (rollback selisih mitra)")
            elif stack_changed:
                await decrease_stack_allocation(source["productId"], stack_code, qty, "Sistem (rollback selisih mitra)")
            if product_changed:
                rollback_delta = qty if method == "PENGAMBILAN_KELEBIHAN" else -qty
                await db.products.update_one(
                    {"id": source["productId"]},
                    {"$inc": {
                        "stock": rollback_delta,
                        f"channelStock.{channel}.stock": rollback_delta,
                    }},
                )
            raise
