"""Auth configuration loading."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CONFIG_PATH = _PROJECT_ROOT / "config" / "auth.yaml"


@dataclass(frozen=True)
class AuthConfig:
    client_id: str
    client_secret: str
    session_secret: str
    public_base_url: str
    guild_id: str | None
    ui_role: str
    bot_token: str


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def load_auth_config(path: Path | None = None) -> AuthConfig:
    config_path = path if path is not None else _DEFAULT_CONFIG_PATH
    with config_path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError("auth config must be a mapping")

    public_base_url = _optional_text(
        data.get("public_base_url") or os.environ.get("KS_PUBLIC_BASE_URL")
    )
    if public_base_url is None:
        raise ValueError("KS_PUBLIC_BASE_URL is required")

    return AuthConfig(
        client_id=_required_env("DISCORD_OAUTH_CLIENT_ID"),
        client_secret=_required_env("DISCORD_OAUTH_CLIENT_SECRET"),
        session_secret=_required_env("KS_SESSION_SECRET"),
        public_base_url=public_base_url,
        guild_id=_optional_text(data.get("guild_id")),
        ui_role=_optional_text(data.get("ui_role")) or "ks-ui",
        bot_token=_required_env("DISCORD_BOT_TOKEN"),
    )

