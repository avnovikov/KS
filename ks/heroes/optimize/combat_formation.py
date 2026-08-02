"""Shared 5-hero 2F+3B combat formation ILP used by Arena and Conquest."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import yaml

from ks.heroes.gear_models import GearRecord
from ks.heroes.models import HeroRecord
from ks.heroes.optimize.gear_assign import (
    assign_exclusive_sets,
    assignment_to_dict,
    load_profile_weights,
    piece_score,
)
from ks.heroes.optimize.scoring import (
    normalize_troop,
    star_progress_factor,
)
from ks.heroes.optimize.types import CatalogEntry

try:
    import pulp
except ImportError as exc:  # pragma: no cover
    raise ImportError("pulp is required for combat formation optimize") from exc

FRONT: tuple[str, ...] = ("F1", "F2")
BACK: tuple[str, ...] = ("B1", "B2", "B3")
ALL_SLOTS: tuple[str, ...] = FRONT + BACK


@dataclass(frozen=True)
class CombatFormationResult:
    """Solver output for any 5-hero 2F+3B formation (Arena or Conquest)."""

    mode: str
    side: str | None
    formation: dict[str, str]
    heroes: tuple[str, ...]
    score: float
    gear_assignment: dict[str, list[dict[str, Any]]] | None
    reasons: dict[str, str]
    status: str = "Optimal"
    explanations: dict[str, dict[str, Any]] | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "mode": self.mode,
            "formation": dict(self.formation),
            "heroes": list(self.heroes),
            "score": self.score,
            "gear_assignment": self.gear_assignment,
            "reasons": dict(self.reasons),
            "status": self.status,
        }
        if self.side is not None:
            out["side"] = self.side
        if self.explanations is not None:
            out["explanations"] = self.explanations
        return out


def load_combat_roles(
    path: Path | str,
    catalog: dict[str, CatalogEntry] | None = None,
) -> dict[str, Any]:
    """Load combat placement config; hero roles come from hero_catalog (SoT).

    The roles YAML keeps slots/placement only. Hero ``arena_role`` /
    ``arena_value`` / ``arena_tags`` are always taken from the catalog.
    """
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("roles YAML must be a mapping")
    out = dict(raw)
    from ks.heroes.optimize.catalog import arena_heroes_from_catalog, load_catalog

    if catalog is None:
        root = Path(__file__).resolve().parents[3]
        catalog = load_catalog(None, root / "config" / "hero_catalog.yaml")
    out["heroes"] = arena_heroes_from_catalog(catalog)
    return out


def _meta_for(hero_name: str, roles: dict[str, Any]) -> dict[str, Any]:
    return (roles.get("heroes") or {}).get(hero_name) or {}


def _hero_tags(hero_name: str, roles: dict[str, Any]) -> set[str]:
    meta = _meta_for(hero_name, roles)
    return {str(t) for t in (meta.get("tags") or meta.get("arena_tags") or [])}


def hero_base_score(
    hero: HeroRecord,
    entry: CatalogEntry | None,
    roles: dict[str, Any],
    *,
    effective_power: int | None,
    gear_bonus: float,
    side: str,
) -> float:
    """Compute a hero's base ILP score before placement multipliers."""
    meta = _meta_for(hero.name, roles)
    if entry is not None and entry.arena_value is not None:
        arena_value = float(entry.arena_value)
    else:
        arena_value = float(meta.get("arena_value") or 40.0)
    star = star_progress_factor(hero.stars, hero.pellets)
    power = effective_power if effective_power is not None else hero.power
    power_term = (float(power) / 1_000_000.0) if power else 0.0
    rarity_bonus = 0.0
    rarity = (entry.rarity if entry else hero.rarity) or ""
    rarity = rarity.lower()
    if rarity in {"legendary", "mythic"}:
        rarity_bonus = 8.0
    elif rarity == "epic":
        rarity_bonus = 4.0
    base = arena_value * star + 40.0 * power_term + gear_bonus + rarity_bonus

    if side == "defense":
        place = roles.get("defense_placement") or roles.get("placement") or {}
        tags = _hero_tags(hero.name, roles)
        if "tank" in tags:
            base *= float(place.get("tank_tag_bonus", 1.15))
        if "heal" in tags:
            base *= float(place.get("heal_tag_bonus", 1.25))
        if "team_def" in tags:
            base *= float(place.get("team_def_tag_bonus", 1.1))
        if "dps" in tags and "tank" not in tags and "heal" not in tags:
            base *= float(place.get("glass_dps_penalty", 0.92))
    return base


