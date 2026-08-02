from __future__ import annotations

from ks.heroes.gear_models import GearRecord
from ks.heroes.models import HeroRecord
from ks.heroes.optimize.gear_assign import (
    assign_best_sets,
    assignment_to_dict,
    gear_bonus_by_troop,
)
from ks.heroes.optimize.bear_damage import BeartrapBuffs
from ks.heroes.optimize.model import solve_mode
from ks.heroes.optimize.troop_stats import TroopStatsTable
from ks.heroes.optimize.troops import breakdown_for_totals
from ks.heroes.optimize.types import (
    CatalogEntry,
    EventProfile,
    RecommendResult,
    Scenario,
    TroopsConfig,
)


def recommend(
    heroes: list[HeroRecord],
    catalog: dict[str, CatalogEntry],
    troops: TroopsConfig,
    scenarios: dict[str, Scenario],
    *,
    force_mode: str | None = None,
    event: EventProfile | None = None,
    troop_stats: TroopStatsTable | None = None,
    truegold: int = 0,
    gear: list[GearRecord] | None = None,
    gear_profile: str = "early_game_growth",
    beartrap_buffs: BeartrapBuffs | None = None,
) -> RecommendResult:
    if not scenarios:
        raise ValueError("scenarios must not be empty")
    if force_mode is not None:
        if force_mode not in scenarios:
            raise ValueError(f"unknown mode {force_mode!r}; have {sorted(scenarios)}")
        modes = {force_mode: scenarios[force_mode]}
    else:
        modes = scenarios

    gear_bonus = (
        gear_bonus_by_troop(gear, profile=gear_profile) if gear else None
    )

    solutions = []
    for mode, scenario in modes.items():
        scenario = Scenario(
            mode=mode,
            combat_rate=scenario.combat_rate,
            minutes_held=scenario.minutes_held,
            personal_rate=scenario.personal_rate,
            p_first=scenario.p_first,
            first_bonus=scenario.first_bonus,
            loot_expected=scenario.loot_expected,
            enemy_power_scale=scenario.enemy_power_scale,
            formation_weights=scenario.formation_weights,
            require_widget=scenario.require_widget,
        )
        solutions.append(
            solve_mode(
                heroes,
                catalog,
                troops,
                scenario,
                event=event,
                troop_stats=troop_stats,
                truegold=truegold,
                gear_bonus_by_troop=gear_bonus,
                beartrap_buffs=beartrap_buffs,
            )
        )

    feasible = [s for s in solutions if s.status == "Optimal"]
    if not feasible:
        raise ValueError("no feasible mode solution for this roster/troops")

    best = max(feasible, key=lambda s: s.expected_personal_points)
    total = sum(best.troops.values()) or 1
    ratios = {k: v / total for k, v in best.troops.items()}
    hero_rows = tuple(
        {
            "name": name,
            "reason": _reason(name, catalog, best.mode),
        }
        for name in best.hero_names
    )
    alternatives = tuple(
        {
            "mode": s.mode,
            "expected_personal_points": s.expected_personal_points,
            "heroes": list(s.hero_names),
            "status": s.status,
        }
        for s in sorted(
            solutions,
            key=lambda s: s.expected_personal_points,
            reverse=True,
        )
        if s.mode != best.mode
    )
    by_level = breakdown_for_totals(troops, best.troops)
    gear_assignment = None
    if gear:
        assigned = assign_best_sets(
            heroes,
            catalog,
            gear,
            selected=list(best.hero_names),
            profile=gear_profile,
        )
        gear_assignment = assignment_to_dict(assigned)
    return RecommendResult(
        recommended_mode=best.mode,
        heroes=hero_rows,
        troops=dict(best.troops),
        ratios=ratios,
        effective_capacity=best.effective_capacity,
        expected_personal_points=best.expected_personal_points,
        breakdown=dict(best.breakdown),
        alternatives=alternatives,
        troops_by_level=by_level,
        gear_assignment=gear_assignment,
    )


def _reason(name: str, catalog: dict[str, CatalogEntry], mode: str) -> str:
    entry = catalog.get(name)
    if entry is None:
        return "owned"
    bits = [f"widget={entry.widget_type or 'none'}"]
    if entry.troop:
        bits.append(f"troop={entry.troop}")
    if mode == "garrison" and entry.garrison_tier:
        bits.append(f"garrison_tier={entry.garrison_tier}")
    if mode == "rally_lead" and entry.rally_tier:
        bits.append(f"rally_tier={entry.rally_tier}")
    if mode == "joiner" and entry.joiner_tier:
        bits.append(f"joiner_tier={entry.joiner_tier}")
    return ", ".join(bits)
