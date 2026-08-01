from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ks.heroes.optimize.types import Scenario


def load_scenarios(path: Path | str) -> dict[str, Scenario]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    modes = raw.get("modes") or raw
    if not isinstance(modes, dict):
        raise ValueError("point_scenarios.yaml must map mode -> scenario")
    out: dict[str, Scenario] = {}
    for mode, meta in modes.items():
        if not isinstance(meta, dict):
            raise ValueError(f"scenario {mode!r} must be a mapping")
        out[str(mode)] = scenario_from_dict(str(mode), meta)
    return out


def scenario_from_dict(mode: str, meta: dict[str, Any]) -> Scenario:
    weights = meta.get("formation_weights") or {
        "infantry": 1.0,
        "cavalry": 1.0,
        "archers": 1.0,
    }
    return Scenario(
        mode=mode,
        combat_rate=float(meta.get("combat_rate", 0.0)),
        minutes_held=float(meta.get("minutes_held", 0.0)),
        personal_rate=float(meta.get("personal_rate", 0.0)),
        p_first=float(meta.get("p_first", 0.0)),
        first_bonus=float(meta.get("first_bonus", 0.0)),
        loot_expected=float(meta.get("loot_expected", 0.0)),
        enemy_power_scale=float(meta.get("enemy_power_scale", 100_000.0)),
        formation_weights={str(k): float(v) for k, v in weights.items()},
        require_widget=meta.get("require_widget"),
    )
