"""Role → permission matrix.

Phase 1 uses fixed roles. Per-asset grants and custom roles are Phase 7; callers
should always check a *permission*, never a role name, so that change is local.
"""

from enum import StrEnum


class Role(StrEnum):
    ADMIN = "admin"
    ENGINEER = "engineer"
    OPERATOR = "operator"
    VIEWER = "viewer"


class Perm(StrEnum):
    READ = "read"
    FACTORY_WRITE = "factory.write"
    ASSET_WRITE = "asset.write"
    ASSET_TYPE_WRITE = "asset_type.write"
    DEVICE_WRITE = "device.write"
    DEVICE_TEST = "device.test"
    AUDIT_READ = "audit.read"
    USER_MANAGE = "user.manage"


ROLE_PERMISSIONS: dict[Role, frozenset[Perm]] = {
    Role.VIEWER: frozenset({Perm.READ}),
    Role.OPERATOR: frozenset({Perm.READ, Perm.DEVICE_TEST}),
    Role.ENGINEER: frozenset(
        {
            Perm.READ,
            Perm.FACTORY_WRITE,
            Perm.ASSET_WRITE,
            Perm.ASSET_TYPE_WRITE,
            Perm.DEVICE_WRITE,
            Perm.DEVICE_TEST,
            Perm.AUDIT_READ,
        }
    ),
    Role.ADMIN: frozenset(Perm),
}


def has_perm(role: str, perm: Perm) -> bool:
    try:
        return perm in ROLE_PERMISSIONS[Role(role)]
    except ValueError:
        return False