def _placement_table(roles: dict[str, Any], side: str) -> dict[str, Any]:
    if side == "defense" and roles.get("defense_placement"):
        return dict(roles["defense_placement"])
    return dict(roles.get("placement") or {})


def placement_mult(
    troop: str,
    slot: str,
    hero_name: str,
    roles: dict[str, Any],
    *,
    side: str,
) -> float:
    """Return placement multiplier for hero/slot/side combination."""
    place = _placement_table(roles, side)
    family = "front" if slot in FRONT else "back"
    key = f"{troop}_{family}"
    mult = float(place.get(key, 1.0))
    meta = _meta_for(hero_name, roles)
    role = str(meta.get("role") or meta.get("arena_role") or "")
    tags = _hero_tags(hero_name, roles)
    if family == "front" and (role.startswith("front") or "tank" in tags):
        mult *= float(place.get("front_tank_bonus", 1.0))
    carry_slot = str(roles.get("slots", {}).get("carry_slot") or "B2")
    if slot == carry_slot and ("dps" in tags or "aoe" in tags or role.startswith("back")):
        mult *= float(place.get("carry_slot_bonus", 1.0))
    if side == "defense":
        heal_slot = str(place.get("heal_slot") or "B1")
        if slot == heal_slot and "heal" in tags:
            mult *= float(place.get("heal_slot_bonus", 1.25))
    return mult


def _provisional_gear_bonus(
    usable: list[HeroRecord],
    catalog: dict[str, CatalogEntry],
    gear: list[GearRecord] | None,
    gear_profile: str,
) -> dict[str, float]:
    gear_bonus_by_hero: dict[str, float] = {h.name: 0.0 for h in usable}
    if not gear:
        return gear_bonus_by_hero
    weights = load_profile_weights(gear_profile)
    score_priority = [
        h.name for h in sorted(usable, key=lambda row: -(row.power or 0))
    ]
    provisional = assign_exclusive_sets(
        usable,
        catalog,
        gear,
        selected=[h.name for h in usable],
        priority=score_priority,
        profile=gear_profile,
    )
    for name, slots in provisional.items():
        gear_bonus_by_hero[name] = 0.15 * sum(
            piece_score(piece, profile=gear_profile, weights=weights)
            for piece in slots.values()
        )
    return gear_bonus_by_hero


def _reason(
    name: str,
    catalog: dict[str, CatalogEntry],
    roles: dict[str, Any],
    troop: str,
    score: float,
) -> str:
    meta = _meta_for(name, roles)
    entry = catalog.get(name)
    bits = [
        f"role={meta.get('role') or meta.get('arena_role') or 'flex'}",
        f"troop={troop}",
        f"arena_value={meta.get('arena_value') or '-'}",
        f"score={score:.1f}",
    ]
    if entry and entry.rarity:
        bits.append(f"rarity={entry.rarity}")
    tags = meta.get("tags") or meta.get("arena_tags") or []
    if tags:
        bits.append("tags=" + "+".join(str(t) for t in tags))
    return ", ".join(bits)


def _infeasible_result(mode: str, side: str | None, status: str) -> CombatFormationResult:
    return CombatFormationResult(
        mode=mode,
        side=side,
        formation={},
        heroes=(),
        score=float("-inf"),
        gear_assignment=None,
        reasons={},
        status=status,
    )


