"""Aggregate governor gear into per-troop Attack%/Defense% + set bonuses."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from ks.heroes.governor_config import GovernorGearConfig, ladder_rank, ladder_step, slot_troop
from ks.heroes.governor_models import GovernorPiece, GovernorTroopBonuses

_TROOPS = ("infantry", "cavalry", "archers")


def governor_troop_bonuses(
    pieces: Sequence[GovernorPiece],
    cfg: GovernorGearConfig,
) -> GovernorTroopBonuses:
    """Sum piece Atk%/Def% by troop and apply 3pc/6pc set bonuses.

    Set rule (see config header): count pieces sharing the same ``tier`` key.
    Prefer the highest-ranked tier that reaches the 3 or 6 threshold.
    """
    attack = {t: 0.0 for t in _TROOPS}
    defense = {t: 0.0 for t in _TROOPS}
    for piece in pieces:
        troop = slot_troop(cfg, piece.slot_id)
        attack[troop] += float(piece.attack_pct)
        defense[troop] += float(piece.defense_pct)

    counts = Counter(p.tier for p in pieces)
    set_tier: str | None = None
    set_def = 0.0
    set_atk = 0.0

    qualifying = [tier for tier, n in counts.items() if n >= 3]
    if qualifying:
        set_tier = max(qualifying, key=lambda t: ladder_rank(cfg, t))
        # Use set % from the lowest star step of that tier on the ladder
        # (tables share set bonus across stars within a tier card).
        step = _set_step_for_tier(cfg, set_tier)
        if step is not None:
            set_def = float(step.set_defense_pct)
            if counts[set_tier] >= 6:
                set_atk = float(step.set_attack_pct)

    if set_atk:
        for t in _TROOPS:
            attack[t] += set_atk
    if set_def:
        for t in _TROOPS:
            defense[t] += set_def

    return GovernorTroopBonuses(
        attack_pct=attack,
        defense_pct=defense,
        set_attack_pct=set_atk,
        set_defense_pct=set_def,
        set_tier=set_tier if set_def else None,
    )


def _set_step_for_tier(cfg: GovernorGearConfig, tier: str):
    for step in cfg.ladder:
        if step.tier == tier:
            return step
    return None


def enrich_piece(piece: GovernorPiece, cfg: GovernorGearConfig) -> GovernorPiece:
    """Fill attack/defense/power from the ladder for ``tier``+``stars``."""
    step = ladder_step(cfg, piece.tier, piece.stars)
    if step is None:
        raise ValueError(
            f"no ladder step for tier={piece.tier!r} stars={piece.stars}"
        )
    return piece.with_ladder(step)
