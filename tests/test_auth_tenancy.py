"""AUTH-05: Request-scoped multi-tenant store isolation tests.

Critical invariant: when auth is on, user A's inventory data is never
visible to user B even when both use the same users_root directory.

Tests here prove isolation via the full HTTP stack (TestClient + auth
middleware + ContextVar binding).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest


# ---------------------------------------------------------------------------
# Shared helpers (duplicated from test_auth_routes for test independence)
# ---------------------------------------------------------------------------

def _make_cfg():
    from ks.auth import AuthConfig

    return AuthConfig(
        client_id="test-client-id",
        client_secret="test-client-secret",
        session_secret="test-session-secret-that-is-32-byt",
        public_base_url="http://localhost:8765",
        guild_id="guild-999",
        ui_role="ks-ui",
        bot_token="bot-test-token",
    )


def _mock_discord_transport(
    *,
    user_id: str,
    username: str,
    member_roles: list[str] | None = None,
    guild_roles: list[dict[str, str]] | None = None,
) -> httpx.MockTransport:
    if member_roles is None:
        member_roles = ["role-ui-id"]
    if guild_roles is None:
        guild_roles = [{"id": "role-ui-id", "name": "ks-ui"}]

    def _handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "oauth2/token" in url:
            return httpx.Response(200, json={"access_token": "tok"}, request=request)
        if "users/@me" in url:
            return httpx.Response(
                200, json={"id": user_id, "username": username}, request=request
            )
        if "members/" in url:
            return httpx.Response(200, json={"roles": member_roles}, request=request)
        if "/roles" in url:
            return httpx.Response(200, json=guild_roles, request=request)
        return httpx.Response(404, json={}, request=request)

    return httpx.MockTransport(_handler)


def _login(client, state: str) -> None:
    """Visit /auth/login (stores state) then simulate Discord callback."""
    client.get("/auth/login")
    resp = client.get(f"/auth/callback?code=code&state={state}")
    assert resp.status_code == 302, f"login failed: {resp.status_code} {resp.text}"


# ---------------------------------------------------------------------------
# Test 1: Two users, one app instance — troops are isolated
# ---------------------------------------------------------------------------

def test_troops_isolated_between_users(tmp_path: Path, monkeypatch: Any) -> None:
    """User A writes troops; User B on the same server sees default (not A's)."""
    import secrets as _secrets

    call_n = [0]

    def _state(*a: Any, **kw: Any) -> str:
        call_n[0] += 1
        return f"st{call_n[0]}"

    monkeypatch.setattr(_secrets, "token_urlsafe", _state)

    from fastapi.testclient import TestClient
    from ks.heroes.ui.app import create_app

    # ---- User A ----
    app_a = create_app(
        auth_config=_make_cfg(),
        users_root=tmp_path,
        http_client_factory=lambda: httpx.AsyncClient(
            transport=_mock_discord_transport(user_id="userA", username="alice")
        ),
    )
    client_a = TestClient(app_a, follow_redirects=False)
    _login(client_a, f"st{call_n[0] + 1}")

    # User A writes a distinctive march capacity
    resp = client_a.put(
        "/api/troops",
        json={"march_capacity": 777_000, "infantry": {}, "cavalry": {}, "archers": {}},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["troops"]["march_capacity"] == 777_000

    # Filesystem evidence: userA dir created
    assert (tmp_path / "userA" / "troops.yaml").is_file()

    # ---- User B (same users_root, separate app instance) ----
    app_b = create_app(
        auth_config=_make_cfg(),
        users_root=tmp_path,
        http_client_factory=lambda: httpx.AsyncClient(
            transport=_mock_discord_transport(user_id="userB", username="bob")
        ),
    )
    client_b = TestClient(app_b, follow_redirects=False)
    _login(client_b, f"st{call_n[0] + 1}")

    # User B reads troops — must NOT see user A's 777_000
    resp_b = client_b.get("/api/troops")
    assert resp_b.status_code == 200, resp_b.text
    troops_b = resp_b.json()["troops"]
    assert troops_b.get("march_capacity") != 777_000, (
        f"User B should not see User A's troops (march_capacity={troops_b.get('march_capacity')})"
    )

    # Filesystem evidence: userB dir created, separate from userA
    assert (tmp_path / "userB" / "troops.yaml").is_file()
    assert (tmp_path / "userA").is_dir()
    assert (tmp_path / "userB").is_dir()
    assert tmp_path / "userA" != tmp_path / "userB"


# ---------------------------------------------------------------------------
# Test 2: Auth on — troops endpoint is no longer 503
# ---------------------------------------------------------------------------

def test_auth_on_troops_endpoint_no_longer_503(tmp_path: Path, monkeypatch: Any) -> None:
    """Authenticated request must not return 503 for /api/troops."""
    import secrets as _secrets

    monkeypatch.setattr(_secrets, "token_urlsafe", lambda *a, **kw: "fixed-state")

    from fastapi.testclient import TestClient
    from ks.heroes.ui.app import create_app

    app = create_app(
        auth_config=_make_cfg(),
        users_root=tmp_path,
        http_client_factory=lambda: httpx.AsyncClient(
            transport=_mock_discord_transport(user_id="user1", username="alice")
        ),
    )
    client = TestClient(app, follow_redirects=False)
    _login(client, "fixed-state")

    resp = client.get("/api/troops")
    assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text}"
    assert "troops" in resp.json()


# ---------------------------------------------------------------------------
# Test 3: Auth on — inventory page no longer 404
# ---------------------------------------------------------------------------

def test_auth_on_inventory_troops_page_is_200(tmp_path: Path, monkeypatch: Any) -> None:
    """Authenticated GET /inventory/troops must return 200 in auth mode."""
    import secrets as _secrets

    monkeypatch.setattr(_secrets, "token_urlsafe", lambda *a, **kw: "fixed-state")

    from fastapi.testclient import TestClient
    from ks.heroes.ui.app import create_app

    app = create_app(
        auth_config=_make_cfg(),
        users_root=tmp_path,
        http_client_factory=lambda: httpx.AsyncClient(
            transport=_mock_discord_transport(user_id="user1", username="alice")
        ),
    )
    client = TestClient(app, follow_redirects=False)
    _login(client, "fixed-state")

    resp = client.get("/inventory/troops")
    assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text}"


