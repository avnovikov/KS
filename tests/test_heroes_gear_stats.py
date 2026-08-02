"""Formula-first expedition stats (rarity + level + mastery)."""

from __future__ import annotations

import pytest

from ks.heroes.gear_models import GearRecord, GearStats
from ks.heroes.optimize.gear_assign import piece_score
from ks.heroes.optimize.gear_stats import (
    expedition_stat_fraction,
    ocr_stat_delta_pct,
)


def test_mythic_level_51_mastery_2_matches_known_ocr() -> None:
    frac = expedition_stat_fraction("mythic", 51, 2)
    assert frac is not None
    assert round(frac * 100, 2) == 39.42


def test_epic_level_41_matches_optimizer_table() -> None:
    frac = expedition_stat_fraction("epic", 41, 0)
    assert frac is not None
    assert round(frac * 100, 2) == 17.61


@pytest.mark.parametrize(
    ("level", "pct"),
    [(0, 6.0), (7, 6.98), (8, 7.12), (9, 7.26)],
)
def test_blue_linear_calibration(level: int, pct: float) -> None:
    frac = expedition_stat_fraction("blue", level, 0)
    assert frac is not None
    assert round(frac * 100, 2) == pct


def test_red_level_120() -> None:
    frac = expedition_stat_fraction("red", 120, 0)
    assert frac is not None
    assert round(frac * 100, 1) == 60.0


def test_grey_green_have_no_formula() -> None:
    assert expedition_stat_fraction("grey", 10, 0) is None
    assert expedition_stat_fraction("green", 10, 0) is None


def test_ocr_delta_near_zero_for_calibrated_mythic() -> None:
    delta = ocr_stat_delta_pct(39.42, "mythic", 51, 2)
    assert delta is not None
    assert abs(delta) < 0.05


def test_piece_score_rises_when_enhancement_rises_with_frozen_ocr() -> None:
    """OCR stats must not freeze score across level-ups."""
    frozen = GearStats(lethality=39.42, expedition={"Cavalry Lethality": 39.42})
    low = GearRecord(
        piece_id="x",
        name="Judicator's Armet",
        troop_type="cavalry",
        slot="helmet",
        rarity="mythic",
        enhancement_level=51,
        mastery_level=2,
        power=152_100,
        stats=frozen,
    )
    high = GearRecord(
        piece_id="x",
        name="Judicator's Armet",
        troop_type="cavalry",
        slot="helmet",
        rarity="mythic",
        enhancement_level=61,
        mastery_level=2,
        power=168_214,
        stats=frozen,
    )
    assert piece_score(high) > piece_score(low)
