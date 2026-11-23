from __future__ import annotations

import base64
import json
import zlib

from backend.server import db, now_iso
from backend.move_in_flow import (
    MoveInDocumentAllocationInput,
    MoveInItemInput,
    MoveInPlottingInput,
    add_move_in_document_allocation,
    create_move_in_plotting,
)
from backend.inbound_vehicle_flow import (
    InboundCompleteItem,
    InboundLoadComplete,
    InboundLoadCreate,
    InboundPlanItem,
    InboundStartInput,
    complete_inbound_load,
    create_inbound_load,
    start_inbound_load,
)

MARKER = "historical-inbound-b0010152z-20261123-v1"
PRODUCT_SKU = "B0010152Z"
PAYLOAD_B64 = "eNrtnFtz2jgYhv+Khut2o4N1yp1TToaYEmPaJTu9YAKbMs1CJiGd7nT631cGygYZKlsYYlJdtRbEyI+kT+/3Stb3yv3DbPR0M+99eaqcVy4gRBBRfF15U7m/m80fK+d/fa8M7yZD9b9Kt1V7Cz2EMMRMfWE0nI9VaXL1FiH1iSp7HE9H4wdV+u4D6PrVALT8gQ9qod9b3HE4nY5HV/N/K+eIMEb/gOovbmb3yW2iWjd636sl35v/05mpkjg8IxRx7wyhs+RHzqBU1VOffx1/ntzcjZeVm6qvou2VuZ/dTR4nyZ2AwNID1WpS64fJ10UN+73Q72i1kggldbqdzTauR8N/hrfjUf3p7m5RDJ8Vdoc3X9S/72ZP07n6ZF3u38yfhncfx5Pbz/P27epvvg4fJsPpzTgaDx9nU1UJ9cB9P6j8/Kt1eYJyru78bjZaPBY5u1g80vjb/fIp+fopbx9mj4/L31Ek1M/gVVk4mWoFw2/rAnX3B/X9ChTnBJ5DmNx7OkoK5Lrg7/E4XP5+t9ZpBFEQqsLpbAG68uPNkj02spcYC1C9cOwLZ08M7GtAIMzBZc2xL5y9Z2B/ofq9FCAOPjr4hcOn5oAPGQS1umNfOHtmDvheEvADx75w9tzAvgqEJAzUnNApnr3IEvClC/gHgS/NAd+TEHRCx75w9gia4XMKwXXDwS8efobcViIMqk0Hv3j42BzzqYIfd31Hv3j6xNz1ERSg4br+AeB7ZviEKplvEfThYeG3+5HfaYD26slOtwkyZLkMEtB0LVB0C3xK2uCn7d3pt4K3aKfvjXTfO/k+qPq9MOj4zYUBrrUH5pLBDN43pcLG+0b6FMUQAe3B9fNu4rcCrVKEQrjRS34WlDVKolKa3yn4nHigN7g0wCc6fOLg53e/U/AxFyoKxb+G70EdvpQiH3y8Ez6iuei3/GYQ+x1wWesulsxOpCk8c1MIItQ4CPOOA1xgU5DfoSlohvkgGRWDOP984B02JF3WLoLmfqoBldIgT8clykF9MMgZl1QBci1gZZOnwxHFKhy1TeGI6dMyk64FrMzydBSCPIMq1ceAmg9w+ZMXVLLkhe5MXmje5AV5HhRZkhdpl7xQ3V8TAoSGSIlTvQSWXD7TUuYuKfZKs2ne5hb4fNkf/oe/KnDwc+UuOnxIksXEniE+cl2lcdfzLbIVHb7ETE1OH/ILtJzw6U74RObXBzYpCy1lypKKRNIzi4XUNICkJC8pFk6tPbYoB7ZTObDcykESkUU5MA9ZKQemJ1mMgOsr/7VJB1ZK6aDDZ4RaDFgH30o6pHo+pWZ7gaxG47PkVggHP7d00OEjys2es+v5xegEHT7FiU7oH1y3/X7wmRm+ytVBb9BxPf8Yhmaq53NsnnC39XxSfkOTlUsT852amOfeCuDB5bKUSRMLaqWJudUqHE6twpV8iPJSamIdPuTYHB9PbysAL6Um1uFzlmXRky9H4zM7DREHP7cm5narba7nF6GJuY2LX8DOi5f3zngpZbLeHh5jajC8z+9lnsCuzTI0ATc0QRVIIjzg110LHG/1n1tti0wJUSSka4Ls+UrUjTJb+N0YRMF1ewC6/TjyQeS39GRFUsSyrPwztr9/n7zWRPUX+vzqwlfbWFRIjdKTsxOW9V93jWeXScdYbhQ/lnOfvFLAEIgjhx0e0bNPXqaBWHuZxmE/tFsfK3EMJajWHXZ4XJ9eqOm/ETjs8LgOPZFp+y/NPbXpkjjue5jzNSAol6Dbtuju9ATN+aOwT8tcsVPmipwyl8EsJ9NxhK1krtBDIZPg+r2hb5zeqpkomcwVGSzJLaHw5N6KFCXTuSK1s1KAWNtZ6bgXL3SFNgWxLFPQKvKtqTN4Aq+7iJefgHphO89WyV7Q8SMQ+p2quito+5H/0e807NwWBnkBuyVVB8GIgKuN/hH2t1Rqc1iurp0wtDNbFuvxjZajflyvBVOonZHnqB/YaqkB6am+3nTUj+m01JMTkhjodx31IxotyZHX3AOx76gf1WaRCHngylGHh13KTVGH2FEvlro0UycQgYGZOmOb1JfXjnrGg05T0pFyBpr5BbvHTmDbAitJIi13JtLSKpHO6ufabVuQdpOQdrLI6rq0A1OWLJGWdpOQo75XIi11mZstkXbU90qkN6hHq5Su7qgfNpGWdjO/o75XIi3tEmlHfa9EWtpZdY76Xom0tFsMcNT3SqSl3cKXo75fIq1Pp4xD4GvHW23lTjXu1HH/dQ4dt/KsRcdBw9/2ZnLmzf6ikM3+DHPQuTRsT1hVad0ZVtfOzbJZfVaRD6oJ58ptfj7q8vP2t89ew46/Uq8/JwfzSArCqsN+5K3+3uJInj8N3F/BmTwvM9NnN8t3zvRZ/XFvf3/8Fb+DUGqHPDmRD4vUAUGO+4E98sXRpSQLd33rLWEIl3/v7UulO59+/AeNYAVM"

