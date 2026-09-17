from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.opname_lots import (
    LotReconcileInput,
    LotReconcileItem,
    reconcile_stock_opname_lots as base_reconcile_stock_opname_lots,
)
from backend.stock_opname import require_opname_approval

router = APIRouter(prefix="/api")


def aggregate_lot_reconcile_input(body: LotReconcileInput) -> LotReconcileInput:
    """Normalize one request so each lot is mutated at most once.

    Duplicate rows for the same lot are combined when they refer to the same
    product and stack. Reusing one lot ID across different products/stacks is
    rejected instead of guessing the intended physical source.
    """
    grouped: dict[str, dict] = {}
    order: list[str] = []

    for item in body.items:
        product_id = item.productId.strip()
        stack_code = item.stackCode.strip().upper()
        lot_id = item.lotId.strip()
        qty = float(item.qty)

        existing = grouped.get(lot_id)
        if existing:
            if existing["productId"] != product_id or existing["stackCode"] != stack_code:
                raise HTTPException(
                    status_code=400,
                    detail="Satu lot tidak boleh direkonsiliasi ke produk/tumpukan yang berbeda dalam permintaan yang sama",
                )
            existing["qty"] += qty
            continue

        grouped[lot_id] = {
            "productId": product_id,
            "stackCode": stack_code,
            "lotId": lot_id,
            "qty": qty,
        }
        order.append(lot_id)

    return LotReconcileInput(
        items=[LotReconcileItem(**grouped[lot_id]) for lot_id in order],
        note=body.note,
    )


@router.post("/stock-opnames/{opname_id}/reconcile-lots")
async def guarded_reconcile_stock_opname_lots(
    opname_id: str,
    body: LotReconcileInput,
    user: dict = Depends(require_opname_approval),
):
    normalized = aggregate_lot_reconcile_input(body)
    return await base_reconcile_stock_opname_lots(opname_id, normalized, user)
