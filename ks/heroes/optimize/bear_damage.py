"""Bear Trap 10-round damage simulator (community formula)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import yaml

from ks.heroes.optimize.troop_stats import TroopStatsTable, TroopUnitStats

BEAR_COUNT = 5000
BEAR_DEFENSE = 83.3333 * 10.0 / 100.0  # 8.33333
ARCHER_RANGED_STRIKE = 1.10
ROUNDS = 10
TRAP_ATTACK_PER_LEVEL = 0.05


@dataclass(frozen=True)
class TypeDamage:
    count: int
    attack_per_troop: float
    army: float
    round_damage: float


@dataclass(frozen=True)
class BearDamageResult:
    score: int
    round_damage_total: float
    skillmod: float
    trap_attack_bonus: float
    by_type: dict[str, TypeDamage]

    def breakdown(self) -> dict[str, float]:
        out: dict[str, float] = {
            "bear_damage": float(self.score),
            "round_damage": float(self.round_damage_total),
            "skillmod": float(self.skillmod),
            "trap_attack_bonus": float(self.trap_attack_bonus),
        }
        for typ, row in self.by_type.items():
            out[f"{typ}_count"] = float(row.count)
            out[f"{typ}_army"] = float(row.army)
            out[f"{typ}_round_damage"] = float(row.round_damage)
            out[f"{typ}_attack_per_troop"] = float(row.attack_per_troop)
        return out


@dataclass(frozen=True)
class BeartrapBuffs:
    trap_level: int = 5
    host_attack_pct: float = 0.0
    base_skillmod: float = 5.08
    joiner_skillmod: float = 1.0
    hero_strength_scale: float = 0.0
    # Calibration metadata (documentation only)
    calibration_score: int = 180_000
    calibration_march: int = 80_245

    @property
    def trap_attack_bonus(self) -> float:
        level = max(0, int(self.trap_level))
        return TRAP_ATTACK_PER_LEVEL * level

    def effective_skillmod(self, lineup_hero_strength: float = 0.0) -> float:
        hero_factor = 1.0 + float(self.hero_strength_scale) * float(lineup_hero_strength)
        assert hero_factor > 0, f"hero_factor must be positive; got {hero_factor}"
        sm = (
            float(self.base_skillmod)
            * float(self.joiner_skillmod)
            * hero_factor
        )
        assert sm > 0, f"skillmod must be positive; got {sm}"
        return sm


def load_beartrap_buffs(path: Path | str) -> BeartrapBuffs:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("beartrap_buffs.yaml must be a mapping")
    return BeartrapBuffs(
        trap_level=int(raw.get("trap_level", 5)),
        host_attack_pct=float(raw.get("host_attack_pct", 0.0)),
        base_skillmod=float(raw.get("base_skillmod", 5.08)),
        joiner_skillmod=float(raw.get("joiner_skillmod", 1.0)),
        hero_strength_scale=float(raw.get("hero_strength_scale", 0.0)),
        calibration_score=int(raw.get("calibration_score", 180_000)),
        calibration_march=int(raw.get("calibration_march", 80_245)),
    )


def attack_per_troop(
    unit: TroopUnitStats,
    *,
    trap_attack_bonus: float,
    skillmod: float,
    host_attack_pct: float = 0.0,
) -> float:
    assert skillmod > 0, f"skillmod must be positive; got {skillmod}"
    assert trap_attack_bonus >= 0, f"trap_attack_bonus must be >= 0; got {trap_attack_bonus}"
    return (
        float(unit.attack)
        * (1.0 + float(trap_attack_bonus))
        * (float(unit.lethality) / 100.0)
        * float(skillmod)
        * (1.0 + float(host_attack_pct))
    )


def simulate(
    counts: Mapping[str, int],
    attack_by_type: Mapping[str, float],
    *,
    skillmod: float = 1.0,
    trap_attack_bonus: float = 0.25,
    host_attack_pct: float = 0.0,
) -> BearDamageResult:
    """
    Simulate constant 10-round bear damage.

    ``attack_by_type`` is *base* attack (before trap / skillmod / host %), typically
    from troop_stats. Lethality is assumed already baked as 10 in community tables
    via attack_per_troop when building from TroopUnitStats — here we accept precomputed
    base attack and apply lethality=10 unless ``attack_by_type`` values are already
    full attack_per_troop with skillmod=1 and trap applied.

    Preferred path: pass base attack from stats; this function applies trap, lethality 10,
    skillmod, and host attack %.
    """
    if skillmod <= 0:
        raise ValueError(f"skillmod must be positive; got {skillmod}")
    if trap_attack_bonus < 0:
        raise ValueError(f"trap_attack_bonus must be >= 0; got {trap_attack_bonus}")

    by_type: dict[str, TypeDamage] = {}
    round_total = 0.0
    for typ in ("infantry", "cavalry", "archers"):
        n = int(counts.get(typ, 0) or 0)
        if n < 0:
            raise ValueError(f"{typ} count must be >= 0; got {n}")
        base_atk = float(attack_by_type.get(typ, 0.0) or 0.0)
        # Community formula: attack_per_troop = base × (1+trap) × lethality/100 × skillmod
        # Base stats use lethality=10.
        atk = (
            base_atk
            * (1.0 + trap_attack_bonus)
            * (10.0 / 100.0)
            * skillmod
            * (1.0 + host_attack_pct)
        )
        army = math.sqrt(n * BEAR_COUNT) if n > 0 else 0.0
        dmg = (army * atk / BEAR_DEFENSE / 100.0) if n > 0 else 0.0
        if typ == "archers":
            dmg *= ARCHER_RANGED_STRIKE
        by_type[typ] = TypeDamage(
            count=n,
            attack_per_troop=atk,
            army=army,
            round_damage=dmg,
        )
        round_total += dmg

    score = int(math.ceil(round_total * ROUNDS)) if round_total > 0 else 0
    return BearDamageResult(
        score=score,
        round_damage_total=round_total,
        skillmod=skillmod,
        trap_attack_bonus=trap_attack_bonus,
        by_type=by_type,
    )


def simulate_from_units(
    units_by_type: Mapping[str, TroopUnitStats | None],
    counts: Mapping[str, int],
    *,
    skillmod: float = 1.0,
    trap_attack_bonus: float = 0.25,
    host_attack_pct: float = 0.0,
) -> BearDamageResult:
    """Simulate using full TroopUnitStats (attack + lethality from table)."""
    if skillmod <= 0:
        raise ValueError(f"skillmod must be positive; got {skillmod}")

    by_type: dict[str, TypeDamage] = {}
    round_total = 0.0
    for typ in ("infantry", "cavalry", "archers"):
        n = int(counts.get(typ, 0) or 0)
        if n < 0:
            raise ValueError(f"{typ} count must be >= 0; got {n}")
        unit = units_by_type.get(typ)
        if n == 0 or unit is None:
            by_type[typ] = TypeDamage(0, 0.0, 0.0, 0.0)
            continue
        atk = attack_per_troop(
            unit,
            trap_attack_bonus=trap_attack_bonus,
            skillmod=skillmod,
            host_attack_pct=host_attack_pct,
        )
        army = math.sqrt(n * BEAR_COUNT)
        dmg = army * atk / BEAR_DEFENSE / 100.0
        if typ == "archers":
            dmg *= ARCHER_RANGED_STRIKE
        by_type[typ] = TypeDamage(n, atk, army, dmg)
        round_total += dmg

    score = int(math.ceil(round_total * ROUNDS)) if round_total > 0 else 0
    return BearDamageResult(
        score=score,
        round_damage_total=round_total,
        skillmod=skillmod,
        trap_attack_bonus=trap_attack_bonus,
        by_type=by_type,
    )


def blend_unit_stats(
    levels: Mapping[int, int],
    table: TroopStatsTable,
    troop_type: str,
    *,
    truegold: int = 0,
) -> TroopUnitStats | None:
    """Weighted-average unit stats for a type's tier mix (count-weighted)."""
    total = sum(int(c) for c in levels.values() if int(c) > 0)
    if total <= 0:
        return None
    atk = leth = hp = defense = 0.0
    for tier, count in levels.items():
        n = int(count)
        if n <= 0:
            continue
        u = table.get(troop_type, int(tier), truegold=truegold)
        atk += n * u.attack
        leth += n * u.lethality
        hp += n * u.health
        defense += n * u.defense
    return TroopUnitStats(
        attack=atk / total,
        defense=defense / total,
        lethality=leth / total,
        health=hp / total,
    )


