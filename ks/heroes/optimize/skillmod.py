"""Expedition SkillMod stacking by community ``effect_op`` identifiers.

Bear / rally joiners contribute only their **first expedition** skill. Attack
and Lethality first skills both land in the attacker ``DamageUp`` bucket;
same ``effect_op`` values add, different ops multiply:

    DamageUp = ∏ (1 + sum_pct[op] / 100)

Full SkillMod (PvP) is ``(DamageUp × OppDefenseDown) / (OppDamageDown × DefenseUp)``.
Bear Trap is attacker-vs-PVE, so only the DamageUp (and rare OppDefenseDown)
numerator matters for ``joiner_skillmod``.

Sources: kingshotguide.net joiner-hero-mechanics; catalog ``effect_op`` /
``first_expedition`` tags on ``config/hero_catalog.yaml``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from ks.heroes.optimize.scoring import effect_percent_points
from ks.heroes.optimize.types import CatalogEntry, EffectTag

# Kinds that feed the attacker DamageUp SkillMod bucket (joiner first skill).
_DAMAGE_UP_KINDS = frozenset({"attack_up", "lethality_up"})

# Optional second numerator bucket (rare on joiners).
_OPP_DEFENSE_DOWN_KINDS = frozenset({"opp_defense_down"})


def stack_effect_ops(pct_by_op: Mapping[int, float]) -> float:
    """Multiply ``(1 + pct/100)`` across distinct effect_op keys (empty → 1.0)."""
    if not pct_by_op:
        return 1.0
    return math.prod(1.0 + float(pct) / 100.0 for pct in pct_by_op.values())


def damage_up_skillmod(pct_by_op: Mapping[int, float]) -> float:
    """Attacker DamageUp factor from summed percents keyed by effect_op."""
    return stack_effect_ops(pct_by_op)


def _accumulate_damage_up(
    tag: EffectTag,
    *,
    joiner_only: bool,
    out: dict[int, float],
) -> None:
    if tag.applies_to != "expedition":
        return
    if tag.kind not in _DAMAGE_UP_KINDS:
        return
    if joiner_only and not tag.first_expedition:
        return
    if tag.effect_op is None:
        # Untagged first skills still stack under a synthetic op so they count
        # additively without inventing a catalog code.
        op = 0
    else:
        op = int(tag.effect_op)
    out[op] = out.get(op, 0.0) + effect_percent_points(float(tag.max_value), tag)


def joiner_damage_up_from_entries(
    entries: Sequence[CatalogEntry],
) -> float:
    """SkillMod DamageUp from joiner heroes (first expedition Attack/Lethality only).

    Each entry is one joiner contribution. Max-value percents are used (level-5
    / star-max assumption for joiner slots); callers that need star scaling
    should pre-scale tags before building entries.
    """
    by_op: dict[int, float] = {}
    for entry in entries:
        for tag in entry.effects:
            _accumulate_damage_up(tag, joiner_only=True, out=by_op)
    return damage_up_skillmod(by_op)


def lineup_skillmod_detail(
    hero_names: Sequence[str],
    catalog: Mapping[str, CatalogEntry],
    *,
    joiner_only: bool = True,
    heroes_by_name: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """UI/API payload: DamageUp factor + per-op and per-hero first-skill rows.

    Percent values use catalog ``max_value`` scaled by star progress when a
    matching ``HeroRecord`` is supplied in ``heroes_by_name``.
    """
    from ks.heroes.optimize.scoring import effect_percent_points, star_progress_factor

    by_op: dict[int, float] = {}
    by_hero: list[dict[str, Any]] = []
    for name in hero_names:
        entry = catalog.get(name)
        if entry is None:
            continue
        hero = (heroes_by_name or {}).get(name)
        scale = 1.0
        if hero is not None:
            scale = float(
                star_progress_factor(
                    getattr(hero, "stars", None),
                    getattr(hero, "pellets", None),
                )
            )
        for tag in entry.effects:
            if tag.applies_to != "expedition":
                continue
            if tag.kind not in _DAMAGE_UP_KINDS:
                continue
            if joiner_only and not tag.first_expedition:
                continue
            op = 0 if tag.effect_op is None else int(tag.effect_op)
            pct = effect_percent_points(float(tag.max_value) * scale, tag)
            by_op[op] = by_op.get(op, 0.0) + pct
            by_hero.append(
                {
                    "name": name,
                    "kind": tag.kind,
                    "effect_op": op,
                    "pct": pct,
                    "first_expedition": bool(tag.first_expedition),
                }
            )
    return {
        "joiner_only": bool(joiner_only),
        "damage_up": damage_up_skillmod(by_op),
        "by_op": {str(op): pct for op, pct in sorted(by_op.items())},
        "by_hero": by_hero,
    }


def skillmod_numerator_from_tags(
    tags: Sequence[EffectTag],
    *,
    joiner_only: bool = False,
) -> float:
    """``DamageUp × OppDefenseDown`` from expedition tags (Bear attacker side)."""
    damage_up: dict[int, float] = {}
    opp_def: dict[int, float] = {}
    for tag in tags:
        if tag.applies_to != "expedition":
            continue
        if joiner_only and not tag.first_expedition:
            continue
        op = 0 if tag.effect_op is None else int(tag.effect_op)
        if tag.kind in _DAMAGE_UP_KINDS:
            damage_up[op] = damage_up.get(op, 0.0) + effect_percent_points(
                float(tag.max_value), tag
            )
        elif tag.kind in _OPP_DEFENSE_DOWN_KINDS:
            opp_def[op] = opp_def.get(op, 0.0) + effect_percent_points(
                float(tag.max_value), tag
            )
    return stack_effect_ops(damage_up) * stack_effect_ops(opp_def)
