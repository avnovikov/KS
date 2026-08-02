"""Arena attack/defense optimizer: pick 5 heroes and 2F+3B placement."""

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
    raise ImportError("pulp is required for arena optimize") from exc

FRONT = ("F1", "F2")
BACK = ("B1", "B2", "B3")
ALL_SLOTS = FRONT + BACK

# Attack: carry and fronts claim gear first.
_ATTACK_GEAR_ORDER = ("B2", "F1", "F2", "B1", "B3")
# Defense: tanks survive first, then carry, then heal last.
_DEFENSE_GEAR_ORDER = ("F1", "F2", "B2", "B3", "B1")


@dataclass(frozen=True)
class ArenaResult:
    side: str
    formation: dict[str, str]  # slot -> hero name
    heroes: tuple[str, ...]
    score: float
    gear_assignment: dict[str, list[dict[str, Any]]] | None
    reasons: dict[str, str]
    status: str = "Optimal"
    explanations: dict[str, dict[str, Any]] | None = None

    def to_dict(self) -> dict[str, Any]:
        out = {
            "side": self.side,
            "formation": dict(self.formation),
            "heroes": list(self.heroes),
            "score": self.score,
            "gear_assignment": self.gear_assignment,
            "reasons": dict(self.reasons),
            "status": self.status,
        }
        if self.explanations is not None:
            out["explanations"] = self.explanations
        return out


def load_arena_roles(
    path: Path | str,
    catalog: dict[str, CatalogEntry] | None = None,
) -> dict[str, Any]:
    """Load arena placement config; hero roles come from hero_catalog (SoT).

    ``arena_roles.yaml`` keeps slots/placement only. Hero ``arena_role`` /
    ``arena_value`` / ``arena_tags`` are always taken from the catalog.
    """
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("arena_roles.yaml must be a mapping")
    out = dict(raw)
    from ks.heroes.optimize.catalog import arena_heroes_from_catalog, load_catalog

    if catalog is None:
        # Default SoT: config/hero_catalog.yaml (YAML-only; pro cache optional).
        root = Path(__file__).resolve().parents[3]
        catalog = load_catalog(None, root / "config" / "hero_catalog.yaml")
    out["heroes"] = arena_heroes_from_catalog(catalog)
    # Drop any legacy heroes block from the placement file.
    return out


def _meta_for(hero_name: str, roles: dict[str, Any]) -> dict[str, Any]:
    return (roles.get("heroes") or {}).get(hero_name) or {}


def _hero_tags(hero_name: str, roles: dict[str, Any]) -> set[str]:
    meta = _meta_for(hero_name, roles)
    return {str(t) for t in (meta.get("tags") or meta.get("arena_tags") or [])}


def _arena_value_for(
    hero: HeroRecord, entry: CatalogEntry | None, meta: dict[str, Any]
) -> float:
    """Catalog arena_value wins; fall back to per-hero role metadata, then a default."""
    if entry is not None and entry.arena_value is not None:
        return float(entry.arena_value)
    return float(meta.get("arena_value") or 40.0)


def _rarity_bonus(entry: CatalogEntry | None, hero: HeroRecord) -> float:
    rarity = ((entry.rarity if entry else hero.rarity) or "").lower()
    if rarity in {"legendary", "mythic"}:
        return 8.0
    if rarity == "epic":
        return 4.0
    return 0.0


def _defense_tag_multiplier(hero_name: str, roles: dict[str, Any]) -> float:
    """Combined offline-defense multiplier from tank/heal/team_def/glass-dps tags."""
    place = roles.get("defense_placement") or roles.get("placement") or {}
    tags = _hero_tags(hero_name, roles)
    multiplier = 1.0
    if "tank" in tags:
        multiplier *= float(place.get("tank_tag_bonus", 1.15))
    if "heal" in tags:
        multiplier *= float(place.get("heal_tag_bonus", 1.25))
    if "team_def" in tags:
        multiplier *= float(place.get("team_def_tag_bonus", 1.1))
    # Pure glass DPS is slightly less valuable offline than on attack.
    if "dps" in tags and "tank" not in tags and "heal" not in tags:
        multiplier *= float(place.get("glass_dps_penalty", 0.92))
    return multiplier


def _hero_base_score(
    hero: HeroRecord,
    entry: CatalogEntry | None,
    roles: dict[str, Any],
    *,
    effective_power: int | None,
    gear_bonus: float,
    side: str,
) -> float:
    meta = _meta_for(hero.name, roles)
    arena_value = _arena_value_for(hero, entry, meta)
    star = star_progress_factor(hero.stars, hero.pellets)
    power = effective_power if effective_power is not None else hero.power
    power_term = (float(power) / 1_000_000.0) if power else 0.0
    base = (
        arena_value * star
        + 40.0 * power_term
        + gear_bonus
        + _rarity_bonus(entry, hero)
    )

    if side == "defense":
        base *= _defense_tag_multiplier(hero.name, roles)
    return base


