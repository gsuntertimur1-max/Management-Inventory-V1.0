from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.server import db, now_iso, require_admin, require_write
from backend.outbound_flow import complete_outbound_load
from backend.operational_guards import (
    _load_product_ids,
    _tag_load_transaction_product_ids,
    idempotent_operation,
    operation_guard,
    product_lock_keys,
    surat_jalan_with_exact_locations,
)
import backend.fefo_conservative as fefo_conservative
import backend.consignment as consignment_module
from backend.fefo_atomic import consume_tracked_fefo_atomic

fefo_conservative._consume_tracked_fefo = consume_tracked_fefo_atomic
consume_stack_lots_conservative = fefo_conservative.consume_stack_lots_conservative

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)


async def _record_issue(load_id: str, stage: str, exc: Exception) -> None:
    """Persist a repairable post-commit issue without ever masking a successful stock mutation."""
    try:
        issue_id = f"outbound-complete:{load_id}:{stage}"
        await db.operational_postcommit_issues.update_one(
            {"id": issue_id},
            {"$set": {
                "id": issue_id,
                "loadId": load_id,
                "operation": "OUTBOUND_COMPLETE",
                "stage": stage,
                "status": "OPEN",
                "message": str(exc)[:1000],
                "updatedAt": now_iso(),
            }, "$setOnInsert": {"createdAt": now_iso()}},
            upsert=True,
        )
    except Exception:
        logger.exception("Gagal mencatat post-commit issue %s untuk load %s", stage, load_id)


async def _resolve_issue(load_id: str, stage: str) -> None:
    try:
        await db.operational_postcommit_issues.update_one(
            {"id": f"outbound-complete:{load_id}:{stage}", "status": "OPEN"},
            {"$set": {"status": "RESOLVED", "resolvedAt": now_iso(), "updatedAt": now_iso()}},
        )
    except Exception:
        logger.exception("Gagal menutup post-commit issue %s untuk load %s", stage, load_id)


async def _enrich_completed_outbound(load_id: str, load: dict, surat_jalan: dict | None = None, *, products_locked: bool = False) -> dict:
    warnings = []
    result: dict = {}

    try:
        await _tag_load_transaction_product_ids(load_id, load)
        await _resolve_issue(load_id, "TRANSACTION_METADATA")
    except Exception as exc:
        logger.exception("Outbound %s selesai tetapi tagging transaksi gagal", load_id)
        await _record_issue(load_id, "TRANSACTION_METADATA", exc)
        warnings.append("Metadata transaksi belum lengkap dan masuk antrean perbaikan integritas.")

    try:
        sj_source = surat_jalan
        if not sj_source:
            sj_id = str(load.get("surat_jalan_id") or "")
            if sj_id:
                sj_source = await db.surat_jalan.find_one({"id": sj_id}, {"_id": 0})
            if not sj_source:
                sj_source = await db.surat_jalan.find_one({"load_id": load_id}, {"_id": 0})
        sj = surat_jalan_with_exact_locations(load, sj_source)
        if sj and sj.get("id"):
            await db.surat_jalan.update_one(
                {"id": sj["id"]},
                {"$set": {"items": sj.get("items", []), "unit_loading": sj.get("unit_loading", "")}},
            )
            result["suratJalan"] = sj
        await _resolve_issue(load_id, "SURAT_JALAN_LOCATION")
    except Exception as exc:
        logger.exception("Outbound %s selesai tetapi enrichment Surat Jalan gagal", load_id)
        await _record_issue(load_id, "SURAT_JALAN_LOCATION", exc)
        warnings.append("Lokasi detail Surat Jalan belum tersinkron dan masuk antrean perbaikan integritas.")

    destination = str(load.get("consignment_destination") or "").strip()
    if destination in consignment_module.DESTINATIONS:
        try:
            product_ids = sorted({
                str(item.get("productId") or "")
                for item in (load.get("items") or [])
                if str(item.get("productId") or "")
            })
            preferred_stack = str(load.get("consignment_zone") or "")
            operator = str(load.get("completed_by") or load.get("created_by") or "Sistem")
            sync_rows = []
            for product_id in product_ids:
                sync_rows.append(await consignment_module.sync_consignment_layout_balance(
                    destination,
                    product_id,
                    operator=operator,
                    preferred_stack=preferred_stack,
                    operation_key=f"main-consignment-inbound:{load_id}:{product_id}",
                    note="Penempatan otomatis setelah barang selesai dimuat dari Gudang Utama.",
                ))
            result["consignmentLayoutSync"] = sync_rows
            await _resolve_issue(load_id, "CONSIGNMENT_LAYOUT_SYNC")
        except Exception as exc:
            logger.exception("Outbound %s selesai tetapi lokasi Bazar/E-commerce belum sinkron", load_id)
            await _record_issue(load_id, "CONSIGNMENT_LAYOUT_SYNC", exc)
            warnings.append("Saldo Bazar/E-commerce sudah bertambah, tetapi lokasi fisiknya perlu sinkronisasi ulang.")

    try:
        fefo = await consume_stack_lots_conservative(load, lock_products=not products_locked)
        result["fefo"] = fefo
        await db.outbound_loads.update_one(
            {"id": load_id},
            {"$set": {
                "fefo_tracked_qty": fefo.get("tracked", 0),
                "fefo_untracked_qty": fefo.get("untracked", 0),
                "fefo_legacy_protected_qty": fefo.get("legacyProtected", 0),
                "fefo_policy": fefo.get("policy", "CONSERVATIVE_LEGACY_FIRST"),
                "fefo_sync_status": "SYNCED",
                "fefo_synced_at": now_iso(),
                "fefo_sync_error": "",
            }},
        )
        await _resolve_issue(load_id, "FEFO_SYNC")
    except Exception as exc:
        logger.exception("Outbound %s selesai tetapi sinkronisasi FEFO gagal", load_id)
        try:
            await db.outbound_loads.update_one(
                {"id": load_id},
                {"$set": {"fefo_sync_status": "REPAIR_REQUIRED", "fefo_sync_error": str(exc)[:500]}},
            )
        except Exception:
            logger.exception("Gagal menandai FEFO repair required untuk %s", load_id)
        await _record_issue(load_id, "FEFO_SYNC", exc)
        warnings.append("FEFO belum tersinkron. Stok outbound tetap sah; Kontrol Integritas menandai kebutuhan repair.")

    if warnings:
        result["postCommitWarnings"] = warnings
    return result


