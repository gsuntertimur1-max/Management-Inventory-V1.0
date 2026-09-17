from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.inventory_flow import SupplierReplacementInput, receive_supplier_replacement
from backend.operational_guards import idempotent_operation, lock_keys, product_lock_keys
from backend.server import db, require_write

router = APIRouter(prefix="/api")
EPS = 1e-9


def supplier_return_lock_keys(return_id: str, product_id: str = "") -> list[str]:
    return lock_keys(
        [f"supplier-return:{str(return_id or '').strip()}"],
        product_lock_keys([product_id] if product_id else []),
    )


async def _existing_replacement_by_reference(reference_no: str) -> dict | None:
    ref = str(reference_no or "").strip()
    if not ref:
        return None
    return await db.transactions.find_one(
        {"document_type": "PENGGANTIAN_PEMASOK", "ref": ref},
        {"_id": 0},
    )


@router.post("/supplier-returns/{return_id}/replacement")
async def guarded_receive_supplier_replacement(
    return_id: str,
    body: SupplierReplacementInput,
    request: Request,
    user: dict = Depends(require_write),
):
    # Resolve the product before acquiring the cross-worker lock so the same
    # product cannot be mutated concurrently by another critical operation.
    claim = await db.supplier_returns.find_one({"id": return_id}, {"_id": 0})
    if not claim:
        raise HTTPException(status_code=404, detail="Retur pemasok tidak ditemukan")
    product_id = str(claim.get("product_id") or "")

    async def action():
        current = await db.supplier_returns.find_one({"id": return_id}, {"_id": 0})
        if not current:
            raise HTTPException(status_code=404, detail="Retur pemasok tidak ditemukan")

        qty = float(body.qty)
        total = float(current.get("qty", 0) or 0)
        received = float(current.get("replacement_qty", 0) or 0)
        remaining = max(total - received, 0.0)
        if remaining <= EPS:
            raise HTTPException(status_code=409, detail="Retur pemasok ini sudah selesai diganti")
        if qty > remaining + EPS:
            raise HTTPException(
                status_code=400,
                detail=f"Penggantian melebihi sisa retur ({remaining:g} {current.get('unit', '')})",
            )

        # When supplier paperwork has an explicit reference number, treat it
        # as a business idempotency key as well. This protects users who retry
        # from another browser/session without reusing X-Idempotency-Key.
        explicit_ref = body.referenceNo.strip()
        if explicit_ref:
            existing = await _existing_replacement_by_reference(explicit_ref)
            if existing:
                if str(existing.get("parent_document") or "") == str(current.get("return_no") or ""):
                    return current
                raise HTTPException(status_code=409, detail="Nomor dokumen penggantian pemasok sudah digunakan")

        result = await receive_supplier_replacement(return_id, body, user)
        return result

    return await idempotent_operation(
        request,
        user,
        f"supplier-replacement:{return_id}",
        supplier_return_lock_keys(return_id, product_id),
        action,
    )
