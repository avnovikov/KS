"""API-level survival / sensitivity on Arena + Conquest (no Events UI)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ks.heroes.models import HeroRecord
from ks.heroes.store import HeroStore


def _seed_roster(tmp_path: Path) -> Path:
    store = HeroStore(tmp_path)
    rows = [
        ("Amadeus", "infantry", "legendary", 5, 900_000),
        ("Hilde", "infantry", "legendary", 4, 700_000),
        ("Helga", "infantry", "legendary", 3, 500_000),
        ("Howard", "infantry", "epic", 3, 390_000),
        ("Jabel", "cavalry", "legendary", 4, 650_000),
        ("Chenko", "cavalry", "epic", 3, 400_000),
        ("Gordon", "cavalry", "epic", 2, 230_000),
        ("Marlin", "archer", "legendary", 3, 350_000),
        ("Saul", "archer", "legendary", 2, 250_000),
        ("Diana", "archer", "epic", 3, 450_000),
    ]
    for i, (name, troop, rarity, stars, power) in enumerate(rows):
        store.upsert(
            HeroRecord(
                name=name,
                troop_type=troop,
                rarity=rarity,
                stars=stars,
                pellets=0,
                power=power,
                escorts=5,
                roster_page=0,
                roster_index=i,
                scraped_at="t",
            )
        )
    return tmp_path


def test_optimize_api_includes_survival_and_sensitivity(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ks.heroes.ui.app import create_app

    client = TestClient(create_app(heroes_dir=_seed_roster(tmp_path / "heroes")))
    payload = client.get("/api/optimize").json()
    arena = payload["arena"]
    conquest = payload["conquest"]

    for label, row in (
        ("arena_attack", arena["attack"]),
        ("arena_defense", arena["defense"]),
        ("conquest", conquest),
    ):
        surv = row.get("survival")
        assert surv, f"{label} missing survival"
        assert "score_eff" in surv
        assert "foes" in surv
        sens = surv.get("sensitivity")
        assert sens, f"{label} missing sensitivity"
        assert sens.get("win_summary")
        ids = {v["id"] for v in sens["variants"]}
        assert {
            "baseline",
            "gear_f2_first",
            "gear_back_first",
            "swap_front",
            "swap_front_f1_gear",
        } <= ids
        baseline = next(v for v in sens["variants"] if v["id"] == "baseline")
        assert baseline["delta_score_eff"] == 0.0
