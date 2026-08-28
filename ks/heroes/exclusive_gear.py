"""Exclusive gear (widget) level scaling for optimiser and UI."""

from __future__ import annotations

from ks.heroes.models import HeroRecord

DEFAULT_EXCLUSIVE_GEAR_MAX_LEVEL = 10


def exclusive_gear_level_factor(
    level: int | None, *, max_level: int = DEFAULT_EXCLUSIVE_GEAR_MAX_LEVEL
) -> float:
    """Map widget level to a 0..1 scale for catalog max_value."""
    if level is None or level <= 0:
        return 0.0
    if max_level <= 0:
        raise ValueError(f"max_level must be positive; got {max_level}")
    return min(1.0, float(level) / float(max_level))


def widget_effect_at_level(
    max_value: float,
    level: int | None,
    *,
    max_level: int = DEFAULT_EXCLUSIVE_GEAR_MAX_LEVEL,
) -> float:
    return max_value * exclusive_gear_level_factor(level, max_level=max_level)


def widget_level_from_hero(hero: HeroRecord) -> int | None:
    eg = hero.exclusive_gear
    if eg is None:
        return None
    return eg.level


def widget_max_level_from_hero(hero: HeroRecord) -> int:
    eg = hero.exclusive_gear
    if eg is None or eg.max_level is None:
        return DEFAULT_EXCLUSIVE_GEAR_MAX_LEVEL
    return int(eg.max_level)


def widget_impacts_table(
    max_value: float, *, max_level: int = DEFAULT_EXCLUSIVE_GEAR_MAX_LEVEL
) -> dict[int, float]:
    """Effective catalog value at each widget level (1..max_level)."""
    return {
        lvl: widget_effect_at_level(max_value, lvl, max_level=max_level)
        for lvl in range(1, max_level + 1)
    }


def widget_effects_for_hero(
    hero: HeroRecord,
    catalog_effects: tuple[object, ...],
) -> list[tuple[str, float]]:
    """Return (kind, effective_value) for widget-applied catalog tags."""
    level = widget_level_from_hero(hero)
    max_level = widget_max_level_from_hero(hero)
    out: list[tuple[str, float]] = []
    for tag in catalog_effects:
        applies_to = getattr(tag, "applies_to", None)
        if applies_to != "widget":
            continue
        kind = str(getattr(tag, "kind", "effect"))
        max_value = float(getattr(tag, "max_value", 0.0))
        out.append((kind, widget_effect_at_level(max_value, level, max_level=max_level)))
    return out
