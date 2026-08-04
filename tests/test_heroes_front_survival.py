"""Front-survival math and naive infantry-first opponent placement."""

from ks.heroes.models import HeroRecord, HeroStats
from ks.heroes.optimize.front_survival import (
    hero_tau,
    sanitize_power,
    survival_score,
)
from ks.heroes.optimize.opponent_models import build_naive_max_power
from ks.heroes.optimize.types import CatalogEntry


def test_sanitize_power_drops_ocr_blowup() -> None:
    assert sanitize_power(9_269_680, median_power=300_000) == 300_000.0
    assert sanitize_power(400_000, median_power=300_000) == 400_000.0


def test_sanitize_power_respects_median_factor_and_max_abs() -> None:
    assert sanitize_power(5_000_000, median_power=300_000, max_abs=2_000_000) == 300_000.0
    assert (
        sanitize_power(
            2_500_000,
            median_power=300_000,
            max_abs=10_000_000,
            median_factor=5.0,
        )
        == 300_000.0
    )
    assert (
        sanitize_power(
            1_200_000,
            median_power=300_000,
            max_abs=10_000_000,
            median_factor=5.0,
        )
        == 1_200_000.0
    )


def test_survival_degrades_when_front_weak() -> None:
    strong = survival_score(
        tau_F=1e9,
        tau_B=1e6,
        O=100,
        U_front=100,
        U_back=200,
        lambda_tau=0,
        O_scale=1e5,
    )
    weak = survival_score(
        tau_F=1e5,
        tau_B=1e6,
        O=100,
        U_front=100,
        U_back=200,
        lambda_tau=0,
        O_scale=1e5,
    )
    assert strong.delta > weak.delta
    assert strong.score_eff > weak.score_eff


def test_hero_tau_uses_hp_times_def() -> None:
    hero = HeroRecord(
        name="Howard",
        stats=HeroStats(conquest={"Hero Health": 100, "Hero Defense": 50}),
    )
    assert hero_tau(hero) == 5000.0


def test_arena_attack_gear_order_is_front_first() -> None:
    from ks.heroes.optimize.arena import _ATTACK_GEAR_ORDER
    from ks.heroes.optimize.opponent_models import GEAR_FRONT_FIRST

    assert _ATTACK_GEAR_ORDER == GEAR_FRONT_FIRST
    assert _ATTACK_GEAR_ORDER[0] == "F1"


def test_naive_max_power_puts_infantry_front() -> None:
    heroes = [
        HeroRecord(name="Diana", power=500_000, troop_type="archer"),
        HeroRecord(name="Quinn", power=480_000, troop_type="archer"),
        HeroRecord(name="Jabel", power=450_000, troop_type="cavalry"),
        HeroRecord(name="Howard", power=300_000, troop_type="infantry"),
        HeroRecord(name="Helga", power=290_000, troop_type="infantry"),
        HeroRecord(name="Chenko", power=280_000, troop_type="cavalry"),
    ]
    catalog = {
        h.name: CatalogEntry(name=h.name, troop=h.troop_type, rarity="epic")
        for h in heroes
    }
    roles = {
        "slots": {"front": ["F1", "F2"], "back": ["B1", "B2", "B3"], "carry_slot": "B2"},
        "placement": {},
        "heroes": {
            h.name: {"arena_role": "flex", "arena_value": 50, "tags": []}
            for h in heroes
        },
    }
    foe = build_naive_max_power(heroes, catalog, roles, gear=None)
    assert foe.formation["F1"] in {"Howard", "Helga"}
    assert foe.formation["F2"] in {"Howard", "Helga"}
    assert foe.formation["F1"] != foe.formation["F2"]


import pytest

from ks.heroes.models import HeroRecord
from ks.heroes.optimize.front_survival import rarity_median_powers, sanitize_power


def _h(name: str, power: int | None, rarity: str | None) -> HeroRecord:
    return HeroRecord(name=name, power=power, rarity=rarity)


