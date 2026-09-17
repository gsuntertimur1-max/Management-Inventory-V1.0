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
from backend.stack_lots import expiry_status, lot_sort_key
import backend.opname_lots as opname_lots
import backend.opname_lots_conservative as opname_lots_conservative
from backend.opname_lot_atomic import reduce_single_lot_atomic


def _first_endpoint(path: str, method: str):
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route.endpoint
    return None


def test_fefo_routes_are_registered():
    assert _first_endpoint("/api/stack-lots", "GET").__name__ == "list_stack_lots"
    assert _first_endpoint("/api/fefo-recommendations", "GET").__name__ == "fefo_recommendations"
    assert _first_endpoint("/api/outbound-loads/{load_id}/complete", "POST").__name__ == "hardened_complete_outbound"
    assert _first_endpoint("/api/operational-corrections/receipts/{operation_id}/void", "POST").__name__ == "void_receipt_operation"


def test_opname_engines_use_compensated_single_lot_reducer():
    assert opname_lots._reduce_single_lot is reduce_single_lot_atomic
    assert opname_lots_conservative._reduce_single_lot is reduce_single_lot_atomic


def test_fefo_sort_prioritizes_earliest_dated_lot_before_undated():
    lots = [
        {"id": "undated", "exp": "", "receivedAt": "2026-01-01"},
        {"id": "late", "exp": "2027-12-31", "receivedAt": "2026-01-01"},
        {"id": "early", "exp": "2026-10-01", "receivedAt": "2026-09-01"},
    ]
    ordered = sorted(lots, key=lot_sort_key)
    assert [row["id"] for row in ordered] == ["early", "late", "undated"]


def test_expiry_status_handles_past_future_and_missing_dates():
    assert expiry_status("2000-01-01") == "EXPIRED"
    assert expiry_status("2999-12-31") == "AMAN"
    assert expiry_status("") == "TANPA_EXPIRED"
    assert expiry_status("bukan-tanggal") == "TANGGAL_INVALID"