def _placement_table(roles: dict[str, Any], side: str) -> dict[str, Any]:
    if side == "defense" and roles.get("defense_placement"):
        return dict(roles["defense_placement"])
    return dict(roles.get("placement") or {})


def _placement_mult(
    troop: str,
    slot: str,
    hero_name: str,
    roles: dict[str, Any],
    *,
    side: str,
) -> float:
    place = _placement_table(roles, side)
    family = "front" if slot in FRONT else "back"
    key = f"{troop}_{family}"
    mult = float(place.get(key, 1.0))
    meta = _meta_for(hero_name, roles)
    role = str(meta.get("role") or meta.get("arena_role") or "")
    tags = _hero_tags(hero_name, roles)
    if family == "front" and (
        role.startswith("front") or "tank" in tags
    ):
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


def _arena_error_result(side: str, status: str) -> ArenaResult:
    """Build the shared "no formation" result shape for early-exit failures."""
    return ArenaResult(
        side=side,
        formation={},
        heroes=(),
        score=float("-inf"),
        gear_assignment=None,
        reasons={},
        status=status,
    )


def _build_troop_lookup(
    usable: list[HeroRecord], catalog: dict[str, CatalogEntry]
) -> dict[str, str]:
    return {
        h.name: normalize_troop(catalog[h.name].troop)
        or normalize_troop(h.troop_type)
        or "infantry"
        for h in usable
    }


def _compute_base_scores(
    usable: list[HeroRecord],
    catalog: dict[str, CatalogEntry],
    roles: dict[str, Any],
    gear_bonus_by_hero: dict[str, float],
    *,
    side: str,
) -> dict[str, float]:
    return {
        h.name: _hero_base_score(
            h,
            catalog.get(h.name),
            roles,
            effective_power=h.power,
            gear_bonus=float(gear_bonus_by_hero.get(h.name, 0.0)),
            side=side,
        )
        for h in usable
    }


def _build_ilp_problem(
    side: str,
    usable: list[HeroRecord],
    roles: dict[str, Any],
    troop_of: dict[str, str],
    base: dict[str, float],
) -> tuple[pulp.LpProblem, dict[tuple[str, str], Any]]:
    """Assemble the "one hero per slot" assignment ILP and its objective."""
    prob = pulp.LpProblem(f"arena_{side}", pulp.LpMaximize)
    x = pulp.LpVariable.dicts(
        "place",
        ((h.name, s) for h in usable for s in ALL_SLOTS),
        cat="Binary",
    )

    for s in ALL_SLOTS:
        prob += pulp.lpSum(x[h.name, s] for h in usable) == 1
    for h in usable:
        prob += pulp.lpSum(x[h.name, s] for s in ALL_SLOTS) <= 1

    obj = [
        base[h.name]
        * _placement_mult(troop_of[h.name], s, h.name, roles, side=side)
        * x[h.name, s]
        for h in usable
        for s in ALL_SLOTS
    ]
    prob += pulp.lpSum(obj)
    return prob, x


def _extract_formation(
    usable: list[HeroRecord], x: dict[tuple[str, str], Any]
) -> dict[str, str]:
    formation: dict[str, str] = {}
    for h in usable:
        for s in ALL_SLOTS:
            value = pulp.value(x[h.name, s])
            if value and value > 0.5:
                formation[s] = h.name
    return formation


def _build_reasons(
    ordered: tuple[str, ...],
    catalog: dict[str, CatalogEntry],
    roles: dict[str, Any],
    troop_of: dict[str, str],
    base: dict[str, float],
) -> dict[str, str]:
    return {
        name: _reason(name, catalog, roles, troop_of[name], base[name])
        for name in ordered
    }


def _assign_gear_for_formation(
    formation: dict[str, str],
    usable: list[HeroRecord],
    catalog: dict[str, CatalogEntry],
    gear: list[GearRecord] | None,
    gear_profile: str,
    gear_slot_order: tuple[str, ...],
    ordered: tuple[str, ...],
) -> dict[str, list[dict[str, Any]]] | None:
    if not gear:
        return None
    # Slot claim order (defense: fronts first, heal/B1 last).
    priority_names = [
        name for name in (formation.get(slot) for slot in gear_slot_order) if name
    ]
    assigned = assign_exclusive_sets(
        usable,
        catalog,
        gear,
        selected=list(ordered),
        priority=priority_names,
        profile=gear_profile,
    )
    return assignment_to_dict(assigned)


