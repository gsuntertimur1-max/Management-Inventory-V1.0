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
from backend.outbound_flow import OutboundItemInput
from backend.stack_reservation_guard import aggregate_stack_demand


def _first_endpoint(path: str, method: str):
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route.endpoint
    return None


def test_stack_reservation_guard_is_first_outbound_route():
    assert _first_endpoint("/api/outbound-loads", "POST").__name__ == "stack_reserved_create_outbound"
    assert _first_endpoint("/api/outbound-loads/{load_id}/edit", "PUT").__name__ == "stack_reserved_edit_outbound"


def test_stack_demand_aggregates_same_product_and_stack():
    items = [
        OutboundItemInput(productId="p1", qty=7, stackCode="18/a01"),
        OutboundItemInput(productId="p1", qty=5, stackCode="18/A01"),
        OutboundItemInput(productId="p1", qty=3, stackCode="18/A02"),
    ]
    assert aggregate_stack_demand(items) == {
        ("p1", "18/A01"): 12.0,
        ("p1", "18/A02"): 3.0,
    }


def test_stack_demand_supports_dict_items_and_ignores_blank_stack():
    assert aggregate_stack_demand([
        {"productId": "p2", "qty": 4, "stackCode": "19/B02"},
        {"productId": "p2", "qty": 6, "stackCode": ""},
    ]) == {("p2", "19/B02"): 4.0}
