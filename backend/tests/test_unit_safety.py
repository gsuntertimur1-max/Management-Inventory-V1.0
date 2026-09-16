import os
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "management_inventory_test")
os.environ.setdefault("JWT_SECRET", "test-only-jwt-secret")

from backend import server
from backend.inventory_flow import ReceiptItemInput, receipt_condition_quantities
from backend.outbound_flow import loading_units_from_items, _linked_totals, _source_product_totals, _all_source_documents_settled
from backend.stack_allocations import _parse_treatment_date
from backend.runtime_hardening import blocks_legacy_product_mutation, blocks_legacy_direct_transaction, measure_unit
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
    assert "/api/auth/login" in paths
    assert "/api/api/auth/login" not in paths


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


def test_linked_documents_are_scoped_to_source_document():
    load = {"ref": "ND/001", "documents": ["ND/001", "ND/002"], "items": [{"productId": "p1", "documentNo": "ND/001", "qty": 10}, {"productId": "p1", "documentNo": "ND/002", "qty": 20}], "document_links": [{"type": "SO", "sourceDocumentNo": "ND/001", "items": [{"productId": "p1", "qty": 4}]}, {"type": "SO", "sourceDocumentNo": "ND/002", "items": [{"productId": "p1", "qty": 7}]}]}
    assert _linked_totals(load, "p1", "ND/001") == (0.0, 4.0)
    assert _linked_totals(load, "p1", "ND/002") == (0.0, 7.0)
    assert _source_product_totals(load, "ND/001")["p1"]["qty"] == 10
    assert _all_source_documents_settled(load) is False


def test_treatment_date_parser_rejects_invalid_dates():
    assert _parse_treatment_date("2026-09-16", "Tanggal").isoformat() == "2026-09-16"
    with pytest.raises(HTTPException, match="YYYY-MM-DD"):
        _parse_treatment_date("16/09/2026", "Tanggal")


def test_legacy_product_mutations_are_blocked_but_reads_remain_available():
    assert blocks_legacy_product_mutation("POST", "/api/products") is True
    assert blocks_legacy_product_mutation("PUT", "/api/products/p1") is True
    assert blocks_legacy_product_mutation("DELETE", "/api/products/p1") is True
    assert blocks_legacy_product_mutation("GET", "/api/products") is False
    assert blocks_legacy_product_mutation("POST", "/api/products-master") is False


def test_legacy_direct_stock_transaction_is_blocked_but_history_read_is_allowed():
    assert blocks_legacy_direct_transaction("POST", "/api/transactions") is True
    assert blocks_legacy_direct_transaction("POST", "/api/transactions/") is True
    assert blocks_legacy_direct_transaction("GET", "/api/transactions") is False
    assert blocks_legacy_direct_transaction("POST", "/api/receipts") is False
    assert blocks_legacy_direct_transaction("POST", "/api/outbound-loads") is False


def test_measure_unit_normalization_never_labels_liter_or_pcs_as_kg():
    assert measure_unit("liter") == "liter"
    assert measure_unit("pcs") == "pcs"
    assert measure_unit("kg") == "kg"
    assert measure_unit("unknown") == "kg"
