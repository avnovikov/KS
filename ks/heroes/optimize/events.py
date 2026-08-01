from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ks.heroes.optimize.types import EventProfile


def load_event_profile(path: Path | str) -> EventProfile:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("event profile must be a mapping")
    name = str(raw.get("name") or Path(path).stem)
    sources = tuple(str(s) for s in (raw.get("sources") or []))
    kind_raw = raw.get("mode_kind_weights") or {}
    op_raw = raw.get("effect_op_weights") or {}
    mode_kind: dict[str, dict[str, float]] = {}
    for mode, weights in kind_raw.items():
        if not isinstance(weights, dict):
            raise ValueError(f"mode_kind_weights.{mode} must be a mapping")
        mode_kind[str(mode)] = {str(k): float(v) for k, v in weights.items()}
    effect_ops: dict[str, dict[int, float]] = {}
    for mode, weights in op_raw.items():
        if not isinstance(weights, dict):
            raise ValueError(f"effect_op_weights.{mode} must be a mapping")
        effect_ops[str(mode)] = {int(k): float(v) for k, v in weights.items()}
    return EventProfile(
        name=name,
        sources=sources,
        mode_kind_weights=mode_kind or None,
        effect_op_weights=effect_ops or None,
    )


def default_kind_weights() -> dict[str, dict[str, float]]:
    """Fallback when no event profile is loaded."""
    return {
        "garrison": {
            "defender_attack": 3.0,
            "defender_health": 3.0,
            "defender_defense": 3.0,
            "damage_taken_down": 2.5,
            "defense_up": 2.0,
            "attack_up": 1.0,
            "lethality_up": 0.8,
            "rally_attack": 0.2,
            "rally_lethality": 0.2,
        },
        "rally_lead": {
            "rally_attack": 3.0,
            "rally_lethality": 3.0,
            "attack_up": 2.0,
            "lethality_up": 2.0,
            "defender_attack": 0.2,
            "damage_taken_down": 0.5,
            "defense_up": 0.5,
        },
        "joiner": {
            "damage_taken_down": 2.5,
            "lethality_up": 2.5,
            "attack_up": 2.2,
            "defense_up": 2.0,
            "defender_attack": 1.0,
            "rally_attack": 0.5,
        },
        "solo": {
            "attack_up": 2.0,
            "lethality_up": 2.0,
            "defense_up": 1.0,
            "damage_taken_down": 1.0,
            "rally_attack": 0.0,
            "defender_attack": 0.0,
            "rally_lethality": 0.0,
        },
    }