def _attach_explanations(
    side: str,
    heroes: list[HeroRecord],
    catalog: dict[str, CatalogEntry],
    roles: dict[str, Any],
    formation: dict[str, str],
    base: dict[str, float],
    score: float,
    gear: list[GearRecord] | None,
    gear_profile: str,
    reasons: dict[str, str],
) -> dict[str, dict[str, Any]] | None:
    """Compute leave-one-out explanations, folding summaries into ``reasons``.

    ``reasons`` is mutated in place so the caller's dict reflects the
    per-hero summaries (or a warning) regardless of success/failure.
    """
    from ks.heroes.optimize.explain import explain_arena_formation

    try:
        explanations = explain_arena_formation(
            side,
            heroes,
            catalog,
            roles,
            formation,
            base,
            score,
            gear=gear,
            gear_profile=gear_profile,
        )
    except Exception as exc:  # noqa: BLE001 — keep Optimal solve if LOO fails
        reasons["_explain_warning"] = f"explainability unavailable: {exc}"
        return None
    for name, exp in explanations.items():
        reasons[name] = exp.get("summary") or reasons.get(name, "")
    return explanations


def _solve_arena(
    side: str,
    heroes: list[HeroRecord],
    catalog: dict[str, CatalogEntry],
    roles: dict[str, Any],
    *,
    gear: list[GearRecord] | None,
    gear_profile: str,
    gear_slot_order: tuple[str, ...],
    with_explanations: bool = True,
) -> ArenaResult:
    usable = [h for h in heroes if h.name in catalog]
    if len(usable) < 5:
        return _arena_error_result(side, "Infeasible")

    troop_of = _build_troop_lookup(usable, catalog)
    gear_bonus_by_hero = _provisional_gear_bonus(usable, catalog, gear, gear_profile)
    base = _compute_base_scores(usable, catalog, roles, gear_bonus_by_hero, side=side)

    prob, x = _build_ilp_problem(side, usable, roles, troop_of, base)
    status = prob.solve(pulp.PULP_CBC_CMD(msg=False))
    status_name = pulp.LpStatus.get(status, str(status))
    if status_name != "Optimal":
        return _arena_error_result(side, status_name)

    formation = _extract_formation(usable, x)
    if set(formation) != set(ALL_SLOTS):
        return _arena_error_result(side, "Error")

    ordered = tuple(formation[s] for s in ALL_SLOTS)
    reasons = _build_reasons(ordered, catalog, roles, troop_of, base)
    gear_assignment = _assign_gear_for_formation(
        formation, usable, catalog, gear, gear_profile, gear_slot_order, ordered
    )

    objective = pulp.value(prob.objective)
    if objective is None:
        return _arena_error_result(side, "Error")
    score = float(objective)

    explanations = None
    if with_explanations:
        explanations = _attach_explanations(
            side, heroes, catalog, roles, formation, base, score, gear, gear_profile, reasons
        )

    return ArenaResult(
        side=side,
        formation=formation,
        heroes=ordered,
        score=score,
        gear_assignment=gear_assignment,
        reasons=reasons,
        status="Optimal",
        explanations=explanations,
    )


def optimize_arena_attack(
    heroes: list[HeroRecord],
    catalog: dict[str, CatalogEntry],
    roles: dict[str, Any],
    *,
    gear: list[GearRecord] | None = None,
    gear_profile: str = "early_game_combat",
    with_explanations: bool = True,
) -> ArenaResult:
    return _solve_arena(
        "attack",
        heroes,
        catalog,
        roles,
        gear=gear,
        gear_profile=gear_profile,
        gear_slot_order=_ATTACK_GEAR_ORDER,
        with_explanations=with_explanations,
    )


def optimize_arena_defense(
    heroes: list[HeroRecord],
    catalog: dict[str, CatalogEntry],
    roles: dict[str, Any],
    *,
    gear: list[GearRecord] | None = None,
    gear_profile: str = "early_game_combat",
    with_explanations: bool = True,
) -> ArenaResult:
    """Offline defense: prefer tanks + heal; fronts claim gear first."""
    return _solve_arena(
        "defense",
        heroes,
        catalog,
        roles,
        gear=gear,
        gear_profile=gear_profile,
        gear_slot_order=_DEFENSE_GEAR_ORDER,
        with_explanations=with_explanations,
    )


def optimize_arena(
    side: str,
    heroes: list[HeroRecord],
    catalog: dict[str, CatalogEntry],
    roles: dict[str, Any],
    *,
    gear: list[GearRecord] | None = None,
    gear_profile: str = "early_game_combat",
    with_explanations: bool = True,
) -> ArenaResult:
    solvers: dict[str, Callable[..., ArenaResult]] = {
        "attack": optimize_arena_attack,
        "defense": optimize_arena_defense,
    }
    if side not in solvers:
        raise ValueError(
            f"unsupported arena side {side!r}; have {sorted(solvers)}"
        )
    return solvers[side](
        heroes,
        catalog,
        roles,
        gear=gear,
        gear_profile=gear_profile,
        with_explanations=with_explanations,
    )


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
