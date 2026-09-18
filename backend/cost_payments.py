from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from pymongo.errors import OperationFailure

from backend.server import db, get_current_user, now_iso, require_write

router = APIRouter(prefix="/api")


class DailyUnloadingSettlementInput(BaseModel):
    recipient: Literal["BURUH", "HARIAN"]
    group: str = ""
    note: str = ""


def unloading_total(transactions: list[dict], recipient: str, group: str = "") -> float:
    key = "labor" if recipient == "BURUH" else "daily"
    return sum(float((row.get("unloading_cost") or {}).get(key, 0) or 0) for row in transactions if not group or str(row.get("unloading_group") or "") == group)


async def ensure_cost_payment_indexes() -> None:
    for collection in (db.loading_cost_settlements, db.unloading_cost_settlements):
        try:
            await collection.drop_index("date_1_recipient_1")
        except OperationFailure:
            pass
        await collection.create_index([("date", 1), ("recipient", 1), ("group", 1)], unique=True, name="date_recipient_group_unique")


@router.get("/cost-settlements")
async def get_cost_settlements(user: dict = Depends(get_current_user)):
    loading = await db.loading_cost_settlements.find({}, {"_id": 0}).sort("date", -1).to_list(5000)
    unloading = await db.unloading_cost_settlements.find({}, {"_id": 0}).sort("date", -1).to_list(5000)
    return {"loading": loading, "unloading": unloading}


@router.post("/unloading-costs/{date}/settle")
async def settle_unloading_cost(
    date: str,
    body: DailyUnloadingSettlementInput,
    user: dict = Depends(require_write),
):
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Tanggal harus YYYY-MM-DD") from exc

    transactions = await db.transactions.find(
        {
            "type": "MASUK",
            "voided": {"$ne": True},
            "$or": [
                {"operational_date": date},
                {"operational_date": {"$in": ["", None]}, "time": {"$regex": f"^{date}"}},
            ],
        },
        {"_id": 0, "unloading_cost": 1, "unloading_group": 1},
    ).to_list(10000)
    group = body.group.strip()
    amount = unloading_total(transactions, body.recipient, group)
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Tidak ada biaya bongkar yang perlu dibayarkan untuk tanggal ini")

    doc = {
        "date": date,
        "recipient": body.recipient,
        "group": group,
        "amount": amount,
        "settledAt": now_iso(),
        "settledBy": user.get("name", ""),
        "note": body.note.strip(),
    }
    await db.unloading_cost_settlements.update_one(
        {"date": date, "recipient": body.recipient, "group": group},
        {"$set": doc, "$push": {"history": dict(doc)}},
        upsert=True,
    )
    return doc
