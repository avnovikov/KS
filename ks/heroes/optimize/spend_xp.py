"""Allocate enhancement fodder XP to maximize event optimizer utility."""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Iterator

from ks.heroes.gear_models import GearRecord
from ks.heroes.governor_models import GovernorTroopBonuses
from ks.heroes.models import HeroRecord
from ks.heroes.optimize.xp_ladder import (
    FodderBag,
    cap_for_rarity,
    load_fodder_xp_values,
    load_xp_ladder,
    xp_cost_next_level,
)
from ks.heroes.ui.power import compute_gear_power, known_rarity

REPO_ROOT = Path(__file__).resolve().parents[3]

UtilityFn = Callable[[list[GearRecord]], tuple[float, dict[str, Any]]]


@dataclass(frozen=True)
class SpendStep:
    piece_id: str
    name: str | None
    from_level: int
    to_level: int
    xp_spent: int
    fodder_spent: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "piece_id": self.piece_id,
            "name": self.name,
            "from_level": self.from_level,
            "to_level": self.to_level,
            "xp_spent": self.xp_spent,
            "fodder_spent": dict(self.fodder_spent),
        }


@dataclass(frozen=True)
class SpendResult:
    event: str
    baseline_utility: float
    best_utility: float
    steps: tuple[SpendStep, ...]
    leftover: FodderBag
    baseline_summary: dict[str, Any]
    best_summary: dict[str, Any]
    value_summary: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "baseline_utility": self.baseline_utility,
            "best_utility": self.best_utility,
            "delta_utility": self.best_utility - self.baseline_utility,
            "steps": [s.to_dict() for s in self.steps],
            "leftover": self.leftover.counts(),
            "baseline_summary": dict(self.baseline_summary),
            "best_summary": dict(self.best_summary),
            "value_summary": self.value_summary,
        }


def _with_level(piece: GearRecord, level: int) -> GearRecord:
    power = piece.power
    if known_rarity(piece.rarity):
        try:
            power = compute_gear_power(piece.rarity, level, piece.mastery_level)
        except ValueError:
            power = piece.power
    return replace(piece, enhancement_level=level, power=power)


def apply_levels(
    gear: list[GearRecord],
    levels: dict[str, int],
) -> list[GearRecord]:
    out: list[GearRecord] = []
    for piece in gear:
        if piece.piece_id in levels:
            out.append(_with_level(piece, int(levels[piece.piece_id])))
        else:
            out.append(piece)
    return out


def current_levels(gear: list[GearRecord]) -> dict[str, int]:
    return {
        p.piece_id: int(p.enhancement_level or 0)
        for p in gear
        if p.piece_id
    }


