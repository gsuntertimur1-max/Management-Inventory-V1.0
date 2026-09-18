import os
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "management_inventory_test")
os.environ.setdefault("JWT_SECRET", "test-only-jwt-secret")

import backend.role_four_config  # noqa: F401
from backend.consignment_operations import _ensure_access, BAZAR, ECOM


def test_bazar_role_is_scoped_to_bazar():
    user = {"role": "Operator"}
    _ensure_access(user, BAZAR, write=True)
    with pytest.raises(HTTPException) as exc:
        _ensure_access(user, ECOM, write=True)
    assert exc.value.status_code == 403


def test_ecommerce_role_is_scoped_to_ecommerce():
    user = {"role": "QC"}
    _ensure_access(user, ECOM, write=True)
    with pytest.raises(HTTPException) as exc:
        _ensure_access(user, BAZAR, write=True)
    assert exc.value.status_code == 403


def test_superadmin_can_operate_both_subledgers():
    user = {"role": "Administrator"}
    _ensure_access(user, BAZAR, write=True)
    _ensure_access(user, ECOM, write=True)


def test_bazar_close_item_keeps_stack_identity():
    from backend.consignment_operations import BazarCloseItem
    row = BazarCloseItem(
        productId="p1",
        stackCode="18/A02-BAZAR",
        soldQty=5,
        returnedGoodQty=1,
        returnedDamagedQty=0,
    )
    assert row.stackCode == "18/A02-BAZAR"
