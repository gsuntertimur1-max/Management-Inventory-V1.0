import os
from datetime import timedelta

import pytest
from pydantic import ValidationError

os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "management_inventory_test")
os.environ.setdefault("JWT_SECRET", "test-only-jwt-secret")

from backend import server
from backend.inventory_flow import ReceiptItemInput, receipt_condition_quantities
from backend.outbound_flow import loading_units_from_items
from fastapi import HTTPException


def test_seed_file_contains_no_operational_rows():
    text = (server.ROOT_DIR / "seed_data.csv").read_text(encoding="utf-8")
    assert server.parse_seed_rows(text) == []


def test_operational_clock_uses_wib():
    assert server.operational_now().utcoffset() == timedelta(hours=7)


def test_product_rejects_negative_stock():
    with pytest.raises(ValidationError):
        server.ProductBody(name="Produk", sku="SKU-1", stock=-1)


def test_purchase_order_requires_items():
    with pytest.raises(ValidationError):
        server.POBody(supplier="Supplier", items=[], total=0)


def test_service_routes_do_not_duplicate_api_prefix():
    paths = {route.path for route in server.app.routes}
    assert "/auth/login" in paths
    assert "/api/auth/login" not in paths


@pytest.mark.parametrize(
    "role, permission, expected",
    [
        ("Administrator", "currentWrite", True),
        ("Superadmin", "currentWrite", True),
        ("Supervisor", "inbound", True),
        ("Supervisor", "outbound", True),
        ("Supervisor", "qc", False),
        ("Operator", "rebagging", True),
        ("Operator", "inbound", False),
        ("Operator", "outbound", False),
        ("QC", "qc", True),
        ("QC", "inbound", False),
        ("QC", "outbound", False),
    ],
)
def test_final_role_permissions(role, permission, expected):
    assert server.has_role_permission(role, permission) is expected


def test_role_aliases_and_labels_preserve_legacy_values():
    assert server.canonical_role("Superadmin") == "Administrator"
    assert server.canonical_role("Admin") == "Supervisor"
    assert server.role_label("Administrator") == "Superadmin"
    assert server.role_label("Supervisor") == "Admin Gudang"


def test_receipt_quantities_preserve_legacy_condition_and_validate_split_total():
    old_item = ReceiptItemInput(productId="minyak", qty=6)
    assert receipt_condition_quantities(old_item, "RUSAK") == (0.0, 6.0)
    split_item = ReceiptItemInput(productId="minyak", qty=1000, goodQty=994, damagedQty=6)
    assert receipt_condition_quantities(split_item, "BAIK") == (994.0, 6.0)
    with pytest.raises(HTTPException, match="Total penerimaan"):
        receipt_condition_quantities(ReceiptItemInput(productId="minyak", qty=1000, goodQty=994, damagedQty=5), "BAIK")


def test_mixed_loading_sources_get_distinct_queue_prefix():
    assert loading_units_from_items([{"stackCode": "18/A01"}, {"stackCode": "19/B02"}]) == ("Unit 18 / Unit 19", "M")
    assert loading_units_from_items([{"stackCode": "18/A01"}, {"stackCode": "18/B02"}]) == ("Unit 18", "18")
    assert loading_units_from_items([{"location": "Gudang 18"}, {"location": "Gudang 19"}]) == ("Unit 18 / Unit 19", "M")
