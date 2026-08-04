"""Regression tests for Bugbot findings on PR #26 survival / foe scoring."""

from __future__ import annotations

from ks.heroes.gear_models import GearRecord, GearStats
from ks.heroes.models import HeroRecord, SkillRecord
from ks.heroes.optimize.combat_formation import (
    _provisional_contributions,
    contributions_from_assignment,
)
from ks.heroes.optimize.conquest import _conquest_base_score, ultimate_level_multiplier
from ks.heroes.optimize.opponent_models import (
    _contribution_map,
    _heuristic_offense,
    opponent_from_formation,
)
from ks.heroes.optimize.survival_pipeline import (
    sanitize_hero_powers,
    slot_utilities,
)
from ks.heroes.optimize.types import CatalogEntry


def _cat(name: str, troop: str = "infantry") -> CatalogEntry:
    return CatalogEntry(name=name, troop=troop, rarity="legendary")


def _hero(name: str, power: int, *, ult: int | None = None) -> HeroRecord:
    skills = ()
    if ult is not None:
        skills = (SkillRecord(slot=0, level=ult),)
    return HeroRecord(name=name, power=power, troop_type="infantry", skills=skills)


def _piece(piece_id: str, *, power: int = 50_000) -> GearRecord:
    return GearRecord(
        piece_id=piece_id,
        name=f"Mythic Helm {piece_id}",
        rarity="legendary",
        troop_type="infantry",
        slot="helmet",
        enhancement_level=10,
        power=power,
        stats=GearStats(lethality=12.0, expedition={"Infantry Lethality": 12.0}),
    )


def test_contribution_map_uses_assigned_pieces_not_repooled() -> None:
    """Bugbot high: flattening assigned gear must not re-assign by roster power."""
    heroes = [
        _hero("A", 100_000),
        _hero("B", 200_000),
        _hero("C", 300_000),
        _hero("D", 800_000),
        _hero("E", 900_000),
    ]
    catalog = {h.name: _cat(h.name) for h in heroes}
    formation = {"F1": "A", "F2": "B", "B1": "C", "B2": "D", "B3": "E"}
    best = GearRecord(
        piece_id="best",
        name="Mythic Helm best",
        rarity="legendary",
        troop_type="infantry",
        slot="helmet",
        enhancement_level=10,
        power=250_000,
        stats=GearStats(lethality=40.0, expedition={"Infantry Lethality": 40.0}),
    )
    junk = GearRecord(
        piece_id="junk",
        name="Mythic Helm junk",
        rarity="legendary",
        troop_type="infantry",
        slot="helmet",
        enhancement_level=1,
        power=10_000,
        stats=GearStats(lethality=5.0, expedition={"Infantry Lethality": 5.0}),
    )
    # Give best to weak A, junk to strong E — re-pool by roster power would flip that.
    gear_asg = {
        "A": {"helmet": best},
        "B": {},
        "C": {},
        "D": {},
        "E": {"helmet": junk},
    }
    contributions = _contribution_map(formation, heroes, catalog, gear_asg)
    # A's gear-derived power share must reflect its own assigned piece (best,
    # 250k) — not E's despite E's much higher roster power (900k).
    assert contributions["A"].power.gear > contributions["E"].power.gear
    direct = contributions_from_assignment(
        gear_asg, catalog=catalog, heroes_by_name={h.name: h for h in heroes}
    )
    assert contributions["A"].power.gear == direct["A"].power.gear
    assert contributions["E"].power.gear == direct["E"].power.gear


def test_heuristic_offense_honors_conquest_base_score() -> None:
    """Bugbot high: Conquest foe O must use ultimate-scaled scoring."""
    hero = _hero("Chenko", 300_000, ult=5)
    catalog = {"Chenko": _cat("Chenko")}
    formation = {"F1": "Chenko"}
    by_name = {"Chenko": hero}
    roles: dict = {"heroes": {}, "placement": {}, "slots": {}}
    plain = _heuristic_offense(formation, by_name, catalog, roles)
    conquest = _heuristic_offense(
        formation,
        by_name,
        catalog,
        roles,
        base_score_fn=_conquest_base_score,
    )
    assert ultimate_level_multiplier(hero) > 1.0
    assert conquest > plain
    assert abs(conquest / plain - ultimate_level_multiplier(hero)) < 1e-6


