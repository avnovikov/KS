"""Per-hero power/stat split into hero / skills / gear shares (estimate A).

This module is the only place that decides how much of a hero's strength came
from the hero itself, from skills, and from gear. Every optimiser reads
``StatContribution`` totals instead of raw ``hero.power`` plus an ad-hoc gear
heuristic.

Estimation rule A (see the design doc):

1. **Skills** — family-filtered percents from the scrape (falling back to the
   catalog). Conquest is a *multiplicative* buff on the flat scraped stat, so
   the skills share of a naked value ``v`` under a total percent ``p`` is
   ``v * p / (1 + p)`` — which is always in ``[0, v)``, so the hero share can
   never go negative. Expedition percents are additive percent points.
2. **Hero** — naked scraped value minus the skills share.
3. **Gear** — summed from the assigned pieces: conquest flats from OCR,
   expedition percents from OCR when present, otherwise the calibrated
   ``expedition_stat_fraction`` formula, plus piece power.
4. **Total** — hero + skills + gear.

Skill power share is not estimable from any scraped field, so power is always
reported as ``hero = naked``, ``skills = 0``, and the result is flagged via
``skills_incomplete`` when the skill scrape is partial.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from ks.heroes.gear_models import GearRecord
from ks.heroes.models import HeroRecord
from ks.heroes.optimize.gear_assign import infer_slot
from ks.heroes.optimize.gear_stats import expedition_stat_fraction
from ks.heroes.optimize.scoring import normalize_troop
from ks.heroes.optimize.skill_effects import (
    CONQUEST,
    EXPEDITION,
    catalog_percents,
    family_percents,
    skill_percents,
)
from ks.heroes.optimize.types import CatalogEntry

__all__ = [
    "CONQUEST",
    "EXPEDITION",
    "CONQUEST_LABELS",
    "EXPEDITION_STATS",
    "EVENT_FAMILY",
    "Share",
    "StatContribution",
    "contribution_strength",
    "expedition_labels",
    "family_for_event",
    "formation_contribution",
    "hero_contribution",
    "weighted_expedition_totals",
]

# Event key → stat family. Lives here so no scorer re-invents the mapping.
EVENT_FAMILY: dict[str, str] = {
    "arena": CONQUEST,
    "arena_attack": CONQUEST,
    "arena_defense": CONQUEST,
    "conquest": CONQUEST,
    "sword": EXPEDITION,
    "swordland": EXPEDITION,
    "bear": EXPEDITION,
    "beartrap": EXPEDITION,
    "bear_trap": EXPEDITION,
}

CONQUEST_LABELS: tuple[str, ...] = (
    "Hero Attack",
    "Hero Defense",
    "Hero Health",
    "Escort Attack",
    "Escort Defense",
    "Escort Health",
)

EXPEDITION_STATS: tuple[str, ...] = ("Attack", "Defense", "Health", "Lethality")

# Gear OCR emits the singular "Archer" prefix for archers pieces.
_TROOP_PREFIX: dict[str, str] = {
    "infantry": "Infantry",
    "cavalry": "Cavalry",
    "archers": "Archer",
}

# Conquest: a percent kind lifts these flat labels.
# Coeff / rate / heal kinds are scored by conquest_combat sim-lite — do not
# fold Damage Up / AoE / AS / Crit / Heal into Hero Attack or Health flats.
_CONQUEST_KIND_LABELS: dict[str, tuple[str, ...]] = {
    "attack_up": ("Hero Attack", "Escort Attack"),
    "defender_attack": ("Hero Attack", "Escort Attack"),
    "defense_up": ("Hero Defense", "Escort Defense"),
    "damage_taken_down": ("Hero Defense", "Escort Defense"),
    "opp_damage_down": ("Hero Defense", "Escort Defense"),
    "defender_defense": ("Hero Defense", "Escort Defense"),
    "health_up": ("Hero Health", "Escort Health"),
    "defender_health": ("Hero Health", "Escort Health"),
}

# Expedition: a percent kind adds to these troop stats.
_EXPEDITION_KIND_STATS: dict[str, tuple[str, ...]] = {
    "attack_up": ("Attack",),
    "damage_up": ("Attack",),
    "defense_up": ("Defense",),
    "damage_taken_down": ("Defense",),
    "opp_damage_down": ("Defense",),
    "health_up": ("Health",),
    "lethality_up": ("Lethality",),
}

# Gear slot → the expedition stat the formula fraction represents.
_SLOT_EXPEDITION_STAT: dict[str, str] = {
    "helmet": "Lethality",
    "boots": "Lethality",
    "chest": "Health",
    "gloves": "Health",
}

# contribution_strength normalizers — chosen so power, flat conquest stats and
# expedition percents land in comparable magnitudes for the ILP objective.
_POWER_SCALE = 1_000_000.0
_CONQUEST_COMBAT_SCALE = 10_000.0
_CONQUEST_HEALTH_SCALE = 100_000.0
_EXPEDITION_PERCENT_SCALE = 100.0


@dataclass(frozen=True)
class Share:
    """One stat's split. ``total`` is always the sum of the three parts."""

    hero: float = 0.0
    skills: float = 0.0
    gear: float = 0.0

    @property
    def total(self) -> float:
        return self.hero + self.skills + self.gear

    def to_dict(self) -> dict[str, float]:
        return {
            "hero": self.hero,
            "skills": self.skills,
            "gear": self.gear,
            "total": self.total,
        }


