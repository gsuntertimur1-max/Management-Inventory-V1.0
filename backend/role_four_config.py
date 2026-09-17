from __future__ import annotations

"""Compatibility layer for warehouse access roles.

Stored legacy role values are retained for API compatibility. Operator and QC are
re-used as internal storage codes for the two tightly-scoped consignment roles:
Petugas Bazar and Petugas E-commerce. UI labels expose the business names only.
"""

from fastapi import Depends, HTTPException

import backend.server as server

ROLE_SUPERADMIN = server.ROLE_SUPERADMIN          # Administrator
ROLE_WAREHOUSE_HEAD = server.ROLE_WAREHOUSE_HEAD  # Kepala Gudang
ROLE_ADMIN = server.ROLE_ADMIN                    # Supervisor
ROLE_BAZAR = server.ROLE_OPERATOR                 # Operator (internal code)
ROLE_ECOM = server.ROLE_QC                        # QC (internal code)
ROLE_VIEWER = server.ROLE_VIEWER                  # Pemantau

LEGACY_ROLE_MAP = {
    "Administrator": ROLE_SUPERADMIN,
    "Superadmin": ROLE_SUPERADMIN,
    "Kepala Gudang": ROLE_WAREHOUSE_HEAD,
    "Supervisor": ROLE_ADMIN,
    "Admin": ROLE_ADMIN,
    "Admin Operasional": ROLE_ADMIN,
    "Operator": ROLE_BAZAR,
    "Petugas Bazar": ROLE_BAZAR,
    "QC": ROLE_ECOM,
    "Petugas E-commerce": ROLE_ECOM,
    "Petugas Ecom": ROLE_ECOM,
    "Mandor": ROLE_ADMIN,
    "Pemantau": ROLE_VIEWER,
    "Viewer": ROLE_VIEWER,
    "Viewer / Auditor": ROLE_VIEWER,
}

ROLE_LABELS = {
    ROLE_SUPERADMIN: "Superadmin",
    ROLE_WAREHOUSE_HEAD: "Kepala Gudang",
    ROLE_ADMIN: "Admin Operasional",
    ROLE_BAZAR: "Petugas Bazar",
    ROLE_ECOM: "Petugas E-commerce",
    ROLE_VIEWER: "Viewer",
}

ROLE_PERMISSIONS = {
    ROLE_SUPERADMIN: {
        "masterWrite", "inbound", "outbound", "rebagging", "qc", "users",
        "settings", "costView", "corrections", "warehouseApprove", "currentWrite",
        "bazarView", "bazarOps", "ecomView", "ecomOps", "consignmentView",
    },
    ROLE_WAREHOUSE_HEAD: {
        "inbound", "outbound", "costView", "corrections", "warehouseApprove",
        "currentWrite", "bazarView", "bazarOps", "ecomView", "ecomOps", "consignmentView",
    },
    ROLE_ADMIN: {
        "inbound", "outbound", "costView", "currentWrite",
        "bazarView", "bazarOps", "ecomView", "ecomOps", "consignmentView",
    },
    ROLE_BAZAR: {"bazarView", "bazarOps", "consignmentView"},
    ROLE_ECOM: {"ecomView", "ecomOps", "consignmentView"},
    ROLE_VIEWER: {"bazarView", "ecomView", "consignmentView"},
}


def canonical_role(role: str | None) -> str:
    value = str(role or ROLE_VIEWER).strip()
    return LEGACY_ROLE_MAP.get(value, ROLE_VIEWER)


def has_role_permission(role: str | None, permission: str) -> bool:
    canonical = canonical_role(role)
    if permission == "view":
        return canonical in ROLE_PERMISSIONS
    if permission == "operations":
        return (
            "inbound" in ROLE_PERMISSIONS.get(canonical, set())
            or "outbound" in ROLE_PERMISSIONS.get(canonical, set())
        )
    if permission == "outboundPage":
        return (
            "outbound" in ROLE_PERMISSIONS.get(canonical, set())
            or "costView" in ROLE_PERMISSIONS.get(canonical, set())
        )
    return permission in ROLE_PERMISSIONS.get(canonical, set())


def role_destination(role: str | None) -> str:
    canonical = canonical_role(role)
    if canonical == ROLE_BAZAR:
        return "Gudang Bazar"
    if canonical == ROLE_ECOM:
        return "Gudang E-commerce"
    return ""


async def require_operational_approval(user: dict = Depends(server.get_current_user)) -> dict:
    canonical = canonical_role(user.get("role"))
    if canonical not in {ROLE_SUPERADMIN, ROLE_WAREHOUSE_HEAD}:
        raise HTTPException(status_code=403, detail="Hanya Superadmin atau Kepala Gudang yang diizinkan")
    return user


def configure_roles() -> None:
    server.ROLE_ALIASES.clear()
    server.ROLE_ALIASES.update(LEGACY_ROLE_MAP)
    server.ROLE_LABELS.clear()
    server.ROLE_LABELS.update(ROLE_LABELS)
    server.ROLE_PERMISSIONS.clear()
    server.ROLE_PERMISSIONS.update(ROLE_PERMISSIONS)
    server.canonical_role = canonical_role
    server.has_role_permission = has_role_permission
    server.WRITE_ROLES = {ROLE_SUPERADMIN, ROLE_WAREHOUSE_HEAD, ROLE_ADMIN}
    server.require_admin = require_operational_approval


configure_roles()
