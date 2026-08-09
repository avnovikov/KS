"""Deterministic floor combat vs stub (#38) — not full Monte Carlo variance."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ks.heroes.optimize.mystic_trial.floors import FloorStub
from ks.heroes.optimize.mystic_trial.proxy import MarchScore


@dataclass(frozen=True)
class McResult:
    win_rate: float
    remaining_hp_est: float
    rounds: int
    player_score: float
    enemy_score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "win_rate": self.win_rate,
            "remaining_hp_est": self.remaining_hp_est,
            "rounds": self.rounds,
            "player_score": self.player_score,
            "enemy_score": self.enemy_score,
        }


def simulate_floor(
    player: MarchScore,
    stub: FloorStub,
    *,
    rounds: int = 10,
) -> McResult:
    """Compare player proxy to scaled enemy proxy; map ratio to win_rate.

    Enemy score ≈ player_score × enemy_power_scale (stub difficulty).
    win_rate = clamp(player / (player + enemy), 0, 1).
    remaining_hp_est ≈ (player - enemy) / max(player, 1) clipped to [-1, 1].
    """
    if rounds < 1:
        raise ValueError(f"rounds must be >= 1; got {rounds}")
    player_score = float(player.score)
    enemy_score = max(0.0, player_score * float(stub.enemy_power_scale))
    # Bias by troop mix mismatch: if enemy is infantry-heavy and player offense
    # is archer-skewed in by_type, slightly reduce player (simple heuristic).
    mix_penalty = _mix_penalty(player.by_type, stub.enemy_ratio)
    adj_player = max(0.0, player_score * (1.0 - mix_penalty))
    denom = adj_player + enemy_score
    win_rate = 0.5 if denom <= 0 else adj_player / denom
    win_rate = min(1.0, max(0.0, win_rate))
    remaining = 0.0 if denom <= 0 else (adj_player - enemy_score) / max(adj_player, 1.0)
    remaining = min(1.0, max(-1.0, remaining))
    return McResult(
        win_rate=win_rate,
        remaining_hp_est=remaining,
        rounds=int(rounds),
        player_score=adj_player,
        enemy_score=enemy_score,
    )


def _mix_penalty(
    by_type: Mapping[str, Mapping[str, float]],
    enemy_ratio: Mapping[str, float],
) -> float:
    """Small penalty when player offense share diverges from enemy ratio."""
    offense = {t: float((by_type.get(t) or {}).get("offense") or 0.0) for t in enemy_ratio}
    total = sum(offense.values())
    if total <= 0:
        return 0.0
    shares = {t: offense[t] / total for t in offense}
    # Distance from mirror of enemy (prefer matching lanes lightly).
    dist = sum(abs(shares.get(t, 0.0) - float(enemy_ratio.get(t, 0.0))) for t in enemy_ratio)
    return min(0.15, 0.05 * dist)