def build_event_utility(
    event: str,
    heroes: list[HeroRecord],
    *,
    config_root: Path | None = None,
    troops_path: Path | None = None,
    mode: str | None = None,
    governor: GovernorTroopBonuses | None = None,
) -> UtilityFn:
    """Return U(gear) -> (utility, summary) for sword/bear/arena events.

    `troops_path` overrides where troop counts/truegold are read from (the
    UI-editable copy); it defaults to the repo-relative config/troops.yaml
    used before Task 2 wired in a store. ``governor`` is passed through to
    child recommend / arena scorers (OG-06).
    """
    root = (config_root or REPO_ROOT).expanduser().resolve()
    key = event.strip().lower().replace(" ", "_")

    from ks.heroes.optimize.catalog import load_catalog

    catalog = load_catalog(None, root / "config" / "hero_catalog.yaml")

    if key in {"arena_attack", "arena_defense", "arena"}:
        from ks.heroes.optimize.arena import load_arena_roles, optimize_arena

        side = "defense" if "defense" in key else "attack"
        if key == "arena" and mode in {"attack", "defense"}:
            side = mode
        roles = load_arena_roles(
            root / "config" / "arena_roles.yaml", catalog=catalog
        )

        def _arena(gear: list[GearRecord]) -> tuple[float, dict[str, Any]]:
            result = optimize_arena(
                side,
                heroes,
                catalog,
                roles,
                gear=gear,
                with_explanations=False,
                governor=governor,
            )
            util = float(result.score) if result.status == "Optimal" else float("-inf")
            return util, {
                "status": result.status,
                "side": side,
                "formation": dict(result.formation),
                "heroes": list(result.heroes),
                "score": result.score if result.status == "Optimal" else None,
                "stat_family": result.stat_family,
                "formation_totals": result.formation_totals,
                "contributions": result.contributions,
            }

        return _arena

    from ks.heroes.optimize.events import load_event_profile
    from ks.heroes.optimize.recommend import recommend, recommend_all_modes
    from ks.heroes.optimize.scenarios import load_scenarios
    from ks.heroes.optimize.troop_stats import load_troop_stats
    from ks.heroes.optimize.troops import load_troops_config
    import yaml

    if key in {"sword", "swordland"}:
        event_path = root / "config" / "events" / "swordland.yaml"
        scenarios_path = root / "config" / "point_scenarios.yaml"
        gear_profile = "early_game_growth"
    elif key in {"bear", "beartrap", "bear_trap"}:
        event_path = root / "config" / "events" / "beartrap.yaml"
        scenarios_path = root / "config" / "point_scenarios_beartrap.yaml"
        gear_profile = "early_game_growth"
    else:
        raise ValueError(f"unsupported event {event!r}")

    resolved_troops_path = (
        Path(troops_path).expanduser().resolve()
        if troops_path is not None
        else root / "config" / "troops.yaml"
    )
    troops = load_troops_config(resolved_troops_path)
    scenarios = load_scenarios(scenarios_path)
    event_profile = load_event_profile(event_path)
    troop_stats = load_troop_stats(root / "config" / "troop_stats.yaml")
    raw_troops = yaml.safe_load(
        resolved_troops_path.read_text(encoding="utf-8")
    ) or {}
    truegold = int(raw_troops.get("truegold", troop_stats.default_truegold))

    def _event(gear: list[GearRecord]) -> tuple[float, dict[str, Any]]:
        if mode:
            result = recommend(
                heroes,
                catalog,
                troops,
                scenarios,
                force_mode=mode,
                event=event_profile,
                troop_stats=troop_stats,
                truegold=truegold,
                gear=gear,
                gear_profile=gear_profile,
                governor=governor,
            )
            return float(result.expected_personal_points), {
                "mode": result.recommended_mode,
                "heroes": [h["name"] for h in result.heroes],
                "expected_personal_points": result.expected_personal_points,
                "stat_family": result.stat_family,
                "formation_totals": result.formation_totals,
            }
        results = recommend_all_modes(
            heroes,
            catalog,
            troops,
            scenarios,
            event=event_profile,
            troop_stats=troop_stats,
            truegold=truegold,
            gear=gear,
            gear_profile=gear_profile,
            governor=governor,
        )
        best = max(results.values(), key=lambda r: r.expected_personal_points)
        return float(best.expected_personal_points), {
            "mode": best.recommended_mode,
            "heroes": [h["name"] for h in best.heroes],
            "expected_personal_points": best.expected_personal_points,
            "modes": {
                m: r.expected_personal_points for m, r in results.items()
            },
            "stat_family": best.stat_family,
            "formation_totals": best.formation_totals,
        }

    return _event


@dataclass(frozen=True)
class _UpgradeCandidate:
    """A single +1 level upgrade under consideration, with its ΔU and XP cost."""

    delta: float
    xp_cost: int
    piece_id: str
    from_level: int
    to_level: int
    fodder_plan: dict[str, int]

    @property
    def delta_per_xp(self) -> float:
        if self.xp_cost <= 0:
            return float("-inf")
        return self.delta / float(self.xp_cost)


def _is_better_candidate(candidate: _UpgradeCandidate, best: _UpgradeCandidate) -> bool:
    """Prefer higher ΔU/XP; break ties with higher raw ΔU, then lower XP cost."""
    if candidate.delta_per_xp != best.delta_per_xp:
        return candidate.delta_per_xp > best.delta_per_xp
    if candidate.delta != best.delta:
        return candidate.delta > best.delta
    return candidate.xp_cost < best.xp_cost


# How many of a step's evaluated candidates get logged, sorted best-first —
# the search itself still considers every affordable piece; only the log
# line is capped, so a 30-piece inventory reads as "here is where the XP
# would go" instead of a wall of every candidate evaluated.
_LOG_TOP_CANDIDATES = 5


