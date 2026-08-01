from __future__ import annotations

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
    usable = [h for h in heroes if h.name in catalog]
    if len(usable) < 3:
        return ModeSolution(
            mode=scenario.mode,
            hero_names=(),
            troops={"infantry": 0, "cavalry": 0, "archers": 0},
            effective_capacity=troops.march_capacity,
            expected_personal_points=float("-inf"),
            breakdown={},
            status="Infeasible",
        )

    troop_of = {
        h.name: (normalize_troop(catalog[h.name].troop) or "") for h in usable
    }
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
    escorts = {h.name: int(h.escorts or 0) for h in usable}
    widget = {
        h.name: (catalog[h.name].widget_type or "none") for h in usable
    }

    prob = pulp.LpProblem(f"heroes_{scenario.mode}", pulp.LpMaximize)
    x = pulp.LpVariable.dicts("hero", [h.name for h in usable], cat="Binary")
    t_i = pulp.LpVariable("t_infantry", lowBound=0, upBound=troops.infantry, cat="Integer")
    t_c = pulp.LpVariable("t_cavalry", lowBound=0, upBound=troops.cavalry, cat="Integer")
    t_a = pulp.LpVariable("t_archers", lowBound=0, upBound=troops.archers, cat="Integer")

    prob += pulp.lpSum(x[h.name] for h in usable) == 3

    # Capacity: march_capacity + escorts of selected heroes
    cap = troops.march_capacity + pulp.lpSum(x[n] * escorts[n] for n in x)
    prob += t_i + t_c + t_a <= cap

    if scenario.require_widget:
        matching = [n for n, w in widget.items() if w == scenario.require_widget]
        if not matching:
            return ModeSolution(
                mode=scenario.mode,
                hero_names=(),
                troops={"infantry": 0, "cavalry": 0, "archers": 0},
                effective_capacity=troops.march_capacity,
                expected_personal_points=float("-inf"),
                breakdown={},
                status="Infeasible",
            )
        prob += pulp.lpSum(x[n] for n in matching) >= 1

    if one_per_troop_type:
        by_type: dict[str, list[str]] = {"infantry": [], "cavalry": [], "archers": []}
        for n, t in troop_of.items():
            if t == "infantry":
                by_type["infantry"].append(n)
            elif t == "cavalry":
                by_type["cavalry"].append(n)
            elif t in ("archer", "archers"):
                by_type["archers"].append(n)
        for names in by_type.values():
            if names:
                prob += pulp.lpSum(x[n] for n in names) <= 1

    weights = scenario.formation_weights or {
        "infantry": 1.0,
        "cavalry": 1.0,
        "archers": 1.0,
    }
    if troop_stats is not None:
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
        w_i = float(weights.get("infantry", 1.0)) * float(combat_w["infantry"])
        w_c = float(weights.get("cavalry", 1.0)) * float(combat_w["cavalry"])
        w_a = float(weights.get("archers", 1.0)) * float(combat_w["archers"])
    else:
        w_i = float(weights.get("infantry", 1.0))
        w_c = float(weights.get("cavalry", 1.0))
        w_a = float(weights.get("archers", 1.0))

    hero_str = pulp.lpSum(x[n] * strengths[n] for n in x)
    troop_str = w_i * t_i + w_c * t_c + w_a * t_a
    # Scale troop contribution so heroes still matter but formation fills capacity.
    strength = hero_str + 0.001 * troop_str

    combat = (scenario.combat_rate / 10_000.0) * scenario.enemy_power_scale * (
        0.01 * strength
    )
    occupation = scenario.minutes_held * scenario.personal_rate
    first = scenario.p_first * scenario.first_bonus
    loot = scenario.loot_expected
    # Slight mode-specific coupling: occupation only fully counts if garrison-like strength present
    # Keep linear: occupation/first/loot are constants per scenario; combat scales with strength.
    expected = combat + occupation + first + loot

    prob += expected

    status = prob.solve(pulp.PULP_CBC_CMD(msg=False))
    status_name = pulp.LpStatus.get(status, str(status))
    if status_name != "Optimal":
        return ModeSolution(
            mode=scenario.mode,
            hero_names=(),
            troops={"infantry": 0, "cavalry": 0, "archers": 0},
            effective_capacity=troops.march_capacity,
            expected_personal_points=float("-inf"),
            breakdown={},
            status=status_name,
        )

    chosen = tuple(sorted(n for n in x if pulp.value(x[n]) and pulp.value(x[n]) > 0.5))
    ti = int(round(pulp.value(t_i) or 0))
    tc = int(round(pulp.value(t_c) or 0))
    ta = int(round(pulp.value(t_a) or 0))
    eff_cap = troops.march_capacity + sum(escorts[n] for n in chosen)
    breakdown = {
        "combat": float(pulp.value(combat) or 0.0),
        "occupation": float(occupation),
        "first_control": float(first),
        "loot": float(loot),
    }
    return ModeSolution(
        mode=scenario.mode,
        hero_names=chosen,
        troops={"infantry": ti, "cavalry": tc, "archers": ta},
        effective_capacity=eff_cap,
        expected_personal_points=float(pulp.value(prob.objective) or 0.0),
        breakdown=breakdown,
        status="Optimal",
    )
