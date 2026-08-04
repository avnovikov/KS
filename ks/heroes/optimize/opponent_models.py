"""Self-play opponent lineups from our heroes + gear for survival scoring."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable

from ks.heroes.gear_models import GearRecord
from ks.heroes.models import HeroRecord
from ks.heroes.optimize.combat_formation import (
    ALL_SLOTS,
    BACK,
    FRONT,
    hero_base_score,
    placement_mult,
)
from ks.heroes.optimize.front_survival import (
    rarity_median_powers,
    roster_median_power,
    sanitize_power,
)
from ks.heroes.optimize.gear_assign import assign_exclusive_sets
from ks.heroes.optimize.scoring import normalize_troop
from ks.heroes.optimize.types import CatalogEntry

GEAR_FRONT_FIRST = ("F1", "F2", "B2", "B1", "B3")


@dataclass(frozen=True)
class OpponentLineup:
    model: str
    formation: dict[str, str]
    heroes: tuple[str, ...]
    gear_assignment: dict[str, dict[str, GearRecord]]
    heuristic_offense: float

    def to_dict(self) -> dict[str, Any]:
        gear_out: dict[str, list[dict[str, Any]]] = {}
        for name, slots in self.gear_assignment.items():
            gear_out[name] = [
                {
                    "slot": slot,
                    "name": piece.name,
                    "rarity": piece.rarity,
                    "enhancement_level": piece.enhancement_level,
                    "piece_id": piece.piece_id,
                    "power": piece.power,
                }
                for slot, piece in slots.items()
            ]
        return {
            "model": self.model,
            "formation": dict(self.formation),
            "heroes": list(self.heroes),
            "heuristic_offense": self.heuristic_offense,
            "gear_assignment": gear_out,
        }


def _troop(
    name: str,
    heroes_by_name: dict[str, HeroRecord],
    catalog: dict[str, CatalogEntry],
) -> str:
    entry = catalog.get(name)
    if entry is not None:
        t = normalize_troop(entry.troop)
        if t:
            return t
    hero = heroes_by_name.get(name)
    if hero is not None:
        t = normalize_troop(hero.troop_type)
        if t:
            return t
    return "infantry"


def _place_infantry_first(
    names: list[str],
    heroes_by_name: dict[str, HeroRecord],
    catalog: dict[str, CatalogEntry],
    *,
    power_key: Callable[[str], float],
) -> dict[str, str]:
    """Fill F1/F2 with infantry first (by power), then remaining by power."""
    ordered = sorted(names, key=power_key, reverse=True)
    infantry = [n for n in ordered if _troop(n, heroes_by_name, catalog) == "infantry"]
    formation: dict[str, str] = {}
    used: set[str] = set()
    for slot in FRONT:
        pick = next((n for n in infantry if n not in used), None)
        if pick is None:
            pick = next((n for n in ordered if n not in used), None)
        if pick is None:
            break
        formation[slot] = pick
        used.add(pick)
    for slot in BACK:
        pick = next((n for n in ordered if n not in used), None)
        if pick is None:
            break
        formation[slot] = pick
        used.add(pick)
    return formation


def _assign_gear(
    formation: dict[str, str],
    heroes: list[HeroRecord],
    catalog: dict[str, CatalogEntry],
    gear: list[GearRecord] | None,
    *,
    profile: str,
) -> dict[str, dict[str, GearRecord]]:
    if not gear:
        return {formation[s]: {} for s in ALL_SLOTS if s in formation}
    selected = [formation[s] for s in ALL_SLOTS if s in formation]
    priority = [formation[s] for s in GEAR_FRONT_FIRST if s in formation]
    # Clone pool so foe and us do not strip each other.
    cloned = deepcopy(gear)
    return assign_exclusive_sets(
        heroes,
        catalog,
        cloned,
        selected=selected,
        priority=priority,
        profile=profile,
    )


def _sanitize_knobs(roles: dict[str, Any]) -> tuple[int, float]:
    cfg = roles.get("survival") or {}
    return (
        int(cfg.get("power_sanitize_max", 2_000_000)),
        float(cfg.get("power_sanitize_median_factor", 20.0)),
    )


def _gear_bonus_map(
    formation: dict[str, str],
    heroes: list[HeroRecord],
    catalog: dict[str, CatalogEntry],
    gear_asg: dict[str, dict[str, GearRecord]],
    *,
    profile: str,
) -> dict[str, float]:
    """ILP-style gear bonuses from the foe's *already assigned* pieces.

    Must not flatten pieces back into a pool and re-assign by roster power —
    that clobbers explicit exclusive assignments (Bugbot high).
    """
    del heroes, catalog  # assignment is authoritative; keep signature stable
    from ks.heroes.optimize.combat_formation import gear_bonus_from_assignment

    selected = [formation[s] for s in ALL_SLOTS if s in formation]
    scoped = {name: gear_asg.get(name, {}) for name in selected}
    return gear_bonus_from_assignment(scoped, profile=profile)


def _heuristic_offense(
    formation: dict[str, str],
    heroes_by_name: dict[str, HeroRecord],
    catalog: dict[str, CatalogEntry],
    roles: dict[str, Any],
    *,
    gear_bonus_by_hero: dict[str, float] | None = None,
    power_by_name: dict[str, float] | None = None,
    side: str = "attack",
    base_score_fn: Callable[..., float] | None = None,
) -> float:
    gear_bonus_by_hero = gear_bonus_by_hero or {}
    power_by_name = power_by_name or {}
    score_fn = base_score_fn or (
        lambda h, entry, roles, *, effective_power, gear_bonus: hero_base_score(
            h,
            entry,
            roles,
            effective_power=effective_power,
            gear_bonus=gear_bonus,
            side=side,
        )
    )
    total = 0.0
    for slot, name in formation.items():
        hero = heroes_by_name[name]
        entry = catalog.get(name)
        troop = _troop(name, heroes_by_name, catalog)
        eff_power = power_by_name.get(name)
        if eff_power is None:
            eff_power = float(hero.power) if hero.power else 0.0
        base = score_fn(
            hero,
            entry,
            roles,
            effective_power=int(round(eff_power)) if eff_power else hero.power,
            gear_bonus=float(gear_bonus_by_hero.get(name, 0.0)),
        )
        total += base * placement_mult(troop, slot, name, roles, side=side)
    return float(total)


def _sanitized_power_map(
    heroes: list[HeroRecord],
    roles: dict[str, Any],
) -> dict[str, float]:
    median = roster_median_power(heroes)
    max_abs, median_factor = _sanitize_knobs(roles)
    rarity_medians = rarity_median_powers(heroes, max_abs=max_abs)
    return {
        h.name: sanitize_power(
            h.power,
            median_power=median,
            rarity=h.rarity,
            rarity_medians=rarity_medians,
            max_abs=max_abs,
            median_factor=median_factor,
        )
        for h in heroes
    }


def build_naive_max_power(
    heroes: list[HeroRecord],
    catalog: dict[str, CatalogEntry],
    roles: dict[str, Any],
    *,
    gear: list[GearRecord] | None = None,
    gear_profile: str = "early_game_combat",
    n: int = 5,
    side: str = "attack",
    base_score_fn: Callable[..., float] | None = None,
) -> OpponentLineup:
    if n != 5:
        raise ValueError(f"opponent size must be 5; got {n}")
    usable = [h for h in heroes if h.name in catalog]
    if len(usable) < 5:
        raise ValueError(f"need >=5 catalog heroes; got {len(usable)}")
    by_name = {h.name: h for h in usable}
    power_map = _sanitized_power_map(usable, roles)

    def power_key(name: str) -> float:
        return power_map[name]

    ranked = sorted(by_name.keys(), key=power_key, reverse=True)[:5]
    formation = _place_infantry_first(ranked, by_name, catalog, power_key=power_key)
    gear_asg = _assign_gear(formation, usable, catalog, gear, profile=gear_profile)
    gear_bonus = _gear_bonus_map(
        formation, usable, catalog, gear_asg, profile=gear_profile
    )
    offense = _heuristic_offense(
        formation,
        by_name,
        catalog,
        roles,
        gear_bonus_by_hero=gear_bonus,
        power_by_name=power_map,
        side=side,
        base_score_fn=base_score_fn,
    )
    ordered = tuple(formation[s] for s in ALL_SLOTS)
    return OpponentLineup(
        model="naive_max_power",
        formation=formation,
        heroes=ordered,
        gear_assignment=gear_asg,
        heuristic_offense=offense,
    )


def build_troop_balanced_naive(
    heroes: list[HeroRecord],
    catalog: dict[str, CatalogEntry],
    roles: dict[str, Any],
    *,
    gear: list[GearRecord] | None = None,
    gear_profile: str = "early_game_combat",
    side: str = "attack",
    base_score_fn: Callable[..., float] | None = None,
) -> OpponentLineup:
    usable = [h for h in heroes if h.name in catalog]
    if len(usable) < 5:
        raise ValueError(f"need >=5 catalog heroes; got {len(usable)}")
    by_name = {h.name: h for h in usable}
    power_map = _sanitized_power_map(usable, roles)

    def power_key(name: str) -> float:
        return power_map[name]

    infantry = sorted(
        [h.name for h in usable if _troop(h.name, by_name, catalog) == "infantry"],
        key=power_key,
        reverse=True,
    )
    others = sorted(
        [h.name for h in usable if h.name not in infantry],
        key=power_key,
        reverse=True,
    )
    picked: list[str] = []
    for name in infantry[:2]:
        picked.append(name)
    for name in others:
        if len(picked) >= 5:
            break
        picked.append(name)
    # If fewer than 2 infantry, fill from global power.
    if len(picked) < 5:
        for name in sorted(by_name.keys(), key=power_key, reverse=True):
            if name not in picked:
                picked.append(name)
            if len(picked) >= 5:
                break
    formation = _place_infantry_first(picked[:5], by_name, catalog, power_key=power_key)
    gear_asg = _assign_gear(formation, usable, catalog, gear, profile=gear_profile)
    gear_bonus = _gear_bonus_map(
        formation, usable, catalog, gear_asg, profile=gear_profile
    )
    offense = _heuristic_offense(
        formation,
        by_name,
        catalog,
        roles,
        gear_bonus_by_hero=gear_bonus,
        power_by_name=power_map,
        side=side,
        base_score_fn=base_score_fn,
    )
    ordered = tuple(formation[s] for s in ALL_SLOTS)
    return OpponentLineup(
        model="troop_balanced_naive",
        formation=formation,
        heroes=ordered,
        gear_assignment=gear_asg,
        heuristic_offense=offense,
    )


def opponent_from_formation(
    model: str,
    formation: dict[str, str],
    heroes: list[HeroRecord],
    catalog: dict[str, CatalogEntry],
    roles: dict[str, Any],
    *,
    gear: list[GearRecord] | None = None,
    gear_profile: str = "early_game_combat",
    gear_assignment: dict[str, dict[str, GearRecord]] | None = None,
    side: str = "attack",
    base_score_fn: Callable[..., float] | None = None,
) -> OpponentLineup:
    by_name = {h.name: h for h in heroes if h.name in catalog}
    gear_asg = gear_assignment or _assign_gear(
        formation, list(by_name.values()), catalog, gear, profile=gear_profile
    )
    power_map = _sanitized_power_map(list(by_name.values()), roles)
    gear_bonus = _gear_bonus_map(
        formation, list(by_name.values()), catalog, gear_asg, profile=gear_profile
    )
    offense = _heuristic_offense(
        formation,
        by_name,
        catalog,
        roles,
        gear_bonus_by_hero=gear_bonus,
        power_by_name=power_map,
        side=side,
        base_score_fn=base_score_fn,
    )
    ordered = tuple(formation[s] for s in ALL_SLOTS if s in formation)
    return OpponentLineup(
        model=model,
        formation=dict(formation),
        heroes=ordered,
        gear_assignment=gear_asg,
        heuristic_offense=offense,
    )
