"""Radiant Spire dual-march proxy optimiser (foundational score).

Proxy is tunable, not game-authoritative — see design spec.
Monte Carlo / floor stubs are deferred (GitHub #37 / #38).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ks.heroes.gear_models import GearRecord
from ks.heroes.governor_models import GovernorTroopBonuses
from ks.heroes.models import HeroRecord
from ks.heroes.optimize.bear_damage import blend_unit_stats
from ks.heroes.optimize.gear_assign import assign_exclusive_sets
from ks.heroes.optimize.scoring import normalize_troop
from ks.heroes.optimize.stat_contributions import (
    EXPEDITION,
    hero_contribution,
)
from ks.heroes.optimize.troop_stats import TroopStatsTable, TroopUnitStats
from ks.heroes.optimize.types import CatalogEntry, TroopsConfig

TROOP_TYPES: tuple[str, ...] = ("infantry", "cavalry", "archers")
PROXY_BANNER = "Proxy score — not in-game clear prediction."
SEED_RATIO: dict[str, float] = {
    "infantry": 0.50,
    "cavalry": 0.15,
    "archers": 0.35,
}
PUBLISHED_RATIOS: tuple[dict[str, float], ...] = (
    SEED_RATIO,
    {"infantry": 0.55, "cavalry": 0.10, "archers": 0.35},
    {"infantry": 0.60, "cavalry": 0.10, "archers": 0.30},
    {"infantry": 0.50, "cavalry": 0.10, "archers": 0.40},
    {"infantry": 0.50, "cavalry": 0.20, "archers": 0.30},
    {"infantry": 1 / 3, "cavalry": 1 / 3, "archers": 1 / 3},
)


@dataclass(frozen=True)
class MarchScore:
    score: float
    offense_sum: float
    tough_sum: float
    by_type: dict[str, dict[str, float]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "offense_sum": self.offense_sum,
            "tough_sum": self.tough_sum,
            "by_type": {k: dict(v) for k, v in self.by_type.items()},
        }


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
class RadiantResult:
    marches: tuple[MarchResult, ...]
    lineup_score: float
    governor: dict[str, Any]
    proxy_banner: str = PROXY_BANNER
    active_marches: int = 2
    schema_marches: int = 3

    def to_dict(self) -> dict[str, Any]:
        marches: list[dict[str, Any] | None] = [m.to_dict() for m in self.marches]
        while len(marches) < self.schema_marches:
            marches.append(None)
        return {
            "marches": marches,
            "lineup_score": self.lineup_score,
            "governor": dict(self.governor),
            "proxy_banner": self.proxy_banner,
            "active_marches": self.active_marches,
            "schema_marches": self.schema_marches,
        }


def _normalize_ratio(raw: Mapping[str, float]) -> dict[str, float]:
    vals = {t: max(0.0, float(raw.get(t, 0.0))) for t in TROOP_TYPES}
    total = sum(vals.values())
    if total <= 0:
        raise ValueError(f"ratio must have positive mass; got {dict(raw)}")
    return {t: vals[t] / total for t in TROOP_TYPES}


def ratio_candidates(*, step: float = 0.05) -> list[dict[str, float]]:
    """Seed + published alternates + ±step grid on two axes (third residual)."""
    seen: set[tuple[float, float, float]] = set()
    out: list[dict[str, float]] = []

    def add(raw: Mapping[str, float]) -> None:
        r = _normalize_ratio(raw)
        key = (round(r["infantry"], 6), round(r["cavalry"], 6), round(r["archers"], 6))
        if key in seen:
            return
        seen.add(key)
        out.append(r)

    for pub in PUBLISHED_RATIOS:
        add(pub)

    # Grid: infantry and cavalry in [0, 1] by step; archers = residual.
    n = int(round(1.0 / step))
    for i in range(n + 1):
        for c in range(n + 1 - i):
            inf = i * step
            cav = c * step
            arch = 1.0 - inf - cav
            if arch < -1e-9:
                continue
            add({"infantry": inf, "cavalry": cav, "archers": max(0.0, arch)})
    return out


def counts_for_ratio(
    ratio: Mapping[str, float],
    capacity: int,
    owned: Mapping[str, int],
) -> dict[str, int]:
    """Largest-remainder allocation, capped by owned inventory."""
    if capacity < 0:
        raise ValueError(f"capacity must be >= 0; got {capacity}")
    r = _normalize_ratio(ratio)
    soft_cap = min(
        int(capacity),
        sum(max(0, int(owned.get(t, 0))) for t in TROOP_TYPES),
    )
    if soft_cap == 0:
        return {t: 0 for t in TROOP_TYPES}

    exact = {t: r[t] * soft_cap for t in TROOP_TYPES}
    floors = {t: int(math.floor(exact[t])) for t in TROOP_TYPES}
    for t in TROOP_TYPES:
        floors[t] = min(floors[t], max(0, int(owned.get(t, 0))))
    rem = soft_cap - sum(floors.values())
    order = sorted(
        TROOP_TYPES,
        key=lambda t: (exact[t] - math.floor(exact[t]), r[t]),
        reverse=True,
    )
    for t in order:
        if rem <= 0:
            break
        room = max(0, int(owned.get(t, 0)) - floors[t])
        take = min(room, rem)
        floors[t] += take
        rem -= take
    # If inventory blocked remainder, leave unused capacity (honest fill).
    return floors


def score_march(
    counts: Mapping[str, int],
    units: Mapping[str, TroopUnitStats | None],
    *,
    atk_pct: Mapping[str, float],
    def_pct: Mapping[str, float],
    leth_pct: Mapping[str, float],
    hp_pct: Mapping[str, float],
) -> MarchScore:
    """Geometric-mean proxy √(Σoffense × Σtough) from the design spec."""
    offense_sum = 0.0
    tough_sum = 0.0
    by_type: dict[str, dict[str, float]] = {}
    for troop in TROOP_TYPES:
        n = int(counts.get(troop, 0) or 0)
        unit = units.get(troop)
        if n <= 0 or unit is None:
            by_type[troop] = {"n": float(n), "offense": 0.0, "tough": 0.0}
            continue
        atk_m = 1.0 + float(atk_pct.get(troop, 0.0)) / 100.0
        def_m = 1.0 + float(def_pct.get(troop, 0.0)) / 100.0
        leth_m = 1.0 + float(leth_pct.get(troop, 0.0)) / 100.0
        hp_m = 1.0 + float(hp_pct.get(troop, 0.0)) / 100.0
        offense = n * unit.attack * atk_m * (unit.lethality / 100.0) * leth_m
        tough = n * unit.defense * def_m * unit.health * hp_m
        by_type[troop] = {"n": float(n), "offense": offense, "tough": tough}
        offense_sum += offense
        tough_sum += tough
    score = math.sqrt(max(0.0, offense_sum) * max(0.0, tough_sum))
    return MarchScore(
        score=score,
        offense_sum=offense_sum,
        tough_sum=tough_sum,
        by_type=by_type,
    )


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


def _radiant_rank(contrib: Any, troop: str) -> float:
    """Attack+Lethality primary, Defense+Health secondary."""
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
    """Greedy: take best remaining hero per troop type (or top 3)."""
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
            "rank": _radiant_rank(contrib, troop),
        }
    return atk, defense, leth, hp, shares


def optimize_radiant(
    heroes: Sequence[HeroRecord],
    catalog: Mapping[str, CatalogEntry],
    *,
    gear_pieces: Sequence[GearRecord],
    governor: GovernorTroopBonuses,
    troops: TroopsConfig,
    troop_stats: TroopStatsTable,
    active_marches: int = 2,
    truegold: int | None = None,
    one_per_troop_type: bool = True,
) -> RadiantResult:
    """Assign exclusive hero marches and search troop ratios via proxy score."""
    if active_marches not in (1, 2, 3):
        raise ValueError(f"active_marches must be 1–3; got {active_marches}")

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
        # Provisional rank without exclusive gear (gear assigned after lineup pick).
        contrib = hero_contribution(hero, entry, family=EXPEDITION, gear_pieces=None)
        ranked.append((hero, troop, _radiant_rank(contrib, troop)))
    ranked.sort(key=lambda row: row[2], reverse=True)

    remaining = list(ranked)
    marches: list[MarchResult] = []
    remaining_owned = dict(owned)

    for _ in range(active_marches):
        pick = _pick_march_heroes(remaining, one_per_troop_type=one_per_troop_type)
        if len(pick) < 3:
            break
        pick_names = [h.name for h in pick]
        remaining = [(h, t, r) for h, t, r in remaining if h.name not in pick_names]

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
        atk_pct = {
            t: hero_atk[t]
            + float(governor.attack_pct.get(t, 0.0))
            + float(governor.set_attack_pct)
            for t in TROOP_TYPES
        }
        def_pct = {
            t: hero_def[t]
            + float(governor.defense_pct.get(t, 0.0))
            + float(governor.set_defense_pct)
            for t in TROOP_TYPES
        }

        escorts = sum(int(h.escorts or 0) for h in pick)
        capacity = troops.march_capacity + escorts
        fill_cap = min(capacity, sum(remaining_owned.values()))

        best: MarchResult | None = None
        for ratio in ratio_candidates():
            counts = counts_for_ratio(ratio, fill_cap, remaining_owned)
            scored = score_march(
                counts,
                units,
                atk_pct=atk_pct,
                def_pct=def_pct,
                leth_pct=hero_leth,
                hp_pct=hero_hp,
            )
            candidate = MarchResult(
                hero_names=tuple(h.name for h in pick),
                ratio=dict(ratio),
                counts=dict(counts),
                capacity=capacity,
                score=scored.score,
                breakdown={
                    "proxy": scored.to_dict(),
                    "atk_pct": dict(atk_pct),
                    "def_pct": dict(def_pct),
                    "leth_pct": dict(hero_leth),
                    "hp_pct": dict(hero_hp),
                    "hero_shares": hero_shares,
                    "governor_attack_pct": dict(governor.attack_pct),
                    "governor_defense_pct": dict(governor.defense_pct),
                    "set_attack_pct": governor.set_attack_pct,
                    "set_defense_pct": governor.set_defense_pct,
                },
            )
            if best is None or candidate.score > best.score:
                best = candidate
        assert best is not None
        for t in TROOP_TYPES:
            remaining_owned[t] = max(0, remaining_owned[t] - best.counts[t])
        marches.append(best)

    return RadiantResult(
        marches=tuple(marches),
        lineup_score=sum(m.score for m in marches),
        governor=governor.to_dict(),
        active_marches=active_marches,
    )