@dataclass(frozen=True)
class StatContribution:
    """One hero's (or one formation's) power + stat split for a family."""

    family: str
    estimated: bool
    skills_incomplete: bool
    power: Share
    stats: dict[str, Share] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "estimated": self.estimated,
            "skills_incomplete": self.skills_incomplete,
            "power": self.power.to_dict(),
            "stats": {k: v.to_dict() for k, v in self.stats.items()},
        }


def family_for_event(event: str | None) -> str:
    """Stat family for an event key (``arena``/``conquest``/``swordland``/…)."""
    key = (event or "").strip().lower().replace(" ", "_")
    family = EVENT_FAMILY.get(key)
    if family is None:
        raise ValueError(
            f"unknown event {event!r}; have {sorted(EVENT_FAMILY)}"
        )
    return family


def expedition_labels(troop: str | None) -> tuple[str, ...]:
    """Expedition stat labels for a hero's troop class."""
    key = normalize_troop(troop) or "infantry"
    prefix = _TROOP_PREFIX.get(key, key.title())
    return tuple(f"{prefix} {stat}" for stat in EXPEDITION_STATS)


def _hero_troop(hero: HeroRecord, entry: CatalogEntry | None) -> str:
    if entry is not None:
        troop = normalize_troop(entry.troop)
        if troop:
            return troop
    return normalize_troop(hero.troop_type) or "infantry"


def _conquest_stats(
    hero: HeroRecord,
    percents: Mapping[str, float],
    gear_pieces: Sequence[GearRecord],
) -> dict[str, Share]:
    naked = dict((hero.stats.conquest if hero.stats else None) or {})
    by_label: dict[str, float] = {label: 0.0 for label in CONQUEST_LABELS}
    for kind, percent in percents.items():
        for label in _CONQUEST_KIND_LABELS.get(kind, ()):
            by_label[label] = by_label.get(label, 0.0) + float(percent) / 100.0

    gear_by_label: dict[str, float] = {label: 0.0 for label in CONQUEST_LABELS}
    for piece in gear_pieces:
        flats = (piece.stats.conquest if piece.stats else None) or {}
        for label, value in flats.items():
            gear_by_label[label] = gear_by_label.get(label, 0.0) + float(value)

    out: dict[str, Share] = {}
    for label in CONQUEST_LABELS:
        base = float(naked.get(label) or 0.0)
        p = max(0.0, by_label.get(label, 0.0))
        skills = base * p / (1.0 + p) if base > 0 else 0.0
        out[label] = Share(
            hero=base - skills,
            skills=skills,
            gear=gear_by_label.get(label, 0.0),
        )
    return out


def _gear_expedition_percent(piece: GearRecord, labels: tuple[str, ...]) -> dict[str, float]:
    """Percent points this piece adds, keyed by expedition label."""
    out: dict[str, float] = {}
    stats = piece.stats
    if stats is not None and stats.expedition:
        for label, value in stats.expedition.items():
            if label in labels:
                out[label] = out.get(label, 0.0) + float(value)
    if out:
        return out
    slot = infer_slot(piece)
    stat = _SLOT_EXPEDITION_STAT.get(slot or "")
    if stat is None:
        return out
    frac = expedition_stat_fraction(
        piece.rarity, piece.enhancement_level, piece.mastery_level
    )
    if frac is None or frac <= 0:
        return out
    label = next((lb for lb in labels if lb.endswith(f" {stat}")), None)
    if label is None:
        return out
    out[label] = float(frac) * 100.0
    return out


