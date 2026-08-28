"""Attach front-survival analysis vs self-play foes to a combat formation result."""

from __future__ import annotations

from typing import Any, Callable

from ks.heroes.gear_models import GearRecord
from ks.heroes.models import HeroRecord
from ks.heroes.optimize.combat_formation import (
    ALL_SLOTS,
    BACK,
    FRONT,
    CombatFormationResult,
    hero_base_score,
    placement_mult,
    solve_combat_formation,
)
from ks.heroes.optimize.front_survival import (
    formation_tau,
    hero_tau,
    pressure_scale,
    rarity_median_powers,
    roster_median_power,
    sanitize_power,
    survival_score,
)
from ks.heroes.optimize.gear_assign import assign_exclusive_sets
from ks.heroes.optimize.opponent_models import (
    GEAR_FRONT_FIRST,
    OpponentLineup,
    build_naive_max_power,
    build_troop_balanced_naive,
    opponent_from_formation,
)
from ks.heroes.optimize.scoring import normalize_troop
from ks.heroes.optimize.stat_contributions import (
    CONQUEST,
    StatContribution,
    hero_contribution,
)
from ks.heroes.optimize.types import CatalogEntry

BaseScoreFn = Callable[..., float]


def sanitize_hero_powers(
    heroes: list[HeroRecord],
    *,
    roles: dict[str, Any] | None = None,
) -> dict[str, int | None]:
    """Return name → sanitized power for ILP / ranking (OCR blow-ups → median).

    Reads ``survival.power_sanitize_max`` and ``survival.power_sanitize_median_factor``
    from ``roles`` when present. If cleaned power is ≤0, keeps the original
    ``h.power`` (may be None).
    """
    cfg = (roles or {}).get("survival") or {}
    max_abs = int(cfg.get("power_sanitize_max", 2_000_000))
    median_factor = float(cfg.get("power_sanitize_median_factor", 20.0))
    median = roster_median_power(heroes)
    rarity_medians = rarity_median_powers(heroes, max_abs=max_abs)
    out: dict[str, int | None] = {}
    for h in heroes:
        cleaned = sanitize_power(
            h.power,
            median_power=median,
            rarity=h.rarity,
            rarity_medians=rarity_medians,
            max_abs=max_abs,
            median_factor=median_factor,
        )
        out[h.name] = int(round(cleaned)) if cleaned > 0 else h.power
    return out


def gear_maps_for_formation(
    formation: dict[str, str],
    heroes: list[HeroRecord],
    catalog: dict[str, CatalogEntry],
    gear: list[GearRecord] | None,
    *,
    profile: str,
    gear_order: tuple[str, ...] = GEAR_FRONT_FIRST,
) -> dict[str, dict[str, GearRecord]]:
    if not gear:
        return {}
    selected = [formation[s] for s in ALL_SLOTS if s in formation]
    priority = [formation[s] for s in gear_order if s in formation]
    return assign_exclusive_sets(
        heroes,
        catalog,
        gear,
        selected=selected,
        priority=priority,
        profile=profile,
    )


def slot_utilities(
    formation: dict[str, str],
    heroes_by_name: dict[str, HeroRecord],
    catalog: dict[str, CatalogEntry],
    roles: dict[str, Any],
    *,
    side: str,
    base_score_fn: BaseScoreFn,
    power_by_name: dict[str, int | None] | None = None,
    contributions: dict[str, StatContribution] | None = None,
) -> tuple[float, float, dict[str, float]]:
    contributions = contributions or {}
    u_front = 0.0
    u_back = 0.0
    per: dict[str, float] = {}
    for slot, name in formation.items():
        hero = heroes_by_name[name]
        entry = catalog.get(name)
        troop = (
            normalize_troop(entry.troop if entry else None)
            or normalize_troop(hero.troop_type)
            or "infantry"
        )
        power = (
            power_by_name.get(name, hero.power)
            if power_by_name is not None
            else hero.power
        )
        base = base_score_fn(
            hero,
            entry,
            roles,
            effective_power=power,
            contribution=contributions.get(name),
        )
        contrib = base * placement_mult(troop, slot, name, roles, side=side)
        per[name] = contrib
        if slot in FRONT:
            u_front += contrib
        elif slot in BACK:
            u_back += contrib
    return u_front, u_back, per


def roster_pressure_scale(
    heroes: list[HeroRecord],
    catalog: dict[str, CatalogEntry],
    roles: dict[str, Any],
    *,
    base_score_fn: BaseScoreFn,
    power_by_name: dict[str, int | None] | None = None,
    contributions: dict[str, StatContribution] | None = None,
) -> float:
    contributions = contributions or {}
    by_name = {h.name: h for h in heroes if h.name in catalog}
    tau_samples: list[float] = []
    u_samples: list[float] = []
    for name, hero in by_name.items():
        contribution = contributions.get(name)
        tau_samples.append(hero_tau(hero, contribution=contribution))
        entry = catalog.get(name)
        power = (
            power_by_name.get(name, hero.power)
            if power_by_name is not None
            else hero.power
        )
        base = base_score_fn(
            hero, entry, roles, effective_power=power, contribution=contribution
        )
        u_samples.append(base)
    return pressure_scale(tau_samples=tau_samples, U_samples=u_samples)


