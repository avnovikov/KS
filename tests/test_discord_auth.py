"""Role-gate helpers for Discord write actions."""

from types import SimpleNamespace

from ks.discord.auth import member_has_write_role


def _member_with_roles(*names: str):
    roles = [SimpleNamespace(name=n) for n in names]
    return SimpleNamespace(roles=roles)


def test_member_has_write_role_when_role_present():
    member = _member_with_roles("member", "ks-ops")
    assert member_has_write_role(member, "ks-ops") is True


def test_member_lacks_write_role_when_missing():
    member = _member_with_roles("member")
    assert member_has_write_role(member, "ks-ops") is False


def test_member_has_write_role_is_case_sensitive():
    member = _member_with_roles("KS-OPS")
    assert member_has_write_role(member, "ks-ops") is False