KNOWN_PLOTS = {
    "PJE-04112026": "6530d2c8bd604c5fa3563aa6ba1f5d49",
    "NUJI-16112026": "d2d65097211441e3aedd267a36d6e85a",
}

SYSTEM_USER = {
    "id": "system-historical-import-20261123",
    "username": "system-historical-import",
    "name": "Import Excel 23-11-2026",
    "role": "Superadmin",
}


def _payload() -> dict:
    return json.loads(zlib.decompress(base64.b64decode(PAYLOAD_B64)).decode("utf-8"))


def _doc_total(vehicle: dict) -> float:
    return (
        float(vehicle.get("goodQty", 0) or 0)
        + float(vehicle.get("damagedFullQty", 0) or 0)
        + float(vehicle.get("damagedPackageCount", 0) or 0)
    )


def _target_load_no(plot: dict, vehicle: dict) -> str:
    date_key = str(vehicle["date"]).replace("-", "")
    prefix = str(plot["alias"]).split("-", 1)[0].upper()[:6]
    return f"PB-MIG-{date_key}-{prefix}{int(vehicle['no']):02d}"


async def _find_or_create_plot(plot: dict, product: dict) -> dict:
    alias = plot["alias"]
    existing = await db.move_in_plottings.find_one({"historicalImportAlias": alias}, {"_id": 0})
    if not existing and alias in KNOWN_PLOTS:
        existing = await db.move_in_plottings.find_one({"id": KNOWN_PLOTS[alias]}, {"_id": 0})
    if not existing:
        existing = await create_move_in_plotting(
            MoveInPlottingInput(
                plottingDate=plot["date"],
                scope=plot["scope"],
                senderType="MITRA",
                senderName=plot["sender"],
                items=[MoveInItemInput(productId=product["id"], qty=float(plot["plannedQty"]))],
                note=f"Import historis Excel 23-11-2026 · {alias}",
            ),
            SYSTEM_USER,
        )

    planned = float(plot["plannedQty"])
    actual_doc = sum(_doc_total(v) for v in plot["vehicles"])
    hidden_capacity = max(planned, actual_doc)
    item = {
        "productId": product["id"],
        "sku": product.get("sku", ""),
        "name": product.get("name", ""),
        "qty": planned,
        "unit": product.get("unit", ""),
        "weight": float(product.get("weight", 0) or 0),
        "secondary": product.get("secondary", ""),
        "secondaryQty": float(product.get("secondaryQty", 0) or 0),
        "channel": product.get("channel", "PSO"),
    }
    await db.move_in_plottings.update_one(
        {"id": existing["id"]},
        {"$set": {
            "plottingDate": plot["date"],
            "scope": plot["scope"],
            "senderType": "MITRA",
            "senderName": plot["sender"],
            "items": [item],
            "historicalImportAlias": alias,
            "historicalImportSource": MARKER,
            "updatedAt": now_iso(),
        }},
    )

    po_id = str(existing.get("poId") or "")
    if not po_id:
        refreshed = await db.move_in_plottings.find_one({"id": existing["id"]}, {"_id": 0}) or existing
        po_id = str(refreshed.get("poId") or "")
    await db.purchase_orders.update_one(
        {"id": po_id},
        {"$set": {
            "supplier": plot["sender"],
            "date": f"{plot['date']}T00:00:00+07:00",
            "sourceType": "MOVE_IN",
            "moveInPlottingId": existing["id"],
            "moveInScope": plot["scope"],
            "moveInSenderType": "MITRA",
            "items.0.productId": product["id"],
            "items.0.sku": product.get("sku", ""),
            "items.0.name": product.get("name", ""),
            "items.0.qty": hidden_capacity,
            "items.0.unit": product.get("unit", ""),
            "items.0.weight": float(product.get("weight", 0) or 0),
            "items.0.secondary": product.get("secondary", ""),
            "items.0.secondaryQty": float(product.get("secondaryQty", 0) or 0),
            "items.0.channel": product.get("channel", "PSO"),
        }},
    )

    if alias == "NUJI-16112026":
        legacy_loads = await db.inbound_loads.find(
            {
                "moveInPlottingId": existing["id"],
                "status": {"$in": ["Menunggu Bongkar", "Sedang Bongkar"]},
                "legacyMoveInReceiptId": {"$exists": True},
            },
            {"_id": 0, "id": 1},
        ).to_list(100)
        legacy_ids = [x.get("id") for x in legacy_loads if x.get("id")]
        if legacy_ids:
            await db.unloading_sessions.delete_many({"inboundLoadId": {"$in": legacy_ids}})
            await db.inbound_loads.delete_many({"id": {"$in": legacy_ids}})
        await db.move_in_plottings.update_one(
            {"id": existing["id"]},
            {"$set": {"receipts": [], "updatedAt": now_iso()}},
        )

    refreshed = await db.move_in_plottings.find_one({"id": existing["id"]}, {"_id": 0})
    return refreshed or existing


