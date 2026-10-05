"""Google OAuth helpers. The session keeps a verified email and nothing else."""

from __future__ import annotations

from urllib.parse import urlencode

import httpx

from ks.auth.config import AuthConfig
from ks.auth.google_identity import verified_email_from_profile
from ks.auth.session_user import PROVIDER_GOOGLE, SessionUser


_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


def google_redirect_uri(cfg: AuthConfig) -> str:
    if not cfg.public_base_url:
        raise ValueError("public_base_url is required")
    return f"{cfg.public_base_url.rstrip('/')}/auth/google/callback"


def google_authorize_url(cfg: AuthConfig, state: str) -> str:
    if not cfg.google_client_id:
        raise ValueError("google_client_id is required")
    query = urlencode(
        {
            "client_id": cfg.google_client_id,
            "redirect_uri": google_redirect_uri(cfg),
            "response_type": "code",
            "scope": "openid email",
            "state": state,
        }
    )
    return f"{_AUTHORIZE_URL}?{query}"


async def exchange_google_code(cfg: AuthConfig, code: str, http: httpx.AsyncClient) -> dict:
    if not cfg.google_client_id or not cfg.google_client_secret:
        raise ValueError("Google OAuth client id and secret are required")
    response = await http.post(
        _TOKEN_URL,
        data={
            "client_id": cfg.google_client_id,
            "client_secret": cfg.google_client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": google_redirect_uri(cfg),
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Google token response must be a JSON object")
    return payload


async def fetch_google_user(access_token: str, http: httpx.AsyncClient) -> SessionUser:
    response = await http.get(
        _USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
    )
    response.raise_for_status()
    email = verified_email_from_profile(response.json())
    return SessionUser(provider=PROVIDER_GOOGLE, email=email)
