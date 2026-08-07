from __future__ import annotations

from dataclasses import dataclass

from ks.heroes.gear_models import GearRecord
from ks.heroes.models import HeroRecord
from ks.heroes.optimize.bear_damage import (
    BeartrapBuffs,
    greedy_fill_march,
)
from ks.heroes.optimize.scoring import hero_strength, max_power_by_troop, normalize_troop
from ks.heroes.optimize.stat_contributions import (
    EXPEDITION,
    StatContribution,
    expedition_labels,
    hero_contribution,
)
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
    # This hero's own troop-percentage bonus (Attack+Lethality, or
    # Health+Defense in garrison), from skills/gear — see
    # _hero_troop_bonus_pct. Scales that troop's combat weight in the
    # objective when this hero is the one selected for its troop slot.
    troop_bonus_pct: dict[str, float]


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


def _use_bear_damage(event: EventProfile | None, mode: str) -> bool:
    return bool(event and event.name == "beartrap" and mode == "rally_lead")


def _inventory_levels(troops: TroopsConfig) -> dict[str, dict[int, int]]:
    """Per-type tier maps; flat inventories (no levels) default to T6 pool."""
    out: dict[str, dict[int, int]] = {}
    for typ in ("infantry", "cavalry", "archers"):
        levels = troops.levels(typ)
        if levels:
            out[typ] = dict(levels)
        else:
            owned = troops.owned(typ)
            out[typ] = {6: owned} if owned > 0 else {}
    return out


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


def _troop_bonus_stat_names(mode: str) -> tuple[str, str]:
    """Which two expedition percent stats scale a troop's combat weight.

    TroopUnitStats defines offense = attack*lethality, toughness =
    health*defense (troop_stats.py); the additive approximation used here
    (Attack% + Lethality%, or Health% + Defense%) matches how
    contribution_strength already folds percent stats additively elsewhere,
    rather than introducing a different, multiplicative treatment only here.
    """
    if mode == "garrison":
        return ("Health", "Defense")
    return ("Attack", "Lethality")


def _hero_troop_bonus_pct(
    contribution: StatContribution, troop: str, mode: str
) -> float:
    """This hero's own Attack+Lethality (or Health+Defense) percent total.

    A hero's expedition contribution only ever carries its own troop's four
    labels (e.g. "Cavalry Attack"), so this sums whichever two of those match
    the stats relevant to ``mode``.
    """
    stat_names = _troop_bonus_stat_names(mode)
    total = 0.0
    for label in expedition_labels(troop):
        if any(label.endswith(" " + stat) for stat in stat_names):
            share = contribution.stats.get(label)
            if share is not None:
                total += share.total
    return total


def _compute_hero_features(
    usable: list[HeroRecord],
    catalog: dict[str, CatalogEntry],
    scenario: Scenario,
    event: EventProfile | None,
    gear_by_troop: dict[str, dict[str, GearRecord]] | None,
) -> _HeroFeatures:
    troop_of = {
        h.name: (normalize_troop(catalog[h.name].troop) or "") for h in usable
    }
    # Gear is fungible within a troop class: score power using the best geared
    # hero of that class (widgets / skills / stars stay on the selected hero).
    class_power = max_power_by_troop(usable, catalog)
    gear = gear_by_troop or {}
    strengths: dict[str, float] = {}
    troop_bonus_pct: dict[str, float] = {}
    for h in usable:
        troop = troop_of[h.name]
        contribution = hero_contribution(
            h,
            catalog[h.name],
            family=EXPEDITION,
            gear_pieces=gear.get(troop),
            power=class_power.get(troop, h.power),
            catalog=catalog,
        )
        strengths[h.name] = hero_strength(
            h, catalog[h.name], scenario.mode, event=event, contribution=contribution
        )
        troop_bonus_pct[h.name] = _hero_troop_bonus_pct(contribution, troop, scenario.mode)
    _warn_missing_escorts(usable)
    escorts = {h.name: int(h.escorts or 0) for h in usable}
    widget = {h.name: (catalog[h.name].widget_type or "none") for h in usable}
    return _HeroFeatures(
        troop_of=troop_of,
        strengths=strengths,
        escorts=escorts,
        widget=widget,
        troop_bonus_pct=troop_bonus_pct,
    )


