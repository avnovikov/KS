"""Enemy floor stubs for Mystic Trial rooms (Radiant #37 first)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

import yaml

from ks.heroes.optimize.mystic_trial.ratios import TROOP_TYPES, normalize_ratio

BONUS_KEYS: tuple[str, ...] = (
    "attack_pct",
    "defense_pct",
    "lethality_pct",
    "health_pct",
)

_ZERO_TROOP_BONUS: dict[str, float] = {k: 0.0 for k in BONUS_KEYS}


def empty_enemy_bonuses() -> dict[str, dict[str, float]]:
    return {t: dict(_ZERO_TROOP_BONUS) for t in TROOP_TYPES}


def parse_enemy_bonuses(raw: Any) -> dict[str, dict[str, float]]:
    """Parse battle-report style % bonuses; missing keys default to 0."""
    out = empty_enemy_bonuses()
    if raw is None:
        return out
    if not isinstance(raw, dict):
        raise ValueError(f"enemy_bonuses must be a mapping; got {type(raw).__name__}")
    for troop in TROOP_TYPES:
        row = raw.get(troop)
        if row is None:
            continue
        if not isinstance(row, dict):
            raise ValueError(f"enemy_bonuses.{troop} must be a mapping")
        for key in BONUS_KEYS:
            if key not in row:
                continue
            out[troop][key] = float(row[key])
    return out


@dataclass(frozen=True)
class FloorStub:
    floor: int
    enemy_ratio: dict[str, float]
    enemy_power_scale: float
    enemy_bonuses: dict[str, dict[str, float]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "floor": self.floor,
            "enemy_ratio": dict(self.enemy_ratio),
            "enemy_power_scale": self.enemy_power_scale,
            "enemy_bonuses": {
                t: dict(self.enemy_bonuses.get(t, _ZERO_TROOP_BONUS)) for t in TROOP_TYPES
            },
        }

    def with_overrides(
        self,
        *,
        enemy_ratio: Mapping[str, float] | None = None,
        enemy_bonuses: Mapping[str, Mapping[str, float]] | None = None,
    ) -> FloorStub:
        """Return a copy with optional UI / battle-report overrides applied."""
        ratio = (
            normalize_ratio(enemy_ratio) if enemy_ratio is not None else self.enemy_ratio
        )
        bonuses = (
            parse_enemy_bonuses(enemy_bonuses)
            if enemy_bonuses is not None
            else self.enemy_bonuses
        )
        return replace(self, enemy_ratio=ratio, enemy_bonuses=bonuses)


def ratio_from_parts(
    infantry: float | None,
    cavalry: float | None,
    archers: float | None,
) -> dict[str, float] | None:
    """Build a normalized ratio from query parts.

    Values may be fractions (sum ≈ 1) or percents (sum ≈ 100). All three
    required when any is set.
    """
    parts = (infantry, cavalry, archers)
    if all(p is None for p in parts):
        return None
    if any(p is None for p in parts):
        raise ValueError(
            "enemy_infantry, enemy_cavalry, and enemy_archers must all be set together"
        )
    vals = {
        "infantry": float(infantry),
        "cavalry": float(cavalry),
        "archers": float(archers),
    }
    if any(v < 0 for v in vals.values()):
        raise ValueError(f"enemy ratio parts must be non-negative; got {vals}")
    total = sum(vals.values())
    if total <= 0:
        raise ValueError("enemy ratio parts must sum to a positive value")
    if total > 1.5:
        vals = {k: v / 100.0 for k, v in vals.items()}
    return normalize_ratio(vals)


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
    default_bonuses = parse_enemy_bonuses(defaults.get("enemy_bonuses"))

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
        if "enemy_bonuses" in row:
            bonuses = parse_enemy_bonuses(row["enemy_bonuses"])
        else:
            bonuses = {t: dict(default_bonuses[t]) for t in TROOP_TYPES}
        out[floor] = FloorStub(
            floor=floor,
            enemy_ratio=ratio,
            enemy_power_scale=scale,
            enemy_bonuses=bonuses,
        )
    return out


def get_floor(floors: dict[int, FloorStub], floor: int) -> FloorStub | None:
    return floors.get(int(floor))