def _best_upgrade_candidate(
    by_id: dict[str, GearRecord],
    levels: dict[str, int],
    xp_ladder: dict[str, Any],
    values: dict[str, int],
    bag: FodderBag,
    gear: list[GearRecord],
    utility_fn: UtilityFn,
    current_u: float,
) -> tuple[_UpgradeCandidate | None, list[_UpgradeCandidate]]:
    """Scan every piece for the affordable +1 with the best ΔU per XP.

    Returns ``(best, ranked)`` — ``ranked`` is every affordable candidate
    found this step, best-first, so a caller can report progress without
    re-scanning.
    """
    candidates: list[_UpgradeCandidate] = []
    for piece_id, piece in by_id.items():
        cur_lv = int(levels.get(piece_id, piece.enhancement_level or 0))
        cap = cap_for_rarity(piece.rarity, ladder=xp_ladder)
        if cur_lv >= cap:
            continue
        cost = xp_cost_next_level(xp_ladder, cur_lv)
        if cost is None or cost <= 0:
            continue
        plan = bag.plan_cover(cost, values=values)
        if plan is None:
            continue
        trial_levels = dict(levels)
        trial_levels[piece_id] = cur_lv + 1
        trial_gear = apply_levels(gear, trial_levels)
        trial_u, _summary = utility_fn(trial_gear)
        if trial_u == float("-inf"):
            continue
        delta = trial_u - current_u
        candidates.append(
            _UpgradeCandidate(delta, int(cost), piece_id, cur_lv, cur_lv + 1, plan)
        )
    best: _UpgradeCandidate | None = None
    for cand in candidates:
        if best is None or _is_better_candidate(cand, best):
            best = cand
    candidates.sort(key=lambda c: (-c.delta_per_xp, -c.delta, c.xp_cost))
    return best, candidates


def _apply_upgrade_step(
    candidate: _UpgradeCandidate,
    *,
    gear: list[GearRecord],
    levels: dict[str, int],
    bag: FodderBag,
    xp_ladder: dict[str, Any],
    by_id: dict[str, GearRecord],
    utility_fn: UtilityFn,
) -> tuple[FodderBag, float, dict[str, Any], SpendStep]:
    """Consume fodder for ``candidate``, bump its level, and re-score utility."""
    cost = xp_cost_next_level(xp_ladder, candidate.from_level) or 0
    new_bag = bag.consume(candidate.fodder_plan)
    levels[candidate.piece_id] = candidate.to_level
    trial_gear = apply_levels(gear, levels)
    new_u, new_summary = utility_fn(trial_gear)
    piece = by_id[candidate.piece_id]
    step = SpendStep(
        piece_id=candidate.piece_id,
        name=piece.name,
        from_level=candidate.from_level,
        to_level=candidate.to_level,
        xp_spent=int(cost),
        fodder_spent=dict(candidate.fodder_plan),
    )
    return new_bag, new_u, new_summary, step


def _merge_same_piece_steps(
    steps: list[SpendStep],
    final_bag: FodderBag,
    values: dict[str, int],
) -> tuple[list[SpendStep], FodderBag]:
    """Collapse every level gained on the same piece into one step.

    The greedy loop covers each level's cost independently as it goes, so a
    piece that stays a top (but not always *the* top) pick can pay for each
    level with whatever's cheapest *at that moment* — e.g. a 55 XP level and
    a 65 XP level each rounding up to their own 100-XP part when nothing
    smaller is left, spending 200 XP of fodder for 120 XP of real cost. Worse,
    the loop routinely ping-pongs between two or three near-tied pieces one
    level at a time, so the same piece's own levels are rarely even adjacent
    in the raw step list — nine raw rows for three pieces reads as far more
    "still working" than three pieces actually is.

    This groups every step for a piece — wherever it falls in the sequence —
    in the order that piece was FIRST picked, and re-covers its whole net
    level gain in one min-waste plan. It does not change which piece or
    level gets picked, or the bag's affordability check at each step; it
    only refunds a piece's naive fodder into the bag before replanning its
    combined cost, exactly as a single contiguous run already did.
    """
    order: list[str] = []
    by_piece: dict[str, list[SpendStep]] = {}
    for step in steps:
        if step.piece_id not in by_piece:
            order.append(step.piece_id)
            by_piece[step.piece_id] = []
        by_piece[step.piece_id].append(step)

    merged: list[SpendStep] = []
    bag = final_bag
    for piece_id in order:
        run = by_piece[piece_id]
        if len(run) == 1:
            merged.append(run[0])
            continue
        run_xp = sum(s.xp_spent for s in run)
        run_fodder: dict[str, int] = {}
        for s in run:
            for kind, n in s.fodder_spent.items():
                run_fodder[kind] = run_fodder.get(kind, 0) + n
        refunded = bag
        for kind, n in run_fodder.items():
            refunded = replace(refunded, **{kind: getattr(refunded, kind) + n})
        # refunded always covers run_xp (it held at least run_fodder's raw XP
        # value before the refund), so this cannot return None in practice —
        # the fallback keeps a working result if that ever stops holding.
        new_plan = refunded.plan_cover(run_xp, values=values) or run_fodder
        bag = refunded.consume(new_plan)
        merged.append(
            SpendStep(
                piece_id=piece_id,
                name=run[0].name,
                from_level=run[0].from_level,
                to_level=run[-1].to_level,
                xp_spent=run_xp,
                fodder_spent=new_plan,
            )
        )
    return merged, bag


