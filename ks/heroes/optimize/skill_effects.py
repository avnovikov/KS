"""Turn scraped hero skills into family-tagged percent bonuses.

Scraped skills carry no machine-readable kind — only an ``upgrade_preview``
string such as ``"Attack Up: 8%/12%/15%/20%/24%"`` plus a ``current_bonus``
percent. This module is the single place that reads that text, so no scorer
has to guess what a skill does.

Family membership (conquest vs expedition) comes from the catalog's
``applies_to`` field when a kind appears there; kinds the catalog never
mentions fall back to ``_DEFAULT_KIND_FAMILY``. ``widget`` effects are march
/ rally buffs and belong to neither hero-stat family.
"""

from __future__ import annotations

from ks.heroes.exclusive_gear import (
    exclusive_gear_level_factor,
    widget_level_from_hero,
    widget_max_level_from_hero,
)
from ks.heroes.models import HeroRecord
from ks.heroes.optimize.scoring import effect_percent_points, star_progress_factor
from ks.heroes.optimize.types import CatalogEntry, CatalogSkill, EffectTag

CONQUEST = "conquest"
EXPEDITION = "expedition"

# Skill preview label (lowercased, text before the first ":") → catalog kind.
# Labels absent here are economy/utility skills and contribute no combat stat.
_SKILL_LABEL_KINDS: dict[str, str] = {
    "attack up": "attack_up",
    "defense up": "defense_up",
    "health up": "health_up",
    "lethality up": "lethality_up",
    "damage taken down": "damage_taken_down",
    "damage taken chance down": "damage_taken_down",
    "enemy troops attack down": "opp_damage_down",
    "attack speed up": "attack_speed_up",
    "crit rate": "crit_rate_up",
    "damage up": "damage_up",
    "area of effect damage up": "aoe_damage_up",
    "2nd wave damage up": "damage_up",
    "heal up": "heal_up",
    "enemy damage taken up": "enemy_damage_taken_up",
}

# Fallback family for kinds the catalog never tags with applies_to.
_DEFAULT_KIND_FAMILY: dict[str, str] = {
    "attack_up": EXPEDITION,
    "defense_up": EXPEDITION,
    "health_up": EXPEDITION,
    "lethality_up": EXPEDITION,
    "damage_taken_down": EXPEDITION,
    "opp_damage_down": EXPEDITION,
    "damage_up": CONQUEST,
    "aoe_damage_up": CONQUEST,
    "heal_up": CONQUEST,
    "attack_speed_up": CONQUEST,
    "crit_rate_up": CONQUEST,
    "enemy_damage_taken_up": CONQUEST,
}

_WIDGET = "widget"

_UTILITY_KINDS = frozenset(
    {
        "stamina_cost_down",
        "wilderness_march_speed",
        "gathering_speed_up",
        "construction_speed_up",
        "research_speed_up",
        "training_speed_up",
        "healing_speed_up",
    }
)


def skill_kind(label: str | None) -> str | None:
    """Canonical effect kind for a skill ``upgrade_preview`` line, or None."""
    if not label:
        return None
    head = label.split(":", 1)[0].strip().lower()
    if not head:
        return None
    return _SKILL_LABEL_KINDS.get(head)


def skill_percents(hero: HeroRecord) -> tuple[dict[str, float], bool]:
    """Sum scraped ``current_bonus`` per kind.

    Returns ``(kind → percent, skills_incomplete)``. ``skills_incomplete`` is
    True when the hero has no skills at all, or when any skill is missing its
    ``current_bonus`` (the split for that skill is unknowable from the scrape).
    """
    if not hero.skills:
        return {}, True
    out: dict[str, float] = {}
    incomplete = False
    for skill in hero.skills:
        kind = skill_kind(skill.upgrade_preview)
        if skill.current_bonus is None:
            incomplete = True
            continue
        if kind is None:
            continue
        out[kind] = out.get(kind, 0.0) + float(skill.current_bonus)
    return out, incomplete


