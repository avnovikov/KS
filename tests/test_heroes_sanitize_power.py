"""Unit tests for power OCR sanitize (leading-digit glitch handling)."""

from __future__ import annotations

from ks.heroes.collector import _sanitize_power


def test_keeps_sub_million_power() -> None:
    assert _sanitize_power(172_650, previous=None) == 172_650


def test_keeps_legitimate_million_without_previous() -> None:
    assert _sanitize_power(1_726_500, previous=None) == 1_726_500
    assert _sanitize_power(1_500_000, previous=None) == 1_500_000


def test_keeps_legitimate_million_near_previous() -> None:
    assert _sanitize_power(1_726_500, previous=1_700_000) == 1_726_500
    assert _sanitize_power(1_500_000, previous=1_400_000) == 1_500_000


def test_strips_leading_digit_glitch_vs_previous() -> None:
    # 8 glued onto prior ~172650
    assert _sanitize_power(8_172_650, previous=172_650) == 172_650


def test_rejects_implausible_keeps_previous() -> None:
    assert _sanitize_power(9_999_999, previous=100_000) == 100_000
