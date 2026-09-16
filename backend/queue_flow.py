from fastapi import APIRouter, Depends

from backend.server import db, get_current_user

router = APIRouter(prefix="/api")


@router.get("/outbound-queue")
async def list_active_outbound_queue(user: dict = Depends(get_current_user)):
    projection = {
        "_id": 0,
        "id": 1,
        "antrian": 1,
        "bon_no": 1,
        "status": 1,
        "party": 1,
        "ref": 1,
        "documents": 1,
        "polisi": 1,
        "pengambil": 1,
        "unit_loading": 1,
        "operational_date": 1,
        "created_at": 1,
        "started_at": 1,
        "items.name": 1,
        "items.qty": 1,
        "items.unit": 1,
        "items.berat": 1,
        "items.measureUnit": 1,
        "items.documentNo": 1,
        "items.stackCode": 1,
    }
    return await db.outbound_loads.find(
        {"status": {"$in": ["Menunggu", "Sedang Dimuat"]}},
        projection,
    ).sort("created_at", 1).to_list(250)
