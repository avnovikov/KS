"""Kingshotdata skill flavor text for hero detail UI."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SKILL_DESCRIPTIONS_JSON = (
    _REPO_ROOT / "config" / "hero_skill_descriptions.json"
)
_FULL_WEB_STATS_CACHE = (
    _REPO_ROOT / "data" / "heroes" / "catalog_cache" / "kingshotdata_stats.json"
)


def _skill_text_from_web_stats(payload: dict[str, Any]) -> dict[str, dict[str, dict[str, str | None]]]:
    out: dict[str, dict[str, dict[str, str | None]]] = {}
    for hero in payload.get("heroes") or []:
        name = str(hero["name"])
        skills: dict[str, dict[str, str | None]] = {}
        for sk in hero.get("skills") or []:
            desc = sk.get("description")
            preview = sk.get("upgrade_preview")
            if not desc and not preview:
                continue
            skills[str(sk["name"])] = {
                "description": desc,
                "upgrade_preview": preview,
            }
        if skills:
            out[name] = skills
    return out


@lru_cache(maxsize=1)
def load_skill_descriptions_by_hero(
    path: str | None = None,
) -> dict[str, dict[str, dict[str, str | None]]]:
    """Return hero -> skill name -> {description, upgrade_preview}."""
    if path is not None:
        p = Path(path)
        if not p.is_file():
            return {}
        raw = json.loads(p.read_text(encoding="utf-8"))
        if "heroes" in raw and isinstance(raw["heroes"], dict):
            return raw["heroes"]
        return _skill_text_from_web_stats(raw)

    if _FULL_WEB_STATS_CACHE.is_file():
        raw = json.loads(_FULL_WEB_STATS_CACHE.read_text(encoding="utf-8"))
        return _skill_text_from_web_stats(raw)

    if not DEFAULT_SKILL_DESCRIPTIONS_JSON.is_file():
        return {}
    raw = json.loads(DEFAULT_SKILL_DESCRIPTIONS_JSON.read_text(encoding="utf-8"))
    heroes = raw.get("heroes")
    if isinstance(heroes, dict):
        return heroes
    return {}


def _widget_description_fallback(
    hero_name: str,
    skill_name: str,
    by_skill: dict[str, dict[str, str | None]],
    *,
    widget_march_skill: str | None = None,
) -> tuple[str | None, str | None]:
    """Resolve widget text when the weapon name differs from the skill name."""
    meta = by_skill.get(skill_name)
    if meta:
        return meta.get("description"), meta.get("upgrade_preview")
    # Kingshotdata often names the widget skill differently (e.g. Helga → Zeal).
    for candidate in by_skill.values():
        preview = candidate.get("upgrade_preview") or ""
        low = preview.lower()
        if "rally squad" in low or "defender squad" in low:
            return candidate.get("description"), preview
    if widget_march_skill:
        return widget_march_skill, None
    return None, None


def enrich_catalog_skills(
    hero_name: str,
    catalog_skills: list[dict[str, Any]],
    *,
    descriptions_path: str | None = None,
    widget_march_skill: str | None = None,
) -> list[dict[str, Any]]:
    """Attach kingshotdata description fields to catalog skill dicts."""
    by_hero = load_skill_descriptions_by_hero(descriptions_path)
    by_skill = by_hero.get(hero_name) or {}

    enriched: list[dict[str, Any]] = []
    for skill in catalog_skills:
        row = dict(skill)
        name = str(skill.get("name") or "")
        family = str(skill.get("family") or "").lower()
        if family == "widget":
            desc, preview = _widget_description_fallback(
                hero_name,
                name,
                by_skill,
                widget_march_skill=widget_march_skill,
            )
            if desc:
                row["description"] = desc
            if preview:
                row["upgrade_preview"] = preview
        else:
            meta = by_skill.get(name)
            if meta:
                desc = meta.get("description")
                preview = meta.get("upgrade_preview")
                if desc:
                    row["description"] = desc
                if preview:
                    row["upgrade_preview"] = preview
        enriched.append(row)
    return enriched
