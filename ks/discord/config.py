"""Load Discord bot settings from YAML + environment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_DISCORD_CONFIG = _PROJECT_ROOT / "config" / "discord.yaml"


@dataclass(frozen=True)
class DiscordConfig:
    token: str
    write_role: str
    proposal_ttl_seconds: int
    guild_id: int | None
    candidates_json: Path | None


def load_discord_config(path: Path | None = None) -> DiscordConfig:
    config_path = path if path is not None else _DEFAULT_DISCORD_CONFIG
    with config_path.open(encoding="utf-8") as handle:
        data: dict[str, Any] = yaml.safe_load(handle) or {}

    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        raise ValueError(
            "DISCORD_BOT_TOKEN is required (set the environment variable to the bot token)"
        )

    write_role = data.get("write_role") or ""
    if not isinstance(write_role, str) or not write_role.strip():
        raise ValueError("write_role must be a non-empty string")

    ttl = int(data.get("proposal_ttl_seconds", 300))
    if ttl <= 0:
        raise ValueError(f"proposal_ttl_seconds must be positive; got {ttl}")

    guild_raw = data.get("guild_id")
    guild_id = int(guild_raw) if guild_raw is not None else None

    candidates_raw = data.get("candidates_json")
    candidates_json = Path(candidates_raw) if candidates_raw else None

    return DiscordConfig(
        token=token,
        write_role=write_role.strip(),
        proposal_ttl_seconds=ttl,
        guild_id=guild_id,
        candidates_json=candidates_json,
    )
