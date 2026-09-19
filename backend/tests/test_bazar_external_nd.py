import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "management_inventory_test")
os.environ.setdefault("JWT_SECRET", "test-only-jwt-secret")

from backend.bazar_external_nd import summarize_external_nd


def _document():
    return {
        "id": "nd-1",
        "ndNo": "ND-001",
        "items": [{"productId": "p1", "name": "Minyak 2 L", "orderedQty": 100}],
        "receipts": [],
        "returns": [],
        "realizations": [],
        "soDocuments": [],
    }


def test_new_nd_is_registered_without_stock_realization():
    result = summarize_external_nd(_document())
    assert result["status"] == "ND_TERDAFTAR"
    assert result["summaryItems"][0]["remainingToReceive"] == 100
    assert result["summaryItems"][0]["unsettledQty"] == 0


def test_received_nd_tracks_return_and_late_so_without_double_counting():
    document = _document()
    document["receipts"] = [{"items": [{"productId": "p1", "goodQty": 98, "damagedQty": 2}]}]
    document["returns"] = [{"items": [{"productId": "p1", "qty": 10}]}]
    document["realizations"] = [{"items": [{"productId": "p1", "qty": 85}]}]
    document["soDocuments"] = [{"soNo": "SO-001", "items": [{"productId": "p1", "qty": 85}]}]
    result = summarize_external_nd(document)
    row = result["summaryItems"][0]
    assert row["received"] == 100
    assert row["returned"] == 10
    assert row["realized"] == 85
    assert row["settled"] == 85
    assert row["physicalBalance"] == 3
    assert row["eligibleSoQty"] == 0
    assert row["unsettledQty"] == 3
    assert result["status"] == "SO_TERBIT_SEBAGIAN"


def test_nd_finishes_when_good_receipt_is_fully_returned_or_settled():
    document = _document()
    document["receipts"] = [{"items": [{"productId": "p1", "goodQty": 98, "damagedQty": 2}]}]
    document["returns"] = [{"items": [{"productId": "p1", "qty": 13}]}]
    document["realizations"] = [{"items": [{"productId": "p1", "qty": 85}]}]
    document["soDocuments"] = [{"soNo": "SO-001", "items": [{"productId": "p1", "qty": 85}]}]
    result = summarize_external_nd(document)
    assert result["summaryItems"][0]["unsettledQty"] == 0
    assert result["status"] == "SELESAI"
