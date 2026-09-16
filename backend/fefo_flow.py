from fastapi import APIRouter, Depends, Request

from backend.server import db, require_write
from backend.operational_guards import guarded_complete_outbound as base_guarded_complete_outbound
from backend.stack_lots import consume_stack_lots_for_outbound

router = APIRouter(prefix="/api")


@router.post("/outbound-loads/{load_id}/complete")
async def guarded_complete_outbound(load_id: str, request: Request, user: dict = Depends(require_write)):
    result = await base_guarded_complete_outbound(load_id, request, user)
    load = result.get("load") or await db.outbound_loads.find_one({"id": load_id}, {"_id": 0}) or {}
    fefo = await consume_stack_lots_for_outbound(load)
    result["fefo"] = fefo
    if load_id:
        await db.outbound_loads.update_one(
            {"id": load_id},
            {"$set": {
                "fefo_tracked_qty": fefo.get("tracked", 0),
                "fefo_untracked_qty": fefo.get("untracked", 0),
            }},
        )
        if result.get("load"):
            result["load"]["fefo_tracked_qty"] = fefo.get("tracked", 0)
            result["load"]["fefo_untracked_qty"] = fefo.get("untracked", 0)
    return result
