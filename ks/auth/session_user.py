"""Session user payload helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, MutableMapping

from ks.auth.google_identity import email_path_segment


SESSION_USER_KEY = "ks_user"
PROVIDER_DISCORD = "discord"
PROVIDER_GOOGLE = "google"


@dataclass(frozen=True)
class SessionUser:
    id: str = ""
    username: str = ""
    provider: str = PROVIDER_DISCORD
    email: str = ""


def session_user_to_dict(user: SessionUser) -> dict[str, str]:
    if user.provider == PROVIDER_GOOGLE:
        return {"provider": PROVIDER_GOOGLE, "email": email_path_segment(user.email)}
    if user.provider != PROVIDER_DISCORD:
        raise ValueError(f"unknown auth provider: {user.provider}")
    return {
        "provider": PROVIDER_DISCORD,
        "id": user.id,
        "username": user.username,
    }


def session_user_from_dict(data: dict[str, Any]) -> SessionUser:
    provider = data.get("provider", PROVIDER_DISCORD)
    if provider == PROVIDER_GOOGLE:
        email = data.get("email")
        if not isinstance(email, str):
            raise ValueError("google session email must be a string")
        return SessionUser(provider=PROVIDER_GOOGLE, email=email_path_segment(email))
    if provider != PROVIDER_DISCORD:
        raise ValueError(f"unknown auth provider: {provider}")

    user_id = data.get("id")
    username = data.get("username")
    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("session user id must be a non-empty string")
    if not isinstance(username, str) or not username.strip():
        raise ValueError("session user username must be a non-empty string")
    return SessionUser(id=user_id, username=username, provider=PROVIDER_DISCORD)


def get_session_user(session: MutableMapping[str, Any]) -> SessionUser | None:
    raw = session.get(SESSION_USER_KEY)
    if not isinstance(raw, dict):
        return None
    try:
        return session_user_from_dict(raw)
    except ValueError:
        return None


def set_session_user(session: MutableMapping[str, Any], user: SessionUser) -> None:
    session[SESSION_USER_KEY] = session_user_to_dict(user)


def clear_session_user(session: MutableMapping[str, Any]) -> None:
    session.pop(SESSION_USER_KEY, None)