def _value_summary(
    raw_deltas: list[tuple[int, float]],
    total_delta_u: float,
    *,
    threshold: float = 0.9,
) -> str | None:
    """One line: how much of the XP spent bought most of the point gain.

    The greedy loop always takes the best available ΔU/XP next, so later
    steps are progressively less efficient — this walks the steps in the
    order they were picked, finds the shortest prefix whose cumulative ΔU
    already reaches ``threshold`` of the total, and reports that prefix's
    XP share against the rest. Returns None when there's nothing to spend
    or the last step still contributes meaningfully (no "burn" tail to call
    out).
    """
    if total_delta_u <= 0 or not raw_deltas:
        return None
    total_xp = sum(xp for xp, _ in raw_deltas)
    target = threshold * total_delta_u
    cum_u = 0.0
    cum_xp = 0
    for xp, du in raw_deltas:
        cum_u += du
        cum_xp += xp
        if cum_u >= target:
            break
    if cum_xp >= total_xp:
        return None
    pct_xp = 100.0 * cum_xp / total_xp
    pct_u = 100.0 * min(cum_u, total_delta_u) / total_delta_u
    return (
        f"The first {cum_xp:,} XP ({pct_xp:.0f}% of {total_xp:,} XP spent) already "
        f"captured {pct_u:.0f}% of the {total_delta_u:.2f}-point gain — the rest "
        "spends spare fodder for diminishing returns."
    )


def _candidate_label(piece: GearRecord | None, piece_id: str) -> str:
    if piece is None:
        return piece_id
    bits = [piece.name or piece_id]
    tags = [t for t in (piece.slot, piece.rarity) if t]
    if tags:
        bits.append("(" + ", ".join(tags) + ")")
    return " ".join(bits)


def _candidate_event(
    by_id: dict[str, GearRecord], candidate: _UpgradeCandidate
) -> dict[str, Any]:
    return {
        "piece_id": candidate.piece_id,
        "label": _candidate_label(by_id.get(candidate.piece_id), candidate.piece_id),
        "from_level": candidate.from_level,
        "to_level": candidate.to_level,
        "delta": candidate.delta,
        "xp_cost": candidate.xp_cost,
    }


def iter_allocate_fodder_xp(
    gear: list[GearRecord],
    bag: FodderBag,
    utility_fn: UtilityFn,
    *,
    event: str = "swordland",
    max_steps: int = 50,
    ladder: dict[str, Any] | None = None,
    fodder_values: dict[str, int] | None = None,
) -> Iterator[dict[str, Any]]:
    """Same greedy search as ``allocate_fodder_xp``, as a stream of progress
    events instead of a blocking return.

    Each step re-solves the target event's optimiser once per affordable
    candidate piece, so a large inventory can take a while — this yields one
    event per step as it happens (plus start/stop/merge/done markers) so a
    caller with its own I/O (a log line, a streamed HTTP response) can show
    real progress instead of waiting out the whole search in silence. The
    final event is always ``{"type": "done", "result": SpendResult,
    "elapsed": float}``.
    """
    if not gear:
        raise ValueError("gear inventory is empty")
    xp_ladder = ladder or load_xp_ladder()
    values = fodder_values or load_fodder_xp_values()
    levels = current_levels(gear)
    by_id = {p.piece_id: p for p in gear if p.piece_id}

    started = time.monotonic()
    baseline_u, baseline_summary = utility_fn(gear)
    if baseline_u == float("-inf"):
        raise ValueError("baseline event utility is infeasible")
    yield {
        "type": "start",
        "event": event,
        "gear_count": len(by_id),
        "baseline_utility": float(baseline_u),
        "max_steps": max_steps,
    }

    steps: list[SpendStep] = []
    raw_deltas: list[tuple[int, float]] = []
    current_bag = bag
    current_u = baseline_u
    current_summary = baseline_summary

    for step_no in range(1, max_steps + 1):
        candidate, ranked = _best_upgrade_candidate(
            by_id, levels, xp_ladder, values, current_bag, gear, utility_fn, current_u
        )
        elapsed = time.monotonic() - started
        if candidate is None or candidate.delta <= 0:
            reason = "no affordable candidate raises utility" if ranked else "nothing affordable in the bag"
            yield {
                "type": "stop",
                "step_no": step_no,
                "max_steps": max_steps,
                "reason": reason,
                "elapsed": elapsed,
            }
            break
        current_bag, current_u, current_summary, step = _apply_upgrade_step(
            candidate,
            gear=gear,
            levels=levels,
            bag=current_bag,
            xp_ladder=xp_ladder,
            by_id=by_id,
            utility_fn=utility_fn,
        )
        steps.append(step)
        raw_deltas.append((candidate.xp_cost, candidate.delta))
        yield {
            "type": "step",
            "step_no": step_no,
            "max_steps": max_steps,
            "candidate_count": len(ranked),
            "top": [_candidate_event(by_id, c) for c in ranked[:_LOG_TOP_CANDIDATES]],
            "chosen": _candidate_event(by_id, candidate),
            "utility": float(current_u),
            "elapsed": elapsed,
        }

    merged_steps, merged_bag = _merge_same_piece_steps(steps, current_bag, values)
    if len(merged_steps) != len(steps):
        yield {
            "type": "merge",
            "before": len(steps),
            "after": len(merged_steps),
        }

    result = SpendResult(
        event=event,
        baseline_utility=float(baseline_u),
        best_utility=float(current_u),
        steps=tuple(merged_steps),
        leftover=merged_bag,
        baseline_summary=dict(baseline_summary),
        best_summary=dict(current_summary),
        value_summary=_value_summary(raw_deltas, current_u - baseline_u),
    )
    yield {"type": "done", "result": result, "elapsed": time.monotonic() - started}


