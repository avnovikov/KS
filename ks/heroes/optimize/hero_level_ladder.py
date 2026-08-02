"""Hero level XP ladder and power-scale factors (scraped tables)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).resolve().parents[3]
_OPT = _ROOT / "config" / "hero_level_optimizer"


def _opt_path(name: str) -> Path:
    return _OPT / name


def load_hero_level_ladder(
    *,
    xp_path: Path | None = None,
    power_path: Path | None = None,
) -> dict[str, Any]:
    """Load XP costs + power factors into a single ladder dict.

    Returns keys: max_level, by_level[L] -> {xp_cost, cumulative_xp, power_factor}.
    """
    xp_raw = yaml.safe_load(
        (xp_path or _opt_path("hero_level_xp_costs.yaml")).read_text(encoding="utf-8")
    ) or {}
    pow_raw = yaml.safe_load(
        (power_path or _opt_path("hero_level_power.yaml")).read_text(encoding="utf-8")
    ) or {}
    max_level = int(xp_raw.get("max_level") or pow_raw.get("max_level") or 80)
    by_level: dict[int, dict[str, float | int]] = {}
    for row in xp_raw.get("levels") or []:
        lv = int(row["level"])
        by_level[lv] = {
            "xp_cost": int(row.get("xp_cost") or 0),
            "cumulative_xp": int(row.get("cumulative_xp") or 0),
            "power_factor": 0.0,
        }
    for row in pow_raw.get("levels") or []:
        lv = int(row["level"])
        entry = by_level.setdefault(
            lv, {"xp_cost": 0, "cumulative_xp": 0, "power_factor": 0.0}
        )
        entry["power_factor"] = float(row.get("power_factor") or 0)
    if not by_level:
        raise ValueError("hero level ladder is empty")
    return {"max_level": max_level, "by_level": by_level}


def level_power_factor(ladder: dict[str, Any], level: int) -> float:
    by_level: dict[int, dict[str, float | int]] = ladder["by_level"]
    if level not in by_level:
        raise ValueError(f"level {level} not in hero power ladder")
    return float(by_level[level]["power_factor"])


def xp_cost_next_hero_level(ladder: dict[str, Any], current_level: int) -> int | None:
    """XP required to go from current_level to current_level+1."""
    nxt = current_level + 1
    by_level: dict[int, dict[str, float | int]] = ladder["by_level"]
    if nxt not in by_level:
        return None
    return int(by_level[nxt]["xp_cost"])


def xp_cost_between_hero_levels(
    ladder: dict[str, Any],
    from_level: int,
    to_level: int,
) -> int:
    if to_level < from_level:
        raise ValueError(f"to_level {to_level} < from_level {from_level}")
    if to_level == from_level:
        return 0
    by_level: dict[int, dict[str, float | int]] = ladder["by_level"]
    if from_level not in by_level or to_level not in by_level:
        raise ValueError(f"levels {from_level}..{to_level} not in hero XP ladder")
    return int(by_level[to_level]["cumulative_xp"]) - int(
        by_level[from_level]["cumulative_xp"]
    )
