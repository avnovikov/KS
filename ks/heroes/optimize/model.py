from __future__ import annotations

from dataclasses import dataclass

from ks.heroes.models import HeroRecord
from ks.heroes.optimize.scoring import hero_strength, max_power_by_troop, normalize_troop
from ks.heroes.optimize.troop_stats import TroopStatsTable, inventory_combat_weights
from ks.heroes.optimize.types import (
    CatalogEntry,
    EventProfile,
    ModeSolution,
    Scenario,
    TroopsConfig,
)

try:
    import pulp
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "pulp is required for ks.heroes.optimize; install project deps (pulp>=2.8)"
    ) from exc


@dataclass(frozen=True)
class _HeroFeatures:
    """Per-hero ILP inputs, keyed by hero name."""

    troop_of: dict[str, str]
    strengths: dict[str, float]
    escorts: dict[str, int]
    widget: dict[str, str]


@dataclass
class _TroopVariables:
    """The ILP problem plus its hero-pick and troop-count decision variables.

    Not frozen: `prob += constraint` reassigns `variables.prob` in place as
    helpers incrementally add constraints and the objective.
    """

    prob: pulp.LpProblem
    hero_selected: dict[str, pulp.LpVariable]
    infantry: pulp.LpVariable
    cavalry: pulp.LpVariable
    archers: pulp.LpVariable


@dataclass(frozen=True)
class _ObjectiveTerms:
    """Expected personal-points value, split into its named components."""

    combat: pulp.LpAffineExpression
    occupation: float
    first_control: float
    loot: float

    @property
    def expected(self) -> pulp.LpAffineExpression:
        return self.combat + self.occupation + self.first_control + self.loot


def _empty_troops() -> dict[str, int]:
    return {"infantry": 0, "cavalry": 0, "archers": 0}


def _infeasible_solution(
    scenario: Scenario, troops: TroopsConfig, status: str = "Infeasible"
) -> ModeSolution:
    return ModeSolution(
        mode=scenario.mode,
        hero_names=(),
        troops=_empty_troops(),
        effective_capacity=troops.march_capacity,
        expected_personal_points=float("-inf"),
        breakdown={},
        status=status,
    )


def _select_usable_heroes(
    heroes: list[HeroRecord], catalog: dict[str, CatalogEntry]
) -> list[HeroRecord]:
    usable = [h for h in heroes if h.name in catalog]
    dropped = sorted({h.name for h in heroes} - {h.name for h in usable})
    if dropped:
        print(
            f"warn: dropped {len(dropped)} hero(es) not in catalog: "
            f"{', '.join(dropped[:12])}{'…' if len(dropped) > 12 else ''}"
        )
    return usable


def _warn_missing_escorts(usable: list[HeroRecord]) -> None:
    missing = [h.name for h in usable if h.escorts is None]
    if missing:
        print(
            "warn: missing escorts OCR for "
            f"{', '.join(missing[:12])}"
            f"{'…' if len(missing) > 12 else ''}; treating as 0"
        )


def _compute_hero_features(
    usable: list[HeroRecord],
    catalog: dict[str, CatalogEntry],
    scenario: Scenario,
    event: EventProfile | None,
    gear_bonus_by_troop: dict[str, float] | None,
) -> _HeroFeatures:
    troop_of = {h.name: (normalize_troop(catalog[h.name].troop) or "") for h in usable}
    # Gear is fungible within troop class: score power using best geared hero
    # of that class (widgets / skills / stars stay on the selected hero).
    class_power = max_power_by_troop(usable, catalog)
    gear_bonus = gear_bonus_by_troop or {}
    strengths = {
        h.name: hero_strength(
            h,
            catalog[h.name],
            scenario.mode,
            event=event,
            effective_power=class_power.get(troop_of[h.name], h.power),
            gear_bonus=float(gear_bonus.get(troop_of[h.name], 0.0)),
        )
        for h in usable
    }
    _warn_missing_escorts(usable)
    escorts = {h.name: int(h.escorts or 0) for h in usable}
    widget = {h.name: (catalog[h.name].widget_type or "none") for h in usable}
    return _HeroFeatures(troop_of=troop_of, strengths=strengths, escorts=escorts, widget=widget)


def _build_ilp_variables(
    usable: list[HeroRecord],
    troops: TroopsConfig,
    escorts: dict[str, int],
    mode: str,
) -> _TroopVariables:
    prob = pulp.LpProblem(f"heroes_{mode}", pulp.LpMaximize)
    x = pulp.LpVariable.dicts("hero", [h.name for h in usable], cat="Binary")
    t_i = pulp.LpVariable("t_infantry", lowBound=0, upBound=troops.infantry, cat="Integer")
    t_c = pulp.LpVariable("t_cavalry", lowBound=0, upBound=troops.cavalry, cat="Integer")
    t_a = pulp.LpVariable("t_archers", lowBound=0, upBound=troops.archers, cat="Integer")

    prob += pulp.lpSum(x[h.name] for h in usable) == 3

    # Capacity: march_capacity + escorts of selected heroes
    cap = troops.march_capacity + pulp.lpSum(x[n] * escorts[n] for n in x)
    prob += t_i + t_c + t_a <= cap

    return _TroopVariables(prob=prob, hero_selected=x, infantry=t_i, cavalry=t_c, archers=t_a)


def _apply_widget_requirement(
    variables: _TroopVariables,
    widget: dict[str, str],
    required_widget: str | None,
) -> bool:
    """Require at least one selected hero to carry `required_widget`.

    Returns False when no usable hero can ever satisfy the requirement, which
    signals the caller to short-circuit with an infeasible solution instead
    of handing pulp an unsatisfiable constraint.
    """
    if not required_widget:
        return True
    matching = [n for n, w in widget.items() if w == required_widget]
    if not matching:
        return False
    variables.prob += pulp.lpSum(variables.hero_selected[n] for n in matching) >= 1
    return True


