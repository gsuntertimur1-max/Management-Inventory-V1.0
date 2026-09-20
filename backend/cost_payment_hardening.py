from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from backend.server import require_write
from backend.operational_guards import idempotent_operation
from backend.outbound_flow import (
    DailyLoadingSettlementInput,
    LoadingFeePaymentInput,
    record_loading_fee_payment,
    settle_loading_cost,
)
from backend.cost_payments import (
    DailyUnloadingSettlementInput,
    settle_unloading_cost,
)

router = APIRouter(prefix="/api")


@router.post("/outbound-loads/{load_id}/loading-fee-payment")
async def hardened_loading_fee_payment(
    load_id: str,
    body: LoadingFeePaymentInput,
    request: Request,
    user: dict = Depends(require_write),
):
    return await idempotent_operation(
        request,
        user,
        f"loading-fee-payment:{load_id}",
        [f"loading-fee-payment:{load_id}"],
        lambda: record_loading_fee_payment(load_id, body, user),
    )


@router.post("/loading-costs/{date}/settle")
async def hardened_loading_settlement(
    date: str,
    body: DailyLoadingSettlementInput,
    request: Request,
    user: dict = Depends(require_write),
):
    group = body.group.strip()
    return await idempotent_operation(
        request,
        user,
        f"loading-cost-settlement:{date}:{body.recipient}:{group}",
        [f"loading-cost-settlement:{date}:{body.recipient}:{group}"],
        lambda: settle_loading_cost(date, body, user),
    )


@router.post("/unloading-costs/{date}/settle")
async def hardened_unloading_settlement(
    date: str,
    body: DailyUnloadingSettlementInput,
    request: Request,
    user: dict = Depends(require_write),
):
    group = body.group.strip()
    return await idempotent_operation(
        request,
        user,
        f"unloading-cost-settlement:{date}:{body.recipient}:{group}",
        [f"unloading-cost-settlement:{date}:{body.recipient}:{group}"],
        lambda: settle_unloading_cost(date, body, user),
    )
