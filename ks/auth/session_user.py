"""Session user payload helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, MutableMapping


SESSION_USER_KEY = "ks_user"


@dataclass(frozen=True)
class SessionUser:
    id: str
    username: str


def session_user_to_dict(user: SessionUser) -> dict[str, str]:
    return {"id": user.id, "username": user.username}


def session_user_from_dict(data: dict[str, Any]) -> SessionUser:
    user_id = data.get("id")
    username = data.get("username")
    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("session user id must be a non-empty string")
    if not isinstance(username, str) or not username.strip():
        raise ValueError("session user username must be a non-empty string")
    return SessionUser(id=user_id, username=username)


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

