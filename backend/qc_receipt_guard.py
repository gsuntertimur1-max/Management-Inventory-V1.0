from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field

from backend.server import db, require_write
from backend.inventory_flow import ReceiptInput
from backend.correction_receipts import guarded_receive_stock_with_metadata

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)


class QCReceiptInput(ReceiptInput):
    """Backward-compatible receipt payload with optional QC/process linkage.

    Empty qcStatus keeps the existing Inventory receipt flow unchanged.
    Integrations that already know QC state can explicitly submit APPROVED,
    PENDING, or REJECTED.
    """

    qcStatus: Literal["", "PENDING", "APPROVED", "REJECTED"] = ""
    qcReference: str = Field(default="", max_length=120)
    processOrderNo: str = Field(default="", max_length=120)


def qc_receipt_allowed(status: str) -> bool:
    return str(status or "").strip().upper() in {"", "APPROVED"}


@router.post("/receipts")
async def guarded_receive_stock_qc(
    body: QCReceiptInput,
    request: Request,
    user: dict = Depends(require_write),
):
    qc_status = str(body.qcStatus or "").strip().upper()
    qc_reference = str(body.qcReference or "").strip()
    process_order_no = str(body.processOrderNo or "").strip()

    if qc_status == "PENDING":
        raise HTTPException(
            status_code=409,
            detail="Penerimaan ditolak karena QC bahan baku masih PENDING. Selesaikan QC terlebih dahulu; stok belum ditambah.",
        )
    if qc_status == "REJECTED":
        raise HTTPException(
            status_code=409,
            detail="Penerimaan ditolak karena hasil QC REJECTED. Barang reject tidak boleh masuk stok Inventory.",
        )
    if qc_status == "APPROVED" and not qc_reference:
        raise HTTPException(
            status_code=400,
            detail="Nomor/referensi QC wajib diisi untuk penerimaan berstatus APPROVED.",
        )

    result = await guarded_receive_stock_with_metadata(body, request, user)

    # Metadata QC/MO is enrichment only. A metadata write must never turn a
    # successfully committed stock receipt into a false failed response.
    if qc_status or qc_reference or process_order_no:
        operation_id = str(result.get("operationId") or "")
        if operation_id:
            patch = {
                "qc_status": qc_status or "NOT_APPLICABLE",
                "qc_reference": qc_reference,
                "process_order_no": process_order_no,
            }
            try:
                await db.transactions.update_many(
                    {"operation_id": operation_id},
                    {"$set": patch},
                )
                for txn in result.get("transactions") or []:
                    txn.update(patch)
            except Exception:
                logger.exception("Gagal menambahkan metadata QC/MO penerimaan %s", operation_id)

    result["qc"] = {
        "status": qc_status or "NOT_APPLICABLE",
        "reference": qc_reference,
        "processOrderNo": process_order_no,
    }
    return result
