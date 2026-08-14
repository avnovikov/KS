"""Discord OAuth and session-user helper tests."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest


def test_discord_authorize_url_uses_expected_query_shape():
    from ks.auth import AuthConfig, discord_authorize_url

    cfg = AuthConfig(
        client_id="client-123",
        client_secret="client-secret",
        session_secret="session-secret",
        public_base_url="https://ks.example.com",
        guild_id="987654321",
        ui_role="ks-ui",
        bot_token="bot-token",
    )

    url = discord_authorize_url(cfg, state="state-abc")
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert parsed.netloc == "discord.com"
    assert parsed.path == "/oauth2/authorize"
    assert query["client_id"] == ["client-123"]
    assert query["redirect_uri"] == ["https://ks.example.com/auth/callback"]
    assert query["response_type"] == ["code"]
    assert query["scope"] == ["identify"]
    assert query["state"] == ["state-abc"]


def test_session_user_helpers_round_trip():
    from ks.auth.session_user import (
        SessionUser,
        clear_session_user,
        get_session_user,
        set_session_user,
        session_user_from_dict,
        session_user_to_dict,
    )

    user = SessionUser(id="123", username="alex")
    payload = session_user_to_dict(user)

    assert payload == {"id": "123", "username": "alex"}
    assert session_user_from_dict(payload) == user

    session: dict[str, object] = {}
    set_session_user(session, user)
    assert get_session_user(session) == user

    clear_session_user(session)
    assert get_session_user(session) is None


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"id": "123"},
        {"username": "alex"},
        {"id": "", "username": "alex"},
        {"id": "123", "username": ""},
        {"id": 123, "username": "alex"},
    ],
)
def test_session_user_from_dict_rejects_invalid_payload(payload: dict[str, object]):
    from ks.auth.session_user import session_user_from_dict

    with pytest.raises(ValueError):
        session_user_from_dict(payload)  # type: ignore[arg-type]


def test_load_auth_config_reads_yaml_and_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from ks.auth import load_auth_config

    auth_yaml = tmp_path / "auth.yaml"
    auth_yaml.write_text(
        "guild_id: 987654321\n"
        "ui_role: ks-ui\n"
        "public_base_url: https://ks.example.com\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DISCORD_OAUTH_CLIENT_ID", "client-123")
    monkeypatch.setenv("DISCORD_OAUTH_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("KS_SESSION_SECRET", "session-secret")
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "bot-token")

    cfg = load_auth_config(auth_yaml)

    assert cfg.client_id == "client-123"
    assert cfg.client_secret == "client-secret"
    assert cfg.session_secret == "session-secret"
    assert cfg.bot_token == "bot-token"
    assert cfg.guild_id == "987654321"
    assert cfg.ui_role == "ks-ui"
    assert cfg.public_base_url == "https://ks.example.com"

