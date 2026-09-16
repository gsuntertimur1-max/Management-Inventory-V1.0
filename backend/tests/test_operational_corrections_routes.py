import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "management_inventory_test")
os.environ.setdefault("JWT_SECRET", "test-only-jwt-secret")

from backend.correction_receipts import guarded_receive_stock_with_metadata
from backend.correction_reversal import void_receipt_operation
from backend.correction_outbound import correct_completed_outbound_metadata


def test_correction_endpoints_are_defined():
    assert guarded_receive_stock_with_metadata.__name__ == "guarded_receive_stock_with_metadata"
    assert void_receipt_operation.__name__ == "void_receipt_operation"
    assert correct_completed_outbound_metadata.__name__ == "correct_completed_outbound_metadata"
