import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "management_inventory_test")
os.environ.setdefault("JWT_SECRET", "test-only-jwt-secret")

from app import app
from backend.integrity_control import product_integrity_row


def _first_endpoint(path: str, method: str):
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route.endpoint
    return None


def test_integrity_control_route_is_registered():
    endpoint = _first_endpoint("/api/integrity-control", "GET")
    assert endpoint is not None
    assert endpoint.__name__ == "integrity_control"


def test_integrity_row_ok_when_master_stack_and_channels_match():
    product = {
        "id": "p1",
        "sku": "SKU1",
        "name": "Beras",
        "unit": "Pack",
        "stock": 100,
        "damaged": 5,
        "channelStock": {
            "PSO": {"stock": 60, "damaged": 2},
            "KOM": {"stock": 40, "damaged": 3},
        },
    }
    row = product_integrity_row(product, 100, 20, 1)
    assert row["severity"] == "OK"
    assert row["stackDifference"] == 0
    assert row["channelGoodDifference"] == 0
    assert row["channelDamagedDifference"] == 0
    assert row["availableGoodAfterReservation"] == 80


def test_integrity_row_flags_overallocated_stack_and_channel_mismatch():
    product = {
        "id": "p2",
        "sku": "SKU2",
        "name": "Minyak",
        "unit": "Pouch",
        "stock": 90,
        "damaged": 2,
        "channelStock": {
            "PSO": {"stock": 50, "damaged": 1},
            "KOM": {"stock": 30, "damaged": 0},
        },
    }
    row = product_integrity_row(product, 100, 95, 3)
    assert row["severity"] == "ERROR"
    assert any("tumpukan" in issue.lower() for issue in row["issues"])
    assert any("pso/kom" in issue.lower() for issue in row["issues"])
    assert any("reservasi" in issue.lower() for issue in row["issues"])
