"""Tests for viewport OCR helpers."""

from ks.placement.viewport_ocr import _in_range, _parse_coords


def test_parse_coords():
    assert _parse_coords("#2339 X:700 Y:817") == (700, 817)
    assert _parse_coords("foo X:696 Y:821 bar") == (696, 821)
    assert _parse_coords("no coords") is None


def test_in_range_bear_trap():
    assert _in_range(700, 817)
    assert not _in_range(687, 629)
    assert not _in_range(800, 817)
