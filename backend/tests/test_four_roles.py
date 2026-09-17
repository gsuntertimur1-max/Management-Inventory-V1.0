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
    ROLE_SUPERADMIN,
    ROLE_VIEWER,
    ROLE_WAREHOUSE_HEAD,
    canonical_four_role,
    has_four_role_permission,
)


def test_legacy_roles_collapse_to_four_roles():
    assert canonical_four_role("Administrator") == ROLE_SUPERADMIN
    assert canonical_four_role("Superadmin") == ROLE_SUPERADMIN
    assert canonical_four_role("Kepala Gudang") == ROLE_WAREHOUSE_HEAD
    for role in ("Supervisor", "Admin", "Admin Operasional", "Operator", "QC", "Mandor"):
        assert canonical_four_role(role) == ROLE_ADMIN
    for role in ("Pemantau", "Viewer", "Viewer / Auditor", "unknown"):
        assert canonical_four_role(role) == ROLE_VIEWER


def test_superadmin_keeps_full_control():
    for permission in ("masterWrite", "currentWrite", "users", "settings", "corrections", "costView"):
        assert has_four_role_permission(ROLE_SUPERADMIN, permission)


def test_warehouse_head_has_operational_control_without_system_admin():
    for permission in ("currentWrite", "inbound", "outbound", "corrections", "costView", "warehouseApprove"):
        assert has_four_role_permission(ROLE_WAREHOUSE_HEAD, permission)
    for permission in ("users", "settings", "masterWrite"):
        assert not has_four_role_permission(ROLE_WAREHOUSE_HEAD, permission)


def test_admin_operasional_can_operate_but_not_administer_system():
    for permission in ("currentWrite", "inbound", "outbound", "costView"):
        assert has_four_role_permission(ROLE_ADMIN, permission)
    for permission in ("users", "settings", "masterWrite", "corrections", "warehouseApprove"):
        assert not has_four_role_permission(ROLE_ADMIN, permission)


def test_viewer_is_read_only():
    assert has_four_role_permission(ROLE_VIEWER, "view")
    for permission in ("currentWrite", "inbound", "outbound", "costView", "users", "settings", "corrections"):
        assert not has_four_role_permission(ROLE_VIEWER, permission)