def _build_ilp_variables(
    usable: list[HeroRecord],
    troops: TroopsConfig,
    escorts: dict[str, int],
    mode: str,
    *,
    bear_mode: bool = False,
) -> _TroopVariables:
    prob = pulp.LpProblem(f"heroes_{mode}", pulp.LpMaximize)
    x = pulp.LpVariable.dicts("hero", [h.name for h in usable], cat="Binary")
    t_i = pulp.LpVariable("t_infantry", lowBound=0, upBound=troops.infantry, cat="Integer")
    t_c = pulp.LpVariable("t_cavalry", lowBound=0, upBound=troops.cavalry, cat="Integer")
    t_a = pulp.LpVariable("t_archers", lowBound=0, upBound=troops.archers, cat="Integer")

    prob += pulp.lpSum(x[h.name] for h in usable) == 3

    # Capacity: march_capacity + escorts of selected heroes
    cap = troops.march_capacity + pulp.lpSum(x[n] * escorts[n] for n in x)
    if bear_mode:
        # Troop formation is filled post-solve via damage greedy; keep vars at 0.
        prob += t_i + t_c + t_a == 0
    else:
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


def _troop_bonus_term(
    variables: _TroopVariables,
    troop_of: dict[str, str],
    troop_bonus_pct: dict[str, float],
    troops: TroopsConfig,
    troop_weights: tuple[float, float, float],
) -> pulp.LpAffineExpression | float:
    """Linearize each selected hero's own troop-percentage bonus × that
    troop's deployed count via McCormick envelopes, so a hero's Attack/
    Lethality (or Health/Defense) gear+skill percent scales their own troop
    type's combat weight during hero SELECTION itself — not as a flat,
    troop-count-blind nudge folded into that hero's pick score, and not as a
    post-hoc correction applied after the formation is already chosen.

    Exact only when at most one hero per troop type can be selected (this
    module's ``one_per_troop_type`` default, applied by every caller today):
    the auxiliary variable for a troop type equals that troop's deployed
    count only while its one bonus-carrying hero is selected, and 0
    otherwise — this is what the four McCormick inequalities below encode
    for a binary × bounded-continuous product. With that precondition
    violated, multiple same-troop heroes' bonuses would each independently
    read against the *full* troop count and overstate the total bonus, so
    this term is skipped entirely rather than risk that.
    """
    w_i, w_c, w_a = troop_weights
    x = variables.hero_selected
    troop_var = {
        "infantry": variables.infantry,
        "cavalry": variables.cavalry,
        "archers": variables.archers,
    }
    troop_weight = {"infantry": w_i, "cavalry": w_c, "archers": w_a}
    troop_bound = {
        "infantry": troops.infantry,
        "cavalry": troops.cavalry,
        "archers": troops.archers,
    }

    eligible = [
        name
        for name, troop in troop_of.items()
        if troop in troop_var
        and troop_bonus_pct.get(name, 0.0) > 0.0
        and troop_bound[troop] > 0
    ]
    if not eligible:
        return 0.0

    y = pulp.LpVariable.dicts("troop_bonus", eligible, lowBound=0)
    terms = []
    for name in eligible:
        troop = troop_of[name]
        bound = troop_bound[troop]
        t_var = troop_var[troop]
        # y[name] == t_var when x[name]==1 (this hero selected), 0 otherwise.
        variables.prob += y[name] <= t_var
        variables.prob += y[name] <= bound * x[name]
        variables.prob += y[name] >= t_var - bound * (1 - x[name])
        terms.append((troop_weight[troop] * troop_bonus_pct[name] / 100.0) * y[name])
    return pulp.lpSum(terms)


def _build_objective(
    variables: _TroopVariables,
    features: _HeroFeatures,
    troops: TroopsConfig,
    troop_weights: tuple[float, float, float],
    scenario: Scenario,
    *,
    one_per_troop_type: bool = True,
) -> _ObjectiveTerms:
    """Add the expected-personal-points objective to `variables.prob` and return its terms.

    occupation/first_control/loot are constants per scenario; only combat
    scales with hero+troop strength. Kept as a single linear expression
    (no mode-specific branching) so the ILP stays a straight LP relaxation.
    """
    w_i, w_c, w_a = troop_weights
    x = variables.hero_selected
    hero_str = pulp.lpSum(x[n] * features.strengths[n] for n in x)
    troop_str = w_i * variables.infantry + w_c * variables.cavalry + w_a * variables.archers
    if one_per_troop_type:
        troop_str = troop_str + _troop_bonus_term(
            variables, features.troop_of, features.troop_bonus_pct, troops, troop_weights
        )
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


