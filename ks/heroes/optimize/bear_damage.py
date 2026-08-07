"""Bear Trap 10-round damage simulator (community formula)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

import yaml

from ks.heroes.optimize.troop_stats import TroopStatsTable, TroopUnitStats

if TYPE_CHECKING:
    from ks.heroes.models import HeroRecord
    from ks.heroes.optimize.types import CatalogEntry

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
class AssumedJoinerSkill:
    """One assumed joiner first-expedition skill (effect_op + percent)."""

    effect_op: int
    pct: float


@dataclass(frozen=True)
class BeartrapBuffs:
    trap_level: int = 5
    host_attack_pct: float = 0.0
    # Research / city buffs only — hero DamageUp comes from catalog + joiners.
    research_skillmod: float = 1.0
    assumed_joiners: tuple[AssumedJoinerSkill, ...] = ()
    # Legacy aliases kept so old callers/tests that set base_skillmod still load.
    base_skillmod: float | None = None
    joiner_skillmod: float = 1.0
    hero_strength_scale: float = 0.0
    calibration_score: int = 180_000
    calibration_march: int = 80_245

    @property
    def trap_attack_bonus(self) -> float:
        level = max(0, int(self.trap_level))
        return TRAP_ATTACK_PER_LEVEL * level

    def joiner_damage_up_buckets(self) -> dict[int, float]:
        buckets: dict[int, float] = {}
        for skill in self.assumed_joiners:
            op = int(skill.effect_op)
            buckets[op] = buckets.get(op, 0.0) + float(skill.pct)
        return buckets

    def joiner_damage_up_product(self) -> float:
        return bucket_product(self.joiner_damage_up_buckets())

    def effective_skillmod(
        self,
        lineup_hero_strength: float = 0.0,
        *,
        host_damage_up: Mapping[int, float] | None = None,
        host_defense_up: Mapping[int, float] | None = None,
        host_opp_damage_down: Mapping[int, float] | None = None,
        host_opp_defense_down: Mapping[int, float] | None = None,
    ) -> float:
        """SkillMod from research × host × assumed joiners (op-bucket product).

        ``lineup_hero_strength`` is accepted for API compatibility with the
        old linear scale; when ``hero_strength_scale`` is 0 (default) it is
        ignored. Prefer passing host DamageUp buckets from the catalog.
        """
        research = float(
            self.research_skillmod
            if self.base_skillmod is None
            else self.base_skillmod
        )
        # Legacy joiner_skillmod multiplies when no assumed_joiners listed.
        joiner_buckets = self.joiner_damage_up_buckets()
        damage_up = merge_pct_buckets(host_damage_up, joiner_buckets)
        sm = compute_skillmod(
            research=research,
            damage_up=damage_up,
            defense_up=host_defense_up,
            opp_damage_down=host_opp_damage_down,
            opp_defense_down=host_opp_defense_down,
        )
        if not joiner_buckets and self.joiner_skillmod != 1.0:
            sm *= float(self.joiner_skillmod)
        if self.hero_strength_scale:
            sm *= 1.0 + float(self.hero_strength_scale) * float(lineup_hero_strength)
        assert sm > 0, f"skillmod must be positive; got {sm}"
        return sm


def bucket_product(pct_by_op: Mapping[int, float] | None) -> float:
    """∏ (1 + sum_pct[op]/100) over effect_op buckets."""
    if not pct_by_op:
        return 1.0
    prod = 1.0
    for pct in pct_by_op.values():
        prod *= 1.0 + float(pct) / 100.0
    return prod


def merge_pct_buckets(
    *maps: Mapping[int, float] | None,
) -> dict[int, float]:
    out: dict[int, float] = {}
    for mapping in maps:
        if not mapping:
            continue
        for op, pct in mapping.items():
            key = int(op)
            out[key] = out.get(key, 0.0) + float(pct)
    return out


def compute_skillmod(
    *,
    research: float = 1.0,
    damage_up: Mapping[int, float] | None = None,
    opp_defense_down: Mapping[int, float] | None = None,
    opp_damage_down: Mapping[int, float] | None = None,
    defense_up: Mapping[int, float] | None = None,
) -> float:
    """Community SkillMod = research × DamageUp × OppDefDown / (OppDmgDown × DefUp)."""
    if research <= 0:
        raise ValueError(f"research_skillmod must be positive; got {research}")
    numerator = (
        float(research)
        * bucket_product(damage_up)
        * bucket_product(opp_defense_down)
    )
    denominator = bucket_product(opp_damage_down) * bucket_product(defense_up)
    if denominator <= 0:
        raise ValueError(f"skillmod denominator must be positive; got {denominator}")
    return numerator / denominator


# Catalog kinds → (SkillMod family, default effect_op when tag.effect_op is None).
_SKILLMOD_KIND: dict[str, tuple[str, int]] = {
    "lethality_up": ("damage_up", 101),
    "rally_lethality": ("damage_up", 101),
    "attack_up": ("damage_up", 102),
    "rally_attack": ("damage_up", 102),
    "defense_up": ("defense_up", 111),
    "damage_taken_down": ("defense_up", 111),
    "opp_damage_down": ("opp_damage_down", 201),
    "opp_defense_down": ("opp_defense_down", 202),
}


def host_skillmod_buckets(
    heroes_with_entries: list[tuple[Any, Any]],
) -> dict[str, dict[int, float]]:
    """Build SkillMod percent buckets from host lineup catalog effects.

    Includes ``expedition`` and ``widget`` applies_to (host skills fire).
    Values are star-scaled catalog ``max_value`` percent points.
    """
    from ks.heroes.optimize.scoring import star_progress_factor
    from ks.heroes.optimize.types import CatalogEntry, EffectTag
    from ks.heroes.models import HeroRecord

    out: dict[str, dict[int, float]] = {
        "damage_up": {},
        "defense_up": {},
        "opp_damage_down": {},
        "opp_defense_down": {},
    }
    for hero, entry in heroes_with_entries:
        if not isinstance(hero, HeroRecord) or not isinstance(entry, CatalogEntry):
            raise TypeError("heroes_with_entries must be (HeroRecord, CatalogEntry)")
        scale = star_progress_factor(hero.stars, hero.pellets)
        for tag in entry.effects:
            if not isinstance(tag, EffectTag):
                continue
            if tag.applies_to not in {"expedition", "widget"}:
                continue
            meta = _SKILLMOD_KIND.get(tag.kind)
            if meta is None:
                continue
            family, default_op = meta
            op = int(tag.effect_op) if tag.effect_op is not None else default_op
            pct = float(tag.max_value) * float(scale)
            if pct <= 0:
                continue
            bucket = out[family]
            bucket[op] = bucket.get(op, 0.0) + pct
    return out


def load_beartrap_buffs(path: Path | str) -> BeartrapBuffs:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("beartrap_buffs.yaml must be a mapping")

    joiners_raw = raw.get("assumed_joiners") or []
    joiners: list[AssumedJoinerSkill] = []
    if isinstance(joiners_raw, list):
        for row in joiners_raw:
            if not isinstance(row, dict):
                raise ValueError("assumed_joiners entries must be mappings")
            op = row.get("effect_op", row.get("op"))
            pct = row.get("pct", row.get("value"))
            if op is None or pct is None:
                raise ValueError(
                    "assumed_joiners entries need effect_op (or op) and pct (or value)"
                )
            joiners.append(AssumedJoinerSkill(effect_op=int(op), pct=float(pct)))

    research = raw.get("research_skillmod")
    legacy_base = raw.get("base_skillmod")
    if research is None and legacy_base is not None:
        # Old YAML folded everything into base_skillmod — do not treat that
        # lump as research-only; start research at 1.0 and use joiners.
        research = 1.0
    elif research is None:
        research = 1.0

    return BeartrapBuffs(
        trap_level=int(raw.get("trap_level", 5)),
        host_attack_pct=float(raw.get("host_attack_pct", 0.0)),
        research_skillmod=float(research),
        assumed_joiners=tuple(joiners),
        base_skillmod=None,
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
