"""Enemy floor stubs for Mystic Trial rooms (Radiant #37 first)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ks.heroes.optimize.mystic_trial.ratios import normalize_ratio


@dataclass(frozen=True)
class FloorStub:
    floor: int
    enemy_ratio: dict[str, float]
    enemy_power_scale: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "floor": self.floor,
            "enemy_ratio": dict(self.enemy_ratio),
            "enemy_power_scale": self.enemy_power_scale,
        }


def load_floors(path: Path | str) -> dict[int, FloorStub]:
    p = Path(path).expanduser().resolve()
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"floors file must be a mapping: {p}")
    defaults = raw.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise ValueError("defaults must be a mapping")
    default_ratio = normalize_ratio(
        defaults.get("enemy_ratio")
        or {"infantry": 1 / 3, "cavalry": 1 / 3, "archers": 1 / 3}
    )
    default_scale = float(defaults.get("enemy_power_scale", 1.0))
    if default_scale <= 0:
        raise ValueError(f"enemy_power_scale must be positive; got {default_scale}")

    floors_raw = raw.get("floors") or {}
    if not isinstance(floors_raw, dict) or not floors_raw:
        raise ValueError(f"floors must be a non-empty mapping: {p}")

    out: dict[int, FloorStub] = {}
    for key, item in floors_raw.items():
        floor = int(key)
        row = item if isinstance(item, dict) else {}
        ratio = normalize_ratio(row["enemy_ratio"]) if "enemy_ratio" in row else default_ratio
        scale = float(row.get("enemy_power_scale", default_scale))
        if scale <= 0:
            raise ValueError(f"floor {floor}: enemy_power_scale must be positive; got {scale}")
        out[floor] = FloorStub(floor=floor, enemy_ratio=ratio, enemy_power_scale=scale)
    return out


def get_floor(floors: dict[int, FloorStub], floor: int) -> FloorStub | None:
    return floors.get(int(floor))
