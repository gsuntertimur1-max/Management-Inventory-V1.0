import os
from datetime import timedelta

import pytest
from pydantic import ValidationError

os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "management_inventory_test")
os.environ.setdefault("JWT_SECRET", "test-only-jwt-secret")

import server


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
    assert server.role_label("Supervisor") == "Admin"
