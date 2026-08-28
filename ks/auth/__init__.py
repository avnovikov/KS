"""Discord auth helpers."""

from __future__ import annotations

from ks.auth.config import AuthConfig, load_auth_config
from ks.auth.deps import require_user
from ks.auth.discord_oauth import discord_authorize_url, exchange_code, fetch_discord_user
from ks.auth.gate import user_has_ui_access
from ks.auth.inventory import UserInventoryPaths, ensure_layout, paths_for
from ks.auth.middleware import ProtectRoutesMiddleware, install_auth
from ks.auth.request_inventory import InventoryBundle, build_inventory_bundle, get_current_inventory
from ks.auth.routes import build_auth_router
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
    "InventoryBundle",
    "ProtectRoutesMiddleware",
    "SESSION_USER_KEY",
    "SessionUser",
    "UserInventoryPaths",
    "build_auth_router",
    "build_inventory_bundle",
    "clear_session_user",
    "discord_authorize_url",
    "ensure_layout",
    "exchange_code",
    "fetch_discord_user",
    "get_current_inventory",
    "get_session_user",
    "install_auth",
    "load_auth_config",
    "paths_for",
    "require_user",
    "set_session_user",
    "session_user_from_dict",
    "session_user_to_dict",
    "user_has_ui_access",
]

