"""Smoke tests for Discord bot wiring (no live Discord network)."""

from pathlib import Path

from ks.config import load_config
from ks.discord.bot import APPROVE_PREFIX, REJECT_PREFIX, ConfirmView, KSBot, main
from ks.discord.config import DiscordConfig


def test_confirm_view_custom_ids():
    view = ConfirmView("abc123", timeout=30.0)
    customs = [item.custom_id for item in view.children]
    assert f"{APPROVE_PREFIX}abc123" in customs
    assert f"{REJECT_PREFIX}abc123" in customs


def test_ksbot_builds_with_fixture_config(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "tok")
    discord_cfg = DiscordConfig(
        token="tok",
        write_role="ks-ops",
        proposal_ttl_seconds=60,
        guild_id=None,
        candidates_json=Path("tests/fixtures/candidates.json"),
    )
    app_cfg = load_config(Path("config/params.yaml"))
    bot = KSBot(discord_cfg, app_cfg)
    proposal = bot._build_proposal()
    assert proposal.kind == "gather"


def test_main_missing_token_exits_1(monkeypatch, capsys):
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    code = main([])
    assert code == 1
    err = capsys.readouterr().err
    assert "DISCORD_BOT_TOKEN" in err
