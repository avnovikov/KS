"""Enhancement XP ladder, rarity caps, and typed fodder bags."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).resolve().parents[3]
_OPT = _ROOT / "config" / "hero_gear_optimizer"

# Denominations largest-first for covering a cost.
_FODDER_ORDER = ("purple", "part_100", "blue", "green", "grey")


def _opt_path(name: str) -> Path:
    return _OPT / name


def load_fodder_xp_values(*, path: Path | None = None) -> dict[str, int]:
    cfg = path or _opt_path("pieces_and_stats.yaml")
    raw = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
    fodder = raw.get("fodder_xp_values") or {}
    return {
        "grey": int(fodder.get("grey_gear", 10)),
        "green": int(fodder.get("green_gear", 30)),
        "blue": int(fodder.get("blue_gear", 60)),
        "purple": int(fodder.get("purple_gear", 150)),
        "part_100": int(fodder.get("xp_part_purple_100", 100)),
    }


def load_xp_ladder(*, path: Path | None = None) -> dict[str, Any]:
    cfg = path or _opt_path("enhancement_xp_costs.yaml")
    raw = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
    caps = raw.get("caps") or {}
    levels = raw.get("levels") or []
    by_level: dict[int, dict[str, int]] = {}
    for row in levels:
        lv = int(row["level"])
        by_level[lv] = {
            "xp_cost": int(row.get("xp_cost") or 0),
            "cumulative_xp": int(row.get("cumulative_xp") or 0),
        }
    return {
        "caps": {
            "epic_max": int(caps.get("epic_max", 80)),
            "mythic_max": int(caps.get("mythic_max", 100)),
            "red_max": int(caps.get("red_max", 200)),
        },
        "by_level": by_level,
    }


def cap_for_rarity(rarity: str | None, *, ladder: dict[str, Any] | None = None) -> int:
    caps = (ladder or load_xp_ladder())["caps"]
    key = (rarity or "").strip().lower()
    if key in {"red"}:
        return int(caps["red_max"])
    if key in {"mythic", "gold"}:
        return int(caps["mythic_max"])
    # grey/green/blue/epic/purple and unknown → epic_max as safe soft cap for v1
    return int(caps["epic_max"])


def xp_cost_between(
    ladder: dict[str, Any],
    from_level: int,
    to_level: int,
) -> int:
    if to_level < from_level:
        raise ValueError(f"to_level {to_level} < from_level {from_level}")
    if to_level == from_level:
        return 0
    by_level: dict[int, dict[str, int]] = ladder["by_level"]
    if from_level not in by_level or to_level not in by_level:
        raise ValueError(f"levels {from_level}..{to_level} not in XP ladder")
    return int(by_level[to_level]["cumulative_xp"] - by_level[from_level]["cumulative_xp"])


def xp_cost_next_level(ladder: dict[str, Any], current_level: int) -> int | None:
    nxt = current_level + 1
    by_level: dict[int, dict[str, int]] = ladder["by_level"]
    if nxt not in by_level:
        return None
    return int(by_level[nxt]["xp_cost"])


@dataclass(frozen=True)
class FodderBag:
    grey: int = 0
    green: int = 0
    blue: int = 0
    purple: int = 0
    part_100: int = 0

    def counts(self) -> dict[str, int]:
        return {
            "grey": self.grey,
            "green": self.green,
            "blue": self.blue,
            "purple": self.purple,
            "part_100": self.part_100,
        }

    def total_xp(self, values: dict[str, int] | None = None) -> int:
        vals = values or load_fodder_xp_values()
        return sum(int(self.counts()[k]) * int(vals[k]) for k in vals)

    def plan_cover(
        self,
        cost: int,
        *,
        values: dict[str, int] | None = None,
    ) -> dict[str, int] | None:
        """Greedy largest-first cover; returns counts to spend or None."""
        if cost <= 0:
            return {}
        vals = values or load_fodder_xp_values()
        remaining = int(cost)
        available = dict(self.counts())
        spend = {k: 0 for k in available}
        for kind in _FODDER_ORDER:
            unit = int(vals[kind])
            while available[kind] > 0 and remaining > 0:
                # Take a unit if it helps (even if overshoot).
                available[kind] -= 1
                spend[kind] += 1
                remaining -= unit
        if remaining > 0:
            return None
        return {k: v for k, v in spend.items() if v}

    def consume(self, spend: dict[str, int]) -> FodderBag:
        counts = self.counts()
        for kind, n in spend.items():
            if kind not in counts:
                raise ValueError(f"unknown fodder kind {kind!r}")
            if n < 0 or n > counts[kind]:
                raise ValueError(f"cannot spend {n} of {kind}; have {counts[kind]}")
            counts[kind] -= n
        return FodderBag(**counts)