def evaluate_vs_foe(
    formation: dict[str, str],
    heroes: list[HeroRecord],
    catalog: dict[str, CatalogEntry],
    roles: dict[str, Any],
    foe: OpponentLineup,
    *,
    side: str,
    base_score_fn: BaseScoreFn,
    our_gear: dict[str, dict[str, GearRecord]] | None = None,
    lambda_tau: float = 5.0,
    O_scale: float = 1.0,
    power_by_name: dict[str, int | None] | None = None,
    gear_profile: str = "early_game_combat",
    contributions: dict[str, StatContribution] | None = None,
) -> dict[str, Any]:
    by_name = {h.name: h for h in heroes}
    tau_f, tau_b, tau_by = formation_tau(
        formation, by_name, our_gear, contributions=contributions
    )
    u_front, u_back, _ = slot_utilities(
        formation,
        by_name,
        catalog,
        roles,
        side=side,
        base_score_fn=base_score_fn,
        power_by_name=power_by_name,
        contributions=contributions,
    )
    breakdown = survival_score(
        tau_F=tau_f,
        tau_B=tau_b,
        O=foe.heuristic_offense,
        U_front=u_front,
        U_back=u_back,
        lambda_tau=lambda_tau,
        tau_by_hero=tau_by,
        O_scale=O_scale,
    )
    out = breakdown.to_dict()
    out["O_heuristic"] = foe.heuristic_offense
    out["O_scale"] = O_scale
    out["foe"] = foe.to_dict()
    return out


def build_self_play_foes(
    heroes: list[HeroRecord],
    catalog: dict[str, CatalogEntry],
    roles: dict[str, Any],
    *,
    gear: list[GearRecord] | None = None,
    gear_profile: str = "early_game_combat",
    foe_names: list[str] | None = None,
    heuristic_mode: str = "conquest",
    heuristic_side: str | None = None,
    base_score_fn: BaseScoreFn | None = None,
    gear_order: tuple[str, ...] = GEAR_FRONT_FIRST,
) -> list[OpponentLineup]:
    wanted = foe_names or ["naive_max_power", "troop_balanced_naive", "heuristic_foe"]
    score_fn = base_score_fn or (
        lambda h, entry, roles, *, effective_power, contribution: hero_base_score(
            h,
            entry,
            roles,
            effective_power=effective_power,
            contribution=contribution,
            side=heuristic_side or "attack",
        )
    )
    place_side = heuristic_side or "attack"
    foes: list[OpponentLineup] = []
    for name in wanted:
        if name == "naive_max_power":
            foes.append(
                build_naive_max_power(
                    heroes,
                    catalog,
                    roles,
                    gear=gear,
                    gear_profile=gear_profile,
                    side=place_side,
                    base_score_fn=score_fn,
                )
            )
        elif name == "troop_balanced_naive":
            foes.append(
                build_troop_balanced_naive(
                    heroes,
                    catalog,
                    roles,
                    gear=gear,
                    gear_profile=gear_profile,
                    side=place_side,
                    base_score_fn=score_fn,
                )
            )
        elif name == "heuristic_foe":
            baseline = solve_combat_formation(
                heuristic_mode,
                heroes,
                catalog,
                roles,
                side=heuristic_side,
                gear=gear,
                gear_profile=gear_profile,
                gear_slot_order=gear_order,
                base_score_fn=score_fn,
                placement_mult_fn=lambda troop, slot, n, r: placement_mult(
                    troop, slot, n, r, side=place_side
                ),
                with_explanations=False,
                explain_fn=None,
            )
            if baseline.status != "Optimal":
                continue
            gear_asg = gear_maps_for_formation(
                baseline.formation,
                heroes,
                catalog,
                gear,
                profile=gear_profile,
                gear_order=gear_order,
            )
            foes.append(
                opponent_from_formation(
                    "heuristic_foe",
                    baseline.formation,
                    heroes,
                    catalog,
                    roles,
                    gear=gear,
                    gear_profile=gear_profile,
                    gear_assignment=gear_asg,
                    side=place_side,
                    base_score_fn=score_fn,
                )
            )
        else:
            raise ValueError(f"unknown foe model {name!r}")
    return foes


