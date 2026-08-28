from tools.alliance_ocr_bench.stability import (
    LONG_NAME_EDIT_LIMIT,
    OCR_MERGE_POWER_GAP,
    normalize_name,
    ocr_edit_distance,
)


def test_normalize_strips_punctuation_and_case():
    assert normalize_name("  Lord_X! ") == "lordx"


def test_ocr_edit_distance_detects_near_miss():
    assert ocr_edit_distance("DarkLord99", "DarkLord9") == 1


def test_ocr_edit_distance_rejects_unrelated():
    assert ocr_edit_distance("Alice", "Bob") is None


def test_merge_gap_constant():
    assert OCR_MERGE_POWER_GAP == 0.5
    assert LONG_NAME_EDIT_LIMIT == 2