def _expedition_stats(
    hero: HeroRecord,
    troop: str,
    percents: Mapping[str, float],
    gear_pieces: Sequence[GearRecord],
) -> dict[str, Share]:
    labels = expedition_labels(troop)
    scraped = dict((hero.stats.expedition if hero.stats else None) or {})
    hero_by_label = {lb: float(scraped.get(lb) or 0.0) for lb in labels}

    skills_by_label: dict[str, float] = {lb: 0.0 for lb in labels}
    by_stat: dict[str, float] = {}
    for kind, percent in percents.items():
        for stat in _EXPEDITION_KIND_STATS.get(kind, ()):
            by_stat[stat] = by_stat.get(stat, 0.0) + float(percent)
    for stat, value in by_stat.items():
        label = next((lb for lb in labels if lb.endswith(f" {stat}")), None)
        if label is not None:
            skills_by_label[label] = value

    gear_by_label: dict[str, float] = {lb: 0.0 for lb in labels}
    for piece in gear_pieces:
        for label, value in _gear_expedition_percent(piece, labels).items():
            gear_by_label[label] = gear_by_label.get(label, 0.0) + value

    return {
        lb: Share(
            hero=max(0.0, hero_by_label[lb]),
            skills=max(0.0, skills_by_label[lb]),
            gear=max(0.0, gear_by_label[lb]),
        )
        for lb in labels
    }


def _conquest_percents(
    hero: HeroRecord,
    entry: CatalogEntry | None,
    catalog: dict[str, CatalogEntry] | None,
) -> tuple[dict[str, float], bool]:
    """Conquest-eligible skill percents — trusts ``_CONQUEST_KIND_LABELS``'s
    own key set, not ``skill_effects.kind_family``'s catalog-driven family
    tag.

    ``kind_family`` answers "which family does this hero's catalog *kit*
    effect belong to" (e.g. a first-skill widget bonus scraped as
    ``applies_to: expedition``) — a narrower question than "does a skill of
    this kind count in this family's split." In practice, no catalog entry
    for any hero ever tags ``attack_up``/``defense_up``/``health_up``/
    ``damage_taken_down``/``opp_damage_down`` as conquest, so routing
    conquest through ``family_percents`` silently dropped every Defense
    Up/Health Up/Damage Taken Down/Enemy Troops Attack Down skill before it
    ever reached ``_conquest_stats`` — Hero/Escort Defense and Health skills
    share read as 0 for every hero with only these (very common) skills.
    """
    scraped, incomplete = skill_percents(hero)
    fallback = catalog_percents(entry, hero.stars, hero.pellets)
    merged: dict[str, float] = {}
    for kind, value in scraped.items():
        if kind in _CONQUEST_KIND_LABELS:
            merged[kind] = value
    for kind, value in fallback.items():
        if kind in merged or kind not in _CONQUEST_KIND_LABELS:
            continue
        merged[kind] = value
        incomplete = True
    return merged, incomplete


def hero_contribution(
    hero: HeroRecord,
    entry: CatalogEntry | None,
    *,
    family: str,
    gear_pieces: Sequence[GearRecord] | Mapping[str, GearRecord] | None = None,
    power: int | float | None = None,
    catalog: dict[str, CatalogEntry] | None = None,
) -> StatContribution:
    """Split one hero's power + family stats into hero / skills / gear shares.

    ``gear_pieces`` accepts either the slot→piece mapping produced by
    ``assign_exclusive_sets`` or a plain sequence of pieces. ``power``
    overrides the scraped value (callers pass sanitized power).
    """
    if family not in (CONQUEST, EXPEDITION):
        raise ValueError(f"unknown family {family!r}; want conquest|expedition")
    if isinstance(gear_pieces, Mapping):
        pieces: list[GearRecord] = list(gear_pieces.values())
    else:
        pieces = list(gear_pieces or ())

    if family == CONQUEST:
        percents, incomplete = _conquest_percents(hero, entry, catalog)
        stats = _conquest_stats(hero, percents, pieces)
    else:
        percents, incomplete = family_percents(
            hero, entry, family=family, catalog=catalog
        )
        stats = _expedition_stats(
            hero, _hero_troop(hero, entry), percents, pieces
        )

    naked_power = float(power if power is not None else (hero.power or 0))
    gear_power = float(sum(float(p.power or 0) for p in pieces))
    return StatContribution(
        family=family,
        estimated=True,
        skills_incomplete=incomplete,
        power=Share(hero=max(0.0, naked_power), skills=0.0, gear=gear_power),
        stats=stats,
    )


def _label_troop(label: str) -> str | None:
    low = label.lower()
    if low.startswith("infantry"):
        return "infantry"
    if low.startswith("cavalry"):
        return "cavalry"
    if low.startswith("archer"):
        return "archers"
    return None


