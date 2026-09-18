import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "management_inventory_test")
os.environ.setdefault("JWT_SECRET", "test-only-jwt-secret")

from backend.cost_payments import DailyUnloadingSettlementInput, unloading_total


def test_unloading_total_separates_labor_and_daily():
    rows = [
        {"unloading_cost": {"labor": 100, "daily": 25}},
        {"unloading_cost": {"labor": 200, "daily": 35}},
        {"unloading_cost": {}},
    ]
    assert unloading_total(rows, "BURUH") == 300
    assert unloading_total(rows, "HARIAN") == 60


def test_unloading_settlement_recipient_contract():
    assert DailyUnloadingSettlementInput(recipient="BURUH").recipient == "BURUH"
    assert DailyUnloadingSettlementInput(recipient="HARIAN", note="Lunas").note == "Lunas"
