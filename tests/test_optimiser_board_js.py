"""Shared OptimiserBoard helpers ship for Mystic Trial pages."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "ks" / "heroes" / "ui" / "static" / "optimiser_board.js"


def test_optimiser_board_exports_march_helpers() -> None:
    text = BOARD.read_text(encoding="utf-8")
    assert "appendMarchBoard" in text
    assert "renderMarchReport" in text
    assert "renderModeChips" in text
    assert "troopsLine" in text
    assert "heroSlotEl" in text
    assert "OptimiserBoard" in text
    assert "global.OptimiserBoard" in text or "OptimiserBoard =" in text


def test_optimiser_board_troops_line_uses_capacity_percent() -> None:
    text = BOARD.read_text(encoding="utf-8")
    chunk = text.split("function troopsLine")[1].split("function fmtCounts")[0]
    assert 'Math.round((100 * Number(v)) / cap) + "%"' in chunk
