"""Conquest optimizer: 5 heroes, 2F+3B, Conquest-skill aware scoring + survival."""

from __future__ import annotations

from typing import Any

from ks.heroes.gear_models import GearRecord
from ks.heroes.models import HeroRecord
from ks.heroes.optimize.combat_formation import (
    CombatFormationResult,
    hero_base_score,
    placement_mult,
    solve_combat_formation,
)
from ks.heroes.optimize.opponent_models import GEAR_FRONT_FIRST
from ks.heroes.optimize.survival_pipeline import attach_survival
from ks.heroes.optimize.types import CatalogEntry

CONQUEST_GEAR_ORDER = GEAR_FRONT_FIRST
_ULTIMATE_LEVEL_WEIGHT = 0.04


def ultimate_level_multiplier(hero: HeroRecord) -> float:
    """Return score multiplier based on hero's ultimate skill (slot 0) level.

    Returns 1.0 when no slot-0 skill is present. Each level adds
    ``_ULTIMATE_LEVEL_WEIGHT`` (0.04), capped at level 10.
    """
    for skill in hero.skills:
        if skill.slot == 0 and skill.level is not None:
            level = int(skill.level)
            if level < 0:
                raise ValueError(
                    f"skill level must be >= 0; got {level} for {hero.name}"
                )
            return 1.0 + _ULTIMATE_LEVEL_WEIGHT * min(level, 10)
    return 1.0


def _conquest_base_score(
    hero: HeroRecord,
    entry: CatalogEntry | None,
    roles: dict[str, Any],
    *,
    effective_power: int | None,
    gear_bonus: float,
) -> float:
    """Base ILP score for Conquest: attack scoring amplified by ultimate level."""
    base = hero_base_score(
        hero,
        entry,
        roles,
        effective_power=effective_power,
        gear_bonus=gear_bonus,
        side="attack",
    )
    return base * ultimate_level_multiplier(hero)


def optimize_conquest(
    heroes: list[HeroRecord],
    catalog: dict[str, CatalogEntry],
    roles: dict[str, Any],
    *,
    gear: list[GearRecord] | None = None,
    gear_profile: str = "early_game_combat",
    with_explanations: bool = False,
    with_survival: bool = True,
) -> CombatFormationResult:
    """Select and place the best 5-hero Conquest formation (2F + 3B).

    When ``with_survival`` is true, attach a ``survival`` block comparing the
    lineup to self-play foes from the same roster/gear.
    """
    result = solve_combat_formation(
        "conquest",
        heroes,
        catalog,
        roles,
        side=None,
        gear=gear,
        gear_profile=gear_profile,
        gear_slot_order=CONQUEST_GEAR_ORDER,
        base_score_fn=_conquest_base_score,
        placement_mult_fn=lambda troop, slot, name, roles: placement_mult(
            troop, slot, name, roles, side="attack"
        ),
        with_explanations=with_explanations,
        explain_fn=None,
    )
    if not with_survival:
        return result
    return attach_survival(
        result,
        heroes,
        catalog,
        roles,
        gear=gear,
        gear_profile=gear_profile,
        side="attack",
        base_score_fn=_conquest_base_score,
        gear_order=CONQUEST_GEAR_ORDER,
        heuristic_mode="conquest",
    )
