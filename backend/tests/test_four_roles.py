import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "management_inventory_test")
os.environ.setdefault("JWT_SECRET", "test-only-jwt-secret")

from backend.role_four_config import (
    ROLE_ADMIN,
    ROLE_BAZAR,
    ROLE_ECOM,
    ROLE_SUPERADMIN,
    ROLE_VIEWER,
    ROLE_WAREHOUSE_HEAD,
    canonical_role,
    has_role_permission,
    role_destination,
)


def test_roles_are_canonicalized_to_six_business_roles():
    assert canonical_role("Administrator") == ROLE_SUPERADMIN
    assert canonical_role("Superadmin") == ROLE_SUPERADMIN
    assert canonical_role("Kepala Gudang") == ROLE_WAREHOUSE_HEAD
    for role in ("Supervisor", "Admin", "Admin Operasional", "Mandor"):
        assert canonical_role(role) == ROLE_ADMIN
    assert canonical_role("Operator") == ROLE_BAZAR
    assert canonical_role("Petugas Bazar") == ROLE_BAZAR
    assert canonical_role("QC") == ROLE_ECOM
    assert canonical_role("Petugas E-commerce") == ROLE_ECOM
    for role in ("Pemantau", "Viewer", "Viewer / Auditor", "unknown"):
        assert canonical_role(role) == ROLE_VIEWER


def test_superadmin_keeps_full_control_including_consignment():
    for permission in ("masterWrite", "currentWrite", "users", "settings", "corrections", "costView", "bazarOps", "ecomOps", "consignmentHistory"):
        assert has_role_permission(ROLE_SUPERADMIN, permission)


def test_warehouse_head_keeps_consignment_visibility_and_operations():
    for permission in ("inbound", "outbound", "bazarView", "bazarOps", "ecomView", "ecomOps", "consignmentHistory"):
        assert has_role_permission(ROLE_WAREHOUSE_HEAD, permission)


def test_admin_operasional_sees_consignment_stock_but_not_scoped_outbound_operations():
    for permission in ("inbound", "outbound", "bazarView", "ecomView", "consignmentView"):
        assert has_role_permission(ROLE_ADMIN, permission)
    for permission in ("bazarOps", "ecomOps", "settings", "consignmentHistory"):
        assert not has_role_permission(ROLE_ADMIN, permission)


def test_bazar_role_is_scoped_and_not_general_writer():
    assert role_destination(ROLE_BAZAR) == "Gudang Bazar"
    assert has_role_permission(ROLE_BAZAR, "bazarView")
    assert has_role_permission(ROLE_BAZAR, "bazarOps")
    assert has_role_permission(ROLE_BAZAR, "consignmentHistory")
    for permission in ("ecomView", "ecomOps", "currentWrite", "inbound", "outbound", "masterWrite", "users", "settings"):
        assert not has_role_permission(ROLE_BAZAR, permission)


def test_ecommerce_role_is_scoped_and_not_general_writer():
    assert role_destination(ROLE_ECOM) == "Gudang E-commerce"
    assert has_role_permission(ROLE_ECOM, "ecomView")
    assert has_role_permission(ROLE_ECOM, "ecomOps")
    assert has_role_permission(ROLE_ECOM, "consignmentHistory")
    for permission in ("bazarView", "bazarOps", "currentWrite", "inbound", "outbound", "masterWrite", "users", "settings"):
        assert not has_role_permission(ROLE_ECOM, permission)


def test_viewer_is_read_only():
    assert has_role_permission(ROLE_VIEWER, "view")
    assert has_role_permission(ROLE_VIEWER, "bazarView")
    assert has_role_permission(ROLE_VIEWER, "ecomView")
    for permission in ("currentWrite", "inbound", "outbound", "costView", "users", "settings", "corrections", "bazarOps", "ecomOps", "consignmentHistory"):
        assert not has_role_permission(ROLE_VIEWER, permission)
