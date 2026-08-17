from __future__ import annotations

from dataclasses import replace
from typing import Any

from ks.heroes.gear_models import GearRecord
from ks.heroes.governor_models import GovernorTroopBonuses
from ks.heroes.models import HeroRecord
from ks.heroes.optimize.gear_assign import (
    assign_best_sets,
    assignment_to_dict,
    best_sets_by_troop,
)
from ks.heroes.optimize.bear_damage import BeartrapBuffs
from ks.heroes.optimize.model import solve_mode
from ks.heroes.optimize.stat_contributions import (
    StatContribution,
    family_for_event,
    formation_contribution,
    hero_contribution,
)
from ks.heroes.optimize.troop_stats import TroopStatsTable
from ks.heroes.optimize.troops import breakdown_for_totals
from ks.heroes.optimize.types import (
    CatalogEntry,
    EventProfile,
    ModeSolution,
    RecommendResult,
    Scenario,
    TroopsConfig,
)


def _select_modes(
    scenarios: dict[str, Scenario], force_mode: str | None
) -> dict[str, Scenario]:
    """All scenario modes, or just ``force_mode`` if pinned to a single one."""
    if force_mode is None:
        return scenarios
    if force_mode not in scenarios:
        raise ValueError(f"unknown mode {force_mode!r}; have {sorted(scenarios)}")
    return {force_mode: scenarios[force_mode]}


def _retag_scenario(scenario: Scenario, mode: str) -> Scenario:
    """Copy ``scenario`` with its ``mode`` field set to ``mode``."""
    return replace(scenario, mode=mode)


def _solve_all_modes(
    heroes: list[HeroRecord],
    catalog: dict[str, CatalogEntry],
    troops: TroopsConfig,
    modes: dict[str, Scenario],
    *,
    event: EventProfile | None,
    troop_stats: TroopStatsTable | None,
    truegold: int,
    gear_by_troop: dict[str, dict[str, GearRecord]] | None,
    beartrap_buffs: BeartrapBuffs | None = None,
    governor: GovernorTroopBonuses | None = None,
) -> list[ModeSolution]:
    return [
        solve_mode(
            heroes,
            catalog,
            troops,
            _retag_scenario(scenario, mode),
            event=event,
            troop_stats=troop_stats,
            truegold=truegold,
            gear_by_troop=gear_by_troop,
            beartrap_buffs=beartrap_buffs,
            governor=governor,
        )
        for mode, scenario in modes.items()
    ]


def _pick_best_feasible(solutions: list[ModeSolution]) -> ModeSolution:
    feasible = [s for s in solutions if s.status == "Optimal"]
    if not feasible:
        raise ValueError("no feasible mode solution for this roster/troops")
    return max(feasible, key=lambda s: s.expected_personal_points)


def _explain_hero_rows(
    heroes: list[HeroRecord],
    catalog: dict[str, CatalogEntry],
    troops: TroopsConfig,
    best_scenario: Scenario,
    best: ModeSolution,
    *,
    event: EventProfile | None,
    troop_stats: TroopStatsTable | None,
    truegold: int,
    gear_by_troop: dict[str, dict[str, GearRecord]] | None,
) -> tuple[dict[str, Any], ...]:
    """Best-effort why-cards for the chosen lineup; degrade gracefully on failure."""
    from ks.heroes.optimize.explain import explain_selected_heroes

    try:
        return explain_selected_heroes(
            heroes,
            catalog,
            troops,
            best_scenario,
            best,
            event=event,
            troop_stats=troop_stats,
            truegold=truegold,
            gear_by_troop=gear_by_troop,
        )
    except Exception:  # noqa: BLE001 — keep Optimal lineup if LOO/explain fails
        return tuple(
            {"name": name, "reason": "owned", "explain": None}
            for name in best.hero_names
        )


