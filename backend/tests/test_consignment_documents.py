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
from backend.consignment_locations import consignment_stack_codes
from backend.consignment_documents import _ensure_bazar_access, document_series_code


def test_consignment_stack_codes_are_scoped():
    assert consignment_stack_codes("Gudang Bazar") == (
        "18/A01-BAZAR", "18/A02-BAZAR", "18/A03-BAZAR", "18/A04-BAZAR",
    )
    assert consignment_stack_codes("Gudang E-commerce") == (
        "18/B01(1/2)-ECOM", "18/B02(1/2)-ECOM", "18/B03(1/2)-ECOM", "18/B04(1/2)-ECOM",
    )
    assert normalize_consignment_stack_code("Gudang Bazar", "a01") == "18/A01-BAZAR"
    assert normalize_consignment_stack_code("Gudang Bazar", "BZR/A04") == "18/A04-BAZAR"
    assert normalize_consignment_stack_code("Gudang E-commerce", "ECOM/B02") == "18/B02(1/2)-ECOM"
    assert normalize_consignment_stack_code("Gudang E-commerce", "ECOM/A01") == "18/B01(1/2)-ECOM"
    assert normalize_consignment_stack_code("Gudang E-commerce", "18/B04 (½)") == "18/B04(1/2)-ECOM"
    with pytest.raises(HTTPException):
        normalize_consignment_stack_code("Gudang Bazar", "18/B01(1/2)-ECOM")


def test_bazar_document_series_are_distinct():
    assert document_series_code("BAZAR") == "BZR"
    assert document_series_code("PAKET") == "PKT"


def test_bazar_documents_allow_bazar_operator_and_superadmin():
    _ensure_bazar_access({"role": "Operator"})
    _ensure_bazar_access({"role": "Administrator"})
    with pytest.raises(HTTPException):
        _ensure_bazar_access({"role": "QC"})


def test_stack_code_normalizer_rejects_cross_scope_and_invalid_package_marker():
    with pytest.raises(HTTPException):
        normalize_consignment_stack_code("Gudang E-commerce", "18/A01-BAZAR")
    with pytest.raises(HTTPException):
        normalize_consignment_stack_code("Gudang Bazar", "BZR/PKT")
