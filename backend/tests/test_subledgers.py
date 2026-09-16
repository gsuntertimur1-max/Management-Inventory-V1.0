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
from backend.integrity_lots import apply_lot_integrity
from backend.damaged_stock_area import damaged_movement_qty


def _first_endpoint(path: str, method: str):
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route.endpoint
    return None


def test_lot_integrity_wrapper_is_first_route():
    assert _first_endpoint("/api/integrity-control", "GET").__name__ == "integrity_control"


def test_stock_opname_lot_wrapper_is_first_approval_route():
    assert _first_endpoint("/api/stock-opnames/{opname_id}/approve", "POST").__name__ == "approve_stock_opname"
    assert _first_endpoint("/api/stock-opnames/{opname_id}/sync-lots", "POST").__name__ == "repair_stock_opname_lots"


def test_damaged_stock_area_route_is_registered():
    assert _first_endpoint("/api/damaged-stock-area", "GET").__name__ == "damaged_stock_area"


def test_lot_integrity_marks_legacy_coverage_as_warning():
    row = {"productId": "p1", "stackGood": 100, "unit": "Pack", "severity": "OK", "issues": []}
    result = apply_lot_integrity(row, 60)
    assert result["severity"] == "WARNING"
    assert result["lotTracked"] == 60
    assert result["lotUntracked"] == 40
    assert result["lotCoveragePct"] == 60


def test_lot_integrity_marks_overtracked_as_error():
    row = {"productId": "p1", "stackGood": 100, "unit": "Pack", "severity": "OK", "issues": []}
    result = apply_lot_integrity(row, 110)
    assert result["severity"] == "ERROR"
    assert any("lebih besar" in issue for issue in result["issues"])


def test_damaged_movement_prefers_damaged_change_and_falls_back_to_condition():
    assert damaged_movement_qty({"damaged_change": 5, "change": 99, "kondisi": "BAIK"}) == 5
    assert damaged_movement_qty({"change": -3, "kondisi": "RUSAK"}) == -3
    assert damaged_movement_qty({"change": 8, "kondisi": "BAIK"}) == 0