def _apply_one_hero_per_troop_type(variables: _TroopVariables, troop_of: dict[str, str]) -> None:
    by_type: dict[str, list[str]] = {"infantry": [], "cavalry": [], "archers": []}
    for name, troop in troop_of.items():
        if troop == "infantry":
            by_type["infantry"].append(name)
        elif troop == "cavalry":
            by_type["cavalry"].append(name)
        elif troop in ("archer", "archers"):
            by_type["archers"].append(name)
    for names in by_type.values():
        if names:
            variables.prob += pulp.lpSum(variables.hero_selected[n] for n in names) <= 1


def _troop_combat_weights(
    scenario: Scenario,
    troops: TroopsConfig,
    troop_stats: TroopStatsTable | None,
    truegold: int,
) -> tuple[float, float, float]:
    weights = scenario.formation_weights or {"infantry": 1.0, "cavalry": 1.0, "archers": 1.0}
    if troop_stats is None:
        return (
            float(weights.get("infantry", 1.0)),
            float(weights.get("cavalry", 1.0)),
            float(weights.get("archers", 1.0)),
        )
    combat_w = inventory_combat_weights(
        {
            "infantry": troops.levels("infantry"),
            "cavalry": troops.levels("cavalry"),
            "archers": troops.levels("archers"),
        },
        troop_stats,
        truegold=truegold,
        mode=scenario.mode,
    )
    return (
        float(weights.get("infantry", 1.0)) * float(combat_w["infantry"]),
        float(weights.get("cavalry", 1.0)) * float(combat_w["cavalry"]),
        float(weights.get("archers", 1.0)) * float(combat_w["archers"]),
    )


def _build_objective(
    variables: _TroopVariables,
    strengths: dict[str, float],
    troop_weights: tuple[float, float, float],
    scenario: Scenario,
) -> _ObjectiveTerms:
    """Add the expected-personal-points objective to `variables.prob` and return its terms.

    occupation/first_control/loot are constants per scenario; only combat
    scales with hero+troop strength. Kept as a single linear expression
    (no mode-specific branching) so the ILP stays a straight LP relaxation.
    """
    w_i, w_c, w_a = troop_weights
    x = variables.hero_selected
    hero_str = pulp.lpSum(x[n] * strengths[n] for n in x)
    troop_str = w_i * variables.infantry + w_c * variables.cavalry + w_a * variables.archers
    # Scale troop contribution so heroes still matter but formation fills capacity.
    strength = hero_str + 0.001 * troop_str

    combat = (scenario.combat_rate / 10_000.0) * scenario.enemy_power_scale * (0.01 * strength)
    terms = _ObjectiveTerms(
        combat=combat,
        occupation=scenario.minutes_held * scenario.personal_rate,
        first_control=scenario.p_first * scenario.first_bonus,
        loot=scenario.loot_expected,
    )
    variables.prob += terms.expected
    return terms


def _extract_optimal_solution(
    variables: _TroopVariables,
    features: _HeroFeatures,
    troops: TroopsConfig,
    terms: _ObjectiveTerms,
    scenario: Scenario,
) -> ModeSolution:
    x = variables.hero_selected
    chosen = tuple(sorted(n for n in x if pulp.value(x[n]) and pulp.value(x[n]) > 0.5))
    ti = int(round(pulp.value(variables.infantry) or 0))
    tc = int(round(pulp.value(variables.cavalry) or 0))
    ta = int(round(pulp.value(variables.archers) or 0))
    eff_cap = troops.march_capacity + sum(features.escorts[n] for n in chosen)
    breakdown = {
        "combat": float(pulp.value(terms.combat) or 0.0),
        "occupation": float(terms.occupation),
        "first_control": float(terms.first_control),
        "loot": float(terms.loot),
    }
    return ModeSolution(
        mode=scenario.mode,
        hero_names=chosen,
        troops={"infantry": ti, "cavalry": tc, "archers": ta},
        effective_capacity=eff_cap,
        expected_personal_points=float(pulp.value(variables.prob.objective) or 0.0),
        breakdown=breakdown,
        status="Optimal",
    )


def solve_mode(
    heroes: list[HeroRecord],
    catalog: dict[str, CatalogEntry],
    troops: TroopsConfig,
    scenario: Scenario,
    *,
    event: EventProfile | None = None,
    troop_stats: TroopStatsTable | None = None,
    truegold: int = 0,
    one_per_troop_type: bool = True,
    gear_bonus_by_troop: dict[str, float] | None = None,
) -> ModeSolution:
    usable = _select_usable_heroes(heroes, catalog)
    if len(usable) < 3:
        return _infeasible_solution(scenario, troops)

    features = _compute_hero_features(usable, catalog, scenario, event, gear_bonus_by_troop)
    variables = _build_ilp_variables(usable, troops, features.escorts, scenario.mode)

    if not _apply_widget_requirement(variables, features.widget, scenario.require_widget):
        return _infeasible_solution(scenario, troops)

    if one_per_troop_type:
        _apply_one_hero_per_troop_type(variables, features.troop_of)

    troop_weights = _troop_combat_weights(scenario, troops, troop_stats, truegold)
    terms = _build_objective(variables, features.strengths, troop_weights, scenario)

    status = variables.prob.solve(pulp.PULP_CBC_CMD(msg=False))
    status_name = pulp.LpStatus.get(status, str(status))
    if status_name != "Optimal":
        return _infeasible_solution(scenario, troops, status=status_name)

    return _extract_optimal_solution(variables, features, troops, terms, scenario)
