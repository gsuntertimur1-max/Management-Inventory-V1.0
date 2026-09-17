from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request

from backend.server import db, require_write
from backend.outbound_flow import (
    ConsignmentReturnInput,
    SalesReturnInput,
    SettlementInput,
    create_consignment_return,
    create_sales_return,
    settle_outbound_document,
)
from backend.operational_guards import (
    document_lock_keys,
    idempotent_operation,
    lock_keys,
    product_lock_keys,
)
from backend.return_lot_tracking import record_return_untracked_movements

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)


def _load_lock(load_id: str) -> list[str]:
    return [f"outbound-document:{str(load_id or '').strip()}"]


async def _tag_document_transactions(load_id: str, document_no: str, document_type: str, items: list[dict]) -> None:
    """Attach stable product/location metadata to return/settlement audit rows."""
    for item in items:
        product_id = str(item.get("productId") or "")
        product_name = str(item.get("name") or "")
        if not product_id:
            continue
        patch = {"product_id": product_id}
        placements = list(item.get("placements") or [])
        if placements:
            patch["placements"] = placements
            if len(placements) == 1:
                patch["stackCode"] = str(placements[0].get("stackCode") or "").strip().upper()
        elif item.get("stackCode"):
            patch["stackCode"] = str(item.get("stackCode") or "").strip().upper()
        query = {
            "load_id": load_id,
            "ref": document_no,
            "document_type": document_type,
        }
        if product_name:
            query["product"] = product_name
        await db.transactions.update_many(query, {"$set": patch})


async def _safe_post_commit_audit(load_id: str, link: dict, document_type: str, track_return_lots: bool) -> None:
    """Enrich audit data without turning a committed stock mutation into an apparent failure.

    The stock/document mutation has already committed when this helper runs.  Any enrichment
    error is logged and left for integrity control/reconciliation instead of being surfaced as
    a failed return that an operator might retry.
    """
    try:
        await _tag_document_transactions(
            load_id,
            str(link.get("no") or ""),
            document_type,
            list(link.get("items") or []),
        )
        if track_return_lots:
            await record_return_untracked_movements(load_id, link)
    except Exception:
        logger.exception("Post-commit document audit enrichment failed for load %s document %s", load_id, link.get("no"))


@router.post("/outbound-loads/{load_id}/return")
async def guarded_consignment_return_document(
    load_id: str,
    body: ConsignmentReturnInput,
    request: Request,
    user: dict = Depends(require_write),
):
    document_no = body.documentNo.strip()
    source_no = body.sourceDocumentNo.strip()
    keys = lock_keys(
        _load_lock(load_id),
        product_lock_keys(item.productId for item in body.items),
        document_lock_keys([document_no, source_no]),
    )

    async def action():
        link = await create_consignment_return(load_id, body, user)
        await _safe_post_commit_audit(load_id, link, str(link.get("type") or body.returnType), True)
        return link

    return await idempotent_operation(request, user, f"outbound-return:{load_id}", keys, action)


@router.post("/outbound-loads/{load_id}/sales-return")
async def guarded_sales_return_document(
    load_id: str,
    body: SalesReturnInput,
    request: Request,
    user: dict = Depends(require_write),
):
    document_no = body.documentNo.strip()
    source_no = body.sourceDocumentNo.strip()
    keys = lock_keys(
        _load_lock(load_id),
        product_lock_keys(item.productId for item in body.items),
        document_lock_keys([document_no, source_no]),
    )

    async def action():
        link = await create_sales_return(load_id, body, user)
        await _safe_post_commit_audit(load_id, link, "SO_RETUR", True)
        return link

    return await idempotent_operation(request, user, f"sales-return:{load_id}", keys, action)


@router.post("/outbound-loads/{load_id}/settle")
async def guarded_settle_outbound_document(
    load_id: str,
    body: SettlementInput,
    request: Request,
    user: dict = Depends(require_write),
):
    document_no = body.documentNo.strip()
    source_no = body.sourceDocumentNo.strip()
    keys = lock_keys(
        _load_lock(load_id),
        product_lock_keys(item.productId for item in body.items),
        document_lock_keys([document_no, source_no]),
    )

    async def action():
        link = await settle_outbound_document(load_id, body, user)
        await _safe_post_commit_audit(load_id, link, "SO", False)
        return link

    return await idempotent_operation(request, user, f"outbound-settle:{load_id}", keys, action)
