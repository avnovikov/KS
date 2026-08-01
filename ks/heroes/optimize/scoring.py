from __future__ import annotations

from ks.heroes.models import HeroRecord
from ks.heroes.optimize.events import default_kind_weights
from ks.heroes.optimize.types import CatalogEntry, EffectTag, EventProfile
from ks.heroes.stars_vision import PELLETS_PER_STAR


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


def hero_strength(
    hero: HeroRecord,
    entry: CatalogEntry,
    mode: str,
    *,
    event: EventProfile | None = None,
    effective_power: int | None = None,
    gear_bonus: float = 0.0,
) -> float:
    defaults = default_kind_weights()
    if event and event.mode_kind_weights and mode in event.mode_kind_weights:
        weights = event.mode_kind_weights[mode]
    else:
        weights = defaults.get(mode) or defaults["solo"]

    op_weights: dict[int, float] = {}
    if event and event.effect_op_weights and mode in event.effect_op_weights:
        op_weights = event.effect_op_weights[mode]

    total = 0.0
    for tag in entry.effects:
        if mode == "solo" and tag.applies_to == "widget":
            continue
        if mode == "joiner" and tag.applies_to == "widget":
            continue
        if mode == "joiner" and not tag.first_expedition and tag.applies_to == "expedition":
            w = 0.15 * weights.get(tag.kind, 0.5)
        else:
            w = weights.get(tag.kind, 0.5)
        value = w * _effect_value(tag, hero.stars, hero.pellets)
        if tag.effect_op is not None and tag.first_expedition:
            value *= op_weights.get(tag.effect_op, 1.0)
        total += value

    if entry.widget_type == "defense" and mode == "garrison" and entry.garrison_widget_priority:
        total += 5.0 * entry.garrison_widget_priority
    if entry.widget_type == "attack" and mode == "rally_lead" and entry.rally_widget_priority:
        total += 5.0 * entry.rally_widget_priority

    power = effective_power if effective_power is not None else hero.power
    if power:
        total += power / 1_000_000.0
    if gear_bonus:
        total += float(gear_bonus)
    return total
