"""Deterministic Conquest / Arena skill scoring (sim-lite).

Conquest skill labels like ``Damage Up: 160`` are Attack×coeff skill
coefficients — not Expedition SkillMod and not flat Hero Attack %. See
``docs/superpowers/specs/2026-08-09-conquest-combat-sim-lite-design.md``.
"""

from __future__ import annotations

from dataclasses import dataclass

from ks.heroes.governor_bonuses import governor_attack_mult, governor_defense_mult
from ks.heroes.governor_models import GovernorTroopBonuses
from ks.heroes.models import HeroRecord
from ks.heroes.optimize.scoring import normalize_troop
from ks.heroes.optimize.skill_effects import (
    CONQUEST,
    _effect_max_for_skill,
    leveled_effect_value,
)
from ks.heroes.optimize.types import CatalogEntry, CatalogSkill

# Calibration knobs (OG-09 may retune).
DEFAULT_ALPHA = 0.5
DEFAULT_AOE_TARGETS = 2.0
DEFAULT_CRIT_MULT = 2.0
DEFAULT_DEF_SCALE = 10_000.0
DEFAULT_HEAL_RATE = 1.0
DEFAULT_ESCORT_DPS_WEIGHT = 0.15
_MAX_DR = 0.90

_COEFF_KINDS = frozenset({"damage_up", "aoe_damage_up"})


@dataclass(frozen=True)
class ConquestCombatBreakdown:
    atk_eff: float
    skill_dps: float
    toughness: float
    score: float
    incomplete: bool


def _flat(hero: HeroRecord, key: str) -> float:
    conquest = (hero.stats.conquest if hero.stats else None) or {}
    return float(conquest.get(key) or 0.0)


def _hero_troop(hero: HeroRecord, entry: CatalogEntry | None) -> str:
    raw = (entry.troop if entry and entry.troop else None) or hero.troop_type or "infantry"
    try:
        troop = normalize_troop(raw)
    except ValueError:
        troop = None
    return troop or "infantry"


def _skill_level(hero: HeroRecord, cskill: CatalogSkill) -> int | None:
    by_slot = {int(s.slot): s.level for s in hero.skills if s.level is not None}
    if cskill.slot in by_slot:
        return int(by_slot[cskill.slot])
    for skill in hero.skills:
        if skill.level is None or not skill.name:
            continue
        if skill.name == cskill.name:
            return int(skill.level)
    return None


def _leveled_kind_totals(
    hero: HeroRecord, entry: CatalogEntry | None
) -> tuple[dict[str, float], bool]:
    """Sum leveled Conquest skill values by kind; incomplete if no levels."""
    if entry is None or not entry.skills:
        return {}, True
    totals: dict[str, float] = {}
    any_level = False
    for cskill in entry.skills:
        if cskill.family != CONQUEST or not cskill.effect_kind:
            continue
        level = _skill_level(hero, cskill)
        if level is None:
            continue
        any_level = True
        max_value = _effect_max_for_skill(entry, cskill)
        if max_value is None and cskill.ladder is None:
            continue
        value = leveled_effect_value(
            max_value if max_value is not None else 0.0,
            level,
            cskill.ladder,
        )
        totals[cskill.effect_kind] = totals.get(cskill.effect_kind, 0.0) + value
    return totals, not any_level


def conquest_hero_score(
    hero: HeroRecord,
    entry: CatalogEntry | None,
    *,
    catalog: dict[str, CatalogEntry] | None = None,
    governor: GovernorTroopBonuses | None = None,
    alpha: float = DEFAULT_ALPHA,
    aoe_targets: float = DEFAULT_AOE_TARGETS,
    crit_mult: float = DEFAULT_CRIT_MULT,
    def_scale: float = DEFAULT_DEF_SCALE,
    heal_rate: float = DEFAULT_HEAL_RATE,
    escort_dps_weight: float = DEFAULT_ESCORT_DPS_WEIGHT,
) -> ConquestCombatBreakdown:
    """Score one hero for Conquest/Arena using sim-lite formulas.

    Governor Atk%/Def% (already including set bonuses in the pct maps) apply
    to the escort layer and scale toughness; skill coefficients stay on the
    hero Attack sheet. ``catalog`` is reserved for future lookups.
    """
    del catalog  # reserved
    kinds, incomplete = _leveled_kind_totals(hero, entry)
    troop = _hero_troop(hero, entry)
    gov_atk = governor_attack_mult(governor, troop)
    gov_def = governor_defense_mult(governor, troop)

    attack_up = kinds.get("attack_up", 0.0)
    atk_eff = _flat(hero, "Hero Attack") * (1.0 + attack_up / 100.0)
    escort_atk = (
        _flat(hero, "Escort Attack") * (1.0 + attack_up / 100.0) * gov_atk
    )

    as_up = kinds.get("attack_speed_up", 0.0)
    crit_rate = kinds.get("crit_rate_up", 0.0)
    edt = kinds.get("enemy_damage_taken_up", 0.0)
    rate_global = 1.0 + as_up / 100.0
    crit_e = 1.0 + (crit_rate / 100.0) * (crit_mult - 1.0)
    amp = 1.0 + edt / 100.0

    skill_dps = 0.0
    if entry is not None:
        for cskill in entry.skills:
            if cskill.family != CONQUEST or cskill.effect_kind not in _COEFF_KINDS:
                continue
            level = _skill_level(hero, cskill)
            if level is None:
                continue
            max_value = _effect_max_for_skill(entry, cskill)
            if max_value is None and cskill.ladder is None:
                continue
            coeff = leveled_effect_value(
                max_value if max_value is not None else 0.0,
                level,
                cskill.ladder,
            )
            hits = float(cskill.hits_per_cast or 1)
            cast_rate = float(cskill.cast_rate if cskill.cast_rate is not None else 1.0)
            aoe = aoe_targets if cskill.effect_kind == "aoe_damage_up" else 1.0
            skill_dps += (
                atk_eff
                * (coeff / 100.0)
                * hits
                * cast_rate
                * rate_global
                * aoe
                * amp
                * crit_e
            )
    skill_dps += escort_atk * escort_dps_weight

    def_eff = (
        _flat(hero, "Hero Defense") * (1.0 + kinds.get("defense_up", 0.0) / 100.0)
        + _flat(hero, "Escort Defense")
        * (1.0 + kinds.get("defense_up", 0.0) / 100.0)
        * gov_def
    )
    hp_eff = _flat(hero, "Hero Health") * (1.0 + kinds.get("health_up", 0.0) / 100.0)
    hp_eff += _flat(hero, "Escort Health") * (1.0 + kinds.get("health_up", 0.0) / 100.0)
    dr = min(
        _MAX_DR,
        max(
            0.0,
            (
                kinds.get("damage_taken_down", 0.0)
                + kinds.get("opp_damage_down", 0.0)
            )
            / 100.0,
        ),
    )
    heal_exp = atk_eff * (kinds.get("heal_up", 0.0) / 100.0) * heal_rate
    toughness = (hp_eff + heal_exp) * (1.0 + def_eff / def_scale) / (1.0 - dr)
    if toughness < 1.0:
        toughness = 1.0
    score = skill_dps * (toughness**alpha)
    return ConquestCombatBreakdown(
        atk_eff=atk_eff,
        skill_dps=skill_dps,
        toughness=toughness,
        score=score,
        incomplete=incomplete,
    )
