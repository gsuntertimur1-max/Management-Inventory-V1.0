from fastapi import APIRouter, Depends, HTTPException

from backend.server import db, new_id, now_iso, require_admin
from backend.correction_reversal import CorrectionReasonInput, void_receipt_operation as base_void_receipt_operation

router = APIRouter(prefix="/api")
EPS = 1e-9


@router.post("/operational-corrections/receipts/{operation_id}/void")
async def void_receipt_operation(operation_id: str, body: CorrectionReasonInput, user: dict = Depends(require_admin)):
    lots = await db.stack_lots.find({"operationId": operation_id}, {"_id": 0}).to_list(10000)
    for lot in lots:
        original = float(lot.get("originalQty", 0) or 0)
        remaining = float(lot.get("remainingQty", 0) or 0)
        if remaining + EPS < original:
            raise HTTPException(
                status_code=400,
                detail=f"Penerimaan tidak dapat dibatalkan karena lot {lot.get('lotCode', '')} sudah pernah dipakai untuk pengeluaran. Gunakan proses koreksi/retur yang sesuai.",
            )

    result = await base_void_receipt_operation(operation_id, body, user)
    corrected_at = now_iso()
    for lot in lots:
        remaining = float(lot.get("remainingQty", 0) or 0)
        if remaining > EPS:
            await db.stack_lot_movements.insert_one({
                "id": new_id(), "time": corrected_at, "loadId": "", "lotId": lot.get("id", ""),
                "lotCode": lot.get("lotCode", ""), "movementType": "RECEIPT_VOID",
                "productId": lot.get("productId", ""), "sku": lot.get("sku", ""),
                "product": lot.get("product", ""), "stackCode": lot.get("stackCode", ""),
                "sourceDocument": lot.get("sourceRef", ""), "qty": -remaining,
                "unit": lot.get("unit", ""), "exp": lot.get("exp", ""),
                "note": body.reason.strip(),
            })
        await db.stack_lots.update_one(
            {"id": lot.get("id")},
            {"$set": {"remainingQty": 0.0, "status": "DIBATALKAN", "voidedAt": corrected_at, "voidedBy": user.get("name", ""), "voidReason": body.reason.strip()}},
        )
    return result
