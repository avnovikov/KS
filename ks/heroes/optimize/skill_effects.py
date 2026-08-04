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

from ks.heroes.models import HeroRecord
from ks.heroes.optimize.scoring import star_progress_factor
from ks.heroes.optimize.types import CatalogEntry

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
    "defender_attack": CONQUEST,
    "defender_defense": CONQUEST,
    "defender_health": CONQUEST,
}

_WIDGET = "widget"


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
    """Star-scaled percent per kind from catalog effects (widget kinds dropped)."""
    if entry is None:
        return {}
    factor = star_progress_factor(stars, pellets)
    out: dict[str, float] = {}
    for tag in entry.effects:
        if tag.applies_to == _WIDGET:
            continue
        out[tag.kind] = out.get(tag.kind, 0.0) + float(tag.max_value) * factor
    return out


def kind_family(
    kind: str,
    catalog: dict[str, CatalogEntry] | None = None,
) -> str | None:
    """Family a kind contributes to, or None when it is widget-only/unknown.

    Catalog ``applies_to`` wins: if any catalog entry tags ``kind`` as
    conquest or expedition, that is the family. A kind the catalog only ever
    tags as ``widget`` returns None. Otherwise fall back to the default map.
    """
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


def family_percents(
    hero: HeroRecord,
    entry: CatalogEntry | None,
    *,
    family: str,
    catalog: dict[str, CatalogEntry] | None = None,
) -> tuple[dict[str, float], bool]:
    """Percents for ``family`` from the scrape, falling back to the catalog.

    Scraped ``current_bonus`` is preferred because it reflects the hero's
    actual skill levels. When the scrape yields nothing for a kind the catalog
    knows about, the star-scaled catalog value fills in and the result is
    flagged incomplete.
    """
    if family not in (CONQUEST, EXPEDITION):
        raise ValueError(f"unknown family {family!r}; want conquest|expedition")
    scraped, incomplete = skill_percents(hero)
    fallback = catalog_percents(entry, hero.stars, hero.pellets)
    merged: dict[str, float] = {}
    for kind, value in scraped.items():
        if kind_family(kind, catalog) == family:
            merged[kind] = value
    for kind, value in fallback.items():
        if kind in merged:
            continue
        if kind_family(kind, catalog) != family:
            continue
        merged[kind] = value
        incomplete = True
    return merged, incomplete
