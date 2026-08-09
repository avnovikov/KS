"""Molten Fort single-march mystic-trial optimiser (governor-primary).

Uses ``governor.attack_pct`` / ``defense_pct`` only — those maps already include
set bonuses from ``governor_troop_bonuses()`` (see ``governor_attack_mult``).
Do not add ``set_attack_pct`` / ``set_defense_pct`` again.

Heroes are optional/light: best one-per-troop trio at 15% weight.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from ks.heroes.gear_models import GearRecord
from ks.heroes.governor_models import GovernorTroopBonuses
from ks.heroes.models import HeroRecord
from ks.heroes.optimize.bear_damage import blend_unit_stats
from ks.heroes.optimize.gear_assign import assign_exclusive_sets
from ks.heroes.optimize.mystic_trial.proxy import PROXY_BANNER, score_march
from ks.heroes.optimize.mystic_trial.ratios import (
    TROOP_TYPES,
    counts_for_ratio,
    ratio_candidates,
)
from ks.heroes.optimize.mystic_trial.rooms import load_room
from ks.heroes.optimize.scoring import normalize_troop
from ks.heroes.optimize.stat_contributions import EXPEDITION, hero_contribution
from ks.heroes.optimize.troop_stats import TroopStatsTable, TroopUnitStats
from ks.heroes.optimize.types import CatalogEntry, TroopsConfig

_DEFAULT_ROOM = (
    Path(__file__).resolve().parents[4] / "config" / "mystic_trial" / "molten_fort.yaml"
)

# Light hero contribution relative to governor-primary stack.
HERO_WEIGHT = 0.15


@dataclass(frozen=True)
class MarchResult:
    hero_names: tuple[str, ...]
    ratio: dict[str, float]
    counts: dict[str, int]
    capacity: int
    score: float
    breakdown: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "hero_names": list(self.hero_names),
            "ratio": dict(self.ratio),
            "counts": dict(self.counts),
            "capacity": self.capacity,
            "score": self.score,
            "breakdown": dict(self.breakdown),
        }


@dataclass(frozen=True)
class MoltenResult:
    marches: tuple[MarchResult, ...]
    lineup_score: float
    governor: dict[str, Any]
    room: str = "molten_fort"
    proxy_banner: str = PROXY_BANNER
    active_marches: int = 1
    schema_marches: int = 1
    engine: str = "proxy"

    def to_dict(self) -> dict[str, Any]:
        marches: list[dict[str, Any] | None] = [m.to_dict() for m in self.marches]
        while len(marches) < self.schema_marches:
            marches.append(None)
        return {
            "marches": marches,
            "lineup_score": self.lineup_score,
            "governor": dict(self.governor),
            "room": self.room,
            "proxy_banner": self.proxy_banner,
            "active_marches": self.active_marches,
            "schema_marches": self.schema_marches,
            "engine": self.engine,
        }


def _hero_troop(hero: HeroRecord, entry: CatalogEntry | None) -> str | None:
    if entry is not None:
        troop = normalize_troop(entry.troop)
        if troop:
            return troop
    return normalize_troop(hero.troop_type)


def _stat_points(contrib_stats: Mapping[str, Any], troop: str, suffix: str) -> float:
    prefix = {
        "infantry": "Infantry",
        "cavalry": "Cavalry",
        "archers": "Archer",
    }[troop]
    share = contrib_stats.get(f"{prefix} {suffix}")
    if share is None:
        return 0.0
    return float(share.total)


def _hero_rank(contrib: Any, troop: str) -> float:
    atk = _stat_points(contrib.stats, troop, "Attack")
    leth = _stat_points(contrib.stats, troop, "Lethality")
    defense = _stat_points(contrib.stats, troop, "Defense")
    hp = _stat_points(contrib.stats, troop, "Health")
    power = float(contrib.power.total)
    return 4.0 * atk + 3.0 * leth + 1.5 * defense + 1.5 * hp + power / 1_000_000.0


def _inventory_levels(troops: TroopsConfig) -> dict[str, dict[int, int]]:
    out: dict[str, dict[int, int]] = {}
    for typ in TROOP_TYPES:
        levels = troops.levels(typ)
        if levels:
            out[typ] = dict(levels)
        else:
            owned = troops.owned(typ)
            out[typ] = {6: owned} if owned > 0 else {}
    return out


def _blend_units(
    levels: Mapping[str, Mapping[int, int]],
    table: TroopStatsTable,
    *,
    truegold: int,
) -> dict[str, TroopUnitStats | None]:
    return {
        typ: blend_unit_stats(levels.get(typ) or {}, table, typ, truegold=truegold)
        for typ in TROOP_TYPES
    }


def _pick_march_heroes(
    pool: list[tuple[HeroRecord, str, float]],
) -> list[HeroRecord]:
    """Best one-per-troop trio (governor-primary; heroes optional/light)."""
    chosen: list[HeroRecord] = []
    used_troops: set[str] = set()
    for hero, troop, _rank in sorted(pool, key=lambda row: row[2], reverse=True):
        if troop in used_troops:
            continue
        chosen.append(hero)
        used_troops.add(troop)
        if len(chosen) == 3:
            break
    return chosen


def _lineup_troop_percents(
    heroes: Sequence[HeroRecord],
    catalog: Mapping[str, CatalogEntry],
    gear_by_hero: Mapping[str, Mapping[str, GearRecord]],
    *,
    hero_weight: float,
) -> tuple[dict[str, float], dict[str, float], dict[str, float], dict[str, float], dict[str, Any]]:
    atk = {t: 0.0 for t in TROOP_TYPES}
    defense = {t: 0.0 for t in TROOP_TYPES}
    leth = {t: 0.0 for t in TROOP_TYPES}
    hp = {t: 0.0 for t in TROOP_TYPES}
    shares: dict[str, Any] = {"heroes": {}, "hero_weight": hero_weight}
    for hero in heroes:
        entry = catalog.get(hero.name)
        troop = _hero_troop(hero, entry) or "infantry"
        contrib = hero_contribution(
            hero,
            entry,
            family=EXPEDITION,
            gear_pieces=gear_by_hero.get(hero.name),
        )
        raw_atk = _stat_points(contrib.stats, troop, "Attack")
        raw_def = _stat_points(contrib.stats, troop, "Defense")
        raw_leth = _stat_points(contrib.stats, troop, "Lethality")
        raw_hp = _stat_points(contrib.stats, troop, "Health")
        atk[troop] += hero_weight * raw_atk
        defense[troop] += hero_weight * raw_def
        leth[troop] += hero_weight * raw_leth
        hp[troop] += hero_weight * raw_hp
        shares["heroes"][hero.name] = {
            "troop": troop,
            "attack": hero_weight * raw_atk,
            "defense": hero_weight * raw_def,
            "lethality": hero_weight * raw_leth,
            "health": hero_weight * raw_hp,
            "rank": _hero_rank(contrib, troop),
        }
    return atk, defense, leth, hp, shares


def optimize_molten(
    heroes: Sequence[HeroRecord],
    catalog: Mapping[str, CatalogEntry],
    *,
    gear_pieces: Sequence[GearRecord],
    governor: GovernorTroopBonuses,
    troops: TroopsConfig,
    troop_stats: TroopStatsTable,
    truegold: int | None = None,
    hero_weight: float = HERO_WEIGHT,
    room_path: Path | str | None = None,
) -> MoltenResult:
    """Single-march Molten Fort: governor Atk%/Def% primary; light hero stack."""
    if hero_weight < 0:
        raise ValueError(f"hero_weight must be >= 0; got {hero_weight}")

    room = load_room(room_path or _DEFAULT_ROOM)
    tg = troop_stats.default_truegold if truegold is None else int(truegold)
    levels = _inventory_levels(troops)
    units = _blend_units(levels, troop_stats, truegold=tg)
    owned = {t: troops.owned(t) for t in TROOP_TYPES}

    ranked: list[tuple[HeroRecord, str, float]] = []
    for hero in heroes:
        if hero.name not in catalog:
            continue
        entry = catalog[hero.name]
        troop = _hero_troop(hero, entry)
        if troop is None:
            continue
        contrib = hero_contribution(hero, entry, family=EXPEDITION, gear_pieces=None)
        ranked.append((hero, troop, _hero_rank(contrib, troop)))
    ranked.sort(key=lambda row: row[2], reverse=True)

    pick = _pick_march_heroes(ranked)
    hero_atk = {t: 0.0 for t in TROOP_TYPES}
    hero_def = {t: 0.0 for t in TROOP_TYPES}
    hero_leth = {t: 0.0 for t in TROOP_TYPES}
    hero_hp = {t: 0.0 for t in TROOP_TYPES}
    hero_shares: dict[str, Any] = {"heroes": {}, "hero_weight": hero_weight}
    hero_names: tuple[str, ...] = ()
    escorts = 0

    if len(pick) >= 3 and hero_weight > 0:
        pick_names = [h.name for h in pick]
        gear_by_hero = assign_exclusive_sets(
            list(heroes),
            dict(catalog),
            list(gear_pieces),
            selected=pick_names,
            priority=pick_names,
            profile="early_game_growth",
        )
        hero_atk, hero_def, hero_leth, hero_hp, hero_shares = _lineup_troop_percents(
            pick, catalog, gear_by_hero, hero_weight=hero_weight
        )
        hero_names = tuple(h.name for h in pick)
        escorts = sum(int(h.escorts or 0) for h in pick)
    elif pick:
        # Partial trio still names heroes for UI; no % contribution without 3.
        hero_names = tuple(h.name for h in pick)
        escorts = sum(int(h.escorts or 0) for h in pick)

    # Governor maps already include set bonuses — do not add set_* again.
    atk_pct = {
        t: hero_atk[t] + float(governor.attack_pct.get(t, 0.0)) for t in TROOP_TYPES
    }
    def_pct = {
        t: hero_def[t] + float(governor.defense_pct.get(t, 0.0)) for t in TROOP_TYPES
    }

    capacity = troops.march_capacity + escorts
    fill_cap = min(capacity, sum(owned.values()))

    best: MarchResult | None = None
    for ratio in ratio_candidates(published=room.published_ratios):
        counts = counts_for_ratio(ratio, fill_cap, owned)
        scored = score_march(
            counts,
            units,
            atk_pct=atk_pct,
            def_pct=def_pct,
            leth_pct=hero_leth,
            hp_pct=hero_hp,
        )
        breakdown: dict[str, Any] = {
            "proxy": scored.to_dict(),
            "atk_pct": dict(atk_pct),
            "def_pct": dict(def_pct),
            "leth_pct": dict(hero_leth),
            "hp_pct": dict(hero_hp),
            "hero_shares": hero_shares,
            "hero_weight": hero_weight,
            "governor_attack_pct": dict(governor.attack_pct),
            "governor_defense_pct": dict(governor.defense_pct),
            "set_attack_pct_reported": governor.set_attack_pct,
            "set_defense_pct_reported": governor.set_defense_pct,
            "note": "set bonuses counted only via attack_pct/defense_pct maps",
        }
        candidate = MarchResult(
            hero_names=hero_names,
            ratio=dict(ratio),
            counts=dict(counts),
            capacity=capacity,
            score=scored.score,
            breakdown=breakdown,
        )
        if best is None or candidate.score > best.score:
            best = candidate
    assert best is not None

    return MoltenResult(
        marches=(best,),
        lineup_score=best.score,
        governor=governor.to_dict(),
        room=room.id,
        active_marches=room.active_marches,
        schema_marches=room.schema_marches,
        engine="proxy",
    )


__all__ = [
    "HERO_WEIGHT",
    "MarchResult",
    "MoltenResult",
    "optimize_molten",
]
