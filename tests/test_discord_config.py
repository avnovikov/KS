"""Discord config loading tests."""

from pathlib import Path

import pytest

from ks.discord.config import DiscordConfig, load_discord_config


def test_load_discord_config_defaults(tmp_path: Path, monkeypatch):
    p = tmp_path / "discord.yaml"
    p.write_text(
        "guild_id: null\n"
        "write_role: ks-ops\n"
        "proposal_ttl_seconds: 300\n"
        "candidates_json: null\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token")
    cfg = load_discord_config(p)
    assert isinstance(cfg, DiscordConfig)
    assert cfg.token == "test-token"
    assert cfg.write_role == "ks-ops"
    assert cfg.proposal_ttl_seconds == 300
    assert cfg.guild_id is None
    assert cfg.candidates_json is None


def test_load_discord_config_requires_token(tmp_path: Path, monkeypatch):
    p = tmp_path / "discord.yaml"
    p.write_text(
        "guild_id: null\n"
        "write_role: ks-ops\n"
        "proposal_ttl_seconds: 300\n"
        "candidates_json: null\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    with pytest.raises(ValueError, match="DISCORD_BOT_TOKEN"):
        load_discord_config(p)


def test_load_discord_config_rejects_empty_write_role(tmp_path: Path, monkeypatch):
    p = tmp_path / "discord.yaml"
    p.write_text(
        "guild_id: null\n"
        "write_role: ''\n"
        "proposal_ttl_seconds: 300\n"
        "candidates_json: null\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "tok")
    with pytest.raises(ValueError, match="write_role"):
        load_discord_config(p)


def test_load_discord_config_parses_candidates_path(tmp_path: Path, monkeypatch):
    candidates = tmp_path / "c.json"
    candidates.write_text("[]", encoding="utf-8")
    p = tmp_path / "discord.yaml"
    p.write_text(
        f"guild_id: 123\n"
        f"write_role: ops\n"
        f"proposal_ttl_seconds: 60\n"
        f"candidates_json: {candidates}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "tok")
    cfg = load_discord_config(p)
    assert cfg.guild_id == 123
    assert cfg.write_role == "ops"
    assert cfg.candidates_json == candidates
