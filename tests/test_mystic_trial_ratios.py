"""Shared mystic-trial ratio helpers."""

from __future__ import annotations

from ks.heroes.optimize.mystic_trial.ratios import ratio_candidates


def test_ratio_candidates_include_radiant_seed() -> None:
    cands = ratio_candidates()
    assert any(
        abs(r["infantry"] - 0.50) < 1e-9
        and abs(r["cavalry"] - 0.15) < 1e-9
        and abs(r["archers"] - 0.35) < 1e-9
        for r in cands
    )