def test_sanitize_hero_powers_catalog_usable_median() -> None:
    """Bugbot medium: median should come from the same cohort ILP uses."""
    heroes = [
        _hero("InCat", 300_000),
        _hero("Also", 310_000),
        _hero("Blowup", 9_000_000),
    ]
    catalog = {"InCat": _cat("InCat"), "Also": _cat("Also")}
    usable = [h for h in heroes if h.name in catalog]
    cleaned = sanitize_hero_powers(usable, roles={})
    assert cleaned["InCat"] == 300_000
    assert cleaned["Also"] == 310_000


def test_slot_utilities_include_gear_bonus() -> None:
    """Bugbot medium: our U_front/U_back must include assigned gear contributions."""
    hero = _hero("Helga", 400_000)
    catalog = {"Helga": _cat("Helga")}
    roles: dict = {"heroes": {}, "placement": {}, "slots": {}}
    formation = {"F1": "Helga"}
    by_name = {"Helga": hero}
    zero = slot_utilities(
        formation,
        by_name,
        catalog,
        roles,
        side="attack",
        base_score_fn=_conquest_base_score,
    )
    piece = GearRecord(
        piece_id="helm",
        name="Mythic Helm",
        rarity="legendary",
        troop_type="infantry",
        slot="helmet",
        enhancement_level=10,
        power=250_000,
        stats=GearStats(conquest={"Hero Attack": 50}),
    )
    gear_asg = {"Helga": {"helmet": piece}}
    contributions = contributions_from_assignment(
        gear_asg, catalog=catalog, heroes_by_name=by_name
    )
    geared = slot_utilities(
        formation,
        by_name,
        catalog,
        roles,
        side="attack",
        base_score_fn=_conquest_base_score,
        contributions=contributions,
    )
    assert geared[0] > zero[0]


def test_provisional_gear_priority_uses_sanitized_power() -> None:
    """Bugbot medium: OCR blow-ups must not steal gear claim priority."""
    blowup = _hero("Helga", 9_269_680)
    normal = _hero("Howard", 400_000)
    usable = [blowup, normal]
    catalog = {h.name: _cat(h.name) for h in usable}
    pieces = [_piece("only", power=100_000)]
    contributions_raw = _provisional_contributions(
        usable, catalog, pieces, "early_game_combat"
    )
    assert (
        contributions_raw["Helga"].power.gear > contributions_raw["Howard"].power.gear
    )
    power_by_name = {"Helga": 100_000, "Howard": 400_000}
    contributions_san = _provisional_contributions(
        usable,
        catalog,
        pieces,
        "early_game_combat",
        power_by_name=power_by_name,
    )
    assert (
        contributions_san["Howard"].power.gear
        > contributions_san["Helga"].power.gear
    )


def test_opponent_from_formation_keeps_explicit_assignment_bonus() -> None:
    heroes = [
        _hero("A", 100_000),
        _hero("B", 200_000),
        _hero("C", 300_000),
        _hero("D", 800_000),
        _hero("E", 900_000),
    ]
    catalog = {h.name: _cat(h.name) for h in heroes}
    formation = {"F1": "A", "F2": "B", "B1": "C", "B2": "D", "B3": "E"}
    best = _piece("best", power=250_000)
    gear_asg = {"A": {"helmet": best}, "B": {}, "C": {}, "D": {}, "E": {}}
    roles: dict = {"heroes": {}, "placement": {}, "slots": {}, "survival": {}}
    foe = opponent_from_formation(
        "test",
        formation,
        heroes,
        catalog,
        roles,
        gear_assignment=gear_asg,
    )
    empty = opponent_from_formation(
        "test",
        formation,
        heroes,
        catalog,
        roles,
        gear_assignment={n: {} for n in "ABCDE"},
    )
    assert foe.heuristic_offense > empty.heuristic_offense
