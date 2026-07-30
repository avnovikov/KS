"""Discord role-gate helpers for write actions."""

from __future__ import annotations

from typing import Any, Protocol


class _Role(Protocol):
    name: str


class _Member(Protocol):
    roles: list[_Role]


def member_has_write_role(member: _Member | Any, write_role: str) -> bool:
    """Return True if ``member`` has a role whose name equals ``write_role``.

    Role names are compared exactly (case-sensitive), matching Discord's
    role name string as configured in ``config/discord.yaml``.
    """
    if not write_role:
        raise ValueError("write_role must be a non-empty string")
    roles = getattr(member, "roles", None)
    if not roles:
        return False
    return any(getattr(role, "name", None) == write_role for role in roles)
