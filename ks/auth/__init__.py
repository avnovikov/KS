"""Discord auth helpers."""

from __future__ import annotations

from ks.auth.config import AuthConfig, load_auth_config
from ks.auth.deps import require_user
from ks.auth.discord_oauth import discord_authorize_url, exchange_code, fetch_discord_user
from ks.auth.session_user import (
    SESSION_USER_KEY,
    SessionUser,
    clear_session_user,
    get_session_user,
    set_session_user,
    session_user_from_dict,
    session_user_to_dict,
)

__all__ = [
    "AuthConfig",
    "SESSION_USER_KEY",
    "SessionUser",
    "clear_session_user",
    "discord_authorize_url",
    "exchange_code",
    "fetch_discord_user",
    "get_session_user",
    "load_auth_config",
    "require_user",
    "set_session_user",
    "session_user_from_dict",
    "session_user_to_dict",
]

