import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "management_inventory_test")
os.environ.setdefault("JWT_SECRET", "test-only-jwt-secret")

from backend.fefo_selection import build_fefo_pick_guide


def test_fully_reserved_stack_is_not_recommended():
    allocations = [
        {"stackCode": "18/A01", "primaryQty": 20, "unit": "Pack"},
        {"stackCode": "18/A02", "primaryQty": 20, "unit": "Pack"},
    ]
    lots = [
        {"id": "early", "stackCode": "18/A01", "remainingQty": 20, "exp": "2026-10-01", "receivedAt": "2026-09-01"},
        {"id": "later", "stackCode": "18/A02", "remainingQty": 20, "exp": "2026-12-01", "receivedAt": "2026-09-02"},
    ]
    guide = build_fefo_pick_guide("p1", allocations, lots, {"18/A01": 20})
    assert guide["stacks"][0]["stackCode"] == "18/A02"
    assert guide["recommendedStacks"] == ["18/A02"]
    reserved = next(row for row in guide["stacks"] if row["stackCode"] == "18/A01")
    assert reserved["reservedQty"] == 20
    assert reserved["availableQty"] == 0


def test_partially_reserved_stack_reports_remaining_available_qty():
    allocations = [{"stackCode": "19/B02", "primaryQty": 100, "unit": "Pack"}]
    guide = build_fefo_pick_guide("p2", allocations, [], {"19/B02": 35})
    row = guide["stacks"][0]
    assert row["reservedQty"] == 35
    assert row["availableQty"] == 65
    assert guide["recommendedStacks"] == ["19/B02"]
