from fastapi import APIRouter, Depends, Request

from backend.server import db, require_write
from backend.operational_guards import guarded_complete_outbound as base_guarded_complete_outbound
import backend.fefo_conservative as fefo_conservative
from backend.fefo_atomic import consume_tracked_fefo_atomic

# Replace the tracked-lot mutation used by the conservative FEFO engine with the
# compensated variant. This keeps the existing legacy-first calculation while
# preventing a failed movement insert from leaving a lot silently decremented.
fefo_conservative._consume_tracked_fefo = consume_tracked_fefo_atomic
consume_stack_lots_conservative = fefo_conservative.consume_stack_lots_conservative

router = APIRouter(prefix="/api")


@router.post("/outbound-loads/{load_id}/complete")
async def guarded_complete_outbound(load_id: str, request: Request, user: dict = Depends(require_write)):
    result = await base_guarded_complete_outbound(load_id, request, user)
    load = result.get("load") or await db.outbound_loads.find_one({"id": load_id}, {"_id": 0}) or {}
    fefo = await consume_stack_lots_conservative(load)
    result["fefo"] = fefo
    if load_id:
        await db.outbound_loads.update_one(
            {"id": load_id},
            {"$set": {
                "fefo_tracked_qty": fefo.get("tracked", 0),
                "fefo_untracked_qty": fefo.get("untracked", 0),
                "fefo_legacy_protected_qty": fefo.get("legacyProtected", 0),
                "fefo_policy": fefo.get("policy", "CONSERVATIVE_LEGACY_FIRST"),
            }},
        )
        if result.get("load"):
            result["load"]["fefo_tracked_qty"] = fefo.get("tracked", 0)
            result["load"]["fefo_untracked_qty"] = fefo.get("untracked", 0)
            result["load"]["fefo_legacy_protected_qty"] = fefo.get("legacyProtected", 0)
            result["load"]["fefo_policy"] = fefo.get("policy", "CONSERVATIVE_LEGACY_FIRST")
    return result
