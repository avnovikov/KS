"""Coliseum single-march mystic-trial optimiser (heroes + gear primary).

Governor Atk%/Def% weight is 0 by default — do not stack governor percents into
the proxy. Proxy is tunable, not game-authoritative.
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
    Path(__file__).resolve().parents[4] / "config" / "mystic_trial" / "coliseum.yaml"
)


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
class ColiseumResult:
    marches: tuple[MarchResult, ...]
    lineup_score: float
    governor: dict[str, Any]
    room: str = "coliseum"
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


def _coliseum_rank(contrib: Any, troop: str) -> float:
    """Attack+Lethality primary, Defense+Health secondary (mirrors Radiant)."""
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
    *,
    one_per_troop_type: bool = True,
) -> list[HeroRecord]:
    if not one_per_troop_type:
        return [h for h, _t, _r in sorted(pool, key=lambda row: row[2], reverse=True)[:3]]
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
) -> tuple[dict[str, float], dict[str, float], dict[str, float], dict[str, float], dict[str, Any]]:
    atk = {t: 0.0 for t in TROOP_TYPES}
    defense = {t: 0.0 for t in TROOP_TYPES}
    leth = {t: 0.0 for t in TROOP_TYPES}
    hp = {t: 0.0 for t in TROOP_TYPES}
    shares: dict[str, Any] = {"heroes": {}}
    for hero in heroes:
        entry = catalog.get(hero.name)
        troop = _hero_troop(hero, entry) or "infantry"
        contrib = hero_contribution(
            hero,
            entry,
            family=EXPEDITION,
            gear_pieces=gear_by_hero.get(hero.name),
        )
        atk[troop] += _stat_points(contrib.stats, troop, "Attack")
        defense[troop] += _stat_points(contrib.stats, troop, "Defense")
        leth[troop] += _stat_points(contrib.stats, troop, "Lethality")
        hp[troop] += _stat_points(contrib.stats, troop, "Health")
        shares["heroes"][hero.name] = {
            "troop": troop,
            "attack": _stat_points(contrib.stats, troop, "Attack"),
            "defense": _stat_points(contrib.stats, troop, "Defense"),
            "lethality": _stat_points(contrib.stats, troop, "Lethality"),
            "health": _stat_points(contrib.stats, troop, "Health"),
            "rank": _coliseum_rank(contrib, troop),
        }
    return atk, defense, leth, hp, shares


def optimize_coliseum(
    heroes: Sequence[HeroRecord],
    catalog: Mapping[str, CatalogEntry],
    *,
    gear_pieces: Sequence[GearRecord],
    governor: GovernorTroopBonuses,
    troops: TroopsConfig,
    troop_stats: TroopStatsTable,
    truegold: int | None = None,
    one_per_troop_type: bool = True,
    governor_weight: float = 0.0,
    room_path: Path | str | None = None,
) -> ColiseumResult:
    """Single-march Coliseum: hero expedition + gear; governor off by default."""
    if governor_weight < 0:
        raise ValueError(f"governor_weight must be >= 0; got {governor_weight}")

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
        ranked.append((hero, troop, _coliseum_rank(contrib, troop)))
    ranked.sort(key=lambda row: row[2], reverse=True)

    pick = _pick_march_heroes(ranked, one_per_troop_type=one_per_troop_type)
    marches: list[MarchResult] = []
    if len(pick) >= 3:
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
            pick, catalog, gear_by_hero
        )
        # Governor weight 0 by default — heroes/gear only.
        atk_pct = {
            t: hero_atk[t]
            + governor_weight * float(governor.attack_pct.get(t, 0.0))
            for t in TROOP_TYPES
        }
        def_pct = {
            t: hero_def[t]
            + governor_weight * float(governor.defense_pct.get(t, 0.0))
            for t in TROOP_TYPES
        }

        escorts = sum(int(h.escorts or 0) for h in pick)
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
                "governor_weight": governor_weight,
                "governor_attack_pct": dict(governor.attack_pct),
                "governor_defense_pct": dict(governor.defense_pct),
            }
            candidate = MarchResult(
                hero_names=tuple(h.name for h in pick),
                ratio=dict(ratio),
                counts=dict(counts),
                capacity=capacity,
                score=scored.score,
                breakdown=breakdown,
            )
            if best is None or candidate.score > best.score:
                best = candidate
        assert best is not None
        marches.append(best)

    return ColiseumResult(
        marches=tuple(marches),
        lineup_score=sum(m.score for m in marches),
        governor=governor.to_dict(),
        room=room.id,
        active_marches=room.active_marches,
        schema_marches=room.schema_marches,
        engine="proxy",
    )


__all__ = [
    "ColiseumResult",
    "MarchResult",
    "optimize_coliseum",
]
