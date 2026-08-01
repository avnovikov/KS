"""Arena generic-offense optimizer: pick 5 heroes and 2F+3B placement."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ks.heroes.gear_models import GearRecord
from ks.heroes.models import HeroRecord
from ks.heroes.optimize.gear_assign import (
    assign_exclusive_sets,
    assignment_to_dict,
    gear_bonus_by_troop,
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


@dataclass(frozen=True)
class ArenaResult:
    side: str
    formation: dict[str, str]  # slot -> hero name
    heroes: tuple[str, ...]
    score: float
    gear_assignment: dict[str, list[dict[str, Any]]] | None
    reasons: dict[str, str]
    status: str = "Optimal"

    def to_dict(self) -> dict[str, Any]:
        return {
            "side": self.side,
            "formation": dict(self.formation),
            "heroes": list(self.heroes),
            "score": self.score,
            "gear_assignment": self.gear_assignment,
            "reasons": dict(self.reasons),
            "status": self.status,
        }


def load_arena_roles(path: Path | str) -> dict[str, Any]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("arena_roles.yaml must be a mapping")
    return raw


def _hero_base_score(
    hero: HeroRecord,
    entry: CatalogEntry | None,
    roles: dict[str, Any],
    *,
    effective_power: int | None,
    gear_bonus: float,
) -> float:
    meta = (roles.get("heroes") or {}).get(hero.name) or {}
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
    return arena_value * star + 40.0 * power_term + gear_bonus + rarity_bonus


def _placement_mult(
    troop: str,
    slot: str,
    hero_name: str,
    roles: dict[str, Any],
) -> float:
    place = roles.get("placement") or {}
    family = "front" if slot in FRONT else "back"
    key = f"{troop}_{family}"
    mult = float(place.get(key, 1.0))
    meta = (roles.get("heroes") or {}).get(hero_name) or {}
    role = str(meta.get("role") or "")
    if family == "front" and role.startswith("front"):
        mult *= float(place.get("front_tank_bonus", 1.0))
    carry_slot = str(roles.get("slots", {}).get("carry_slot") or "B2")
    tags = set(meta.get("tags") or [])
    if slot == carry_slot and ("dps" in tags or "aoe" in tags or role.startswith("back")):
        mult *= float(place.get("carry_slot_bonus", 1.0))
    return mult


def optimize_arena_attack(
    heroes: list[HeroRecord],
    catalog: dict[str, CatalogEntry],
    roles: dict[str, Any],
    *,
    gear: list[GearRecord] | None = None,
    gear_profile: str = "early_game_combat",
) -> ArenaResult:
    usable = [h for h in heroes if h.name in catalog]
    if len(usable) < 5:
        return ArenaResult(
            side="attack",
            formation={},
            heroes=(),
            score=float("-inf"),
            gear_assignment=None,
            reasons={},
            status="Infeasible",
        )

    troop_of = {
        h.name: normalize_troop(catalog[h.name].troop)
        or normalize_troop(h.troop_type)
        or "infantry"
        for h in usable
    }
    # Arena scores each hero on their own power (unlike marches, gear is not
    # shared mid-fight). Gear bonus still reflects best available set per class.
    gear_bonus = gear_bonus_by_troop(gear, profile=gear_profile) if gear else {}

    base: dict[str, float] = {}
    for h in usable:
        troop = troop_of[h.name]
        base[h.name] = _hero_base_score(
            h,
            catalog.get(h.name),
            roles,
            effective_power=h.power,
            gear_bonus=float(gear_bonus.get(troop, 0.0)),
        )

    prob = pulp.LpProblem("arena_attack", pulp.LpMaximize)
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
            mult = _placement_mult(troop_of[h.name], s, h.name, roles)
            obj.append(base[h.name] * mult * x[h.name, s])
    prob += pulp.lpSum(obj)

    status = prob.solve(pulp.PULP_CBC_CMD(msg=False))
    status_name = pulp.LpStatus.get(status, str(status))
    if status_name != "Optimal":
        return ArenaResult(
            side="attack",
            formation={},
            heroes=(),
            score=float("-inf"),
            gear_assignment=None,
            reasons={},
            status=status_name,
        )

    formation: dict[str, str] = {}
    for h in usable:
        for s in ALL_SLOTS:
            if pulp.value(x[h.name, s]) and pulp.value(x[h.name, s]) > 0.5:
                formation[s] = h.name

    ordered = tuple(formation[s] for s in ALL_SLOTS if s in formation)
    reasons = {
        name: _reason(name, catalog, roles, troop_of[name], base[name])
        for name in ordered
    }
    gear_assignment = None
    if gear:
        # Carry (B2) and fronts claim gear first; no piece shared across heroes.
        priority = [
            formation.get("B2"),
            formation.get("F1"),
            formation.get("F2"),
            formation.get("B1"),
            formation.get("B3"),
        ]
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

    score = float(pulp.value(prob.objective) or 0.0)
    return ArenaResult(
        side="attack",
        formation=formation,
        heroes=ordered,
        score=score,
        gear_assignment=gear_assignment,
        reasons=reasons,
        status="Optimal",
    )


def _reason(
    name: str,
    catalog: dict[str, CatalogEntry],
    roles: dict[str, Any],
    troop: str,
    score: float,
) -> str:
    meta = (roles.get("heroes") or {}).get(name) or {}
    entry = catalog.get(name)
    bits = [
        f"role={meta.get('role') or 'flex'}",
        f"troop={troop}",
        f"arena_value={meta.get('arena_value') or '-'}",
        f"score={score:.1f}",
    ]
    if entry and entry.rarity:
        bits.append(f"rarity={entry.rarity}")
    tags = meta.get("tags") or []
    if tags:
        bits.append("tags=" + "+".join(str(t) for t in tags))
    return ", ".join(bits)
