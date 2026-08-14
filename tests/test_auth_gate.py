"""Tests for Discord guild access gating."""

from __future__ import annotations

import asyncio

import httpx


def _auth_config():
    from ks.auth import AuthConfig

    return AuthConfig(
        client_id="client-123",
        client_secret="client-secret",
        session_secret="session-secret",
        public_base_url="https://ks.example.com",
        guild_id="guild-123",
        ui_role="ks-ui",
        bot_token="bot-token",
    )


def _run_user_has_ui_access(responses):
    from ks.auth.gate import user_has_ui_access

    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        try:
            status_code, payload = responses[len(calls) - 1]
        except IndexError as exc:  # pragma: no cover - defensive test helper
            raise AssertionError("unexpected extra request") from exc
        return httpx.Response(status_code, json=payload, request=request)

    transport = httpx.MockTransport(handler)
    cfg = _auth_config()

    async def run() -> tuple[bool, list[httpx.Request]]:
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://discord.com",
        ) as client:
            result = await user_has_ui_access(cfg, "user-456", client)
        return result, calls

    return asyncio.run(run())


def test_user_has_ui_access_allows_exact_role_name_match():
    result, calls = _run_user_has_ui_access(
        [
            (200, {"roles": ["role-1", "role-2"]}),
            (200, [{"id": "role-2", "name": "ks-ui"}]),
        ]
    )

    assert result is True
    assert [request.url.path for request in calls] == [
        "/api/v10/guilds/guild-123/members/user-456",
        "/api/v10/guilds/guild-123/roles",
    ]
    assert all(
        request.headers["authorization"] == "Bot bot-token" for request in calls
    )


def test_user_has_ui_access_denies_when_role_name_does_not_match_exactly():
    result, calls = _run_user_has_ui_access(
        [
            (200, {"roles": ["role-1"]}),
            (200, [{"id": "role-1", "name": "Ks-Ui"}]),
        ]
    )

    assert result is False
    assert len(calls) == 2


def test_user_has_ui_access_denies_when_member_is_missing():
    result, calls = _run_user_has_ui_access([(404, {"message": "Unknown Member"})])

    assert result is False
    assert [request.url.path for request in calls] == [
        "/api/v10/guilds/guild-123/members/user-456",
    ]


def test_user_has_ui_access_denies_when_roles_lookup_fails():
    result, calls = _run_user_has_ui_access(
        [
            (200, {"roles": ["role-1"]}),
            (500, {"message": "Server Error"}),
        ]
    )

    assert result is False
    assert [request.url.path for request in calls] == [
        "/api/v10/guilds/guild-123/members/user-456",
        "/api/v10/guilds/guild-123/roles",
    ]