# ---------------------------------------------------------------------------
# Test 4: Per-user dirs created under users_root
# ---------------------------------------------------------------------------

def test_per_user_dirs_created(tmp_path: Path, monkeypatch: Any) -> None:
    """ensure_layout creates gear, heroes, governor, research, troops.yaml."""
    import secrets as _secrets

    monkeypatch.setattr(_secrets, "token_urlsafe", lambda *a, **kw: "fixed-state")

    from fastapi.testclient import TestClient
    from ks.heroes.ui.app import create_app

    app = create_app(
        auth_config=_make_cfg(),
        users_root=tmp_path,
        http_client_factory=lambda: httpx.AsyncClient(
            transport=_mock_discord_transport(user_id="user42", username="tester")
        ),
    )
    client = TestClient(app, follow_redirects=False)
    _login(client, "fixed-state")

    # Trigger any authenticated endpoint to cause ensure_layout
    client.get("/api/troops")

    user_root = tmp_path / "user42"
    assert (user_root / "gear" / "full-run").is_dir()
    assert (user_root / "heroes" / "full-run").is_dir()
    assert (user_root / "governor" / "full-run").is_dir()
    assert (user_root / "research" / "full-run").is_dir()
    assert (user_root / "troops.yaml").is_file()


# ---------------------------------------------------------------------------
# Test 5: InventoryBundle exported from ks.auth
# ---------------------------------------------------------------------------

def test_inventory_bundle_exported() -> None:
    from ks.auth import InventoryBundle, build_inventory_bundle, get_current_inventory

    assert InventoryBundle is not None
    assert callable(build_inventory_bundle)
    assert callable(get_current_inventory)
    assert get_current_inventory() is None  # auth-off context