def solve_combat_formation(
    mode: str,
    heroes: list[HeroRecord],
    catalog: dict[str, CatalogEntry],
    roles: dict[str, Any],
    *,
    side: str | None = None,
    gear: list[GearRecord] | None = None,
    gear_profile: str = "early_game_combat",
    gear_slot_order: tuple[str, ...],
    base_score_fn: Callable[..., float] | None = None,
    placement_mult_fn: Callable[..., float] | None = None,
    with_explanations: bool = True,
    explain_fn: Callable[..., dict[str, dict[str, Any]]] | None = None,
) -> CombatFormationResult:
    """Solve the 5-hero 2F+3B placement ILP for any combat mode.

    ``side`` is passed to scoring helpers; Arena uses "attack"/"defense".
    When omitted, scoring defaults to "attack" behaviour.

    ``base_score_fn`` is called as ``fn(hero, entry, roles, *, effective_power, gear_bonus)``.
    ``placement_mult_fn`` is called as ``fn(troop, slot, hero_name, roles)``.
    """
    effective_side = side or "attack"
    usable = [h for h in heroes if h.name in catalog]
    if len(usable) < 5:
        return _infeasible_result(mode, side, "Infeasible")

    troop_of = {
        h.name: normalize_troop(catalog[h.name].troop)
        or normalize_troop(h.troop_type)
        or "infantry"
        for h in usable
    }
    gear_bonus_by_hero = _provisional_gear_bonus(usable, catalog, gear, gear_profile)

    _base_score_fn = base_score_fn or (
        lambda h, entry, roles, *, effective_power, gear_bonus: hero_base_score(
            h, entry, roles,
            effective_power=effective_power,
            gear_bonus=gear_bonus,
            side=effective_side,
        )
    )
    _placement_mult_fn = placement_mult_fn or (
        lambda troop, slot, hero_name, roles: placement_mult(
            troop, slot, hero_name, roles, side=effective_side
        )
    )

    base: dict[str, float] = {}
    for h in usable:
        base[h.name] = _base_score_fn(
            h,
            catalog.get(h.name),
            roles,
            effective_power=h.power,
            gear_bonus=float(gear_bonus_by_hero.get(h.name, 0.0)),
        )

    prob = pulp.LpProblem(f"{mode}_{effective_side}", pulp.LpMaximize)
    x = pulp.LpVariable.dicts(
        "place",
        ((h.name, s) for h in usable for s in ALL_SLOTS),
        cat="Binary",
    )

    for s in ALL_SLOTS:
        prob += pulp.lpSum(x[h.name, s] for h in usable) == 1
    for h in usable:
        prob += pulp.lpSum(x[h.name, s] for s in ALL_SLOTS) <= 1

    obj = []
    for h in usable:
        for s in ALL_SLOTS:
            mult = _placement_mult_fn(troop_of[h.name], s, h.name, roles)
            obj.append(base[h.name] * mult * x[h.name, s])
    prob += pulp.lpSum(obj)

    status = prob.solve(pulp.PULP_CBC_CMD(msg=False))
    status_name = pulp.LpStatus.get(status, str(status))
    if status_name != "Optimal":
        return _infeasible_result(mode, side, status_name)

    formation: dict[str, str] = {}
    for h in usable:
        for s in ALL_SLOTS:
            if pulp.value(x[h.name, s]) and pulp.value(x[h.name, s]) > 0.5:
                formation[s] = h.name

    if set(formation) != set(ALL_SLOTS):
        return _infeasible_result(mode, side, "Error")

    ordered = tuple(formation[s] for s in ALL_SLOTS)
    reasons = {
        name: _reason(name, catalog, roles, troop_of[name], base[name])
        for name in ordered
    }
    gear_assignment = None
    if gear:
        priority = [formation.get(slot) for slot in gear_slot_order]
        priority_names = [n for n in priority if n]
        assigned = assign_exclusive_sets(
            usable,
            catalog,
            gear,
            selected=list(ordered),
            priority=priority_names,
            profile=gear_profile,
        )
        gear_assignment = assignment_to_dict(assigned)

    objective = pulp.value(prob.objective)
    if objective is None:
        return _infeasible_result(mode, side, "Error")
    score = float(objective)

    explanations = None
    if with_explanations:
        if explain_fn is not None:
            try:
                explanations = explain_fn(
                    # `effective_side`, not `side`: scoring above already ran
                    # on the "attack" default when the caller passed None, so
                    # handing the explainer a bare None would have it explain
                    # a different side than the one that was solved. Conquest
                    # is the only mode with side=None, so the first Conquest
                    # explain_fn would have been the one to hit it.
                    effective_side,
                    heroes,
                    catalog,
                    roles,
                    formation,
                    base,
                    score,
                    gear=gear,
                    gear_profile=gear_profile,
                )
                for name, exp in explanations.items():
                    reasons[name] = exp.get("summary") or reasons.get(name, "")
            except Exception as exc:  # noqa: BLE001
                explanations = None
                reasons["_explain_warning"] = f"explainability unavailable: {exc}"
        elif mode == "arena":
            from ks.heroes.optimize.explain import explain_arena_formation

            try:
                explanations = explain_arena_formation(
                    effective_side,
                    heroes,
                    catalog,
                    roles,
                    formation,
                    base,
                    score,
                    gear=gear,
                    gear_profile=gear_profile,
                )
                for name, exp in explanations.items():
                    reasons[name] = exp.get("summary") or reasons.get(name, "")
            except Exception as exc:  # noqa: BLE001
                explanations = None
                reasons["_explain_warning"] = f"explainability unavailable: {exc}"

    return CombatFormationResult(
        mode=mode,
        side=side,
        formation=formation,
        heroes=ordered,
        score=score,
        gear_assignment=gear_assignment,
        reasons=reasons,
        status="Optimal",
        explanations=explanations,
    )
