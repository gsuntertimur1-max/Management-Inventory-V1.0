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
from backend.operational_guards import (
    document_lock_keys,
    lock_keys,
    product_lock_keys,
    surat_jalan_with_exact_locations,
)


def _first_endpoint(path: str, method: str):
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route.endpoint
    return None


def test_guard_routes_precede_original_mutating_routes():
    assert _first_endpoint("/api/receipts", "POST").__name__ == "guarded_receive_stock_with_metadata"
    assert _first_endpoint("/api/stock-damage-discoveries", "POST").__name__ == "guarded_stock_damage_with_reservations"
    assert _first_endpoint("/api/supplier-returns", "POST").__name__ == "guarded_supplier_return_with_reservations"
    assert _first_endpoint("/api/outbound-loads", "POST").__name__ == "guarded_create_outbound"
    assert _first_endpoint("/api/outbound-loads/{load_id}/complete", "POST").__name__ == "hardened_complete_outbound"
    assert _first_endpoint("/api/outbound-loads/{load_id}/return", "POST").__name__ == "guarded_consignment_return_document"
    assert _first_endpoint("/api/outbound-loads/{load_id}/sales-return", "POST").__name__ == "guarded_sales_return_document"
    assert _first_endpoint("/api/outbound-loads/{load_id}/settle", "POST").__name__ == "guarded_settle_outbound_document"


def test_return_lot_reconciliation_routes_are_registered():
    assert _first_endpoint("/api/return-lot-reconciliations/pending", "GET").__name__ == "list_pending_return_lot_reconciliations"
    assert _first_endpoint("/api/return-lot-reconciliations/{movement_id}", "POST").__name__ == "reconcile_return_lot"


def test_correction_routes_are_superadmin_operational_endpoints():
    assert _first_endpoint("/api/operational-corrections/receipts", "GET").__name__ == "list_receipt_corrections"
    assert _first_endpoint("/api/operational-corrections/receipts/{operation_id}/void", "POST").__name__ == "void_receipt_operation"
    assert _first_endpoint("/api/operational-corrections/outbound/{load_id}", "PUT").__name__ == "correct_completed_outbound_metadata"


def test_lock_keys_are_sorted_and_deduplicated():
    assert lock_keys(["product:p2", "product:p1"], ["product:p1", "document:SO/1"]) == [
        "document:SO/1",
        "product:p1",
        "product:p2",
    ]
    assert product_lock_keys(["p2", "p1", "p2"]) == ["product:p1", "product:p2"]
    assert document_lock_keys(["so/1", " SO/1 ", "tm-2"]) == ["document:SO/1", "document:TM-2"]


def test_surat_jalan_uses_exact_stack_locations_in_item_order():
    load = {
        "unit_loading": "Unit 18 / Unit 19",
        "items": [
            {"stackCode": "18/A01", "location": "GBB 18"},
            {"stackCode": "19/B02", "location": "GBB 19"},
        ],
    }
    sj = {"id": "sj1", "unit_loading": "", "items": [{"location": "GBB 18"}, {"location": "GBB 19"}]}
    updated = surat_jalan_with_exact_locations(load, sj)
    assert updated["unit_loading"] == "Unit 18 / Unit 19"
    assert updated["items"][0]["location"] == "18/A01"
    assert updated["items"][0]["stackCode"] == "18/A01"
    assert updated["items"][1]["location"] == "19/B02"
    assert updated["items"][1]["stackCode"] == "19/B02"