def _build_alternatives(
    solutions: list[ModeSolution], best: ModeSolution
) -> tuple[dict[str, Any], ...]:
    return tuple(
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


def _build_gear_assignment(
    heroes: list[HeroRecord],
    catalog: dict[str, CatalogEntry],
    gear: list[GearRecord] | None,
    best: ModeSolution,
    gear_profile: str,
) -> tuple[
    dict[str, list[dict[str, Any]]] | None,
    dict[str, dict[str, GearRecord]],
]:
    """Return (serialisable assignment, raw slot→piece map per hero)."""
    if not gear:
        return None, {}
    assigned = assign_best_sets(
        heroes,
        catalog,
        gear,
        selected=list(best.hero_names),
        profile=gear_profile,
    )
    return assignment_to_dict(assigned), assigned


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
    governor: GovernorTroopBonuses | None = None,
) -> RecommendResult:
    if not scenarios:
        raise ValueError("scenarios must not be empty")
    modes = _select_modes(scenarios, force_mode)
    gear_by_troop = best_sets_by_troop(gear, profile=gear_profile) if gear else None

    solutions = _solve_all_modes(
        heroes,
        catalog,
        troops,
        modes,
        event=event,
        troop_stats=troop_stats,
        truegold=truegold,
        gear_by_troop=gear_by_troop,
        beartrap_buffs=beartrap_buffs,
        governor=governor,
    )
    best = _pick_best_feasible(solutions)
    total = sum(best.troops.values()) or 1
    ratios = {k: v / total for k, v in best.troops.items()}
    best_scenario = _retag_scenario(modes[best.mode], best.mode)

    hero_rows = _explain_hero_rows(
        heroes,
        catalog,
        troops,
        best_scenario,
        best,
        event=event,
        troop_stats=troop_stats,
        truegold=truegold,
        gear_by_troop=gear_by_troop,
    )
    alternatives = _build_alternatives(solutions, best)
    by_level = breakdown_for_totals(troops, best.troops)
    gear_assignment, assigned = _build_gear_assignment(
        heroes, catalog, gear, best, gear_profile
    )
    stat_family = family_for_event(event.name if event else "swordland")
    hero_by_name = {h.name: h for h in heroes}
    contributions: dict[str, StatContribution] = {}
    for name in best.hero_names:
        hero = hero_by_name.get(name)
        if hero is None:
            continue
        contributions[name] = hero_contribution(
            hero,
            catalog.get(name),
            family=stat_family,
            gear_pieces=assigned.get(name),
            catalog=catalog,
        )
    hero_rows = tuple(
        {
            **row,
            "contributions": (
                contributions[row["name"]].to_dict()
                if row.get("name") in contributions
                else None
            ),
        }
        for row in hero_rows
    )
    formation_totals = (
        formation_contribution(
            list(contributions.values()),
            troop_shares=ratios,
        ).to_dict()
        if contributions
        else None
    )
    skillmod_detail = None
    event_name = (event.name if event else "") or ""
    if event_name == "beartrap" or best.mode in {"joiner", "rally_lead"}:
        from ks.heroes.optimize.skillmod import lineup_skillmod_detail

        skillmod_detail = lineup_skillmod_detail(
            best.hero_names,
            catalog,
            joiner_only=(best.mode == "joiner"),
            heroes_by_name=hero_by_name,
        )
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
        stat_family=stat_family,
        formation_totals=formation_totals,
        skillmod_detail=skillmod_detail,
    )


def recommend_all_modes(
    heroes: list[HeroRecord],
    catalog: dict[str, CatalogEntry],
    troops: TroopsConfig,
    scenarios: dict[str, Scenario],
    *,
    event: EventProfile | None = None,
    troop_stats: TroopStatsTable | None = None,
    truegold: int = 0,
    gear: list[GearRecord] | None = None,
    gear_profile: str = "early_game_growth",
    governor: GovernorTroopBonuses | None = None,
) -> dict[str, RecommendResult]:
    """Run recommend once per scenario mode (full per-mode points/formation).

    Soft-fails per mode: an infeasible mode is omitted so other modes still
    return. Raises only if every mode fails.
    """
    if not scenarios:
        raise ValueError("scenarios must not be empty")
    out: dict[str, RecommendResult] = {}
    errors: dict[str, str] = {}
    for mode in scenarios:
        try:
            out[mode] = recommend(
                heroes,
                catalog,
                troops,
                scenarios,
                force_mode=mode,
                event=event,
                troop_stats=troop_stats,
                truegold=truegold,
                gear=gear,
                gear_profile=gear_profile,
                governor=governor,
            )
        except ValueError as exc:
            errors[mode] = str(exc)
    if not out:
        detail = "; ".join(f"{m}: {err}" for m, err in errors.items())
        raise ValueError(
            f"no feasible mode solution for this roster/troops ({detail})"
        )
    return out

