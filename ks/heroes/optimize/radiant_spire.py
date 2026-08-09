"""Radiant Spire dual-march proxy optimiser (foundational score).

Proxy is tunable, not game-authoritative — see design spec.
Floor stubs / MC: mystic_trial floors + combat_mc (GitHub #37 / #38).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ks.heroes.gear_models import GearRecord
from ks.heroes.governor_models import GovernorTroopBonuses
from ks.heroes.models import HeroRecord
from ks.heroes.optimize.bear_damage import blend_unit_stats
from ks.heroes.optimize.gear_assign import assign_exclusive_sets
from ks.heroes.optimize.mystic_trial.floors import FloorStub
from ks.heroes.optimize.mystic_trial.proxy import (
    PROXY_BANNER,
    MarchScore,
    score_march,
)
from ks.heroes.optimize.mystic_trial.ratios import (
    TROOP_TYPES,
    counts_for_ratio,
    normalize_ratio,
    ratio_candidates,
)
from ks.heroes.optimize.scoring import normalize_troop
from ks.heroes.optimize.stat_contributions import (
    EXPEDITION,
    hero_contribution,
)
from ks.heroes.optimize.troop_stats import TroopStatsTable, TroopUnitStats
from ks.heroes.optimize.types import CatalogEntry, TroopsConfig

# Radiant seed kept for callers / tests that import SEED_RATIO.
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

# Back-compat alias used by older imports.
_normalize_ratio = normalize_ratio


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
    floor: dict[str, Any] | None = None
    opponent: dict[str, Any] | None = None
    engine: str = "proxy"
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        marches: list[dict[str, Any] | None] = [m.to_dict() for m in self.marches]
        while len(marches) < self.schema_marches:
            marches.append(None)
        out: dict[str, Any] = {
            "marches": marches,
            "lineup_score": self.lineup_score,
            "governor": dict(self.governor),
            "proxy_banner": self.proxy_banner,
            "active_marches": self.active_marches,
            "schema_marches": self.schema_marches,
            "engine": self.engine,
        }
        if self.floor is not None:
            out["floor"] = dict(self.floor)
        if self.opponent is not None:
            out["opponent"] = dict(self.opponent)
        if self.warnings:
            out["warnings"] = list(self.warnings)
        return out


def build_opponent_panel(
    player_marches: Sequence[MarchResult],
    stub: FloorStub,
) -> dict[str, Any]:
    """Two AI marches with stub ratio/counts and battle-report bonuses (display)."""
    bonuses = {t: dict(stub.enemy_bonuses.get(t, {})) for t in TROOP_TYPES}
    opp_marches: list[dict[str, Any]] = []
    for march in player_marches:
        filled = sum(int(march.counts.get(t, 0)) for t in TROOP_TYPES)
        # Unlimited owned so ratio fills exactly to the mirrored march size.
        owned = {t: filled for t in TROOP_TYPES}
        counts = (
            counts_for_ratio(stub.enemy_ratio, filled, owned)
            if filled > 0
            else {t: 0 for t in TROOP_TYPES}
        )
        opp_marches.append(
            {
                "hero_names": ["AI", "AI", "AI"],
                "ratio": dict(stub.enemy_ratio),
                "counts": dict(counts),
                "capacity": int(march.capacity),
                "bonuses": {t: dict(bonuses[t]) for t in TROOP_TYPES},
            }
        )
    return {
        "marches": opp_marches,
        "bonuses": bonuses,
        "note": "Bonuses from battle report / opponent screen (YAML); display only.",
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
    floor: int | None = None,
    floors_path: Path | str | None = None,
    enemy_ratio: Mapping[str, float] | None = None,
    enemy_bonuses: Mapping[str, Mapping[str, float]] | None = None,
) -> RadiantResult:
    """Assign exclusive hero marches and search troop ratios via proxy score."""
    from pathlib import Path as _Path

    from ks.heroes.optimize.mystic_trial.floors import get_floor, load_floors

    if active_marches not in (1, 2, 3):
        raise ValueError(f"active_marches must be 1–3; got {active_marches}")
    if (enemy_ratio is not None or enemy_bonuses is not None) and floor is None:
        raise ValueError("enemy_ratio / enemy_bonuses overrides require floor=")

    warnings: list[str] = []
    floor_payload: dict[str, Any] | None = None
    floor_stub = None
    if floor is not None:
        path = (
            _Path(floors_path)
            if floors_path is not None
            else _Path(__file__).resolve().parents[3]
            / "config"
            / "mystic_trial"
            / "radiant_spire_floors.yaml"
        )
        stubs = load_floors(path)
        floor_stub = get_floor(stubs, int(floor))
        if floor_stub is None:
            warnings.append(
                f"unknown Radiant floor {floor}; using proxy without floor stub"
            )
        else:
            if enemy_ratio is not None or enemy_bonuses is not None:
                floor_stub = floor_stub.with_overrides(
                    enemy_ratio=enemy_ratio,
                    enemy_bonuses=enemy_bonuses,
                )
            floor_payload = floor_stub.to_dict()
            if enemy_ratio is not None or enemy_bonuses is not None:
                floor_payload["overrides_applied"] = True

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
        best_key: float | None = None
        for ratio in ratio_candidates(published=PUBLISHED_RATIOS):
            counts = counts_for_ratio(ratio, fill_cap, remaining_owned)
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
                "governor_attack_pct": dict(governor.attack_pct),
                "governor_defense_pct": dict(governor.defense_pct),
                "set_attack_pct": governor.set_attack_pct,
                "set_defense_pct": governor.set_defense_pct,
            }
            rank_key = scored.score
            if floor_stub is not None:
                from ks.heroes.optimize.mystic_trial.combat_mc import simulate_floor

                mc = simulate_floor(scored, floor_stub)
                breakdown["mc"] = mc.to_dict()
                rank_key = mc.win_rate
            candidate = MarchResult(
                hero_names=tuple(h.name for h in pick),
                ratio=dict(ratio),
                counts=dict(counts),
                capacity=capacity,
                score=scored.score if floor_stub is None else rank_key,
                breakdown=breakdown,
            )
            if best is None or best_key is None or rank_key > best_key:
                best = candidate
                best_key = rank_key
        assert best is not None
        for t in TROOP_TYPES:
            remaining_owned[t] = max(0, remaining_owned[t] - best.counts[t])
        marches.append(best)

    engine = "mc" if floor_stub is not None else "proxy"
    opponent = (
        build_opponent_panel(marches, floor_stub) if floor_stub is not None else None
    )
    return RadiantResult(
        marches=tuple(marches),
        lineup_score=sum(m.score for m in marches),
        governor=governor.to_dict(),
        active_marches=active_marches,
        floor=floor_payload,
        opponent=opponent,
        engine=engine,
        warnings=tuple(warnings),
    )


__all__ = [
    "PROXY_BANNER",
    "PUBLISHED_RATIOS",
    "SEED_RATIO",
    "TROOP_TYPES",
    "MarchResult",
    "MarchScore",
    "RadiantResult",
    "build_opponent_panel",
    "counts_for_ratio",
    "optimize_radiant",
    "ratio_candidates",
    "score_march",
]
