from tools.alliance_ocr_bench.schema import GoldRow
from tools.alliance_ocr_bench.score import score_predictions


def test_score_perfect_match():
    gold = [GoldRow(id="1", shot="a.png", roi=None, name="DarkLord", power=12.5)]
    pred = [{"name": "DarkLord", "power": 12.5}]
    s = score_predictions(gold, pred)
    assert s.row_tp == 1
    assert s.f1 == 1.0
    assert s.name_exact == 1


def test_score_near_name_counts_row_tp():
    gold = [GoldRow(id="1", shot="a.png", roi=None, name="DarkLord99", power=12.5)]
    pred = [{"name": "DarkLord9", "power": 12.4}]
    s = score_predictions(gold, pred)
    assert s.row_tp == 1
    assert s.name_near == 1
    assert s.power_within_1_0 == 1


def test_score_unrelated_is_fp_and_fn():
    gold = [GoldRow(id="1", shot="a.png", roi=None, name="Alice", power=20.0)]
    pred = [{"name": "Bob", "power": 11.0}]
    s = score_predictions(gold, pred)
    assert s.row_tp == 0
    assert s.row_fp == 1
    assert s.row_fn == 1
