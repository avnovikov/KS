"""Tests for Bear Trap damage simulator."""

from __future__ import annotations

from pathlib import Path

import pytest

from ks.heroes.optimize.bear_damage import (
    BeartrapBuffs,
    fill_ratio_march,
    greedy_fill_march,
    load_beartrap_buffs,
    simulate,
    skillmod_for_observed_score,
)
from ks.heroes.optimize.troop_stats import load_troop_stats


ROOT = Path(__file__).resolve().parents[1]


def test_guide_fixture_t6_balanced_16797() -> None:
    """Community guide: 6k/6k/6k T6 TG0, +25% trap, skillmod=1 → 16797."""
    result = simulate(
        {"infantry": 6000, "cavalry": 6000, "archers": 6000},
        {"infantry": 243, "cavalry": 730, "archers": 974},
        skillmod=1.0,
        trap_attack_bonus=0.25,
    )
    assert result.score == 16797


def test_calibration_skillmod_hits_180k_balanced() -> None:
    n = 80_245
    each = n // 3
    rem = n - 3 * each
    counts = {
        "infantry": each,
        "cavalry": each,
        "archers": each + rem,
    }
    attack = {"infantry": 243, "cavalry": 730, "archers": 974}
    sm = skillmod_for_observed_score(
        counts, attack, 180_000, trap_attack_bonus=0.25
    )
    score = simulate(
        counts, attack, skillmod=sm, trap_attack_bonus=0.25
    ).score
    assert abs(score - 180_000) / 180_000 <= 0.01
    assert 4.5 <= sm <= 5.5


def test_greedy_prefers_archers_from_inventory() -> None:
    table = load_troop_stats(ROOT / "config" / "troop_stats.yaml")
    inventory = {
        "infantry": {6: 20_000},
        "cavalry": {6: 20_000},
        "archers": {6: 40_000},
    }
    counts, _levels, result = greedy_fill_march(
        inventory,
        capacity=18_000,
        table=table,
        skillmod=1.0,
        trap_attack_bonus=0.25,
    )
    assert counts["archers"] >= counts["cavalry"]
    assert counts["archers"] >= counts["infantry"]
    assert sum(counts.values()) == 18_000
    assert result.score > 0


def test_fill_ratio_balanced_uses_capacity() -> None:
    table = load_troop_stats(ROOT / "config" / "troop_stats.yaml")
    inventory = {
        "infantry": {6: 50_000},
        "cavalry": {6: 50_000},
        "archers": {6: 50_000},
    }
    counts, _, units = fill_ratio_march(
        inventory,
        capacity=80_245,
        ratios={"infantry": 1, "cavalry": 1, "archers": 1},
        table=table,
    )
    assert sum(counts.values()) == 80_245
    assert units["infantry"] is not None
    assert abs(counts["infantry"] - counts["archers"]) <= 2


def test_load_beartrap_buffs_defaults() -> None:
    path = ROOT / "config" / "beartrap_buffs.yaml"
    buffs = load_beartrap_buffs(path)
    assert isinstance(buffs, BeartrapBuffs)
    assert buffs.trap_level == 5
    assert buffs.trap_attack_bonus == 0.25
    assert buffs.research_skillmod == pytest.approx(1.0)
    # Default assumed joiners: 2×101 + 2×102 at 25% → product 2.25
    assert buffs.joiner_damage_up_product() == pytest.approx(2.25)
    assert buffs.effective_skillmod() == pytest.approx(1.0 * 2.25)


def test_bucket_product_same_op_adds_then_scales() -> None:
    from ks.heroes.optimize.bear_damage import bucket_product

    # Four Chenkos at 25% (op 101) → 1 + 100/100 = 2.0
    assert bucket_product({101: 100.0}) == pytest.approx(2.0)
    # Two Chenko + two Amane → 1.5 * 1.5 = 2.25
    assert bucket_product({101: 50.0, 102: 50.0}) == pytest.approx(2.25)


def test_compute_skillmod_multiplies_research_and_damage_up() -> None:
    from ks.heroes.optimize.bear_damage import compute_skillmod

    sm = compute_skillmod(
        research=1.2,
        damage_up={101: 50.0, 102: 50.0},
    )
    assert sm == pytest.approx(1.2 * 2.25)


def test_host_damage_up_buckets_from_catalog_lethality() -> None:
    from ks.heroes.models import HeroRecord
    from ks.heroes.optimize.bear_damage import host_skillmod_buckets
    from ks.heroes.optimize.types import CatalogEntry, EffectTag

    hero = HeroRecord(name="Chenko", stars=5, pellets=0)
    entry = CatalogEntry(
        name="Chenko",
        troop="cavalry",
        effects=(
            EffectTag(
                "lethality_up",
                25.0,
                "expedition",
                effect_op=101,
                first_expedition=True,
            ),
        ),
    )
    buckets = host_skillmod_buckets([(hero, entry)])
    assert buckets["damage_up"][101] == pytest.approx(25.0)
    assert buckets["damage_up"].get(102, 0.0) == 0.0