def catalog_percents(
    entry: CatalogEntry | None,
    stars: int | None,
    pellets: int | None = None,
) -> dict[str, float]:
    """Star-scaled percent per kind from catalog effects (widget/utility dropped)."""
    if entry is None:
        return {}
    factor = star_progress_factor(stars, pellets)
    out: dict[str, float] = {}
    for tag in entry.effects:
        if tag.applies_to == _WIDGET:
            continue
        if tag.kind in _UTILITY_KINDS:
            continue
        out[tag.kind] = out.get(tag.kind, 0.0) + effect_percent_points(
            float(tag.max_value) * factor, tag
        )
    return out


def kind_family(
    kind: str,
    catalog: dict[str, CatalogEntry] | None = None,
) -> str | None:
    """Family a kind contributes to, or None when it is widget/utility/unknown.

    Catalog ``applies_to`` wins: if any catalog entry tags ``kind`` as
    conquest or expedition, that is the family. A kind the catalog only ever
    tags as ``widget`` returns None. Utility economy kinds always return
    None. Otherwise fall back to the default map.
    """
    if kind in _UTILITY_KINDS:
        return None
    if catalog:
        seen: set[str] = set()
        for entry in catalog.values():
            for tag in entry.effects:
                if tag.kind == kind:
                    seen.add(tag.applies_to)
        if CONQUEST in seen:
            return CONQUEST
        if EXPEDITION in seen:
            return EXPEDITION
        if seen == {_WIDGET}:
            return None
    return _DEFAULT_KIND_FAMILY.get(kind)


def leveled_effect_value(
    max_value: float,
    level: int,
    ladder: list[float] | tuple[float, ...] | None = None,
) -> float:
    """Resolve a skill effect at ``level`` (1–5).

    When ``ladder`` has an entry for the level, use that absolute value.
    Otherwise use the linear hybrid fallback ``max_value * level / 5``.
    """
    if level < 1 or level > 5:
        raise ValueError(f"skill level must be 1..5; got {level}")
    if ladder is not None and len(ladder) >= level:
        return float(ladder[level - 1])
    return float(max_value) * (level / 5.0)


def leveled_catalog_percents(
    hero: HeroRecord,
    entry: CatalogEntry | None,
    *,
    family: str | None = None,
) -> dict[str, float]:
    """Percent points from catalog skills scaled by stored skill levels (1–5).

    Uses hybrid ladders when present on the catalog skill; otherwise
    ``max_value * (level / 5)``. When ``family`` is set, only skills of that
    family are included.
    """
    if entry is None or not entry.skills:
        return {}
    level_by_slot: dict[int, int] = {}
    level_by_name: dict[str, int] = {}
    for skill in hero.skills:
        if skill.level is None:
            continue
        level = int(skill.level)
        if level < 1 or level > 5:
            raise ValueError(
                f"skill level must be 1..5; got {level} for {hero.name} slot {skill.slot}"
            )
        level_by_slot[int(skill.slot)] = level
        if skill.name:
            level_by_name[str(skill.name)] = level

    out: dict[str, float] = {}
    for cskill in entry.skills:
        if family is not None and cskill.family != family:
            continue
        if not cskill.effect_kind:
            continue
        if cskill.effect_kind in _UTILITY_KINDS:
            continue
        level = level_by_slot.get(cskill.slot)
        if level is None:
            level = level_by_name.get(cskill.name)
        if level is None:
            continue
        max_value = _effect_max_for_skill(entry, cskill)
        if max_value is None and cskill.ladder is None:
            continue
        value = leveled_effect_value(
            max_value if max_value is not None else 0.0,
            level,
            cskill.ladder,
        )
        tag = _effect_tag_for_skill(entry, cskill)
        if tag is not None:
            value = effect_percent_points(value, tag)
        out[cskill.effect_kind] = out.get(cskill.effect_kind, 0.0) + value
    return out


