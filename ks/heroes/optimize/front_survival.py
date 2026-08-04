"""Front-row toughness and defense-degradation scoring for Arena/Conquest."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

from ks.heroes.gear_models import GearRecord
from ks.heroes.models import HeroRecord
from ks.heroes.optimize.combat_formation import BACK, FRONT
from ks.heroes.optimize.gear_assign import infer_slot
from ks.heroes.optimize.gear_stats import expedition_stat_fraction


@dataclass(frozen=True)
class SurvivalBreakdown:
    tau_F: float
    tau_B: float
    O: float
    s: float
    tau_eff: float
    delta: float
    U_front: float
    U_back: float
    score_eff: float
    tau_by_hero: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "tau_F": self.tau_F,
            "tau_B": self.tau_B,
            "O": self.O,
            "s": self.s,
            "tau_eff": self.tau_eff,
            "delta": self.delta,
            "U_front": self.U_front,
            "U_back": self.U_back,
            "score_eff": self.score_eff,
            "tau_by_hero": dict(self.tau_by_hero),
        }


def sanitize_power(
    power: int | None,
    *,
    median_power: float,
    max_abs: int = 2_000_000,
    median_factor: float = 20.0,
) -> float:
    """Drop OCR blow-ups before naive top-N selection / ILP scoring."""
    if power is None or power <= 0:
        return 0.0
    if max_abs <= 0:
        raise ValueError(f"max_abs must be positive; got {max_abs}")
    if median_factor <= 0:
        raise ValueError(f"median_factor must be positive; got {median_factor}")
    p = float(power)
    if p > max_abs:
        return median_power
    if median_power > 0 and p > float(median_factor) * median_power:
        return median_power
    return p


def roster_median_power(heroes: list[HeroRecord]) -> float:
    vals = sorted(float(h.power) for h in heroes if h.power and h.power > 0)
    if not vals:
        return 0.0
    mid = len(vals) // 2
    if len(vals) % 2:
        return vals[mid]
    return 0.5 * (vals[mid - 1] + vals[mid])


def conquest_stat(hero: HeroRecord, key: str) -> int:
    if hero.stats is None:
        return 0
    raw = hero.stats.conquest.get(key)
    return int(raw) if raw is not None else 0


def gear_health_bonus(pieces: Mapping[str, GearRecord] | None) -> float:
    """Sum formula health fractions for chest/gloves (0..~1+)."""
    if not pieces:
        return 0.0
    total = 0.0
    for slot_name, piece in pieces.items():
        slot = slot_name if slot_name in {"chest", "gloves"} else infer_slot(piece)
        if slot not in {"chest", "gloves"}:
            continue
        frac = expedition_stat_fraction(
            piece.rarity, piece.enhancement_level, piece.mastery_level
        )
        if frac is not None and frac > 0:
            total += float(frac)
    return total


def hero_tau(
    hero: HeroRecord,
    *,
    gear_pieces: Mapping[str, GearRecord] | None = None,
) -> float:
    hp = max(1, conquest_stat(hero, "Hero Health"))
    defense = max(1, conquest_stat(hero, "Hero Defense"))
    g = gear_health_bonus(gear_pieces)
    return float(hp) * float(defense) * (1.0 + g)


def formation_tau(
    formation: Mapping[str, str],
    heroes_by_name: Mapping[str, HeroRecord],
    gear_by_hero: Mapping[str, Mapping[str, GearRecord]] | None = None,
) -> tuple[float, float, dict[str, float]]:
    gear_by_hero = gear_by_hero or {}
    by_hero: dict[str, float] = {}
    tau_f = 0.0
    tau_b = 0.0
    for slot, name in formation.items():
        hero = heroes_by_name.get(name)
        if hero is None:
            raise ValueError(
                f"formation references unknown hero {name!r} in slot {slot!r}"
            )
        tau = hero_tau(hero, gear_pieces=gear_by_hero.get(name))
        by_hero[name] = tau
        if slot in FRONT:
            tau_f += tau
        elif slot in BACK:
            tau_b += tau
    return tau_f, tau_b, by_hero


def pressure_scale(
    *,
    tau_samples: list[float],
    U_samples: list[float],
) -> float:
    """Map heuristic offense units → toughness units (median τ / median U)."""
    taus = sorted(t for t in tau_samples if t > 0)
    us = sorted(u for u in U_samples if u > 0)
    if not taus or not us:
        return 1.0
    mid_t = taus[len(taus) // 2]
    mid_u = us[len(us) // 2]
    if mid_u <= 0:
        return 1.0
    return float(mid_t / mid_u)


def survival_score(
    *,
    tau_F: float,
    tau_B: float,
    O: float,
    U_front: float,
    U_back: float,
    lambda_tau: float = 5.0,
    tau_by_hero: Mapping[str, float] | None = None,
    O_scale: float = 1.0,
) -> SurvivalBreakdown:
    if tau_F < 0 or tau_B < 0:
        raise ValueError(f"tau must be non-negative; got tau_F={tau_F} tau_B={tau_B}")
    if O < 0:
        raise ValueError(f"O must be non-negative; got {O}")
    if O_scale <= 0:
        raise ValueError(f"O_scale must be positive; got {O_scale}")
    # Heuristic offense O is score-units; scale into toughness-units for s.
    O_tau = float(O) * float(O_scale)
    denom = tau_F + O_tau
    s = (tau_F / denom) if denom > 0 else 0.0
    tau_eff = s * tau_F + (1.0 - s) * tau_B
    delta = s
    score_eff = U_front + delta * U_back + float(lambda_tau) * math.log1p(tau_eff)
    return SurvivalBreakdown(
        tau_F=tau_F,
        tau_B=tau_B,
        O=O_tau,
        s=s,
        tau_eff=tau_eff,
        delta=delta,
        U_front=float(U_front),
        U_back=float(U_back),
        score_eff=score_eff,
        tau_by_hero=dict(tau_by_hero or {}),
    )
