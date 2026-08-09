"""Lookup canonical gear display names by troop × slot × rarity.

OCR titles bleed across slots (e.g. gloves scraped as \"Crusader Battle Boots\").
When troop, slot, and rarity are known, inventory and optimizers prefer the
name from ``config/gear_names.yaml`` over the OCR string.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

import yaml

_TROOP_ALIASES = {
    "infantry": "infantry",
    "cavalry": "cavalry",
    "archer": "archers",
    "archers": "archers",
    "marksman": "archers",
    "ranged": "archers",
}

_SLOT_ALIASES = {
    "helmet": "helmet",
    "helm": "helmet",
    "armet": "helmet",
    "faceplate": "helmet",
    "gloves": "gloves",
    "glove": "gloves",
    "gauntlets": "gloves",
    "gauntlet": "gloves",
    "bracers": "gloves",
    "bracer": "gloves",
    "chest": "chest",
    "armor": "chest",
    "armour": "chest",
    "shroud": "chest",
    "breastplate": "chest",
    "leatherwear": "chest",
    "boots": "boots",
    "boot": "boots",
    "greaves": "boots",
    "riders": "boots",
}

_RARITY_ALIASES = {
    "grey": "grey",
    "gray": "grey",
    "common": "grey",
    "green": "green",
    "uncommon": "green",
    "blue": "blue",
    "rare": "blue",
    "purple": "epic",
    "epic": "epic",
    "gold": "mythic",
    "mythic": "mythic",
    "red": "red",
}


def normalize_troop(troop: str | None) -> str | None:
    if not troop:
        return None
    return _TROOP_ALIASES.get(troop.strip().lower())


def normalize_slot(slot: str | None) -> str | None:
    if not slot:
        return None
    return _SLOT_ALIASES.get(slot.strip().lower())


def normalize_rarity(rarity: str | None) -> str | None:
    if not rarity:
        return None
    return _RARITY_ALIASES.get(rarity.strip().lower())


def _default_table_path() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "gear_names.yaml"


@lru_cache(maxsize=4)
def _load_names_table(path_str: str) -> Mapping[str, Any]:
    path = Path(path_str)
    if not path.is_file():
        raise FileNotFoundError(f"gear names table missing: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"gear_names.yaml must be a mapping; got {type(raw).__name__}")
    names = raw.get("names")
    if not isinstance(names, dict):
        raise ValueError("gear_names.yaml must contain a 'names' mapping")
    return names


def canonical_gear_name(
    *,
    troop: str | None,
    slot: str | None,
    rarity: str | None,
    table_path: Path | None = None,
) -> str | None:
    """Return the display name for ``(troop, slot, rarity)``, or None if unknown."""
    nt = normalize_troop(troop)
    ns = normalize_slot(slot)
    nr = normalize_rarity(rarity)
    if nt is None or ns is None or nr is None:
        return None
    path = table_path or _default_table_path()
    table = _load_names_table(str(path.resolve()))
    troop_row = table.get(nt)
    if not isinstance(troop_row, dict):
        return None
    slot_row = troop_row.get(ns)
    if not isinstance(slot_row, dict):
        return None
    name = slot_row.get(nr)
    if name is None:
        return None
    text = str(name).strip()
    return text or None


def apply_canonical_name(
    *,
    name: str | None,
    troop: str | None,
    slot: str | None,
    rarity: str | None,
    table_path: Path | None = None,
) -> str | None:
    """Prefer table name when the triple is known; otherwise keep ``name``."""
    canonical = canonical_gear_name(
        troop=troop, slot=slot, rarity=rarity, table_path=table_path
    )
    return canonical if canonical is not None else name
