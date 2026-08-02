"""Allocate Hero EXP across hero levels to maximize event optimizer utility."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable

from ks.heroes.gear_models import GearRecord
from ks.heroes.models import HeroRecord
from ks.heroes.optimize.hero_level_ladder import (
    load_hero_level_ladder,
    xp_cost_next_hero_level,
)
from ks.heroes.ui.hero_power import scale_power_for_level_change

REPO_ROOT = Path(__file__).resolve().parents[3]

HeroUtilityFn = Callable[[list[HeroRecord]], tuple[float, dict[str, Any]]]


@dataclass(frozen=True)
class HeroSpendStep:
    name: str
    from_level: int
    to_level: int
    xp_spent: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "from_level": self.from_level,
            "to_level": self.to_level,
            "xp_spent": self.xp_spent,
        }


@dataclass(frozen=True)
class HeroSpendResult:
    event: str
    baseline_utility: float
    best_utility: float
    steps: tuple[HeroSpendStep, ...]
    leftover_exp: int
    baseline_summary: dict[str, Any]
    best_summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "baseline_utility": self.baseline_utility,
            "best_utility": self.best_utility,
            "delta_utility": self.best_utility - self.baseline_utility,
            "steps": [s.to_dict() for s in self.steps],
            "leftover_exp": int(self.leftover_exp),
            "baseline_summary": dict(self.baseline_summary),
            "best_summary": dict(self.best_summary),
        }


def eligible_hero(hero: HeroRecord) -> bool:
    """Spend candidate requires name, level, and power."""
    return bool(hero.name) and hero.level is not None and hero.power is not None


def apply_hero_levels(
    heroes: list[HeroRecord],
    levels: dict[str, int],
    *,
    ladder: dict[str, Any] | None = None,
) -> list[HeroRecord]:
    """Return heroes with level bumps and power rescaled from each hero's baseline."""
    table = ladder or load_hero_level_ladder()
    out: list[HeroRecord] = []
    for hero in heroes:
        if hero.name not in levels:
            out.append(hero)
            continue
        new_lv = int(levels[hero.name])
        old_lv = int(hero.level) if hero.level is not None else new_lv
        new_power = scale_power_for_level_change(
            hero.power, old_lv, new_lv, ladder=table
        )
        out.append(replace(hero, level=new_lv, power=new_power))
    return out


def build_hero_event_utility(
    event: str,
    gear: list[GearRecord] | None,
    *,
    config_root: Path | None = None,
    troops_path: Path | None = None,
    mode: str | None = None,
) -> HeroUtilityFn:
    """Return U(heroes) -> (utility, summary) with gear fixed."""
    root = (config_root or REPO_ROOT).expanduser().resolve()
    key = event.strip().lower().replace(" ", "_")
    gear_list = list(gear or [])

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

        def _arena(heroes: list[HeroRecord]) -> tuple[float, dict[str, Any]]:
            result = optimize_arena(
                side,
                heroes,
                catalog,
                roles,
                gear=gear_list or None,
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

    def _event(heroes: list[HeroRecord]) -> tuple[float, dict[str, Any]]:
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
                gear=gear_list or None,
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
            gear=gear_list or None,
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


def allocate_hero_exp(
    heroes: list[HeroRecord],
    hero_exp: int,
    utility_fn: HeroUtilityFn,
    *,
    event: str = "swordland",
    max_steps: int = 50,
    ladder: dict[str, Any] | None = None,
) -> HeroSpendResult:
    """Greedy: repeatedly take the next +1 level with best positive ΔU."""
    if hero_exp < 0:
        raise ValueError(f"hero_exp must be >= 0; got {hero_exp}")
    if not heroes:
        raise ValueError("hero roster is empty")

    table = ladder or load_hero_level_ladder()
    max_level = int(table["max_level"])
    levels: dict[str, int] = {
        h.name: int(h.level)
        for h in heroes
        if eligible_hero(h)
    }
    by_name = {h.name: h for h in heroes if eligible_hero(h)}
    if not by_name:
        raise ValueError("no eligible heroes (need level and power)")

    baseline_u, baseline_summary = utility_fn(heroes)
    if baseline_u == float("-inf"):
        raise ValueError("baseline event utility is infeasible")

    steps: list[HeroSpendStep] = []
    remaining = int(hero_exp)
    current_u = baseline_u
    current_summary = baseline_summary

    for _ in range(max_steps):
        best: tuple[float, str, int, int, int] | None = None
        # delta, name, from_lv, to_lv, cost
        for name, hero in by_name.items():
            cur_lv = int(levels[name])
            if cur_lv >= max_level:
                continue
            cost = xp_cost_next_hero_level(table, cur_lv)
            if cost is None or cost <= 0:
                continue
            if cost > remaining:
                continue
            trial_levels = dict(levels)
            trial_levels[name] = cur_lv + 1
            trial_heroes = apply_hero_levels(heroes, trial_levels, ladder=table)
            trial_u, _summary = utility_fn(trial_heroes)
            if trial_u == float("-inf"):
                continue
            delta = trial_u - current_u
            if best is None or delta > best[0]:
                best = (delta, name, cur_lv, cur_lv + 1, int(cost))

        if best is None or best[0] <= 0:
            break

        _delta, name, from_lv, to_lv, cost = best
        remaining -= cost
        levels[name] = to_lv
        trial_heroes = apply_hero_levels(heroes, levels, ladder=table)
        current_u, current_summary = utility_fn(trial_heroes)
        steps.append(
            HeroSpendStep(
                name=name,
                from_level=from_lv,
                to_level=to_lv,
                xp_spent=cost,
            )
        )

    return HeroSpendResult(
        event=event,
        baseline_utility=float(baseline_u),
        best_utility=float(current_u),
        steps=tuple(steps),
        leftover_exp=remaining,
        baseline_summary=dict(baseline_summary),
        best_summary=dict(current_summary),
    )
