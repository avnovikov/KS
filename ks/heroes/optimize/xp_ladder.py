"""Enhancement XP ladder, rarity caps, and typed fodder bags."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).resolve().parents[3]
_OPT = _ROOT / "config" / "hero_gear_optimizer"

# Prefer large densoms only when they reduce waste; iteration order for DP.
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
            "blue_max": int(caps.get("blue_max", 60)),
            "green_max": int(caps.get("green_max", 40)),
            "grey_max": int(caps.get("grey_max", 20)),
        },
        "by_level": by_level,
    }


def cap_for_rarity(rarity: str | None, *, ladder: dict[str, Any] | None = None) -> int:
    """Max enhancement level by rarity (community caps + optimizer ladder)."""
    caps = (ladder or load_xp_ladder())["caps"]
    key = (rarity or "").strip().lower()
    if key in {"red"}:
        return int(caps["red_max"])
    if key in {"mythic", "gold"}:
        return int(caps["mythic_max"])
    if key in {"epic", "purple"}:
        return int(caps["epic_max"])
    if key in {"blue", "rare"}:
        return int(caps.get("blue_max", 60))
    if key in {"green", "uncommon"}:
        return int(caps.get("green_max", 40))
    if key in {"grey", "gray", "common"}:
        return int(caps.get("grey_max", 20))
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


def _spend_preference_key(spend: dict[str, int]) -> tuple[int, int]:
    """Lower is better: fewer items (larger densoms), then fewer large leftovers used.

    Min-waste already decided; this only breaks ties — e.g. prefer one 100-pt
    plate over six small pieces when both cover 100 XP exactly.
    """
    n_items = sum(int(v) for v in spend.values())
    # Secondary: prefer spending larger densoms when item counts match.
    large_first = tuple(-int(spend.get(k, 0)) for k in _FODDER_ORDER)
    return (n_items, *large_first)


def _plan_cover_min_waste(
    counts: dict[str, int],
    cost: int,
    vals: dict[str, int],
) -> dict[str, int] | None:
    """Cover ``cost`` XP with min overshoot; break ties sparing large densoms."""
    max_unit = max(int(vals[k]) for k in counts)
    limit = int(cost) + max_unit - 1
    # xp -> spend counts achieving that xp
    reachable: dict[int, dict[str, int]] = {0: {}}

    for kind in reversed(_FODDER_ORDER):  # add small densoms first
        unit = int(vals[kind])
        have = int(counts.get(kind, 0))
        if have <= 0 or unit <= 0:
            continue
        previous = reachable
        reachable = dict(previous)
        for xp, spend in previous.items():
            for n in range(1, have + 1):
                new_xp = xp + n * unit
                if new_xp > limit:
                    break
                new_spend = dict(spend)
                new_spend[kind] = int(new_spend.get(kind, 0)) + n
                old = reachable.get(new_xp)
                if old is None or _spend_preference_key(new_spend) < _spend_preference_key(
                    old
                ):
                    reachable[new_xp] = new_spend

    best_xp: int | None = None
    best_spend: dict[str, int] | None = None
    best_key: tuple[int, ...] | None = None
    for xp, spend in reachable.items():
        if xp < cost:
            continue
        key = (xp - cost, *_spend_preference_key(spend))
        if best_key is None or key < best_key:
            best_xp = xp
            best_spend = spend
            best_key = key
    if best_spend is None:
        return None
    return {k: v for k, v in best_spend.items() if v}


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
        """Min-waste cover of ``cost`` XP; returns counts to spend or None.

        Prefers small denominations when they cover with less overshoot than a
        plate/purple (e.g. 5 grey for 45 XP instead of one 100-pt part).
        """
        if cost <= 0:
            return {}
        vals = values or load_fodder_xp_values()
        if self.total_xp(vals) < int(cost):
            return None
        return _plan_cover_min_waste(self.counts(), int(cost), vals)

    def consume(self, spend: dict[str, int]) -> FodderBag:
        counts = self.counts()
        for kind, n in spend.items():
            if kind not in counts:
                raise ValueError(f"unknown fodder kind {kind!r}")
            if n < 0 or n > counts[kind]:
                raise ValueError(f"cannot spend {n} of {kind}; have {counts[kind]}")
            counts[kind] -= n
        return FodderBag(**counts)