def _offense_rank(unit: TroopUnitStats, troop_type: str) -> float:
    """Marginal-damage proxy for fill order (archers get ranged-strike boost)."""
    base = unit.attack * unit.lethality
    if troop_type == "archers":
        return base * ARCHER_RANGED_STRIKE
    return base


def greedy_fill_march(
    inventory_levels: Mapping[str, Mapping[int, int]],
    capacity: int,
    table: TroopStatsTable,
    *,
    truegold: int = 0,
    skillmod: float = 1.0,
    trap_attack_bonus: float = 0.25,
    host_attack_pct: float = 0.0,
) -> tuple[dict[str, int], dict[str, dict[int, int]], BearDamageResult]:
    """
    Fill capacity by repeatedly adding one troop of the type/tier that most
    increases simulated score (highest remaining offense tier per type).
    """
    if capacity < 0:
        raise ValueError(f"capacity must be >= 0; got {capacity}")

    remaining: dict[str, dict[int, int]] = {
        typ: {int(t): int(c) for t, c in (inventory_levels.get(typ) or {}).items() if int(c) > 0}
        for typ in ("infantry", "cavalry", "archers")
    }
    filled_levels: dict[str, dict[int, int]] = {
        "infantry": {},
        "cavalry": {},
        "archers": {},
    }
    counts = {"infantry": 0, "cavalry": 0, "archers": 0}
    used = 0

    def best_tier(typ: str) -> tuple[int, TroopUnitStats] | None:
        pool = remaining[typ]
        if not pool:
            return None
        best: tuple[int, TroopUnitStats] | None = None
        best_rank = -1.0
        for tier, n in pool.items():
            if n <= 0:
                continue
            unit = table.get(typ, int(tier), truegold=truegold)
            rank = _offense_rank(unit, typ)
            if rank > best_rank:
                best_rank = rank
                best = (int(tier), unit)
        return best

    def current_units() -> dict[str, TroopUnitStats | None]:
        out: dict[str, TroopUnitStats | None] = {}
        for typ in ("infantry", "cavalry", "archers"):
            if counts[typ] <= 0:
                out[typ] = None
                continue
            # Blend of what we've already filled
            out[typ] = blend_unit_stats(filled_levels[typ], table, typ, truegold=truegold)
        return out

    # Chunked greedy: evaluate marginal damage of adding a batch of each type's
    # best remaining tier. Chunk size keeps large marches fast.
    while used < capacity:
        left = capacity - used
        chunk = min(left, max(1, capacity // 200))
        candidates: list[tuple[float, str, int, int]] = []
        base_units = current_units()
        base_score = simulate_from_units(
            base_units,
            counts,
            skillmod=skillmod,
            trap_attack_bonus=trap_attack_bonus,
            host_attack_pct=host_attack_pct,
        ).score

        for typ in ("infantry", "cavalry", "archers"):
            pick = best_tier(typ)
            if pick is None:
                continue
            tier, unit = pick
            avail = int(remaining[typ].get(tier, 0))
            add_n = min(chunk, avail, left)
            if add_n <= 0:
                continue
            trial_counts = dict(counts)
            trial_counts[typ] += add_n
            trial_levels = {t: dict(lv) for t, lv in filled_levels.items()}
            trial_levels[typ][tier] = trial_levels[typ].get(tier, 0) + add_n
            trial_units = {
                t: (
                    blend_unit_stats(trial_levels[t], table, t, truegold=truegold)
                    if trial_counts[t] > 0
                    else None
                )
                for t in ("infantry", "cavalry", "archers")
            }
            trial_score = simulate_from_units(
                trial_units,
                trial_counts,
                skillmod=skillmod,
                trap_attack_bonus=trap_attack_bonus,
                host_attack_pct=host_attack_pct,
            ).score
            delta_per = (float(trial_score - base_score) / add_n) + (
                _offense_rank(unit, typ) * 1e-12
            )
            candidates.append((delta_per, typ, tier, add_n))

        if not candidates:
            break
        candidates.sort(key=lambda row: row[0], reverse=True)
        _, typ, tier, add_n = candidates[0]
        remaining[typ][tier] -= add_n
        if remaining[typ][tier] <= 0:
            del remaining[typ][tier]
        filled_levels[typ][tier] = filled_levels[typ].get(tier, 0) + add_n
        counts[typ] += add_n
        used += add_n

    units = current_units()
    result = simulate_from_units(
        units,
        counts,
        skillmod=skillmod,
        trap_attack_bonus=trap_attack_bonus,
        host_attack_pct=host_attack_pct,
    )
    return counts, filled_levels, result


def skillmod_for_observed_score(
    counts: Mapping[str, int],
    attack_by_type: Mapping[str, float],
    observed_score: int,
    *,
    trap_attack_bonus: float = 0.25,
    host_attack_pct: float = 0.0,
    lo: float = 0.01,
    hi: float = 50.0,
) -> float:
    """Binary-search skillmod so simulate(...).score ≈ observed_score."""
    if observed_score <= 0:
        raise ValueError(f"observed_score must be positive; got {observed_score}")
    for _ in range(60):
        mid = (lo + hi) / 2.0
        score = simulate(
            counts,
            attack_by_type,
            skillmod=mid,
            trap_attack_bonus=trap_attack_bonus,
            host_attack_pct=host_attack_pct,
        ).score
        if score < observed_score:
            lo = mid
        else:
            hi = mid
    return hi


def fill_ratio_march(
    inventory_levels: Mapping[str, Mapping[int, int]],
    capacity: int,
    ratios: Mapping[str, float],
    table: TroopStatsTable,
    *,
    truegold: int = 0,
) -> tuple[dict[str, int], dict[str, dict[int, int]], dict[str, TroopUnitStats | None]]:
    """
    Fill a march to ``capacity`` using type ratios, highest tiers first within each type.
    Ratios need not sum to 1; they are normalized. Falls back across types if inventory short.
    """
    if capacity < 0:
        raise ValueError(f"capacity must be >= 0; got {capacity}")
    raw = {
        "infantry": max(0.0, float(ratios.get("infantry", 0.0))),
        "cavalry": max(0.0, float(ratios.get("cavalry", 0.0))),
        "archers": max(0.0, float(ratios.get("archers", 0.0))),
    }
    total_r = sum(raw.values()) or 1.0
    targets = {t: int(capacity * (raw[t] / total_r)) for t in raw}
    # Fix rounding to hit capacity
    while sum(targets.values()) < capacity:
        # Prefer archers for remainder
        for t in ("archers", "cavalry", "infantry"):
            targets[t] += 1
            if sum(targets.values()) >= capacity:
                break

    remaining = {
        typ: {int(t): int(c) for t, c in (inventory_levels.get(typ) or {}).items() if int(c) > 0}
        for typ in ("infantry", "cavalry", "archers")
    }
    filled_levels: dict[str, dict[int, int]] = {
        "infantry": {},
        "cavalry": {},
        "archers": {},
    }
    counts = {"infantry": 0, "cavalry": 0, "archers": 0}

    def take(typ: str, need: int) -> int:
        got = 0
        tiers = sorted(remaining[typ].keys(), reverse=True)
        for tier in tiers:
            if got >= need:
                break
            avail = remaining[typ][tier]
            take_n = min(avail, need - got)
            if take_n <= 0:
                continue
            remaining[typ][tier] -= take_n
            if remaining[typ][tier] <= 0:
                del remaining[typ][tier]
            filled_levels[typ][tier] = filled_levels[typ].get(tier, 0) + take_n
            counts[typ] += take_n
            got += take_n
        return got

    for typ, need in targets.items():
        take(typ, need)

    # Top up any shortfall from remaining inventory (archers first)
    short = capacity - sum(counts.values())
    if short > 0:
        for typ in ("archers", "cavalry", "infantry"):
            if short <= 0:
                break
            got = take(typ, short)
            short -= got

    units = {
        typ: blend_unit_stats(filled_levels[typ], table, typ, truegold=truegold)
        for typ in ("infantry", "cavalry", "archers")
    }
    return counts, filled_levels, units
