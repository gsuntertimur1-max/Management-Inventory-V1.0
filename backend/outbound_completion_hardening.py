from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request

from backend.server import db, now_iso, require_write
from backend.outbound_flow import complete_outbound_load
from backend.operational_guards import (
    _load_product_ids,
    _tag_load_transaction_product_ids,
    idempotent_operation,
    product_lock_keys,
    surat_jalan_with_exact_locations,
)
import backend.fefo_conservative as fefo_conservative
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


@router.post("/outbound-loads/{load_id}/complete")
async def hardened_complete_outbound(load_id: str, request: Request, user: dict = Depends(require_write)):
    _, product_ids = await _load_product_ids(load_id)

    async def action():
        # Core stock/document mutation remains authoritative and rollback-capable.
        result = await complete_outbound_load(load_id, user)
        load = result.get("load") or await db.outbound_loads.find_one({"id": load_id}, {"_id": 0}) or {}
        warnings = []

        # Metadata enrichment must never turn a committed outbound into a false API failure.
        try:
            await _tag_load_transaction_product_ids(load_id, load)
            await _resolve_issue(load_id, "TRANSACTION_METADATA")
        except Exception as exc:
            logger.exception("Outbound %s selesai tetapi tagging transaksi gagal", load_id)
            await _record_issue(load_id, "TRANSACTION_METADATA", exc)
            warnings.append("Metadata transaksi belum lengkap dan masuk antrean perbaikan integritas.")

        try:
            sj = surat_jalan_with_exact_locations(load, result.get("suratJalan"))
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

        try:
            fefo = await consume_stack_lots_conservative(load)
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
                }},
            )
            if result.get("load"):
                result["load"].update({
                    "fefo_tracked_qty": fefo.get("tracked", 0),
                    "fefo_untracked_qty": fefo.get("untracked", 0),
                    "fefo_legacy_protected_qty": fefo.get("legacyProtected", 0),
                    "fefo_policy": fefo.get("policy", "CONSERVATIVE_LEGACY_FIRST"),
                    "fefo_sync_status": "SYNCED",
                })
            await _resolve_issue(load_id, "FEFO_SYNC")
        except Exception as exc:
            logger.exception("Outbound %s selesai tetapi sinkronisasi FEFO gagal", load_id)
            await db.outbound_loads.update_one(
                {"id": load_id},
                {"$set": {"fefo_sync_status": "REPAIR_REQUIRED", "fefo_sync_error": str(exc)[:500]}},
            )
            await _record_issue(load_id, "FEFO_SYNC", exc)
            warnings.append("FEFO belum tersinkron. Stok outbound tetap sah; Kontrol Integritas menandai kebutuhan repair.")

        if warnings:
            result["postCommitWarnings"] = warnings
        return result

    return await idempotent_operation(
        request,
        user,
        f"outbound-complete:{load_id}",
        product_lock_keys(product_ids),
        action,
    )
