from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from ks.heroes.optimize.types import CatalogEntry, CatalogSkill, EffectTag

# Re-export for callers that import arena helpers from catalog.
__all__ = [
    "load_catalog",
    "arena_heroes_from_catalog",
    "heroes_by_troop",
]


def _parse_effects(effects_raw: list[Any]) -> list[EffectTag]:
    effects: list[EffectTag] = []
    for item in effects_raw:
        if not isinstance(item, dict):
            raise ValueError("effect entries must be mappings")
        op = item.get("effect_op")
        proc_raw = item.get("proc_chance")
        proc_chance: float | None = None
        if proc_raw is not None:
            proc_chance = float(proc_raw)
            if not 0.0 < proc_chance <= 1.0:
                raise ValueError(
                    f"effect proc_chance must be in (0, 1]; got {proc_chance}"
                )
        effects.append(
            EffectTag(
                kind=str(item["kind"]),
                max_value=float(item["max_value"]),
                applies_to=str(item.get("applies_to") or "expedition"),
                effect_op=int(op) if op is not None else None,
                first_expedition=bool(item.get("first_expedition", False)),
                proc_chance=proc_chance,
            )
        )
    return effects


_SKILL_FAMILIES = frozenset({"conquest", "expedition", "widget"})


def _parse_skills(skills_raw: list[Any], *, hero_name: str) -> list[CatalogSkill]:
    skills: list[CatalogSkill] = []
    for item in skills_raw:
        if not isinstance(item, dict):
            raise ValueError(f"skills for {hero_name!r} must be mappings")
        name = str(item.get("name") or "").strip()
        if not name:
            raise ValueError(f"skill for {hero_name!r} requires non-empty name")
        family = str(item.get("family") or "").strip().lower()
        if family not in _SKILL_FAMILIES:
            raise ValueError(
                f"skill {name!r} for {hero_name!r} has invalid family {family!r}"
            )
        effect_kind = item.get("effect_kind")
        ladder_raw = item.get("ladder")
        ladder: tuple[float, ...] | None = None
        if ladder_raw is not None:
            if not isinstance(ladder_raw, (list, tuple)) or not ladder_raw:
                raise ValueError(
                    f"skill {name!r} for {hero_name!r} ladder must be a non-empty list"
                )
            ladder = tuple(float(v) for v in ladder_raw)
        hits = item.get("hits_per_cast")
        cast_rate = item.get("cast_rate")
        skills.append(
            CatalogSkill(
                slot=int(item["slot"]),
                name=name,
                family=family,
                effect_kind=str(effect_kind) if effect_kind is not None else None,
                ladder=ladder,
                hits_per_cast=int(hits) if hits is not None else None,
                cast_rate=float(cast_rate) if cast_rate is not None else None,
            )
        )
    skills.sort(key=lambda s: s.slot)
    return skills


def _load_pro_cache_entries(pro_path: Path | str | None) -> dict[str, dict[str, Any]]:
    """Seed catalog rows from the optional pro-cache JSON dump.

    Returns an empty mapping when ``pro_path`` is None or missing, in which
    case the YAML overlay below is the sole source of truth.
    """
    by_name: dict[str, dict[str, Any]] = {}
    if pro_path is None:
        return by_name
    path = Path(pro_path)
    if not path.is_file():
        return by_name
    pro_raw = json.loads(path.read_text(encoding="utf-8"))
    for hero in pro_raw.get("heroes") or []:
        name = str(hero["name"])
        by_name[name] = {
            "name": name,
            "gen": hero.get("gen"),
            "troop": hero.get("troop"),
            "rarity": hero.get("rarity"),
            "rally_tier": hero.get("rally"),
            "garrison_tier": hero.get("garrison"),
            "joiner_tier": hero.get("joiner"),
            "widget_type": None,
            "widget_name": None,
            "widget_march_skill": None,
            "rally_widget_priority": None,
            "garrison_widget_priority": None,
            "effects": [],
        }
    return by_name


def _default_catalog_row(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "effects": [],
        "skills": [],
        "widget_type": None,
        "widget_name": None,
        "widget_march_skill": None,
        "rally_widget_priority": None,
        "garrison_widget_priority": None,
    }


def _coerce_str_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    return [str(item) for item in value]


# Scalar fields copied verbatim from a YAML hero entry when present.
_YAML_OVERLAY_SCALAR_KEYS = (
    "gen",
    "troop",
    "rarity",
    "widget_type",
    "widget_name",
    "widget_march_skill",
    "rally_widget_priority",
    "garrison_widget_priority",
    "arena_role",
    "arena_value",
    "obtain",
    "notes",
)


def _apply_arena_overlay(base: dict[str, Any], meta: dict[str, Any], name: str) -> None:
    """Apply flat ``arena_tags`` and/or nested ``arena: {role, value, tags}`` overrides."""
    if "arena_tags" in meta and meta.get("arena_tags") is not None:
        base["arena_tags"] = _coerce_str_list(
            meta.get("arena_tags"), f"arena_tags for {name!r}"
        )
    arena = meta.get("arena")
    if not isinstance(arena, dict):
        return
    if arena.get("role") is not None:
        base["arena_role"] = arena.get("role")
    if arena.get("value") is not None:
        base["arena_value"] = arena.get("value")
    if arena.get("tags") is not None:
        base["arena_tags"] = _coerce_str_list(
            arena.get("tags"), f"arena.tags for {name!r}"
        )


