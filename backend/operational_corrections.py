from fastapi import APIRouter

from backend.correction_receipts import router as receipt_correction_router
from backend.correction_reversal import router as receipt_reversal_router
from backend.correction_outbound import router as outbound_correction_router

router = APIRouter()
router.include_router(receipt_correction_router)
router.include_router(receipt_reversal_router)
router.include_router(outbound_correction_router)