def attach_survival(
    result: CombatFormationResult,
    heroes: list[HeroRecord],
    catalog: dict[str, CatalogEntry],
    roles: dict[str, Any],
    *,
    gear: list[GearRecord] | None = None,
    gear_profile: str = "early_game_combat",
    side: str = "attack",
    base_score_fn: BaseScoreFn,
    gear_order: tuple[str, ...] = GEAR_FRONT_FIRST,
    heuristic_mode: str = "conquest",
) -> CombatFormationResult:
    """Compute survival block vs self-play foes and stash on explanations."""
    if result.status != "Optimal":
        return result
    survival_cfg = roles.get("survival") or {}
    if survival_cfg.get("enabled", True) is False:
        return result

    # Match ILP cohort: catalog-usable heroes only (Bugbot median mismatch).
    usable = [h for h in heroes if h.name in catalog]
    power_by_name = sanitize_hero_powers(usable, roles=roles)
    our_gear = gear_maps_for_formation(
        result.formation,
        usable,
        catalog,
        gear,
        profile=gear_profile,
        gear_order=gear_order,
    )
    from ks.heroes.optimize.combat_formation import contributions_from_assignment

    our_contributions = contributions_from_assignment(
        {name: our_gear.get(name, {}) for name in result.formation.values()},
        catalog=catalog,
        heroes_by_name={h.name: h for h in usable},
        power_by_name=power_by_name,
        family=CONQUEST,
    )
    # roster_pressure_scale medians over the whole catalog-usable roster, not
    # just the 5 placed heroes — every sample must share one contribution
    # basis, or the median silently straddles gear-bearing and bare heroes
    # and biases O_scale. Non-formation heroes hold no assigned gear, so this
    # is the same contribution each would get if `our_gear` had an (empty)
    # entry for them.
    roster_contributions = {
        h.name: hero_contribution(
            h,
            catalog.get(h.name),
            family=CONQUEST,
            gear_pieces=our_gear.get(h.name),
            power=power_by_name.get(h.name, h.power),
            catalog=catalog,
        )
        for h in usable
    }
    foe_names = list(
        survival_cfg.get("foes")
        or ["naive_max_power", "troop_balanced_naive", "heuristic_foe"]
    )
    primary = str(survival_cfg.get("primary_foe") or "naive_max_power")
    lambda_tau = float(survival_cfg.get("lambda_tau", 5.0))

    foes = build_self_play_foes(
        usable,
        catalog,
        roles,
        gear=gear,
        gear_profile=gear_profile,
        foe_names=foe_names,
        heuristic_mode=heuristic_mode,
        heuristic_side=side if heuristic_mode == "arena" else None,
        base_score_fn=base_score_fn,
        gear_order=gear_order,
    )
    o_scale = roster_pressure_scale(
        usable,
        catalog,
        roles,
        base_score_fn=base_score_fn,
        power_by_name=power_by_name,
        contributions=roster_contributions,
    )
    foe_blocks: dict[str, Any] = {}
    score_eff_primary = None
    for foe in foes:
        block = evaluate_vs_foe(
            result.formation,
            usable,
            catalog,
            roles,
            foe,
            side=side,
            base_score_fn=base_score_fn,
            our_gear=our_gear,
            lambda_tau=lambda_tau,
            O_scale=o_scale,
            power_by_name=power_by_name,
            gear_profile=gear_profile,
            contributions=our_contributions,
        )
        foe_blocks[foe.model] = block
        if foe.model == primary:
            score_eff_primary = block["score_eff"]

    tau_f, tau_b, tau_by = formation_tau(
        result.formation,
        {h.name: h for h in usable},
        our_gear,
        contributions=our_contributions,
    )
    u_front, u_back, _ = slot_utilities(
        result.formation,
        {h.name: h for h in usable},
        catalog,
        roles,
        side=side,
        base_score_fn=base_score_fn,
        power_by_name=power_by_name,
        contributions=our_contributions,
    )
    sensitivity = None
    primary_foe_obj = next((f for f in foes if f.model == primary), None)
    if primary_foe_obj is not None:
        from ks.heroes.optimize.sensitivity import build_sensitivity

        sensitivity = build_sensitivity(
            result.formation,
            usable,
            catalog,
            roles,
            primary_foe_obj,
            side=side,
            base_score_fn=base_score_fn,
            gear=gear,
            gear_profile=gear_profile,
            gear_order=gear_order,
            lambda_tau=lambda_tau,
            O_scale=o_scale,
            power_by_name=power_by_name,
            contributions=our_contributions,
        )

    survival = {
        "our": {
            "formation": dict(result.formation),
            "tau_F": tau_f,
            "tau_B": tau_b,
            "U_front": u_front,
            "U_back": u_back,
            "tau_by_hero": tau_by,
            "stat_family": CONQUEST,
            "contributions": {n: c.to_dict() for n, c in our_contributions.items()},
        },
        "foes": foe_blocks,
        "primary_foe": primary,
        "score_eff": score_eff_primary,
        "ilp_score": result.score,
        "O_scale": o_scale,
        "sensitivity": sensitivity,
    }
    if primary not in foe_blocks:
        survival["error"] = (
            f"primary_foe {primary!r} not among built foes {list(foe_blocks)}"
        )
    explanations = dict(result.explanations or {})
    explanations["survival"] = survival
    return CombatFormationResult(
        mode=result.mode,
        side=result.side,
        formation=result.formation,
        heroes=result.heroes,
        score=result.score,
        gear_assignment=result.gear_assignment,
        reasons=result.reasons,
        status=result.status,
        explanations=explanations,
        stat_family=result.stat_family,
        contributions=result.contributions,
        formation_totals=result.formation_totals,
    )
