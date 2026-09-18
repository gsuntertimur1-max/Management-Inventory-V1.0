import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "management_inventory_test")
os.environ.setdefault("JWT_SECRET", "test-only-jwt-secret")

import backend.server as server
from backend.role_four_config import (
    ROLE_ADMIN,
    ROLE_BAZAR,
    ROLE_ECOM,
    ROLE_LABELS,
    ROLE_PERMISSIONS,
    ROLE_SUPERADMIN,
    ROLE_VIEWER,
    ROLE_WAREHOUSE_HEAD,
    canonical_role,
    has_role_permission,
    role_destination,
)


EXPECTED_PERMISSIONS = {
    ROLE_SUPERADMIN: {
        "masterWrite", "inbound", "outbound", "rebagging", "qc", "users",
        "settings", "costView", "corrections", "warehouseApprove", "currentWrite",
        "bazarView", "bazarOps", "ecomView", "ecomOps", "consignmentView", "consignmentHistory",
    },
    ROLE_WAREHOUSE_HEAD: {
        "inbound", "outbound", "costView", "corrections", "warehouseApprove",
        "currentWrite", "bazarView", "bazarOps", "ecomView", "ecomOps",
        "consignmentView", "consignmentHistory",
    },
    ROLE_ADMIN: {
        "inbound", "outbound", "costView", "currentWrite",
        "bazarView", "ecomView", "consignmentView",
    },
    ROLE_BAZAR: {"bazarView", "bazarOps", "consignmentView", "consignmentHistory"},
    ROLE_ECOM: {"ecomView", "ecomOps", "consignmentView", "consignmentHistory"},
    ROLE_VIEWER: {"bazarView", "ecomView", "consignmentView"},
}

EXPECTED_LABELS = {
    ROLE_SUPERADMIN: "Superadmin",
    ROLE_WAREHOUSE_HEAD: "Kepala Gudang",
    ROLE_ADMIN: "Admin Operasional",
    ROLE_BAZAR: "Petugas Bazar",
    ROLE_ECOM: "Petugas E-commerce",
    ROLE_VIEWER: "Viewer",
}


def test_roles_are_canonicalized_to_six_business_roles():
    aliases = {
        "Administrator": ROLE_SUPERADMIN,
        "Superadmin": ROLE_SUPERADMIN,
        "Kepala Gudang": ROLE_WAREHOUSE_HEAD,
        "Supervisor": ROLE_ADMIN,
        "Admin": ROLE_ADMIN,
        "Admin Operasional": ROLE_ADMIN,
        "Mandor": ROLE_ADMIN,
        "Operator": ROLE_BAZAR,
        "Petugas Bazar": ROLE_BAZAR,
        "QC": ROLE_ECOM,
        "Petugas E-commerce": ROLE_ECOM,
        "Petugas Ecom": ROLE_ECOM,
        "Pemantau": ROLE_VIEWER,
        "Viewer": ROLE_VIEWER,
        "Viewer / Auditor": ROLE_VIEWER,
        "unknown": ROLE_VIEWER,
        "": ROLE_VIEWER,
    }
    for value, expected in aliases.items():
        assert canonical_role(value) == expected


def test_role_labels_are_consistent_with_business_names():
    assert ROLE_LABELS == EXPECTED_LABELS
    for canonical, label in EXPECTED_LABELS.items():
        assert server.role_label(canonical) == label


def test_permission_matrix_is_exact_and_does_not_expand_roles():
    assert ROLE_PERMISSIONS == EXPECTED_PERMISSIONS


def test_derived_permissions_are_consistent():
    for role in EXPECTED_PERMISSIONS:
        assert has_role_permission(role, "view")
        expected_operations = bool(EXPECTED_PERMISSIONS[role] & {"inbound", "outbound"})
        assert has_role_permission(role, "operations") is expected_operations
        expected_outbound_page = bool(EXPECTED_PERMISSIONS[role] & {"outbound", "costView"})
        assert has_role_permission(role, "outboundPage") is expected_outbound_page


def test_scoped_role_destinations_remain_unchanged():
    assert role_destination(ROLE_BAZAR) == "Gudang Bazar"
    assert role_destination(ROLE_ECOM) == "Gudang E-commerce"
    for role in (ROLE_SUPERADMIN, ROLE_WAREHOUSE_HEAD, ROLE_ADMIN, ROLE_VIEWER):
        assert role_destination(role) == ""


def test_bazar_role_is_scoped_and_not_general_writer():
    for permission in ("bazarView", "bazarOps", "consignmentView", "consignmentHistory"):
        assert has_role_permission(ROLE_BAZAR, permission)
    for permission in ("ecomView", "ecomOps", "currentWrite", "inbound", "outbound", "masterWrite", "users", "settings"):
        assert not has_role_permission(ROLE_BAZAR, permission)


def test_ecommerce_role_is_scoped_and_not_general_writer():
    for permission in ("ecomView", "ecomOps", "consignmentView", "consignmentHistory"):
        assert has_role_permission(ROLE_ECOM, permission)
    for permission in ("bazarView", "bazarOps", "currentWrite", "inbound", "outbound", "masterWrite", "users", "settings"):
        assert not has_role_permission(ROLE_ECOM, permission)


def test_viewer_is_read_only():
    assert has_role_permission(ROLE_VIEWER, "view")
    for permission in ("currentWrite", "inbound", "outbound", "costView", "users", "settings", "corrections", "bazarOps", "ecomOps", "consignmentHistory"):
        assert not has_role_permission(ROLE_VIEWER, permission)


def test_user_models_accept_business_and_legacy_labels():
    for role in (
        "Superadmin", "Kepala Gudang", "Admin Operasional",
        "Petugas Bazar", "Petugas E-commerce", "Viewer",
        "Administrator", "Supervisor", "Operator", "QC", "Pemantau",
    ):
        model = server.UserCreate(name="Test", username="test", role=role, password="123456")
        assert canonical_role(model.role) in EXPECTED_PERMISSIONS
