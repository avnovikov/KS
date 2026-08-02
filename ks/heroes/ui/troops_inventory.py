"""Read/write helpers for config/troops.yaml inventory edits."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

TYPE_KEYS = ("infantry", "cavalry", "archers")
TIERS = tuple(range(1, 12))

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_TROOPS_PATH = _PROJECT_ROOT / "config" / "troops.yaml"


def _empty_levels() -> dict[int, int]:
    return {tier: 0 for tier in TIERS}


def _parse_levels(raw: Any, *, label: str) -> dict[int, int]:
    levels = _empty_levels()
    if raw is None:
        return levels
    if isinstance(raw, bool):
        raise ValueError(f"troops.{label} must be a level mapping")
    if isinstance(raw, int):
        if raw < 0:
            raise ValueError(f"troops.{label} must be non-negative; got {raw}")
        if raw:
            levels[1] = raw
        return levels
    if not isinstance(raw, dict):
        raise ValueError(
            f"troops.{label} must be a level mapping; got {type(raw).__name__}"
        )
    for key, value in raw.items():
        tier = int(key)
        count = int(value)
        if tier not in levels:
            # Ignore unknown tiers on load; UI only edits 1–11.
            continue
        if count < 0:
            raise ValueError(
                f"troops.{label}[{tier}] must be non-negative; got {count}"
            )
        levels[tier] = count
    return levels


def _normalize(raw: dict[str, Any]) -> dict[str, Any]:
    if "march_capacity" not in raw:
        raise ValueError("troops config missing keys: ['march_capacity']")
    capacity = int(raw["march_capacity"])
    if capacity < 0:
        raise ValueError(
            f"troops.march_capacity must be non-negative; got {capacity}"
        )
    truegold = int(raw.get("truegold", 0))
    if truegold < 0:
        raise ValueError(f"troops.truegold must be non-negative; got {truegold}")

    missing = [k for k in TYPE_KEYS if k not in raw]
    if missing:
        raise ValueError(f"troops config missing keys: {missing}")

    types = {key: _parse_levels(raw[key], label=key) for key in TYPE_KEYS}
    return {
        "march_capacity": capacity,
        "truegold": truegold,
        **types,
        "totals": {key: sum(types[key].values()) for key in TYPE_KEYS},
    }


def load_inventory(path: Path | str) -> dict[str, Any]:
    file_path = Path(path)
    raw = yaml.safe_load(file_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(
            f"troops config must be a mapping; got {type(raw).__name__}"
        )
    return _normalize(raw)


def _dump_inventory(path: Path, inventory: dict[str, Any]) -> None:
    payload: dict[str, Any] = {
        "march_capacity": int(inventory["march_capacity"]),
        "truegold": int(inventory.get("truegold", 0)),
    }
    for key in TYPE_KEYS:
        payload[key] = {tier: int(inventory[key][tier]) for tier in TIERS}
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )


def set_count(
    path: Path | str, troop_type: str, tier: int, count: int
) -> dict[str, Any]:
    file_path = Path(path)
    if troop_type not in TYPE_KEYS:
        raise KeyError(f"unknown troop type: {troop_type!r}")
    if int(tier) not in TIERS:
        raise KeyError(f"unknown troop tier: {tier!r}")
    value = int(count)
    if value < 0:
        raise ValueError(f"count must be non-negative; got {value}")

    inventory = load_inventory(file_path)
    inventory[troop_type][int(tier)] = value
    inventory["totals"] = {
        key: sum(inventory[key].values()) for key in TYPE_KEYS
    }
    _dump_inventory(file_path, inventory)
    return inventory


def set_march_capacity(path: Path | str, capacity: int) -> dict[str, Any]:
    file_path = Path(path)
    value = int(capacity)
    if value < 0:
        raise ValueError(f"march_capacity must be non-negative; got {value}")
    inventory = load_inventory(file_path)
    inventory["march_capacity"] = value
    _dump_inventory(file_path, inventory)
    return inventory
