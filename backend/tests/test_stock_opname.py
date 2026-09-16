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
from backend.stock_opname import OpnameLineInput


def _first_endpoint(path: str, method: str):
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route.endpoint
    return None


def test_stock_opname_routes_are_registered():
    assert _first_endpoint("/api/stock-opnames", "GET").__name__ == "list_stock_opnames"
    assert _first_endpoint("/api/stock-opnames", "POST").__name__ == "create_stock_opname"
    assert _first_endpoint("/api/stock-opnames/{opname_id}/submit", "POST").__name__ == "submit_stock_opname"
    assert _first_endpoint("/api/stock-opnames/{opname_id}/approve", "POST").__name__ == "approve_stock_opname"


def test_opname_line_rejects_negative_physical_quantity():
    try:
        OpnameLineInput(allocationId="a1", physicalQty=-1, channel="KOM")
    except Exception:
        return
    raise AssertionError("physicalQty negatif harus ditolak")
