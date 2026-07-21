from ks.config import AppConfig
from ks.models import Action, GatherCandidate, NothingToDo, Proposal
from ks.policy.scoring import best_gather, score_gather


def propose_gather(
    candidates: list[GatherCandidate],
    cfg: AppConfig,
    actions: tuple[Action, ...],
) -> Proposal | NothingToDo:
    rates = cfg.account.gather_rate_per_sec
    threshold = cfg.vision.match_threshold
    march_load = cfg.account.march_load

    scored = []
    for candidate in candidates:
        if candidate.resource not in rates:
            continue
        if candidate.vision_confidence < threshold:
            continue
        scored.append(
            score_gather(
                candidate,
                march_load=march_load,
                gather_rate_per_sec=rates[candidate.resource],
            )
        )

    best = best_gather(scored)
    if best is None:
        return NothingToDo(reason="no viable gather candidates")

    rationale = (
        f"resource={best.candidate.resource} "
        f"haul={best.haul} t_gather_s={best.t_gather_s} "
        f"t_march_round_s={best.t_march_round_s} score={best.score}"
    )
    return Proposal(
        kind="gather",
        scored=best,
        actions=actions,
        rationale=rationale,
    )