def widget_skill_percents(
    hero: HeroRecord,
    entry: CatalogEntry | None,
) -> dict[str, float]:
    """Widget-family catalog skills scaled by exclusive gear level."""
    if entry is None:
        return {}
    factor = exclusive_gear_level_factor(
        widget_level_from_hero(hero),
        max_level=widget_max_level_from_hero(hero),
    )
    if factor <= 0.0:
        return {}
    out: dict[str, float] = {}
    for cskill in entry.skills:
        if cskill.family != _WIDGET or not cskill.effect_kind:
            continue
        max_value = _effect_max_for_skill(entry, cskill)
        if max_value is None:
            continue
        value = float(max_value) * factor
        tag = _effect_tag_for_skill(entry, cskill)
        if tag is not None:
            value = effect_percent_points(value, tag)
        out[cskill.effect_kind] = out.get(cskill.effect_kind, 0.0) + value
    return out


def _effect_max_for_skill(entry: CatalogEntry, cskill: CatalogSkill) -> float | None:
    """Resolve max_value for a skill's effect_kind.

    Prefer effects whose ``applies_to`` matches the skill family; otherwise
    fall back to any matching kind (e.g. widget-tagged lethality used by an
    expedition skill row until the catalog has a dedicated expedition effect).
    Last resort: community default caps so leveled skills still score when the
    catalog only lists the skill name.
    """
    assert cskill.effect_kind is not None
    preferred = 0.0
    preferred_hit = False
    fallback = 0.0
    fallback_hit = False
    for tag in entry.effects:
        if tag.kind != cskill.effect_kind:
            continue
        if tag.applies_to == cskill.family:
            preferred += float(tag.max_value)
            preferred_hit = True
        else:
            fallback += float(tag.max_value)
            fallback_hit = True
    if preferred_hit:
        return preferred
    if fallback_hit:
        return fallback
    return _DEFAULT_EFFECT_MAX.get(cskill.effect_kind)


def _effect_tag_for_skill(
    entry: CatalogEntry, cskill: CatalogSkill
) -> EffectTag | None:
    """Prefer a catalog effect whose applies_to matches the skill family."""
    assert cskill.effect_kind is not None
    fallback: EffectTag | None = None
    for tag in entry.effects:
        if tag.kind != cskill.effect_kind:
            continue
        if tag.applies_to == cskill.family:
            return tag
        if fallback is None:
            fallback = tag
    return fallback


def family_percents(
    hero: HeroRecord,
    entry: CatalogEntry | None,
    *,
    family: str,
    catalog: dict[str, CatalogEntry] | None = None,
) -> tuple[dict[str, float], bool]:
    """Percents for ``family`` from leveled skills, scrape, then star catalog.

    Preference order per kind:
    1. Catalog skill with an explicit stored level (``level/5 × max_value``)
    2. Scraped ``current_bonus`` when present (skipped once any skill is leveled)
    3. Star-scaled catalog effect fallback (marks incomplete)
    """
    if family not in (CONQUEST, EXPEDITION):
        raise ValueError(f"unknown family {family!r}; want conquest|expedition")
    leveled = leveled_catalog_percents(hero, entry, family=family)
    has_manual_levels = any(s.level is not None for s in hero.skills)
    # Prefer explicit skill levels; OCR current_bonus is noisy once levels exist.
    if has_manual_levels:
        scraped: dict[str, float] = {}
        incomplete = False
    else:
        scraped, incomplete = skill_percents(hero)
    fallback = catalog_percents(entry, hero.stars, hero.pellets)
    merged: dict[str, float] = {}
    for kind, value in leveled.items():
        merged[kind] = value
    for kind, value in scraped.items():
        if kind in merged:
            continue
        if kind_family(kind, catalog) == family:
            merged[kind] = value
    for kind, value in fallback.items():
        if kind in merged:
            continue
        if kind_family(kind, catalog) != family:
            continue
        # With manual levels, only fill kinds the leveled skills did not cover.
        if has_manual_levels and leveled:
            continue
        merged[kind] = value
        incomplete = True
    return merged, incomplete