async def _link_tm(plot_doc: dict, plot: dict, product: dict) -> None:
    tm_no = str(plot.get("tmNo") or "").strip().upper()
    if not tm_no:
        return
    existing = any(
        str(x.get("documentType") or "").upper() == "TM"
        and str(x.get("documentNo") or "").strip().upper() == tm_no
        for x in plot_doc.get("documentAllocations", [])
    )
    if existing:
        return
    await add_move_in_document_allocation(
        plot_doc["id"],
        MoveInDocumentAllocationInput(
            documentType="TM",
            documentNo=tm_no,
            documentDate="",
            productId=product["id"],
            qty=float(plot["plannedQty"]),
            note="Import historis dari Excel 23-11-2026; nomor MO belum dicantumkan pada file sumber.",
        ),
        SYSTEM_USER,
    )


async def _import_vehicle(plot_doc: dict, plot: dict, vehicle: dict, product: dict) -> bool:
    key = f"{MARKER}:{plot['alias']}:{int(vehicle['no']):03d}"
    target_no = _target_load_no(plot, vehicle)
    load = await db.inbound_loads.find_one(
        {"$or": [{"historicalImportKey": key}, {"loadNo": target_no}]},
        {"_id": 0},
    )
    if load and load.get("status") == "Selesai":
        return False

    if not load:
        weighing = all(float(vehicle.get(k, 0) or 0) > 0 for k in ("grossWeight", "grossMin", "grossMax"))
        body = InboundLoadCreate(
            poId=str(plot_doc.get("poId") or ""),
            items=[InboundPlanItem(
                productId=product["id"],
                qty=float(vehicle["plannedQty"]),
                stackCode=vehicle.get("stackCode", ""),
                exp=vehicle.get("exp", ""),
                channel=product.get("channel", "PSO"),
            )],
            polisi=vehicle["polisi"],
            driver=vehicle.get("driver", ""),
            keterangan=f"IMPORT-HIST-20261123 {key}",
            weighingForm=weighing,
            grossWeight=float(vehicle.get("grossWeight", 0) or 0) if weighing else 0,
            grossMin=float(vehicle.get("grossMin", 0) or 0) if weighing else 0,
            grossMax=float(vehicle.get("grossMax", 0) or 0) if weighing else 0,
            unloadingFeeChargeMode=vehicle.get("feeMode", "PENGIRIM"),
        )
        load = await create_inbound_load(body, SYSTEM_USER)
        start_stamp = f"{vehicle['date']}T{vehicle['start']}+07:00"
        await db.inbound_loads.update_one(
            {"id": load["id"]},
            {"$set": {
                "loadNo": target_no,
                "historicalImportKey": key,
                "historicalImportAlias": plot["alias"],
                "historicalImportSource": MARKER,
                "createdAt": start_stamp,
            }},
        )
        load = await db.inbound_loads.find_one({"id": load["id"]}, {"_id": 0}) or load

    if load.get("status") == "Menunggu Bongkar":
        await start_inbound_load(
            load["id"],
            InboundStartInput(
                actualStartAt=f"{vehicle['date']}T{vehicle['start']}",
                reason="Import historis dari Excel 23-11-2026",
            ),
            SYSTEM_USER,
        )
        load = await db.inbound_loads.find_one({"id": load["id"]}, {"_id": 0}) or load

    if load.get("status") == "Sedang Bongkar":
        doc_total = _doc_total(vehicle)
        variance = doc_total - float(vehicle.get("plannedQty", 0) or 0)
        discrepancy_reason = str(vehicle.get("varianceReason") or "").strip()
        if abs(variance) > 1e-9 and len(discrepancy_reason) < 3:
            discrepancy_reason = "KURANG KIRIM" if variance < 0 else "LEBIH KIRIM"
        damage_reason = str(vehicle.get("damageReason") or "").strip()
        if int(vehicle.get("damagedPackageCount", 0) or 0) > 0 and len(damage_reason) < 3:
            damage_reason = "BS / kemasan rusak kurang timbang"

        await complete_inbound_load(
            load["id"],
            InboundLoadComplete(
                items=[InboundCompleteItem(
                    productId=product["id"],
                    goodQty=float(vehicle.get("goodQty", 0) or 0),
                    damagedQty=float(vehicle.get("damagedFullQty", 0) or 0),
                    damagedPackageCount=int(vehicle.get("damagedPackageCount", 0) or 0),
                    damagedActualWeightKg=float(vehicle.get("damagedActualWeightKg", 0) or 0),
                    shortageClaimReason=damage_reason,
                    discrepancyReason=discrepancy_reason,
                    overtimeQty=None,
                    stackCode=vehicle.get("stackCode", ""),
                    exp=vehicle.get("exp", ""),
                    channel=product.get("channel", "PSO"),
                )],
                note=f"Import historis Excel · {plot['alias']} · Mobil {int(vehicle['no'])}",
                actualCompletedAt=f"{vehicle['date']}T{vehicle['end']}",
                actualCompletionReason="Import historis dari Excel 23-11-2026",
            ),
            SYSTEM_USER,
        )
        await db.inbound_loads.update_one(
            {"id": load["id"]},
            {"$set": {
                "historicalImportKey": key,
                "historicalImportAlias": plot["alias"],
                "historicalImportSource": MARKER,
            }},
        )
        return True

    return False


