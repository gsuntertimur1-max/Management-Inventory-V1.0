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
from backend.consignment import normalize_consignment_stack_code
from backend.consignment_documents import _ensure_bazar_access, document_series_code


def test_consignment_stack_codes_are_scoped():
    assert normalize_consignment_stack_code("Gudang Bazar", "a01") == "BZR/A01"
    assert normalize_consignment_stack_code("Gudang E-commerce", "ECOM/B02") == "ECOM/B02"
    with pytest.raises(HTTPException):
        normalize_consignment_stack_code("Gudang Bazar", "ECOM/A01")


def test_bazar_document_series_are_distinct():
    assert document_series_code("BAZAR") == "BZR"
    assert document_series_code("PAKET") == "PKT"


def test_bazar_documents_allow_bazar_operator_and_superadmin():
    _ensure_bazar_access({"role": "Operator"})
    _ensure_bazar_access({"role": "Administrator"})
    with pytest.raises(HTTPException):
        _ensure_bazar_access({"role": "QC"})
