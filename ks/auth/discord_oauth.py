"""Discord OAuth helper functions."""

from __future__ import annotations

from urllib.parse import urlencode

import httpx

from ks.auth.config import AuthConfig
from ks.auth.session_user import SessionUser


_TOKEN_URL = "https://discord.com/api/v10/oauth2/token"
_USER_URL = "https://discord.com/api/v10/users/@me"
_AUTHORIZE_URL = "https://discord.com/oauth2/authorize"


def discord_authorize_url(cfg: AuthConfig, state: str) -> str:
    if not cfg.public_base_url:
        raise ValueError("public_base_url is required")
    query = urlencode(
        {
            "client_id": cfg.client_id,
            "redirect_uri": f"{cfg.public_base_url.rstrip('/')}/auth/callback",
            "response_type": "code",
            "scope": "identify",
            "state": state,
        }
    )
    return f"{_AUTHORIZE_URL}?{query}"


async def exchange_code(cfg: AuthConfig, code: str, http: httpx.AsyncClient) -> dict:
    response = await http.post(
        _TOKEN_URL,
        data={
            "client_id": cfg.client_id,
            "client_secret": cfg.client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": f"{cfg.public_base_url.rstrip('/')}/auth/callback",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Discord token response must be a JSON object")
    return payload


async def fetch_discord_user(
    access_token: str, http: httpx.AsyncClient
) -> SessionUser:
    response = await http.get(
        _USER_URL,
        headers={"Authorization": f"Bearer {access_token}"},
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Discord user response must be a JSON object")
    user_id = payload.get("id")
    username = payload.get("username")
    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("Discord user id must be a non-empty string")
    if not isinstance(username, str) or not username.strip():
        raise ValueError("Discord username must be a non-empty string")
    return SessionUser(id=user_id, username=username)

