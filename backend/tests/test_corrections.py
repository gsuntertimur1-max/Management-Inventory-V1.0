import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "management_inventory_test")
os.environ.setdefault("JWT_SECRET", "test-only-jwt-secret")

from backend.correction_receipts import receipt_item_metadata, receipt_summary, txn_quantities
from backend.inventory_flow import ReceiptInput


def test_receipt_metadata_separates_good_stack_and_damaged_holding():
    body = ReceiptInput(poId="po-1", items=[{"productId": "p1", "goodQty": 994, "damagedQty": 6, "stackCode": "18/A01", "channel": "KOM"}], party="Supplier A")
    txns = [{"id": "good-txn", "kondisi": "BAIK"}, {"id": "damaged-txn", "kondisi": "RUSAK"}]
    metadata = dict(receipt_item_metadata(body, txns))
    assert metadata["good-txn"]["product_id"] == "p1"
    assert metadata["good-txn"]["stackCode"] == "18/A01"
    assert metadata["good-txn"]["location_type"] == "STACK"
    assert metadata["damaged-txn"]["stackCode"] == ""
    assert metadata["damaged-txn"]["receipt_location"] == "AREA BARANG RUSAK"
    assert metadata["damaged-txn"]["location_type"] == "DAMAGED_HOLDING"


def test_transaction_quantity_fallback_for_legacy_receipt():
    assert txn_quantities({"change": 10, "kondisi": "BAIK"}) == (10, 0)
    assert txn_quantities({"change": 4, "kondisi": "RUSAK"}) == (0, 4)
    assert txn_quantities({"change": 10, "good_change": 8, "damaged_change": 2}) == (8, 2)


def test_legacy_good_receipt_without_stack_is_not_auto_correctable():
    rows = [{"id": "t1", "operation_id": "op1", "time": "2026-09-16T00:00:00+00:00", "ref": "PO-1", "type": "MASUK", "kondisi": "BAIK", "product": "Beras", "sku": "SKU1", "change": 10, "unit": "Pack"}]
    product = {"id": "p1", "sku": "SKU1", "name": "Beras"}
    result = receipt_summary("op1", rows, {"p1": product}, {"SKU1": product}, set())
    assert result["correctable"] is False
    assert "tumpukan asal" in result["reason"].lower()
