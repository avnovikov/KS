from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml

from ks.heroes.optimize.types import TroopsConfig

_TYPE_KEYS = ("infantry", "cavalry", "archers")


def allocate_highest_first(owned: Mapping[int, int], need: int) -> dict[int, int]:
    """Take `need` troops preferring higher tiers."""
    if need < 0:
        raise ValueError(f"need must be non-negative; got {need}")
    remaining = int(need)
    out: dict[int, int] = {}
    for level in sorted((int(k) for k in owned), reverse=True):
        if remaining <= 0:
            break
        have = int(owned[level])
        if have <= 0:
            continue
        take = min(have, remaining)
        out[level] = take
        remaining -= take
    if remaining > 0:
        raise ValueError(
            f"not enough troops to allocate {need}; short by {remaining}"
        )
    return out


def _levels_tuple(mapping: Mapping[int, int]) -> tuple[tuple[int, int], ...]:
    return tuple(sorted((int(k), int(v)) for k, v in mapping.items() if int(v) != 0))


def _parse_type_block(raw: Any, *, label: str) -> tuple[int, tuple[tuple[int, int], ...]]:
    """Accept a flat int (all unspecified tier) or {level: count} mapping."""
    if isinstance(raw, bool):
        raise ValueError(f"troops.{label} must be int or level mapping")
    if isinstance(raw, int):
        if raw < 0:
            raise ValueError(f"troops.{label} must be non-negative; got {raw}")
        if raw == 0:
            return 0, ()
        return raw, ((1, raw),)
    if isinstance(raw, dict):
        levels: dict[int, int] = {}
        for key, value in raw.items():
            level = int(key)
            count = int(value)
            if level < 1:
                raise ValueError(f"troops.{label} level must be >= 1; got {level}")
            if count < 0:
                raise ValueError(
                    f"troops.{label}[{level}] must be non-negative; got {count}"
                )
            levels[level] = count
        total = sum(levels.values())
        return total, _levels_tuple(levels)
    raise ValueError(
        f"troops.{label} must be int or {{level: count}} mapping; got {type(raw).__name__}"
    )


def load_troops_config(path: Path | str) -> TroopsConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"troops config must be a mapping; got {type(raw).__name__}")
    return troops_config_from_dict(raw)


def troops_config_from_dict(raw: dict[str, Any]) -> TroopsConfig:
    if "march_capacity" not in raw:
        raise ValueError("troops config missing keys: ['march_capacity']")
    capacity = int(raw["march_capacity"])
    if capacity < 0:
        raise ValueError(f"troops.march_capacity must be non-negative; got {capacity}")

    missing = [k for k in _TYPE_KEYS if k not in raw]
    if missing:
        raise ValueError(f"troops config missing keys: {missing}")

    parsed = {key: _parse_type_block(raw[key], label=key) for key in _TYPE_KEYS}
    return TroopsConfig(
        infantry=parsed["infantry"][0],
        cavalry=parsed["cavalry"][0],
        archers=parsed["archers"][0],
        march_capacity=capacity,
        infantry_levels=parsed["infantry"][1],
        cavalry_levels=parsed["cavalry"][1],
        archers_levels=parsed["archers"][1],
    )


def breakdown_for_totals(
    troops: TroopsConfig, totals: Mapping[str, int]
) -> dict[str, dict[int, int]]:
    """Map ILP type totals onto owned tiers (highest first)."""
    out: dict[str, dict[int, int]] = {}
    for key in _TYPE_KEYS:
        need = int(totals.get(key, 0))
        owned = troops.levels(key)
        if not owned:
            # Flat inventory with no real tier data — stash under level 1.
            out[key] = {1: need} if need else {}
            continue
        out[key] = allocate_highest_first(owned, need) if need else {}
    return out
