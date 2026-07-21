from ks.models import GatherCandidate, ScoredGather


def score_gather(
    candidate: GatherCandidate,
    *,
    march_load: float,
    gather_rate_per_sec: float,
) -> ScoredGather:
    if march_load <= 0:
        raise ValueError(f"march_load must be > 0; got {march_load}")
    if gather_rate_per_sec <= 0:
        raise ValueError(f"gather_rate_per_sec must be > 0; got {gather_rate_per_sec}")
    if candidate.tile_amount < 0:
        raise ValueError(f"tile_amount must be >= 0; got {candidate.tile_amount}")
    if candidate.march_time_one_way_s < 0:
        raise ValueError(
            f"march_time_one_way_s must be >= 0; got {candidate.march_time_one_way_s}"
        )
    haul = min(candidate.tile_amount, march_load)
    t_gather_s = haul / gather_rate_per_sec
    t_march_round_s = 2.0 * candidate.march_time_one_way_s
    denom = t_gather_s + t_march_round_s
    if denom <= 0:
        raise ValueError("total time must be > 0")
    return ScoredGather(
        candidate=candidate,
        haul=haul,
        t_gather_s=t_gather_s,
        t_march_round_s=t_march_round_s,
        score=haul / denom,
    )


def best_gather(scored: list[ScoredGather]) -> ScoredGather | None:
    if not scored:
        return None
    return max(scored, key=lambda s: s.score)
