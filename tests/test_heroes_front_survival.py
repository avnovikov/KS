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
