from __future__ import annotations

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

router = APIRouter(prefix="/api")


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
        await _tag_document_transactions(load_id, link.get("no", document_no), link.get("type", body.returnType), link.get("items", []))
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
        await _tag_document_transactions(load_id, link.get("no", document_no), "SO_RETUR", link.get("items", []))
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
        await _tag_document_transactions(load_id, link.get("no", document_no), "SO", link.get("items", []))
        return link

    return await idempotent_operation(request, user, f"outbound-settle:{load_id}", keys, action)
