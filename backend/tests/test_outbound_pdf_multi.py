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
from backend.outbound_pdf_multi import _group_items, _loading_route, _secondary_text


def _first_endpoint(path: str, method: str):
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route.endpoint
    return None


def test_multi_document_pdf_routes_precede_legacy_routes():
    assert _first_endpoint("/api/export/bon-muat/{load_id}.pdf", "GET").__module__ == "backend.outbound_pdf_multi"
    assert _first_endpoint("/api/export/surat-jalan/{sj_id}.pdf", "GET").__module__ == "backend.outbound_pdf_multi"


def test_group_items_keeps_document_and_stack_boundaries():
    load = {
        "ref": "SO/1",
        "items": [
            {"productId": "p1", "documentNo": "SO/1", "stackCode": "18/A01", "channel": "KOM", "qty": 10, "berat": 50},
            {"productId": "p1", "documentNo": "SO/1", "stackCode": "18/A01", "channel": "KOM", "qty": 5, "berat": 25},
            {"productId": "p1", "documentNo": "SO/2", "stackCode": "19/B02", "channel": "KOM", "qty": 7, "berat": 35},
        ],
    }
    grouped = _group_items(load)
    assert list(grouped.keys()) == ["SO/1", "SO/2"]
    first = list(grouped["SO/1"].values())[0]
    assert first["qty"] == 15
    assert first["berat"] == 75
    assert first["stack"] == "18/A01"
    second = list(grouped["SO/2"].values())[0]
    assert second["stack"] == "19/B02"


def test_loading_route_preserves_physical_stack_order_without_duplicates():
    load = {"items": [
        {"stackCode": "18/A01"},
        {"stackCode": "18/A01"},
        {"stackCode": "19/B02"},
        {"stackCode": "MP1/A03"},
    ]}
    assert _loading_route(load) == "18/A01 -> 19/B02 -> MP1/A03"


def test_secondary_text_reports_full_secondary_and_loose_primary():
    item = {"qty": 19, "secondaryQty": 8, "secondary": "Dus", "unit": "Pack"}
    assert _secondary_text(item) == "2 Dus + 3 Pack"
