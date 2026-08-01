from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from ks.heroes.optimize.types import CatalogEntry, EffectTag


def _parse_effects(effects_raw: list[Any]) -> list[EffectTag]:
    effects: list[EffectTag] = []
    for item in effects_raw:
        if not isinstance(item, dict):
            raise ValueError("effect entries must be mappings")
        op = item.get("effect_op")
        effects.append(
            EffectTag(
                kind=str(item["kind"]),
                max_value=float(item["max_value"]),
                applies_to=str(item.get("applies_to") or "expedition"),
                effect_op=int(op) if op is not None else None,
                first_expedition=bool(item.get("first_expedition", False)),
            )
        )
    return effects


def load_catalog(pro_path: Path | str, yaml_path: Path | str) -> dict[str, CatalogEntry]:
    pro_raw = json.loads(Path(pro_path).read_text(encoding="utf-8"))
    yaml_raw = yaml.safe_load(Path(yaml_path).read_text(encoding="utf-8")) or {}
    if not isinstance(yaml_raw, dict):
        raise ValueError("hero_catalog.yaml must be a mapping")

    by_name: dict[str, dict[str, Any]] = {}
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

    yaml_heroes = yaml_raw.get("heroes") or {}
    if not isinstance(yaml_heroes, dict):
        raise ValueError("hero_catalog.yaml heroes must be a mapping")

    for name, meta in yaml_heroes.items():
        if not isinstance(meta, dict):
            raise ValueError(f"catalog entry for {name!r} must be a mapping")
        base = by_name.get(
            name,
            {
                "name": name,
                "effects": [],
                "widget_type": None,
                "widget_name": None,
                "widget_march_skill": None,
                "rally_widget_priority": None,
                "garrison_widget_priority": None,
            },
        )
        for key in (
            "gen",
            "troop",
            "rarity",
            "widget_type",
            "widget_name",
            "widget_march_skill",
            "rally_widget_priority",
            "garrison_widget_priority",
        ):
            if meta.get(key) is not None:
                base[key] = meta[key]
        if "effects" in meta:
            base["effects"] = _parse_effects(meta.get("effects") or [])
        by_name[name] = base

    result: dict[str, CatalogEntry] = {}
    for name, data in by_name.items():
        effects = data.get("effects") or []
        if effects and isinstance(effects[0], dict):
            effects = _parse_effects(effects)
        result[name] = CatalogEntry(
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
        )
    return result
