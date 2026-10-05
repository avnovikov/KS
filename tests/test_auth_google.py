"""Google sign-in keeps a verified email and a separate inventory."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import httpx
import pytest


def _cfg(**overrides: object):
    from ks.auth import AuthConfig

    values: dict[str, object] = {
        "client_id": "discord-client",
        "client_secret": "discord-secret",
        "session_secret": "test-session-secret-that-is-32-byt",
        "public_base_url": "https://ks.example.com",
        "guild_id": "guild-999",
        "ui_role": "ks-ui",
        "bot_token": "bot-token",
        "google_client_id": "google-client",
        "google_client_secret": "google-secret",
    }
    values.update(overrides)
    return AuthConfig(**values)  # type: ignore[arg-type]


def _google_state_from_login(html: str) -> str:
    match = re.search(r'href="(https://accounts\.google\.com[^"]+)"', html)
    assert match, "login HTML must include a Google authorize link"
    href = unquote(match.group(1).replace("&amp;", "&"))
    state = parse_qs(urlparse(href).query).get("state", [""])[0]
    assert state, "Google authorize link must include state"
    return state


def test_google_authorize_url_requests_email_scope_only():
    from ks.auth.google_oauth import google_authorize_url

    url = google_authorize_url(_cfg(), state="state-abc")
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert parsed.netloc == "accounts.google.com"
    assert parsed.path == "/o/oauth2/v2/auth"
    assert query["client_id"] == ["google-client"]
    assert query["redirect_uri"] == ["https://ks.example.com/auth/google/callback"]
    assert query["response_type"] == ["code"]
    assert query["scope"] == ["openid email"]
    assert query["state"] == ["state-abc"]
    assert "profile" not in query["scope"][0]


def test_fetch_google_user_keeps_only_verified_email():
    from ks.auth.google_oauth import fetch_google_user
    from ks.auth.session_user import session_user_to_dict

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/userinfo")
        assert request.headers["authorization"] == "Bearer token-1"
        return httpx.Response(
            200,
            json={
                "sub": "google-sub-should-not-stick",
                "email": "Ada@Example.com",
                "email_verified": True,
                "name": "Ada Lovelace",
                "picture": "https://example.com/ada.png",
            },
        )

    async def _fetch():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await fetch_google_user("token-1", http)

    user = asyncio.run(_fetch())

    assert user.provider == "google"
    assert user.email == "ada@example.com"
    assert user.id == ""
    assert user.username == ""
    assert session_user_to_dict(user) == {
        "provider": "google",
        "email": "ada@example.com",
    }


def test_fetch_google_user_rejects_unverified_email():
    from ks.auth.google_oauth import fetch_google_user

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"email": "ada@example.com", "email_verified": False, "sub": "sub"},
        )

    async def _fetch():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await fetch_google_user("token-1", http)

    with pytest.raises(ValueError, match="verified"):
        asyncio.run(_fetch())


def test_google_session_round_trip_stores_only_email():
    from ks.auth.session_user import (
        SessionUser,
        get_session_user,
        session_user_from_dict,
        session_user_to_dict,
    )

    user = SessionUser(
        id="google-sub",
        username="Ada Lovelace",
        provider="google",
        email="Ada@Example.com",
    )
    payload = session_user_to_dict(user)
    assert payload == {"provider": "google", "email": "ada@example.com"}
    assert "name" not in payload
    assert "sub" not in payload

    restored = session_user_from_dict(
        {
            "provider": "google",
            "email": "Ada@Example.com",
            "name": "Ada Lovelace",
            "sub": "google-sub",
            "picture": "https://example.com/ada.png",
        }
    )
    assert restored == SessionUser(provider="google", email="ada@example.com")
    assert session_user_to_dict(restored) == payload

    session: dict[str, object] = {}
    session["ks_user"] = {
        "provider": "google",
        "email": "ada@example.com",
        "name": "Ada Lovelace",
    }
    loaded = get_session_user(session)
    assert loaded is not None
    assert session_user_to_dict(loaded) == {
        "provider": "google",
        "email": "ada@example.com",
    }


def test_legacy_discord_session_without_provider_still_loads():
    from ks.auth.session_user import SessionUser, session_user_from_dict

    user = session_user_from_dict({"id": "123", "username": "alex"})
    assert user == SessionUser(id="123", username="alex", provider="discord", email="")


def test_paths_for_google_email_is_separate_from_discord():
    from ks.auth.inventory import paths_for
    from ks.auth.session_user import SessionUser

    discord_paths = paths_for(
        Path("/inventory/users"),
        SessionUser(id="123", username="alex", provider="discord"),
    )
    google_paths = paths_for(
        Path("/inventory/users"),
        SessionUser(provider="google", email="Ada@Example.com"),
    )

    assert discord_paths.root == Path("/inventory/users/123")
    assert google_paths.root == Path("/inventory/users/google/ada@example.com")
    assert google_paths.troops_path == Path(
        "/inventory/users/google/ada@example.com/troops.yaml"
    )


@pytest.mark.parametrize(
    "email",
    ["../secret", "ada@example.com/../../etc", "not-an-email", "", "ada@example.com\\windows"],
)
def test_paths_for_rejects_unsafe_google_email(email: str):
    from ks.auth.inventory import paths_for
    from ks.auth.session_user import SessionUser

    with pytest.raises(ValueError):
        paths_for(
            Path("/inventory/users"),
            SessionUser(provider="google", email=email),
        )


def test_discord_oauth_state_is_rejected_on_google_callback():
    from ks.auth.routes import make_oauth_state, verify_oauth_state

    cfg = _cfg()
    discord_state = make_oauth_state(cfg, provider="discord")
    google_state = make_oauth_state(cfg, provider="google")

    assert verify_oauth_state(cfg, discord_state, provider="discord") is True
    assert verify_oauth_state(cfg, discord_state, provider="google") is False
    assert verify_oauth_state(cfg, google_state, provider="google") is True
    assert verify_oauth_state(cfg, google_state, provider="discord") is False


def test_load_auth_config_google_is_optional(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from ks.auth import load_auth_config

    auth_yaml = tmp_path / "auth.yaml"
    auth_yaml.write_text(
        "guild_id: 1\nui_role: ks-ui\npublic_base_url: https://ks.example.com\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DISCORD_OAUTH_CLIENT_ID", "discord-client")
    monkeypatch.setenv("DISCORD_OAUTH_CLIENT_SECRET", "discord-secret")
    monkeypatch.setenv("KS_SESSION_SECRET", "session-secret")
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "bot-token")
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_SECRET", raising=False)

    cfg = load_auth_config(auth_yaml)
    assert cfg.google_client_id is None
    assert cfg.google_client_secret is None

    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "google-client")
    with pytest.raises(ValueError, match="GOOGLE_OAUTH_CLIENT_SECRET"):
        load_auth_config(auth_yaml)


def test_login_page_omits_google_until_configured(tmp_path: Path):
    from fastapi.testclient import TestClient
    from ks.heroes.ui.app import create_app

    app = create_app(auth_config=_cfg(google_client_id=None, google_client_secret=None), users_root=tmp_path)
    client = TestClient(app, follow_redirects=False)
    resp = client.get("/auth/login")
    assert resp.status_code == 200
    assert "discord.com" in resp.text
    assert "accounts.google.com" not in resp.text


def test_google_login_creates_email_inventory(tmp_path: Path):
    from fastapi.testclient import TestClient
    from ks.heroes.ui.app import create_app

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "oauth2.googleapis.com/token" in url:
            return httpx.Response(200, json={"access_token": "google-token"})
        if url.endswith("/userinfo"):
            return httpx.Response(
                200,
                json={
                    "sub": "should-not-be-stored",
                    "email": "Ada@Example.com",
                    "email_verified": True,
                    "name": "Ada Lovelace",
                    "picture": "https://example.com/ada.png",
                },
            )
        return httpx.Response(404, json={"error": "not found"})

    app = create_app(
        auth_config=_cfg(public_base_url="http://localhost:8765"),
        users_root=tmp_path,
        http_client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    client = TestClient(app, follow_redirects=False)

    login = client.get("/auth/login")
    assert login.status_code == 200
    assert "accounts.google.com" in login.text
    state = _google_state_from_login(login.text)

    callback = client.get(f"/auth/google/callback?code=test-code&state={state}")
    assert callback.status_code == 302
    assert callback.headers["location"] in ("/", "http://testserver/")

    saved = client.put(
        "/api/troops",
        json={"march_capacity": 42, "infantry": {}, "cavalry": {}, "archers": {}},
    )
    assert saved.status_code == 200, saved.text
    inventory = tmp_path / "google" / "ada@example.com" / "troops.yaml"
    assert inventory.is_file()
    assert "42" in inventory.read_text(encoding="utf-8")
    assert not (tmp_path / "ada@example.com").exists()
    assert not (tmp_path / "should-not-be-stored").exists()


def test_google_callback_rejects_unverified_email(tmp_path: Path):
    from fastapi.testclient import TestClient
    from ks.heroes.ui.app import create_app

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "oauth2.googleapis.com/token" in url:
            return httpx.Response(200, json={"access_token": "google-token"})
        if url.endswith("/userinfo"):
            return httpx.Response(
                200,
                json={"email": "ada@example.com", "email_verified": False},
            )
        return httpx.Response(404, json={"error": "not found"})

    app = create_app(
        auth_config=_cfg(public_base_url="http://localhost:8765"),
        users_root=tmp_path,
        http_client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    client = TestClient(app, follow_redirects=False)
    login = client.get("/auth/login")
    state = _google_state_from_login(login.text)

    callback = client.get(f"/auth/google/callback?code=test-code&state={state}")
    assert callback.status_code == 302
    assert "error=unverified" in callback.headers["location"]
    assert client.get("/api/troops").status_code == 401
    assert not (tmp_path / "google").exists()