def test_rarity_median_powers_groups_by_rarity() -> None:
    medians = rarity_median_powers(
        [
            _h("a", 100_000, "epic"),
            _h("b", 300_000, "epic"),
            _h("c", 900_000, "legendary"),
        ]
    )
    assert medians["epic"] == pytest.approx(200_000.0)
    assert medians["legendary"] == pytest.approx(900_000.0)


def test_rarity_median_ignores_blowups_so_they_cannot_poison_their_own_bucket() -> None:
    medians = rarity_median_powers(
        [
            _h("a", 100_000, "epic"),
            _h("b", 300_000, "epic"),
            _h("bad", 9_000_000, "epic"),
        ]
    )
    assert medians["epic"] == pytest.approx(200_000.0)


def test_sanitize_prefers_same_rarity_median_over_roster_median() -> None:
    assert sanitize_power(
        9_000_000,
        median_power=238_487.0,
        rarity="legendary",
        rarity_medians={"legendary": 337_100.0, "epic": 276_600.0},
    ) == pytest.approx(337_100.0)


def test_sanitize_falls_back_to_roster_median_without_same_rarity_peers() -> None:
    assert sanitize_power(
        9_000_000,
        median_power=238_487.0,
        rarity="mythic",
        rarity_medians={"legendary": 337_100.0},
    ) == pytest.approx(238_487.0)


def test_sanitize_is_rarity_insensitive_for_plausible_power() -> None:
    assert sanitize_power(
        250_000,
        median_power=238_487.0,
        rarity="legendary",
        rarity_medians={"legendary": 337_100.0},
    ) == pytest.approx(250_000.0)


from ks.heroes.models import HeroStats
from ks.heroes.optimize.front_survival import formation_tau, hero_tau
from ks.heroes.optimize.stat_contributions import CONQUEST, Share, StatContribution


def _contrib(health: float, defense: float) -> StatContribution:
    return StatContribution(
        family=CONQUEST,
        estimated=True,
        skills_incomplete=False,
        power=Share(0.0, 0.0, 0.0),
        stats={
            "Hero Health": Share(health * 0.6, health * 0.1, health * 0.3),
            "Hero Defense": Share(defense * 0.6, defense * 0.1, defense * 0.3),
        },
    )


def test_hero_tau_uses_contribution_totals() -> None:
    hero = HeroRecord(
        name="A", stats=HeroStats(conquest={"Hero Health": 100, "Hero Defense": 10})
    )
    assert hero_tau(hero, contribution=_contrib(500.0, 50.0)) == pytest.approx(
        500.0 * 50.0
    )


def test_hero_tau_falls_back_to_scrape_without_contribution() -> None:
    hero = HeroRecord(
        name="A", stats=HeroStats(conquest={"Hero Health": 100, "Hero Defense": 10})
    )
    assert hero_tau(hero) == pytest.approx(100.0 * 10.0)


def test_hero_tau_never_below_one() -> None:
    assert hero_tau(HeroRecord(name="A"), contribution=_contrib(0.0, 0.0)) >= 1.0


def test_formation_tau_splits_front_and_back_from_contributions() -> None:
    heroes = {
        n: HeroRecord(
            name=n, stats=HeroStats(conquest={"Hero Health": 10, "Hero Defense": 2})
        )
        for n in ("a", "b", "c", "d", "e")
    }
    formation = {"F1": "a", "F2": "b", "B1": "c", "B2": "d", "B3": "e"}
    contributions = {n: _contrib(100.0, 10.0) for n in heroes}
    tau_f, tau_b, by_hero = formation_tau(
        formation, heroes, None, contributions=contributions
    )
    assert tau_f == pytest.approx(2 * 100.0 * 10.0)
    assert tau_b == pytest.approx(3 * 100.0 * 10.0)
    assert set(by_hero) == set(heroes)
