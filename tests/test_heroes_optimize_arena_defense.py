"""Arena defense optimizer — prefers tanks/heal over pure glass DPS."""

from __future__ import annotations

import pytest

from ks.heroes.models import HeroRecord
from ks.heroes.optimize.arena import (
    load_arena_roles,
    optimize_arena,
    optimize_arena_defense,
)
from ks.heroes.optimize.types import CatalogEntry


def _roster() -> tuple[list[HeroRecord], dict[str, CatalogEntry]]:
    heroes = [
        HeroRecord(name="Helga", stars=1, pellets=0, power=170000),
        HeroRecord(name="Howard", stars=3, pellets=0, power=390000),
        HeroRecord(name="Jabel", stars=3, pellets=1, power=560000),
        HeroRecord(name="Chenko", stars=3, pellets=1, power=330000),
        HeroRecord(name="Saul", stars=2, pellets=0, power=240000),
        HeroRecord(name="Diana", stars=3, pellets=3, power=450000),
        HeroRecord(name="Gordon", stars=2, pellets=5, power=230000),
    ]
    catalog = {
        "Helga": CatalogEntry(
            name="Helga",
            troop="infantry",
            rarity="legendary",
            arena_role="front_fighter",
            arena_value=90,
            arena_tags=("cc", "aoe", "tank"),
        ),
        "Howard": CatalogEntry(
            name="Howard",
            troop="infantry",
            rarity="epic",
            arena_role="front_tank",
            arena_value=85,
            arena_tags=("tank", "team_def"),
        ),
        "Jabel": CatalogEntry(
            name="Jabel",
            troop="cavalry",
            rarity="legendary",
            arena_role="back_cc",
            arena_value=92,
            arena_tags=("cc", "aoe"),
        ),
        "Chenko": CatalogEntry(
            name="Chenko",
            troop="cavalry",
            rarity="epic",
            arena_role="back_dps",
            arena_value=88,
            arena_tags=("aoe", "dps"),
        ),
        "Saul": CatalogEntry(
            name="Saul",
            troop="archer",
            rarity="legendary",
            arena_role="back_cc",
            arena_value=80,
            arena_tags=("cc", "dps"),
        ),
        "Diana": CatalogEntry(
            name="Diana",
            troop="archer",
            rarity="epic",
            arena_role="back_dps",
            arena_value=70,
            arena_tags=("dps", "aoe", "stamina"),
        ),
        "Gordon": CatalogEntry(
            name="Gordon",
            troop="cavalry",
            rarity="epic",
            arena_role="back_support",
            arena_value=75,
            arena_tags=("heal",),
        ),
    }
    return heroes, catalog


def test_arena_defense_includes_heal_and_tanks() -> None:
    heroes, catalog = _roster()
    roles = load_arena_roles("config/arena_roles.yaml", catalog=catalog)
    result = optimize_arena_defense(heroes, catalog, roles)
    assert result.status == "Optimal"
    assert result.side == "defense"
    assert set(result.formation) == {"F1", "F2", "B1", "B2", "B3"}
    front = {result.formation["F1"], result.formation["F2"]}
    assert "Howard" in front or "Helga" in front
    # Offline defense values heal — Gordon should be in the 5.
    assert "Gordon" in result.heroes


def test_optimize_arena_dispatches_sides() -> None:
    heroes, catalog = _roster()
    roles = load_arena_roles("config/arena_roles.yaml", catalog=catalog)
    attack = optimize_arena("attack", heroes, catalog, roles)
    defense = optimize_arena("defense", heroes, catalog, roles)
    assert attack.side == "attack"
    assert defense.side == "defense"
    assert attack.status == "Optimal"
    assert defense.status == "Optimal"


def test_arena_result_dict_carries_contributions() -> None:
    heroes, catalog = _roster()
    roles = load_arena_roles("config/arena_roles.yaml", catalog=catalog)
    # with_survival=False keeps this test on the path Task 4 owns; the
    # survival pipeline is rewired in Task 5, and the end-to-end
    # with-survival path is covered by the Task 9 wiring suite.
    payload = optimize_arena(
        "attack", heroes, catalog, roles, with_survival=False
    ).to_dict()
    assert payload["stat_family"] == "conquest"
    assert set(payload["contributions"]) == set(payload["heroes"])
    for contrib in payload["contributions"].values():
        assert contrib["family"] == "conquest"
        for share in contrib["stats"].values():
            assert share["hero"] >= 0
            assert share["total"] == pytest.approx(
                share["hero"] + share["skills"] + share["gear"]
            )
