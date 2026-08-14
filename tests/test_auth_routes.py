"""Auth routes + protect middleware integration tests.

Priority acceptance tests:
  1. auth off  — existing create_app with tmp gear/heroes still 200
  2. auth on   — unauthenticated GET /inventory/gear → 302 /auth/login
  3. auth on   — unauthenticated GET /api/troops → 401 {"detail":"unauthorized"}
  4. auth on   — mocked callback success sets session; subsequent protected
                 request is not 401/302-to-login
  5. auth on   — denied role → callback returns 403, no session cookie
"""

from __future__ import annotations

import httpx
import pytest
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Helpers
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


def _make_auth_app(users_root: Path):
    from ks.heroes.ui.app import create_app

    return create_app(auth_config=_make_cfg(), users_root=users_root)


def _mock_discord_transport(
    *,
    access_token: str = "test-access-token",
    user_id: str = "user-123",
    username: str = "testuser",
    member_roles: list[str] | None = None,
    guild_roles: list[dict[str, str]] | None = None,
    member_status: int = 200,
) -> httpx.MockTransport:
    """Return a MockTransport that simulates Discord OAuth + guild API calls."""

    if member_roles is None:
        member_roles = ["role-ui-id"]
    if guild_roles is None:
        guild_roles = [{"id": "role-ui-id", "name": "ks-ui"}]

    def _handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "oauth2/token" in url:
            return httpx.Response(
                200,
                json={"access_token": access_token},
                request=request,
            )
        if "users/@me" in url:
            return httpx.Response(
                200,
                json={"id": user_id, "username": username},
                request=request,
            )
        if "members/" in url:
            if member_status != 200:
                return httpx.Response(member_status, json={}, request=request)
            return httpx.Response(
                200,
                json={"roles": member_roles},
                request=request,
            )
        if "/roles" in url:
            return httpx.Response(200, json=guild_roles, request=request)
        return httpx.Response(404, json={"error": "not found"}, request=request)

    return httpx.MockTransport(_handler)


def _mock_http_factory(transport: httpx.MockTransport):
    """Return a callable that creates AsyncClient with the given transport."""
    return lambda: httpx.AsyncClient(transport=transport)


# ---------------------------------------------------------------------------
# Test 1: auth off — existing create_app keeps working
# ---------------------------------------------------------------------------


def test_auth_off_create_app_with_tmp_gear_is_200(tmp_path: Path) -> None:
    """Auth-off create_app still serves /inventory/troops."""
    from fastapi.testclient import TestClient
    from ks.heroes.ui.app import create_app

    app = create_app(gear_dir=tmp_path)
    client = TestClient(app)
    resp = client.get("/inventory/troops")
    assert resp.status_code == 200


def test_auth_off_create_app_raises_without_dirs() -> None:
    """No auth, no dirs → still raises ValueError."""
    from ks.heroes.ui.app import create_app

    with pytest.raises(ValueError, match="gear_dir or heroes_dir"):
        create_app()


# ---------------------------------------------------------------------------
# Test 2: auth on — unauthenticated HTML → 302 /auth/login
# ---------------------------------------------------------------------------


