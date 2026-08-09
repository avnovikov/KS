"""Radiant Spire / mystic-trial floor stub tests (#37)."""

from __future__ import annotations

from pathlib import Path

from ks.heroes.optimize.mystic_trial.floors import load_floors

ROOT = Path(__file__).resolve().parents[1]
FLOORS = ROOT / "config" / "mystic_trial" / "radiant_spire_floors.yaml"


def test_floor_10_enemy_ratio_near_53_27_20() -> None:
    floors = load_floors(FLOORS)
    stub = floors[10]
    assert abs(stub.enemy_ratio["infantry"] - 0.53) < 1e-9
    assert abs(stub.enemy_ratio["cavalry"] - 0.27) < 1e-9
    assert abs(stub.enemy_ratio["archers"] - 0.20) < 1e-9
    assert stub.enemy_power_scale > 0


def test_default_floor_uses_even_split() -> None:
    floors = load_floors(FLOORS)
    stub = floors[1]
    assert abs(stub.enemy_ratio["infantry"] - 1 / 3) < 1e-6
    assert abs(sum(stub.enemy_ratio.values()) - 1.0) < 1e-9


def test_floor_bonuses_default_to_zero_and_override(tmp_path: Path) -> None:
    path = tmp_path / "floors.yaml"
    path.write_text(
        """
defaults:
  enemy_ratio: {infantry: 0.34, cavalry: 0.33, archers: 0.33}
  enemy_power_scale: 1.0
floors:
  1: {}
  2:
    enemy_bonuses:
      infantry: { attack_pct: 120.5, defense_pct: 80, lethality_pct: 40, health_pct: 55 }
""",
        encoding="utf-8",
    )
    floors = load_floors(path)
    assert floors[1].enemy_bonuses["infantry"]["attack_pct"] == 0.0
    assert floors[2].enemy_bonuses["infantry"]["attack_pct"] == 120.5
    assert floors[2].enemy_bonuses["cavalry"]["defense_pct"] == 0.0
    assert "enemy_bonuses" in floors[2].to_dict()
