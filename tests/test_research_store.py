"""Tests for ResearchStore and ResearchBonuses."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ks.heroes.research_models import ResearchBonuses, TroopResearchRow
from ks.heroes.research_store import ResearchStore


def test_empty_bonuses_zeroed() -> None:
    b = ResearchBonuses.empty()
    assert b.attack_pct()["infantry"] == 0.0
    assert b.lethality_pct()["archers"] == 0.0


def test_from_dict_rejects_negative() -> None:
    with pytest.raises(ValueError, match="attack_pct"):
        TroopResearchRow.from_dict({"attack_pct": -1})


def test_store_creates_yaml_and_round_trips(tmp_path: Path) -> None:
    store = ResearchStore(tmp_path)
    assert store.yaml_path.is_file()
    store.update_from_dict(
        {
            "note": "Academy Battle sum",
            "squad": {"attack_pct": 5.0, "lethality_pct": 2.0},
            "troops": {
                "infantry": {
                    "attack_pct": 22.5,
                    "defense_pct": 10.0,
                    "lethality_pct": 18.0,
                    "health_pct": 12.0,
                }
            },
        }
    )
    reloaded = ResearchStore(tmp_path)
    # Effective maps include squad on every troop.
    assert reloaded.bonuses().attack_pct()["infantry"] == pytest.approx(27.5)
    assert reloaded.bonuses().attack_pct()["cavalry"] == pytest.approx(5.0)
    assert reloaded.bonuses().lethality_pct()["archers"] == pytest.approx(2.0)
    assert reloaded.bonuses().squad.attack_pct == pytest.approx(5.0)
    assert reloaded.bonuses().note == "Academy Battle sum"
    raw = yaml.safe_load(store.yaml_path.read_text(encoding="utf-8"))
    assert raw["troops"]["cavalry"]["attack_pct"] == 0.0
    assert raw["squad"]["attack_pct"] == 5.0


def test_legacy_yaml_without_squad_loads(tmp_path: Path) -> None:
    path = tmp_path / "research.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "note": "old",
                "troops": {
                    "infantry": {"attack_pct": 1.0},
                    "cavalry": {},
                    "archers": {},
                },
            }
        ),
        encoding="utf-8",
    )
    store = ResearchStore(tmp_path)
    assert store.bonuses().squad.attack_pct == 0.0
    assert store.bonuses().attack_pct()["infantry"] == pytest.approx(1.0)


def test_update_rejects_unknown_troop(tmp_path: Path) -> None:
    store = ResearchStore(tmp_path)
    with pytest.raises(KeyError, match="dragons"):
        store.update_from_dict({"troops": {"dragons": {"attack_pct": 1}}})
