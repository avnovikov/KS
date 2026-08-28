"""Sensitivity variants for 5-hero survival (gear claim + front swap)."""

from __future__ import annotations

from ks.heroes.gear_models import GearRecord
from ks.heroes.models import HeroRecord, HeroStats
from ks.heroes.optimize.opponent_models import GEAR_FRONT_FIRST, OpponentLineup
from ks.heroes.optimize.sensitivity import build_sensitivity, win_summary_text
from ks.heroes.optimize.types import CatalogEntry


def _hero(name: str, troop: str, power: int, hp: int = 1000, defense: int = 100) -> HeroRecord:
    return HeroRecord(
        name=name,
        power=power,
        troop_type=troop,
        stats=HeroStats(conquest={"Hero Health": hp, "Hero Defense": defense}),
    )


def _catalog(heroes: list[HeroRecord]) -> dict[str, CatalogEntry]:
    return {
        h.name: CatalogEntry(name=h.name, troop=h.troop_type, rarity="epic")
        for h in heroes
    }


def _roles(heroes: list[HeroRecord]) -> dict:
    return {
        "slots": {
            "front": ["F1", "F2"],
            "back": ["B1", "B2", "B3"],
            "carry_slot": "B2",
        },
        "placement": {},
        "heroes": {
            h.name: {"arena_role": "flex", "arena_value": 50, "tags": []}
            for h in heroes
        },
        "survival": {"enabled": True, "primary_foe": "naive_max_power", "lambda_tau": 0.0},
    }


def _base_score(hero, entry, roles, *, effective_power, contribution):
    return float(effective_power or 0) / 1000.0


def test_build_sensitivity_baseline_delta_zero() -> None:
    heroes = [
        _hero("Helga", "infantry", 200_000, hp=2000, defense=100),
        _hero("Howard", "infantry", 180_000, hp=1500, defense=120),
        _hero("Diana", "archer", 170_000),
        _hero("Jabel", "cavalry", 160_000),
        _hero("Chenko", "cavalry", 150_000),
    ]
    catalog = _catalog(heroes)
    roles = _roles(heroes)
    formation = {
        "F1": "Helga",
        "F2": "Howard",
        "B1": "Diana",
        "B2": "Jabel",
        "B3": "Chenko",
    }
    foe = OpponentLineup(
        model="naive_max_power",
        formation=dict(formation),
        heroes=tuple(formation[s] for s in ("F1", "F2", "B1", "B2", "B3")),
        gear_assignment={},
        heuristic_offense=500.0,
    )
    sens = build_sensitivity(
        formation,
        heroes,
        catalog,
        roles,
        foe,
        side="attack",
        base_score_fn=_base_score,
        gear=None,
        gear_profile="early_game_combat",
        gear_order=GEAR_FRONT_FIRST,
        lambda_tau=0.0,
        O_scale=1.0,
        power_by_name={h.name: h.power for h in heroes},
    )
    by_id = {v["id"]: v for v in sens["variants"]}
    assert "baseline" in by_id
    assert by_id["baseline"]["delta_score_eff"] == 0.0
    assert by_id["swap_front"]["formation"]["F1"] == "Howard"
    assert by_id["swap_front"]["formation"]["F2"] == "Helga"
    assert sens["win_summary"]
    assert "gear_f2_first" in by_id
    assert "gear_back_first" in by_id
    assert "swap_front_f1_gear" in by_id


def _base_score_gear_aware(hero, entry, roles, *, effective_power, contribution):
    power_term = float(effective_power or 0) / 1000.0
    gear_term = float(contribution.power.gear) / 100_000.0 if contribution is not None else 0.0
    return power_term + gear_term


def test_build_sensitivity_rebuilds_contributions_per_variant() -> None:
    """Guards the exact regression build_sensitivity's own docstring warns
    about: reusing one contributions dict across variants would flatten every
    gear-order variant to the baseline's score. Two infantry helmets of very
    different power, one infantry hero front and one back, so that claiming
    order changes which ROW holds the strong piece — not just which hero."""
    heroes = [
        _hero("Helga", "infantry", 200_000, hp=2000, defense=100),
        _hero("Diana", "archer", 170_000),
        _hero("Howard", "infantry", 180_000, hp=1500, defense=120),
        _hero("Jabel", "cavalry", 160_000),
        _hero("Chenko", "cavalry", 150_000),
    ]
    catalog = _catalog(heroes)
    roles = _roles(heroes)
    formation = {
        "F1": "Helga",
        "F2": "Diana",
        "B1": "Howard",
        "B2": "Jabel",
        "B3": "Chenko",
    }
    gear = [
        GearRecord(
            piece_id="strong",
            name="Strong Helm",
            troop_type="infantry",
            slot="helmet",
            rarity="mythic",
            power=500_000,
        ),
        GearRecord(
            piece_id="weak",
            name="Weak Helm",
            troop_type="infantry",
            slot="helmet",
            rarity="rare",
            power=1_000,
        ),
    ]
    # heuristic_offense is set so that O_tau == tau_F (both heroes' front tau
    # totals 300_000), giving s == 0.5 exactly: score_eff = U_front + s *
    # U_back weights front and back roughly evenly, so moving the strong
    # helmet between rows actually moves the needle. (With a small offense
    # s ends up pinned near 1.0, which makes U_front's loss and U_back's gain
    # nearly cancel — a false negative for this regression, not a real one.)
    foe = OpponentLineup(
        model="naive_max_power",
        formation=dict(formation),
        heroes=tuple(formation[s] for s in ("F1", "F2", "B1", "B2", "B3")),
        gear_assignment={},
        heuristic_offense=300_000.0,
    )
    sens = build_sensitivity(
        formation,
        heroes,
        catalog,
        roles,
        foe,
        side="attack",
        base_score_fn=_base_score_gear_aware,
        gear=gear,
        gear_profile="early_game_combat",
        gear_order=GEAR_FRONT_FIRST,
        lambda_tau=0.0,
        O_scale=1.0,
        power_by_name={h.name: h.power for h in heroes},
    )
    by_id = {v["id"]: v for v in sens["variants"]}
    # baseline: front (F1 Helga) claims gear first -> Helga gets the strong
    # helmet, Howard (back) gets the weak one.
    # gear_back_first: back (Howard) claims first -> the strong helmet moves
    # to the back row instead. If the per-variant rebuild were hoisted out of
    # the loop, this would equal baseline's score_eff exactly.
    assert by_id["gear_back_first"]["score_eff"] != by_id["baseline"]["score_eff"]
    assert (
        abs(by_id["gear_back_first"]["score_eff"] - by_id["baseline"]["score_eff"])
        > 1.0
    )


def test_win_summary_mentions_survival_and_delta() -> None:
    text = win_summary_text(
        s=0.35,
        score_eff=440.0,
        foe_front=("Howard", "Forrest"),
        best_alt_label="F2 claims gear first",
        best_alt_delta=2.5,
    )
    assert "0.35" in text or "35%" in text
    assert "Howard" in text
    assert "2.5" in text or "+2.5" in text