def test_auth_on_unauthenticated_html_redirects_to_login(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    app = _make_auth_app(tmp_path)
    client = TestClient(app, follow_redirects=False)
    resp = client.get("/inventory/gear")
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["location"]


def test_auth_on_unauthenticated_root_redirects_to_login(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    app = _make_auth_app(tmp_path)
    client = TestClient(app, follow_redirects=False)
    resp = client.get("/")
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["location"]


# ---------------------------------------------------------------------------
# Test 3: auth on — unauthenticated /api/* → 401 JSON
# ---------------------------------------------------------------------------


def test_auth_on_unauthenticated_api_troops_returns_401(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    app = _make_auth_app(tmp_path)
    client = TestClient(app)
    resp = client.get("/api/troops")
    assert resp.status_code == 401
    assert resp.json() == {"detail": "unauthorized"}


def test_auth_on_unauthenticated_api_gear_returns_401(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    app = _make_auth_app(tmp_path)
    client = TestClient(app)
    resp = client.get("/api/gear")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "unauthorized"


# ---------------------------------------------------------------------------
# Test 4: auth on — mocked callback success sets session; protected route passes
# ---------------------------------------------------------------------------


def test_auth_login_page_returns_html(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    app = _make_auth_app(tmp_path)
    client = TestClient(app, follow_redirects=False)
    resp = client.get("/auth/login")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    # Login page should contain a link to Discord authorize
    assert "discord.com" in resp.text


def test_auth_on_callback_success_sets_session(tmp_path: Path, monkeypatch: Any) -> None:
    """Successful callback → session cookie; subsequent API call is not 401."""
    import secrets as _secrets
    from fastapi.testclient import TestClient
    from ks.auth import routes as routes_mod

    monkeypatch.setattr(_secrets, "token_urlsafe", lambda *a, **kw: "fixed-state")

    transport = _mock_discord_transport()
    factory = _mock_http_factory(transport)

    app = _make_auth_app(tmp_path)
    # Inject mock HTTP factory into the router via build_auth_router factory arg.
    # We rebuild the app with the factory injected.
    from ks.auth.routes import build_auth_router
    from ks.heroes.ui.app import create_app

    app = create_app(
        auth_config=_make_cfg(),
        users_root=tmp_path,
        http_client_factory=factory,
    )

    client = TestClient(app, follow_redirects=False)

    # Step 1: Visit /auth/login — sets oauth_state = "fixed-state" in session
    resp = client.get("/auth/login")
    assert resp.status_code == 200

    # Step 2: Simulate Discord redirecting back with code + matching state
    resp = client.get("/auth/callback?code=test-code&state=fixed-state")
    # Should redirect to / on success
    assert resp.status_code == 302
    assert resp.headers["location"] in ("/", "http://testserver/")

    # Step 3: Subsequent API call — middleware sees user in session → not 401
    resp = client.get("/api/troops")
    assert resp.status_code != 401
    assert resp.status_code != 302  # not redirected to login


# ---------------------------------------------------------------------------
# Test 5: auth on — denied role → 403, no session
# ---------------------------------------------------------------------------


def test_auth_on_callback_denied_role_returns_403_no_session(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """When user_has_ui_access returns False, callback is 403 (no session set)."""
    import secrets as _secrets

    monkeypatch.setattr(_secrets, "token_urlsafe", lambda *a, **kw: "fixed-state")

    # Guild roles do not include "ks-ui"
    transport = _mock_discord_transport(
        guild_roles=[{"id": "role-other-id", "name": "other-role"}]
    )
    factory = _mock_http_factory(transport)

    from ks.heroes.ui.app import create_app

    app = create_app(
        auth_config=_make_cfg(),
        users_root=tmp_path,
        http_client_factory=factory,
    )

    from fastapi.testclient import TestClient

    client = TestClient(app, follow_redirects=False)

    # Set oauth_state
    resp = client.get("/auth/login")
    assert resp.status_code == 200

    # Callback — denied
    resp = client.get("/auth/callback?code=test-code&state=fixed-state")
    assert resp.status_code == 403

    # No session → subsequent request still blocked
    resp = client.get("/api/troops")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Test: /auth/* routes are public (no redirect/401 loop)
# ---------------------------------------------------------------------------


def test_auth_routes_are_public_without_session(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    app = _make_auth_app(tmp_path)
    client = TestClient(app, follow_redirects=False)
    # /auth/login must not redirect to itself
    resp = client.get("/auth/login")
    assert resp.status_code == 200


def test_logout_clears_session(tmp_path: Path, monkeypatch: Any) -> None:
    import secrets as _secrets

    monkeypatch.setattr(_secrets, "token_urlsafe", lambda *a, **kw: "fixed-state")

    transport = _mock_discord_transport()
    factory = _mock_http_factory(transport)

    from ks.heroes.ui.app import create_app

    app = create_app(
        auth_config=_make_cfg(),
        users_root=tmp_path,
        http_client_factory=factory,
    )

    from fastapi.testclient import TestClient

    client = TestClient(app, follow_redirects=False)

    # Log in
    client.get("/auth/login")
    client.get("/auth/callback?code=test-code&state=fixed-state")

    # Verify logged in
    resp = client.get("/api/troops")
    assert resp.status_code != 401

    # Logout via POST (CSRF-safe)
    resp = client.post("/auth/logout")
    assert resp.status_code in (302, 303)

    # Should be blocked again
    resp = client.get("/api/troops")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Test: create_app with auth_config allows no gear/heroes dirs
# ---------------------------------------------------------------------------


def test_auth_on_create_app_allows_no_inventory_dirs(tmp_path: Path) -> None:
    """Auth-on create_app succeeds without gear_dir or heroes_dir."""
    from ks.heroes.ui.app import create_app

    # Should not raise
    app = create_app(auth_config=_make_cfg(), users_root=tmp_path)
    assert app is not None


# ---------------------------------------------------------------------------
# Test: GET /auth/logout redirects to login (does not clear session)
# ---------------------------------------------------------------------------


def test_logout_get_redirects_to_login(tmp_path: Path, monkeypatch: Any) -> None:
    """GET /auth/logout must redirect to login (not error), and not clear session.

    The true logout action requires a POST to prevent CSRF; the GET handler
    is a safe fallback for users who type the URL directly.
    """
    import secrets as _secrets

    monkeypatch.setattr(_secrets, "token_urlsafe", lambda *a, **kw: "fixed-state")

    transport = _mock_discord_transport()
    factory = _mock_http_factory(transport)

    from fastapi.testclient import TestClient
    from ks.heroes.ui.app import create_app

    app = create_app(
        auth_config=_make_cfg(),
        users_root=tmp_path,
        http_client_factory=factory,
    )
    client = TestClient(app, follow_redirects=False)

    # Log in first
    client.get("/auth/login")
    client.get("/auth/callback?code=test-code&state=fixed-state")
    resp = client.get("/api/troops")
    assert resp.status_code not in (401, 302)

    # GET /auth/logout must redirect to login (harmless)
    resp = client.get("/auth/logout")
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["location"]


# ---------------------------------------------------------------------------
# Test: Session secure flag is set for https:// base URLs
# ---------------------------------------------------------------------------


def test_session_https_only_flag_set_for_https_base_url(tmp_path: Path) -> None:
    """install_auth sets https_only=True when public_base_url is https://."""
    from ks.auth import AuthConfig
    from ks.heroes.ui.app import create_app

    https_cfg = AuthConfig(
        client_id="test-client-id",
        client_secret="test-client-secret",
        session_secret="test-session-secret-that-is-32-byt",
        public_base_url="https://example.com",
        guild_id="guild-999",
        ui_role="ks-ui",
        bot_token="bot-test-token",
    )
    app = create_app(auth_config=https_cfg, users_root=tmp_path)

    # Inspect middleware stack: SessionMiddleware must have https_only=True.
    from starlette.middleware.sessions import SessionMiddleware

    found = False
    for layer in app.middleware_stack.__dict__.values() if hasattr(app.middleware_stack, "__dict__") else []:
        if isinstance(layer, SessionMiddleware) and getattr(layer, "https_only", False):
            found = True
            break

    # Fallback: check via the user_middleware list on the app itself.
    if not found:
        for m in getattr(app, "user_middleware", []):
            cls = getattr(m, "cls", None)
            kwargs = getattr(m, "kwargs", {})
            if cls is SessionMiddleware and kwargs.get("https_only") is True:
                found = True
                break

    assert found, (
        "SessionMiddleware should be installed with https_only=True for https:// base URLs"
    )