def allocate_fodder_xp(
    gear: list[GearRecord],
    bag: FodderBag,
    utility_fn: UtilityFn,
    *,
    event: str = "swordland",
    max_steps: int = 50,
    ladder: dict[str, Any] | None = None,
    fodder_values: dict[str, int] | None = None,
    verbose: bool = True,
) -> SpendResult:
    """Drain ``iter_allocate_fodder_xp`` and print its progress to stdout.

    ``verbose`` (on by default) is what made the search's real progress
    visible to a caller with no other way to see it (a script, a test) —
    stays the default here; the streaming HTTP API renders the same events
    to the browser instead of the console (see
    ``ks.heroes.ui.app.api_optimize_gear_xp_stream``).
    """

    def _log(msg: str) -> None:
        if verbose:
            print(f"[gear-xp] {msg}", flush=True)

    result: SpendResult | None = None
    for ev in iter_allocate_fodder_xp(
        gear,
        bag,
        utility_fn,
        event=event,
        max_steps=max_steps,
        ladder=ladder,
        fodder_values=fodder_values,
    ):
        kind = ev["type"]
        if kind == "start":
            _log(
                f"searching event={ev['event']}: {ev['gear_count']} gear piece(s), "
                f"baseline utility={ev['baseline_utility']:.3f}, up to {ev['max_steps']} step(s)"
            )
        elif kind == "step":
            _log(
                f"step {ev['step_no']}/{ev['max_steps']}: {ev['candidate_count']} affordable candidate(s), "
                f"top {len(ev['top'])} by ΔU/XP:"
            )
            for rank, cand in enumerate(ev["top"], start=1):
                _log(
                    f"  {rank}. {cand['label']} +{cand['from_level']}→+{cand['to_level']}  "
                    f"ΔU={cand['delta']:+.3f}  cost={cand['xp_cost']:,} XP"
                )
            _log(
                f"  -> chose {ev['chosen']['label']}, utility now {ev['utility']:.3f} "
                f"({ev['elapsed']:.1f}s elapsed)"
            )
        elif kind == "stop":
            _log(
                f"step {ev['step_no']}/{ev['max_steps']}: {ev['reason']} — "
                f"stopping ({ev['elapsed']:.1f}s elapsed)"
            )
        elif kind == "merge":
            _log(
                f"merged {ev['before']} step(s) into {ev['after']} "
                "(same-piece levels re-covered as one combined spend each)"
            )
        else:  # "done"
            result = ev["result"]
            _log(
                f"done: {len(result.steps)} step(s), "
                f"ΔU total={result.best_utility - result.baseline_utility:+.3f} "
                f"({ev['elapsed']:.1f}s elapsed)"
            )
    assert result is not None
    return result
