"""Tests for masking Discord user ids in UI path display."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_mask_discord_id_in_path_redacts_snowflake() -> None:
    from ks.heroes.ui.path_display import mask_discord_id_in_path

    raw = "/var/lib/ks/users/1462758266772652142/heroes/full-run"
    masked = mask_discord_id_in_path(raw)
    assert "1462758266772652142" not in masked
    assert "***" in masked
    assert masked.startswith("/var/lib/ks/users/")
    assert masked.endswith("/heroes/full-run")
    assert "146" in masked
    assert "2142" in masked


def test_mask_discord_id_in_path_leaves_normal_paths() -> None:
    from ks.heroes.ui.path_display import mask_discord_id_in_path

    raw = "/Users/alexei/KS/data/heroes/full-run"
    assert mask_discord_id_in_path(raw) == raw


def test_inventory_heroes_page_meta_masks_user_id(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ks.heroes.models import HeroRecord
    from ks.heroes.store import HeroStore
    from ks.heroes.ui.app import create_app

    users = tmp_path / "users" / "1462758266772652142" / "heroes" / "full-run"
    users.mkdir(parents=True)
    HeroStore(users).upsert(
        HeroRecord(name="Helga", troop_type="infantry", rarity="legendary")
    )
    client = TestClient(create_app(heroes_dir=users))
    page = client.get("/inventory/heroes")
    assert page.status_code == 200
    assert "1462758266772652142" not in page.text
    assert "***" in page.text
