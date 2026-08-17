from __future__ import annotations

from typing import TYPE_CHECKING

from ks.heroes.models import HeroRecord
from ks.heroes.optimize.events import default_kind_weights
from ks.heroes.optimize.types import CatalogEntry, EffectTag, EventProfile
from ks.heroes.stars_vision import PELLETS_PER_STAR

if TYPE_CHECKING:  # pragma: no cover — runtime import is function-local
    from ks.heroes.optimize.stat_contributions import StatContribution


def star_progress_factor(stars: int | None, pellets: int | None = None) -> float:
    """Map UI star strip (0-5 stars, 6 pellets each) to a [0.5, 1.0] skill scale."""
    if stars is None or stars < 0:
        return 0.5
    pel = int(pellets or 0)
    if pel < 0:
        pel = 0
    if pel > PELLETS_PER_STAR:
        stars = stars + pel // PELLETS_PER_STAR
        pel = pel % PELLETS_PER_STAR
    progress = float(stars) + pel / float(PELLETS_PER_STAR)
    progress = min(5.0, progress)
    if progress <= 0:
        return 0.5
    return min(1.0, 0.4 + 0.12 * progress)


def _star_factor(stars: int | None, pellets: int | None = None) -> float:
    return star_progress_factor(stars, pellets)


# Incoming-damage kinds: a proc is a miss/hit mixture, not a second DR layer.
_REMAINING_DAMAGE_KINDS = frozenset({"damage_taken_down", "opp_damage_down"})


def incoming_damage_factor(
    reduction_pct: float, proc_chance: float | None
) -> float:
    """Expected incoming-damage multiplier for a damage-taken-down effect.

    Guaranteed ``r``% DTD leaves ``1 - r/100`` of the hit.
    A proc is a mixture: miss keeps ``1.0``, hit keeps ``1 - r/100``.
    That is not ``(1 - r/100) * (1 - p)`` (two multiplicative DR layers).
    """
    r = float(reduction_pct) / 100.0
    if r < 0.0:
        raise ValueError(f"reduction_pct must be >= 0; got {reduction_pct}")
    r = min(r, 1.0)
    if proc_chance is None:
        return 1.0 - r
    p = float(proc_chance)
    if not 0.0 < p <= 1.0:
        raise ValueError(f"proc_chance must be in (0, 1]; got {p}")
    return (1.0 - p) * 1.0 + p * (1.0 - r)


def effect_percent_points(magnitude: float, tag: EffectTag) -> float:
    """Catalog percent points after applying an optional proc.

    Remaining-damage kinds use :func:`incoming_damage_factor` (mixture), then
    convert back to equivalent DTD points ``100 * (1 - factor)``. Other kinds
    with a proc contribute ``p * magnitude`` (effect on vs off).
    """
    mag = float(magnitude)
    if mag < 0.0:
        raise ValueError(f"effect magnitude must be >= 0; got {mag}")
    if tag.kind in _REMAINING_DAMAGE_KINDS:
        return 100.0 * (1.0 - incoming_damage_factor(mag, tag.proc_chance))
    if tag.proc_chance is None:
        return mag
    return mag * float(tag.proc_chance)


def _effect_value(
    tag: EffectTag, stars: int | None, pellets: int | None = None
) -> float:
    return tag.max_value * star_progress_factor(stars, pellets)


def normalize_troop(troop: str | None) -> str | None:
    if not troop:
        return None
    key = troop.strip().lower()
    if key in ("archer", "archers"):
        return "archers"
    if key in ("infantry", "cavalry"):
        return key
    return key or None


def max_power_by_troop(
    heroes: list[HeroRecord],
    catalog: dict[str, CatalogEntry],
) -> dict[str, int]:
    """Best scraped power per troop class (gear is fungible within class)."""
    best: dict[str, int] = {}
    for hero in heroes:
        entry = catalog.get(hero.name)
        if entry is None:
            continue
        troop = normalize_troop(entry.troop)
        if troop is None or hero.power is None:
            continue
        prev = best.get(troop)
        if prev is None or hero.power > prev:
            best[troop] = int(hero.power)
    return best


def _resolve_mode_weights(
    mode: str, event: EventProfile | None
) -> tuple[dict[str, float], dict[int, float]]:
    """Pick per-kind and per-effect-op weight tables for ``mode``."""
    defaults = default_kind_weights()
    if event and event.mode_kind_weights and mode in event.mode_kind_weights:
        weights = event.mode_kind_weights[mode]
    else:
        weights = defaults.get(mode) or defaults["solo"]
    op_weights: dict[int, float] = {}
    if event and event.effect_op_weights and mode in event.effect_op_weights:
        op_weights = event.effect_op_weights[mode]
    return weights, op_weights


def _effect_tag_value(
    tag: EffectTag,
    hero: HeroRecord,
    mode: str,
    weights: dict[str, float],
    op_weights: dict[int, float],
) -> float:
    """Score one catalog effect tag for ``hero`` in ``mode`` (0.0 if inapplicable)."""
    if tag.applies_to == "widget" and mode in ("solo", "joiner"):
        return 0.0
    if mode == "joiner" and not tag.first_expedition and tag.applies_to == "expedition":
        weight = 0.15 * weights.get(tag.kind, 0.5)
    else:
        weight = weights.get(tag.kind, 0.5)
    raw = _effect_value(tag, hero.stars, hero.pellets)
    value = weight * effect_percent_points(raw, tag)
    if tag.effect_op is not None and tag.first_expedition:
        value *= op_weights.get(tag.effect_op, 1.0)
    return value


def _widget_priority_bonus(entry: CatalogEntry, mode: str) -> float:
    """Flat bonus for defense/attack widgets prioritized by garrison/rally modes."""
    if entry.widget_type == "defense" and mode == "garrison" and entry.garrison_widget_priority:
        return 5.0 * entry.garrison_widget_priority
    if entry.widget_type == "attack" and mode == "rally_lead" and entry.rally_widget_priority:
        return 5.0 * entry.rally_widget_priority
    return 0.0


def hero_strength(
    hero: HeroRecord,
    entry: CatalogEntry,
    mode: str,
    *,
    event: EventProfile | None = None,
    contribution: "StatContribution | None" = None,
) -> float:
    """Mode-weighted effect score plus the hero's expedition contribution.

    ``contribution`` must be an expedition-family ``StatContribution``; it
    replaces the old effective-power-plus-flat-gear-bonus keyword pair, so
    power and gear percents enter through one estimated split rather than a
    raw scrape plus a 0.15-scaled heuristic.
    """
    # Local import: scoring is an ancestor of stat_contributions (via both
    # gear_assign and skill_effects), so a module-level import is circular.
    from ks.heroes.optimize.stat_contributions import (
        EXPEDITION,
        contribution_strength,
    )

    weights, op_weights = _resolve_mode_weights(mode, event)
    total = sum(
        _effect_tag_value(tag, hero, mode, weights, op_weights)
        for tag in entry.effects
    )
    total += _widget_priority_bonus(entry, mode)

    if contribution is not None:
        if contribution.family != EXPEDITION:
            raise ValueError(
                "hero_strength needs an expedition contribution; got "
                f"{contribution.family!r}"
            )
        total += contribution_strength(contribution)
    return total