async def run_historical_inbound_import_20261123() -> None:
    if await db.migration_markers.find_one({"_id": MARKER}, {"_id": 1}):
        return

    payload = _payload()
    product = await db.products.find_one({"sku": PRODUCT_SKU}, {"_id": 0})
    if not product:
        raise RuntimeError(f"Produk {PRODUCT_SKU} tidak ditemukan")

    completed = 0
    total_good = 0.0
    total_damaged_equiv = 0.0
    total_claim_kg = 0.0
    aliases = []

    for plot in payload["plots"]:
        plot_doc = await _find_or_create_plot(plot, product)
        await _link_tm(plot_doc, plot, product)
        aliases.append(plot["alias"])
        for vehicle in sorted(plot["vehicles"], key=lambda x: int(x["no"])):
            if await _import_vehicle(plot_doc, plot, vehicle, product):
                completed += 1
            total_good += float(vehicle.get("goodQty", 0) or 0)
            total_damaged_equiv += float(vehicle.get("damagedFullQty", 0) or 0)
            if int(vehicle.get("damagedPackageCount", 0) or 0) > 0:
                total_damaged_equiv += float(vehicle.get("damagedActualWeightKg", 0) or 0) / float(product.get("weight", 10) or 10)
                total_claim_kg += max(
                    int(vehicle.get("damagedPackageCount", 0) or 0) * float(product.get("weight", 10) or 10)
                    - float(vehicle.get("damagedActualWeightKg", 0) or 0),
                    0.0,
                )

    await db.migration_markers.update_one(
        {"_id": MARKER},
        {"$set": {
            "completedAt": now_iso(),
            "source": "template_import_massal_B0010152Z_v3_fix_validasi(1).xlsx",
            "productSku": PRODUCT_SKU,
            "plottingAliases": aliases,
            "plottingCount": len(payload["plots"]),
            "vehicleCount": sum(len(x["vehicles"]) for x in payload["plots"]),
            "newlyCompletedInFinalRun": completed,
            "expectedGoodQty": round(total_good, 6),
            "expectedDamagedEquivalentQty": round(total_damaged_equiv, 6),
            "expectedShortageClaimKg": round(total_claim_kg, 6),
        }},
        upsert=True,
    )