def _label_expedition_stat(label: str) -> str | None:
    for stat in EXPEDITION_STATS:
        if label.endswith(f" {stat}"):
            return stat
    if label in EXPEDITION_STATS:
        return stat
    return None


def weighted_expedition_totals(
    stats: Mapping[str, Share],
    troop_shares: Mapping[str, float] | None = None,
) -> dict[str, Share]:
    """Collapse troop-prefixed % into share-weighted Attack/Defense/….

    Same-troop labels are summed first. ``troop_shares`` (march ratio or
    headcount) weights each troop; missing shares → equal weight over troop
    types present in ``stats``. Power is not handled here — callers sum it.
    """
    by_troop: dict[str, dict[str, Share]] = {}
    for label, share in stats.items():
        troop = _label_troop(label)
        stat = _label_expedition_stat(label)
        if troop is None or stat is None:
            continue
        prev = by_troop.setdefault(troop, {}).get(stat)
        if prev is None:
            by_troop[troop][stat] = share
            continue
        by_troop[troop][stat] = Share(
            hero=prev.hero + share.hero,
            skills=prev.skills + share.skills,
            gear=prev.gear + share.gear,
        )
    if not by_troop:
        return {}

    if troop_shares:
        raw = {t: max(0.0, float(troop_shares.get(t, 0.0))) for t in by_troop}
    else:
        raw = {t: 1.0 for t in by_troop}
    mass = sum(raw.values())
    if mass <= 0:
        raw = {t: 1.0 for t in by_troop}
        mass = float(len(raw))
    weights = {t: raw[t] / mass for t in raw}

    out: dict[str, Share] = {}
    for stat in EXPEDITION_STATS:
        hero = skills = gear = 0.0
        seen = False
        for troop, weight in weights.items():
            share = by_troop.get(troop, {}).get(stat)
            if share is None:
                continue
            seen = True
            hero += weight * share.hero
            skills += weight * share.skills
            gear += weight * share.gear
        if seen:
            out[stat] = Share(hero=hero, skills=skills, gear=gear)
    return out


def formation_contribution(
    contributions: Sequence[StatContribution],
    *,
    troop_shares: Mapping[str, float] | None = None,
) -> StatContribution:
    """Combine lineup contributions.

    Power (hero / skills / gear) always sums.
    Conquest: matching flat labels sum.
    Expedition: matching troop labels sum first, then Attack / Defense /
    Health / Lethality collapse via ``weighted_expedition_totals``.
    """
    items = list(contributions)
    if not items:
        raise ValueError("formation_contribution needs at least one contribution")
    families = {c.family for c in items}
    if len(families) > 1:
        raise ValueError(
            f"all contributions must share the same family; got {sorted(families)}"
        )
    power = Share(
        hero=sum(c.power.hero for c in items),
        skills=sum(c.power.skills for c in items),
        gear=sum(c.power.gear for c in items),
    )
    stats: dict[str, Share] = {}
    for c in items:
        for label, share in c.stats.items():
            prev = stats.get(label, Share())
            stats[label] = Share(
                hero=prev.hero + share.hero,
                skills=prev.skills + share.skills,
                gear=prev.gear + share.gear,
            )
    if items[0].family == EXPEDITION:
        stats = weighted_expedition_totals(stats, troop_shares)
    return StatContribution(
        family=items[0].family,
        estimated=any(c.estimated for c in items),
        skills_incomplete=any(c.skills_incomplete for c in items),
        power=power,
        stats=stats,
    )


def contribution_strength(contribution: StatContribution) -> float:
    """Single scalar strength signal for ILP objectives.

    Conquest: power in millions + (attack + defense) / 10k + health / 100k.
    Expedition: power in millions + summed percent points / 100.
    Formation expedition totals are already share-weighted (see
    ``weighted_expedition_totals``); per-hero contributions still use troop
    labels.

    The scales are calibration constants, not game formulas — they exist so
    power and stats land in the same order of magnitude in the objective.
    """
    power_term = contribution.power.total / _POWER_SCALE
    if contribution.family == CONQUEST:
        def _t(label: str) -> float:
            share = contribution.stats.get(label)
            return share.total if share else 0.0

        combat = (
            _t("Hero Attack")
            + _t("Escort Attack")
            + _t("Hero Defense")
            + _t("Escort Defense")
        )
        health = _t("Hero Health") + _t("Escort Health")
        return (
            power_term
            + combat / _CONQUEST_COMBAT_SCALE
            + health / _CONQUEST_HEALTH_SCALE
        )
    percent = sum(share.total for share in contribution.stats.values())
    return power_term + percent / _EXPEDITION_PERCENT_SCALE
