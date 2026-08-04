import pytest

from ks.heroes.models import HeroRecord, HeroStats
from ks.heroes.optimize.combat_formation import (
    ALL_SLOTS,
    BACK,
    FRONT,
    hero_base_score,
    solve_combat_formation,
)
from ks.heroes.optimize.stat_contributions import CONQUEST, Share, StatContribution
from ks.heroes.optimize.types import CatalogEntry


def test_slots_match_arena_shape() -> None:
    assert FRONT == ("F1", "F2")
    assert BACK == ("B1", "B2", "B3")
    assert ALL_SLOTS == FRONT + BACK


def _conq(power: float, attack: float = 0.0, health: float = 0.0) -> StatContribution:
    return StatContribution(
        family=CONQUEST,
        estimated=True,
        skills_incomplete=False,
        power=Share(hero=power, skills=0.0, gear=0.0),
        stats={
            "Hero Attack": Share(attack, 0.0, 0.0),
            "Hero Health": Share(health, 0.0, 0.0),
        },
    )


def _roles() -> dict:
    return {"heroes": {}, "placement": {}, "slots": {"carry_slot": "B2"}}


def test_hero_base_score_rises_with_contribution_power() -> None:
    hero = HeroRecord(name="A", stars=3, power=100_000)
    entry = CatalogEntry(name="A", arena_value=50.0)
    low = hero_base_score(
        hero, entry, _roles(), effective_power=100_000,
        contribution=_conq(100_000), side="attack",
    )
    high = hero_base_score(
        hero, entry, _roles(), effective_power=100_000,
        contribution=_conq(900_000), side="attack",
    )
    assert high > low


def test_hero_base_score_rises_with_conquest_stats() -> None:
    hero = HeroRecord(name="A", stars=3, power=100_000)
    entry = CatalogEntry(name="A", arena_value=50.0)
    bare = hero_base_score(
        hero, entry, _roles(), effective_power=100_000,
        contribution=_conq(100_000), side="attack",
    )
    statted = hero_base_score(
        hero, entry, _roles(), effective_power=100_000,
        contribution=_conq(100_000, attack=5000.0, health=40_000.0), side="attack",
    )
    assert statted > bare


def test_hero_base_score_rejects_expedition_contribution() -> None:
    hero = HeroRecord(name="A", stars=3)
    entry = CatalogEntry(name="A")
    wrong = StatContribution("expedition", True, False, Share(1.0, 0.0, 0.0), {})
    with pytest.raises(ValueError, match="conquest"):
        hero_base_score(
            hero, entry, _roles(), effective_power=None,
            contribution=wrong, side="attack",
        )


def _roster() -> tuple[list[HeroRecord], dict[str, CatalogEntry]]:
    names = ["A", "B", "C", "D", "E"]
    heroes = [
        HeroRecord(
            name=n,
            power=100_000 + 10_000 * i,
            troop_type="infantry" if i < 2 else "archer",
            stars=3,
            stats=HeroStats(
                conquest={
                    "Hero Attack": 1000 + i,
                    "Hero Defense": 900 + i,
                    "Hero Health": 9000 + i,
                }
            ),
        )
        for i, n in enumerate(names)
    ]
    catalog = {
        n: CatalogEntry(
            name=n, troop="infantry" if i < 2 else "archers", arena_value=50.0
        )
        for i, n in enumerate(names)
    }
    return heroes, catalog


def test_solve_combat_formation_emits_contributions() -> None:
    heroes, catalog = _roster()
    result = solve_combat_formation(
        "conquest", heroes, catalog, _roles(),
        gear_slot_order=("F1", "F2", "B2", "B1", "B3"),
        with_explanations=False,
    )
    assert result.status == "Optimal"
    assert result.stat_family == "conquest"
    assert set(result.contributions) == set(result.heroes)
    assert result.formation_totals["power"]["total"] == pytest.approx(
        sum(c["power"]["total"] for c in result.contributions.values())
    )
    payload = result.to_dict()
    assert payload["stat_family"] == "conquest"
    assert payload["formation_totals"] == result.formation_totals
