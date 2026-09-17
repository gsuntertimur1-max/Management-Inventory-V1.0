from __future__ import annotations

"""Compatibility layer for the four-role warehouse access model.

Stored legacy role values are retained so existing API payloads and users remain
compatible, while permissions and labels are consolidated to:
Superadmin, Kepala Gudang, Admin Operasional, Viewer.
"""

import backend.server as server

ROLE_SUPERADMIN = server.ROLE_SUPERADMIN          # Administrator
ROLE_WAREHOUSE_HEAD = server.ROLE_WAREHOUSE_HEAD  # Kepala Gudang
ROLE_ADMIN = server.ROLE_ADMIN                    # Supervisor (stored value)
ROLE_VIEWER = server.ROLE_VIEWER                  # Pemantau (stored value)

LEGACY_ROLE_MAP = {
    "Administrator": ROLE_SUPERADMIN,
    "Superadmin": ROLE_SUPERADMIN,
    "Kepala Gudang": ROLE_WAREHOUSE_HEAD,
    "Supervisor": ROLE_ADMIN,
    "Admin": ROLE_ADMIN,
    "Admin Operasional": ROLE_ADMIN,
    "Operator": ROLE_ADMIN,
    "QC": ROLE_ADMIN,
    "Mandor": ROLE_ADMIN,
    "Pemantau": ROLE_VIEWER,
    "Viewer": ROLE_VIEWER,
    "Viewer / Auditor": ROLE_VIEWER,
}

FOUR_ROLE_LABELS = {
    ROLE_SUPERADMIN: "Superadmin",
    ROLE_WAREHOUSE_HEAD: "Kepala Gudang",
    ROLE_ADMIN: "Admin Operasional",
    ROLE_VIEWER: "Viewer",
}

FOUR_ROLE_PERMISSIONS = {
    ROLE_SUPERADMIN: {
        "masterWrite", "inbound", "outbound", "rebagging", "qc", "users",
        "settings", "costView", "corrections", "warehouseApprove", "currentWrite",
    },
    ROLE_WAREHOUSE_HEAD: {
        "inbound", "outbound", "costView", "corrections", "warehouseApprove",
        "currentWrite",
    },
    ROLE_ADMIN: {
        "inbound", "outbound", "costView", "currentWrite",
    },
    ROLE_VIEWER: set(),
}


def canonical_four_role(role: str | None) -> str:
    value = str(role or ROLE_VIEWER).strip()
    return LEGACY_ROLE_MAP.get(value, ROLE_VIEWER)


def has_four_role_permission(role: str | None, permission: str) -> bool:
    canonical = canonical_four_role(role)
    if permission == "view":
        return canonical in FOUR_ROLE_PERMISSIONS
    if permission == "operations":
        return permission in FOUR_ROLE_PERMISSIONS.get(canonical, set()) or (
            "inbound" in FOUR_ROLE_PERMISSIONS.get(canonical, set())
            or "outbound" in FOUR_ROLE_PERMISSIONS.get(canonical, set())
        )
    return permission in FOUR_ROLE_PERMISSIONS.get(canonical, set())


def configure_four_roles() -> None:
    server.ROLE_ALIASES.clear()
    server.ROLE_ALIASES.update(LEGACY_ROLE_MAP)
    server.ROLE_LABELS.clear()
    server.ROLE_LABELS.update(FOUR_ROLE_LABELS)
    server.ROLE_PERMISSIONS.clear()
    server.ROLE_PERMISSIONS.update(FOUR_ROLE_PERMISSIONS)
    server.canonical_role = canonical_four_role
    server.has_role_permission = has_four_role_permission
    server.WRITE_ROLES = {ROLE_SUPERADMIN, ROLE_WAREHOUSE_HEAD, ROLE_ADMIN}


configure_four_roles()