@router.post("/outbound-loads/{load_id}/complete")
async def hardened_complete_outbound(load_id: str, request: Request, user: dict = Depends(require_write)):
    _, product_ids = await _load_product_ids(load_id)

    async def action():
        # Core stock/document mutation remains authoritative and rollback-capable.
        result = await complete_outbound_load(load_id, user)
        load = result.get("load") or await db.outbound_loads.find_one({"id": load_id}, {"_id": 0}) or {}
        enrichment = await _enrich_completed_outbound(load_id, load, result.get("suratJalan"), products_locked=True)
        result.update(enrichment)
        if result.get("load") and enrichment.get("fefo"):
            fefo = enrichment["fefo"]
            result["load"].update({
                "fefo_tracked_qty": fefo.get("tracked", 0),
                "fefo_untracked_qty": fefo.get("untracked", 0),
                "fefo_legacy_protected_qty": fefo.get("legacyProtected", 0),
                "fefo_policy": fefo.get("policy", "CONSERVATIVE_LEGACY_FIRST"),
                "fefo_sync_status": "SYNCED",
            })
        return result

    return await idempotent_operation(
        request,
        user,
        f"outbound-complete:{load_id}",
        product_lock_keys(product_ids),
        action,
    )


@router.post("/outbound-loads/{load_id}/repair-completion")
async def repair_completed_outbound(load_id: str, user: dict = Depends(require_admin)):
    load, product_ids = await _load_product_ids(load_id)
    if str(load.get("status") or "") != "Selesai":
        raise HTTPException(status_code=400, detail="Repair completion hanya untuk pemuatan yang sudah berstatus Selesai")

    async with operation_guard(product_lock_keys(product_ids) + [f"outbound-repair:{load_id}"]):
        current = await db.outbound_loads.find_one({"id": load_id}, {"_id": 0}) or load
        enrichment = await _enrich_completed_outbound(load_id, current, products_locked=True)
        open_issues = await db.operational_postcommit_issues.find(
            {"loadId": load_id, "operation": "OUTBOUND_COMPLETE", "status": "OPEN"},
            {"_id": 0},
        ).to_list(20)
        return {
            "loadId": load_id,
            "status": "REPAIRED" if not open_issues else "PARTIAL",
            "postCommitWarnings": enrichment.get("postCommitWarnings", []),
            "fefo": enrichment.get("fefo"),
            "suratJalan": enrichment.get("suratJalan"),
            "openIssues": open_issues,
            "stockPhysicalChanged": False,
        }
