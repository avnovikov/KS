"""Gear-claim and front-swap sensitivity for 5-hero survival scoring."""

from __future__ import annotations

from typing import Any, Callable, Mapping

from ks.heroes.gear_models import GearRecord
from ks.heroes.models import HeroRecord
from ks.heroes.optimize.opponent_models import GEAR_FRONT_FIRST, OpponentLineup
from ks.heroes.optimize.types import CatalogEntry

BaseScoreFn = Callable[..., float]

_BACK_FIRST = ("B2", "B1", "B3", "F1", "F2")


def _with_first(first: str, base: tuple[str, ...]) -> tuple[str, ...]:
    rest = tuple(s for s in base if s != first)
    if first not in base:
        return (first, *base)
    return (first, *rest)


def _swap_front(formation: Mapping[str, str]) -> dict[str, str]:
    out = dict(formation)
    if "F1" not in out or "F2" not in out:
        raise ValueError("formation must include F1 and F2 for front swap")
    out["F1"], out["F2"] = out["F2"], out["F1"]
    return out


def win_summary_text(
    *,
    s: float,
    score_eff: float,
    foe_front: tuple[str, ...] | list[str],
    best_alt_label: str | None,
    best_alt_delta: float | None,
) -> str:
    """Plain-language summary of hold rate and best alternate delta."""
    pct = int(round(100.0 * float(s)))
    front = "/".join(str(n) for n in foe_front if n) or "?"
    parts = [
        f"Front toughness share s={float(s):.2f} (~{pct}%); "
        f"backline weight ≈ {pct}% vs foe front {front}. "
        f"Effective score {float(score_eff):.1f}."
    ]
    if best_alt_label and best_alt_delta is not None and abs(best_alt_delta) >= 0.05:
        sign = "+" if best_alt_delta > 0 else ""
        verb = "improves" if best_alt_delta > 0 else "worsens"
        parts.append(
            f"Best alternate — {best_alt_label} — {verb} score_eff by "
            f"{sign}{best_alt_delta:.1f}."
        )
    elif best_alt_label:
        parts.append(
            f"Gear-claim and front-swap alternates stay within ~0 of baseline "
            f"({best_alt_label})."
        )
    return " ".join(parts)


def build_sensitivity(
    formation: dict[str, str],
    heroes: list[HeroRecord],
    catalog: dict[str, CatalogEntry],
    roles: dict[str, Any],
    foe: OpponentLineup,
    *,
    side: str,
    base_score_fn: BaseScoreFn,
    gear: list[GearRecord] | None,
    gear_profile: str,
    gear_order: tuple[str, ...] = GEAR_FRONT_FIRST,
    lambda_tau: float = 5.0,
    O_scale: float = 1.0,
    power_by_name: dict[str, int | None] | None = None,
) -> dict[str, Any]:
    """Evaluate gear-order and F1↔F2 variants vs a fixed primary foe."""
    # Local import avoids circular import with survival_pipeline.
    from ks.heroes.optimize.survival_pipeline import (
        evaluate_vs_foe,
        gear_maps_for_formation,
    )

    if "F1" not in formation or "F2" not in formation:
        raise ValueError("formation must include F1 and F2")

    swapped = _swap_front(formation)
    specs: list[tuple[str, str, dict[str, str], tuple[str, ...]]] = [
        ("baseline", "Baseline (current gear order)", dict(formation), gear_order),
        (
            "gear_f2_first",
            "F2 claims gear first",
            dict(formation),
            _with_first("F2", gear_order),
        ),
        (
            "gear_back_first",
            "Back row claims gear first",
            dict(formation),
            _BACK_FIRST,
        ),
        (
            "swap_front",
            "Swap F1↔F2 (same gear order)",
            swapped,
            gear_order,
        ),
        (
            "swap_front_f1_gear",
            "Swap F1↔F2, then F1 claims gear",
            swapped,
            _with_first("F1", gear_order),
        ),
    ]

    variants: list[dict[str, Any]] = []
    baseline_score: float | None = None
    baseline_s: float | None = None

    for vid, label, form, order in specs:
        our_gear = gear_maps_for_formation(
            form,
            heroes,
            catalog,
            gear,
            profile=gear_profile,
            gear_order=order,
        )
        block = evaluate_vs_foe(
            form,
            heroes,
            catalog,
            roles,
            foe,
            side=side,
            base_score_fn=base_score_fn,
            our_gear=our_gear,
            lambda_tau=lambda_tau,
            O_scale=O_scale,
            power_by_name=power_by_name,
        )
        score_eff = float(block["score_eff"])
        s_val = float(block["s"])
        if vid == "baseline":
            baseline_score = score_eff
            baseline_s = s_val
            delta = 0.0
            delta_s = 0.0
        else:
            assert baseline_score is not None and baseline_s is not None
            delta = score_eff - baseline_score
            delta_s = s_val - baseline_s
        blurb = None
        if vid != "baseline" and abs(delta) >= 0.05:
            sign = "+" if delta > 0 else ""
            blurb = f"{label}: {sign}{delta:.1f} score_eff (s {baseline_s:.2f}→{s_val:.2f})"
        variants.append(
            {
                "id": vid,
                "label": label,
                "formation": dict(form),
                "gear_order": list(order),
                "score_eff": score_eff,
                "s": s_val,
                "tau_F": float(block["tau_F"]),
                "delta_score_eff": round(delta, 4),
                "delta_s": round(delta_s, 6),
                "blurb": blurb,
            }
        )

    assert baseline_score is not None and baseline_s is not None
    alts = [v for v in variants if v["id"] != "baseline"]
    best = max(alts, key=lambda v: v["delta_score_eff"]) if alts else None
    foe_front = (
        foe.formation.get("F1", "?"),
        foe.formation.get("F2", "?"),
    )
    summary = win_summary_text(
        s=baseline_s,
        score_eff=baseline_score,
        foe_front=foe_front,
        best_alt_label=best["label"] if best else None,
        best_alt_delta=best["delta_score_eff"] if best else None,
    )
    return {
        "primary_foe": foe.model,
        "variants": variants,
        "win_summary": summary,
    }