def _build_bear_hero_objective(
    variables: _TroopVariables,
    strengths: dict[str, float],
) -> None:
    """Maximize lineup hero strength; damage score is applied after greedy fill."""
    x = variables.hero_selected
    variables.prob += pulp.lpSum(x[n] * strengths[n] for n in x)


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


def _extract_bear_damage_solution(
    variables: _TroopVariables,
    features: _HeroFeatures,
    troops: TroopsConfig,
    scenario: Scenario,
    *,
    troop_stats: TroopStatsTable,
    truegold: int,
    beartrap_buffs: BeartrapBuffs | None,
    heroes: list[HeroRecord],
    catalog: dict[str, CatalogEntry],
) -> ModeSolution:
    from ks.heroes.optimize.bear_damage import host_skillmod_buckets

    x = variables.hero_selected
    chosen = tuple(sorted(n for n in x if pulp.value(x[n]) and pulp.value(x[n]) > 0.5))
    eff_cap = troops.march_capacity + sum(features.escorts[n] for n in chosen)
    buffs = beartrap_buffs or BeartrapBuffs()
    lineup_strength = sum(features.strengths[n] for n in chosen)
    by_name = {h.name: h for h in heroes}
    host_pairs = [
        (by_name[n], catalog[n])
        for n in chosen
        if n in by_name and n in catalog
    ]
    host_buckets = host_skillmod_buckets(host_pairs)
    skillmod = buffs.effective_skillmod(
        lineup_strength,
        host_damage_up=host_buckets["damage_up"],
        host_defense_up=host_buckets["defense_up"],
        host_opp_damage_down=host_buckets["opp_damage_down"],
        host_opp_defense_down=host_buckets["opp_defense_down"],
    )
    fill_cap = min(eff_cap, troops.infantry + troops.cavalry + troops.archers)
    counts, _filled_levels, dmg = greedy_fill_march(
        _inventory_levels(troops),
        capacity=fill_cap,
        table=troop_stats,
        truegold=truegold,
        skillmod=skillmod,
        trap_attack_bonus=buffs.trap_attack_bonus,
        host_attack_pct=buffs.host_attack_pct,
    )
    breakdown = dmg.breakdown()
    breakdown["hero_strength"] = float(lineup_strength)
    breakdown["research_skillmod"] = float(buffs.research_skillmod)
    breakdown["host_damage_up"] = {
        str(k): float(v) for k, v in host_buckets["damage_up"].items()
    }
    breakdown["joiner_damage_up"] = {
        str(k): float(v) for k, v in buffs.joiner_damage_up_buckets().items()
    }
    return ModeSolution(
        mode=scenario.mode,
        hero_names=chosen,
        troops=dict(counts),
        effective_capacity=eff_cap,
        expected_personal_points=float(dmg.score),
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
    gear_by_troop: dict[str, dict[str, GearRecord]] | None = None,
    beartrap_buffs: BeartrapBuffs | None = None,
) -> ModeSolution:
    usable = _select_usable_heroes(heroes, catalog)
    if len(usable) < 3:
        return _infeasible_solution(scenario, troops)

    bear_mode = _use_bear_damage(event, scenario.mode) and troop_stats is not None
    features = _compute_hero_features(usable, catalog, scenario, event, gear_by_troop)
    variables = _build_ilp_variables(
        usable,
        troops,
        features.escorts,
        scenario.mode,
        bear_mode=bear_mode,
    )

    if not _apply_widget_requirement(variables, features.widget, scenario.require_widget):
        return _infeasible_solution(scenario, troops)

    if one_per_troop_type:
        _apply_one_hero_per_troop_type(variables, features.troop_of)

    if bear_mode:
        _build_bear_hero_objective(variables, features.strengths)
    else:
        troop_weights = _troop_combat_weights(scenario, troops, troop_stats, truegold)
        terms = _build_objective(
            variables,
            features,
            troops,
            troop_weights,
            scenario,
            one_per_troop_type=one_per_troop_type,
        )

    status = variables.prob.solve(pulp.PULP_CBC_CMD(msg=False))
    status_name = pulp.LpStatus.get(status, str(status))
    if status_name != "Optimal":
        return _infeasible_solution(scenario, troops, status=status_name)

    if bear_mode:
        assert troop_stats is not None
        return _extract_bear_damage_solution(
            variables,
            features,
            troops,
            scenario,
            troop_stats=troop_stats,
            truegold=truegold,
            beartrap_buffs=beartrap_buffs,
            heroes=usable,
            catalog=catalog,
        )

    return _extract_optimal_solution(variables, features, troops, terms, scenario)
