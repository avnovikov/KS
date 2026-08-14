"""Discord guild access gate helpers."""

from __future__ import annotations

from typing import Any

import httpx

from ks.auth.config import AuthConfig

_DISCORD_API_BASE = "https://discord.com/api/v10"


def _bot_headers(cfg: AuthConfig) -> dict[str, str]:
    return {"Authorization": f"Bot {cfg.bot_token}"}


def _as_string_set(values: Any) -> set[str] | None:
    if not isinstance(values, list):
        return None
    items: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            return None
        items.add(value)
    return items


def _matching_role_ids(payload: Any, role_name: str) -> set[str] | None:
    if not isinstance(payload, list):
        return None

    matching_ids: set[str] = set()
    for item in payload:
        if not isinstance(item, dict):
            return None
        role_id = item.get("id")
        name = item.get("name")
        if not isinstance(role_id, str) or not role_id.strip():
            return None
        if name == role_name:
            matching_ids.add(role_id)
    return matching_ids


async def user_has_ui_access(
    cfg: AuthConfig, discord_user_id: str, http: httpx.AsyncClient
) -> bool:
    if not cfg.guild_id or not discord_user_id.strip():
        return False

    member_url = (
        f"{_DISCORD_API_BASE}/guilds/{cfg.guild_id}/members/{discord_user_id}"
    )
    try:
        member_response = await http.get(member_url, headers=_bot_headers(cfg))
    except httpx.HTTPError:
        return False
    if member_response.status_code == 404 or member_response.is_error:
        return False

    try:
        member_payload = member_response.json()
    except ValueError:
        return False

    member_roles = _as_string_set(
        member_payload.get("roles") if isinstance(member_payload, dict) else None
    )
    if member_roles is None:
        return False

    roles_url = f"{_DISCORD_API_BASE}/guilds/{cfg.guild_id}/roles"
    try:
        roles_response = await http.get(roles_url, headers=_bot_headers(cfg))
    except httpx.HTTPError:
        return False
    if roles_response.status_code == 404 or roles_response.is_error:
        return False

    try:
        roles_payload = roles_response.json()
    except ValueError:
        return False

    matching_role_ids = _matching_role_ids(roles_payload, cfg.ui_role)
    if matching_role_ids is None:
        return False

    return bool(member_roles.intersection(matching_role_ids))
