"""Allocate enhancement fodder XP to maximize event optimizer utility."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable

from ks.heroes.gear_models import GearRecord
from ks.heroes.models import HeroRecord
from ks.heroes.optimize.xp_ladder import (
    FodderBag,
    cap_for_rarity,
    load_fodder_xp_values,
    load_xp_ladder,
    xp_cost_next_level,
)
from ks.heroes.ui.power import compute_gear_power, known_rarity

REPO_ROOT = Path(__file__).resolve().parents[3]

UtilityFn = Callable[[list[GearRecord]], tuple[float, dict[str, Any]]]


@dataclass(frozen=True)
class SpendStep:
    piece_id: str
    name: str | None
    from_level: int
    to_level: int
    xp_spent: int
    fodder_spent: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "piece_id": self.piece_id,
            "name": self.name,
            "from_level": self.from_level,
            "to_level": self.to_level,
            "xp_spent": self.xp_spent,
            "fodder_spent": dict(self.fodder_spent),
        }


@dataclass(frozen=True)
class SpendResult:
    event: str
    baseline_utility: float
    best_utility: float
    steps: tuple[SpendStep, ...]
    leftover: FodderBag
    baseline_summary: dict[str, Any]
    best_summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "baseline_utility": self.baseline_utility,
            "best_utility": self.best_utility,
            "delta_utility": self.best_utility - self.baseline_utility,
            "steps": [s.to_dict() for s in self.steps],
            "leftover": self.leftover.counts(),
            "baseline_summary": dict(self.baseline_summary),
            "best_summary": dict(self.best_summary),
        }


def _with_level(piece: GearRecord, level: int) -> GearRecord:
    power = piece.power
    if known_rarity(piece.rarity):
        try:
            power = compute_gear_power(piece.rarity, level, piece.mastery_level)
        except ValueError:
            power = piece.power
    return replace(piece, enhancement_level=level, power=power)


def apply_levels(
    gear: list[GearRecord],
    levels: dict[str, int],
) -> list[GearRecord]:
    out: list[GearRecord] = []
    for piece in gear:
        if piece.piece_id in levels:
            out.append(_with_level(piece, int(levels[piece.piece_id])))
        else:
            out.append(piece)
    return out


def current_levels(gear: list[GearRecord]) -> dict[str, int]:
    return {
        p.piece_id: int(p.enhancement_level or 0)
        for p in gear
        if p.piece_id
    }


def build_event_utility(
    event: str,
    heroes: list[HeroRecord],
    *,
    config_root: Path | None = None,
    troops_path: Path | None = None,
    mode: str | None = None,
) -> UtilityFn:
    """Return U(gear) -> (utility, summary) for sword/bear/arena events.

    `troops_path` overrides where troop counts/truegold are read from (the
    UI-editable copy); it defaults to the repo-relative config/troops.yaml
    used before Task 2 wired in a store.
    """
    root = (config_root or REPO_ROOT).expanduser().resolve()
    key = event.strip().lower().replace(" ", "_")

    from ks.heroes.optimize.catalog import load_catalog

    catalog = load_catalog(None, root / "config" / "hero_catalog.yaml")

    if key in {"arena_attack", "arena_defense", "arena"}:
        from ks.heroes.optimize.arena import load_arena_roles, optimize_arena

        side = "defense" if "defense" in key else "attack"
        if key == "arena" and mode in {"attack", "defense"}:
            side = mode
        roles = load_arena_roles(
            root / "config" / "arena_roles.yaml", catalog=catalog
        )

        def _arena(gear: list[GearRecord]) -> tuple[float, dict[str, Any]]:
            result = optimize_arena(
                side,
                heroes,
                catalog,
                roles,
                gear=gear,
                with_explanations=False,
            )
            util = float(result.score) if result.status == "Optimal" else float("-inf")
            return util, {
                "status": result.status,
                "side": side,
                "formation": dict(result.formation),
                "heroes": list(result.heroes),
                "score": result.score if result.status == "Optimal" else None,
            }

        return _arena

    from ks.heroes.optimize.events import load_event_profile
    from ks.heroes.optimize.recommend import recommend, recommend_all_modes
    from ks.heroes.optimize.scenarios import load_scenarios
    from ks.heroes.optimize.troop_stats import load_troop_stats
    from ks.heroes.optimize.troops import load_troops_config
    import yaml

    if key in {"sword", "swordland"}:
        event_path = root / "config" / "events" / "swordland.yaml"
        scenarios_path = root / "config" / "point_scenarios.yaml"
        gear_profile = "early_game_growth"
    elif key in {"bear", "beartrap", "bear_trap"}:
        event_path = root / "config" / "events" / "beartrap.yaml"
        scenarios_path = root / "config" / "point_scenarios_beartrap.yaml"
        gear_profile = "early_game_growth"
    else:
        raise ValueError(f"unsupported event {event!r}")

    resolved_troops_path = (
        Path(troops_path).expanduser().resolve()
        if troops_path is not None
        else root / "config" / "troops.yaml"
    )
    troops = load_troops_config(resolved_troops_path)
    scenarios = load_scenarios(scenarios_path)
    event_profile = load_event_profile(event_path)
    troop_stats = load_troop_stats(root / "config" / "troop_stats.yaml")
    raw_troops = yaml.safe_load(
        resolved_troops_path.read_text(encoding="utf-8")
    ) or {}
    truegold = int(raw_troops.get("truegold", troop_stats.default_truegold))

    def _event(gear: list[GearRecord]) -> tuple[float, dict[str, Any]]:
        if mode:
            result = recommend(
                heroes,
                catalog,
                troops,
                scenarios,
                force_mode=mode,
                event=event_profile,
                troop_stats=troop_stats,
                truegold=truegold,
                gear=gear,
                gear_profile=gear_profile,
            )
            return float(result.expected_personal_points), {
                "mode": result.recommended_mode,
                "heroes": [h["name"] for h in result.heroes],
                "expected_personal_points": result.expected_personal_points,
            }
        results = recommend_all_modes(
            heroes,
            catalog,
            troops,
            scenarios,
            event=event_profile,
            troop_stats=troop_stats,
            truegold=truegold,
            gear=gear,
            gear_profile=gear_profile,
        )
        best = max(results.values(), key=lambda r: r.expected_personal_points)
        return float(best.expected_personal_points), {
            "mode": best.recommended_mode,
            "heroes": [h["name"] for h in best.heroes],
            "expected_personal_points": best.expected_personal_points,
            "modes": {
                m: r.expected_personal_points for m, r in results.items()
            },
        }

    return _event


def allocate_fodder_xp(
    gear: list[GearRecord],
    bag: FodderBag,
    utility_fn: UtilityFn,
    *,
    event: str = "swordland",
    max_steps: int = 50,
    ladder: dict[str, Any] | None = None,
    fodder_values: dict[str, int] | None = None,
) -> SpendResult:
    """Greedy: repeatedly take the next +1 level with best positive ΔU."""
    if not gear:
        raise ValueError("gear inventory is empty")
    xp_ladder = ladder or load_xp_ladder()
    values = fodder_values or load_fodder_xp_values()
    levels = current_levels(gear)
    by_id = {p.piece_id: p for p in gear if p.piece_id}

    baseline_u, baseline_summary = utility_fn(gear)
    if baseline_u == float("-inf"):
        raise ValueError("baseline event utility is infeasible")

    steps: list[SpendStep] = []
    current_bag = bag
    current_u = baseline_u
    current_summary = baseline_summary

    for _ in range(max_steps):
        best: tuple[float, str, int, int, dict[str, int]] | None = None
        # delta, piece_id, from_lv, to_lv, fodder_spend
        for piece_id, piece in by_id.items():
            cur_lv = int(levels.get(piece_id, piece.enhancement_level or 0))
            cap = cap_for_rarity(piece.rarity, ladder=xp_ladder)
            if cur_lv >= cap:
                continue
            cost = xp_cost_next_level(xp_ladder, cur_lv)
            if cost is None or cost <= 0:
                continue
            plan = current_bag.plan_cover(cost, values=values)
            if plan is None:
                continue
            trial_levels = dict(levels)
            trial_levels[piece_id] = cur_lv + 1
            trial_gear = apply_levels(gear, trial_levels)
            trial_u, _summary = utility_fn(trial_gear)
            if trial_u == float("-inf"):
                continue
            delta = trial_u - current_u
            if best is None or delta > best[0]:
                best = (delta, piece_id, cur_lv, cur_lv + 1, plan)

        if best is None or best[0] <= 0:
            break

        delta, piece_id, from_lv, to_lv, plan = best
        cost = xp_cost_next_level(xp_ladder, from_lv) or 0
        current_bag = current_bag.consume(plan)
        levels[piece_id] = to_lv
        trial_gear = apply_levels(gear, levels)
        current_u, current_summary = utility_fn(trial_gear)
        piece = by_id[piece_id]
        steps.append(
            SpendStep(
                piece_id=piece_id,
                name=piece.name,
                from_level=from_lv,
                to_level=to_lv,
                xp_spent=int(cost),
                fodder_spent=dict(plan),
            )
        )

    return SpendResult(
        event=event,
        baseline_utility=float(baseline_u),
        best_utility=float(current_u),
        steps=tuple(steps),
        leftover=current_bag,
        baseline_summary=dict(baseline_summary),
        best_summary=dict(current_summary),
    )