def _apply_yaml_overlay(
    base: dict[str, Any], meta: dict[str, Any], name: str
) -> dict[str, Any]:
    """Merge one YAML ``heroes.<name>`` entry onto a pro-cache (or default) row."""
    for key in _YAML_OVERLAY_SCALAR_KEYS:
        if meta.get(key) is not None:
            base[key] = meta[key]
    _apply_arena_overlay(base, meta, name)
    if "effects" in meta:
        base["effects"] = _parse_effects(meta.get("effects") or [])
    if "skills" in meta:
        base["skills"] = _parse_skills(meta.get("skills") or [], hero_name=name)
    return base


def _merge_yaml_heroes(
    by_name: dict[str, dict[str, Any]], yaml_heroes: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    for name, meta in yaml_heroes.items():
        if not isinstance(meta, dict):
            raise ValueError(f"catalog entry for {name!r} must be a mapping")
        base = by_name.get(name, _default_catalog_row(name))
        by_name[name] = _apply_yaml_overlay(base, meta, name)
    return by_name


def _build_catalog_entry(name: str, data: dict[str, Any]) -> CatalogEntry:
    effects = data.get("effects") or []
    if effects and isinstance(effects[0], dict):
        effects = _parse_effects(effects)
    skills = data.get("skills") or ()
    if skills and isinstance(skills[0], dict):
        skills = _parse_skills(skills, hero_name=name)
    return CatalogEntry(
        name=name,
        gen=int(data["gen"]) if data.get("gen") is not None else None,
        troop=data.get("troop"),
        rarity=data.get("rarity"),
        widget_type=data.get("widget_type"),
        widget_name=data.get("widget_name"),
        widget_march_skill=data.get("widget_march_skill"),
        rally_widget_priority=(
            int(data["rally_widget_priority"])
            if data.get("rally_widget_priority") is not None
            else None
        ),
        garrison_widget_priority=(
            int(data["garrison_widget_priority"])
            if data.get("garrison_widget_priority") is not None
            else None
        ),
        rally_tier=data.get("rally_tier"),
        garrison_tier=data.get("garrison_tier"),
        joiner_tier=data.get("joiner_tier"),
        effects=tuple(effects),
        skills=tuple(skills),
        arena_role=data.get("arena_role"),
        arena_value=(
            float(data["arena_value"]) if data.get("arena_value") is not None else None
        ),
        arena_tags=tuple(data.get("arena_tags") or ()),
        obtain=data.get("obtain"),
        notes=data.get("notes"),
    )


def load_catalog(
    pro_path: Path | str | None, yaml_path: Path | str
) -> dict[str, CatalogEntry]:
    """Merge optional pro-cache JSON with YAML catalog overlays.

    When ``pro_path`` is None or missing, YAML-only catalog is used (no file
    is created).
    """
    yaml_raw = yaml.safe_load(Path(yaml_path).read_text(encoding="utf-8")) or {}
    if not isinstance(yaml_raw, dict):
        raise ValueError("hero_catalog.yaml must be a mapping")

    yaml_heroes = yaml_raw.get("heroes") or {}
    if not isinstance(yaml_heroes, dict):
        raise ValueError("hero_catalog.yaml heroes must be a mapping")

    by_name = _load_pro_cache_entries(pro_path)
    by_name = _merge_yaml_heroes(by_name, yaml_heroes)

    return {name: _build_catalog_entry(name, data) for name, data in by_name.items()}


def heroes_by_troop(
    catalog: dict[str, CatalogEntry],
    *,
    roster_troop: dict[str, str] | None = None,
) -> dict[str, list[str]]:
    """Group catalog hero names by troop class for UI pickers.

    Troop comes from the catalog when set; otherwise from ``roster_troop``
    (scraped inventory). ``archer`` normalizes to ``archers``. Heroes with no
    resolvable troop are omitted.
    """
    from ks.heroes.optimize.scoring import normalize_troop

    out: dict[str, list[str]] = {
        "infantry": [],
        "cavalry": [],
        "archers": [],
    }
    roster = roster_troop or {}
    for name, entry in catalog.items():
        troop = normalize_troop(entry.troop) or normalize_troop(roster.get(name))
        if troop in out:
            out[troop].append(name)
    for names in out.values():
        names.sort()
    return out


def arena_heroes_from_catalog(
    catalog: dict[str, CatalogEntry],
) -> dict[str, dict[str, Any]]:
    """Build arena_roles-style heroes map from the catalog (source of truth)."""
    out: dict[str, dict[str, Any]] = {}
    for name, entry in catalog.items():
        if (
            entry.arena_role is None
            and entry.arena_value is None
            and not entry.arena_tags
        ):
            continue
        out[name] = {
            "role": entry.arena_role,
            "arena_value": entry.arena_value if entry.arena_value is not None else 40.0,
            "tags": list(entry.arena_tags),
        }
    return out
