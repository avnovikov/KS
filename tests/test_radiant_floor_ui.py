"""Radiant Spire UI wires floor query param for MC ranking."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "ks" / "heroes" / "ui" / "static" / "optimiser_radiant_spire.js"
HTML = ROOT / "ks" / "heroes" / "ui" / "templates" / "optimiser_radiant_spire.html"


def test_radiant_js_passes_floor_query() -> None:
    text = JS.read_text(encoding="utf-8")
    assert "floor=" in text
    assert "selectedFloor" in text


def test_radiant_html_has_floor_select() -> None:
    text = HTML.read_text(encoding="utf-8")
    assert 'id="radiant-floor"' in text
    assert "Proxy only" in text
    assert 'id="mode-chips"' in text
    assert 'id="board"' in text


def test_radiant_js_renders_opponent_bonuses() -> None:
    text = JS.read_text(encoding="utf-8")
    assert "renderSelectedBoard" in text or "renderMarchReport" in text
    assert "lethality_pct" in text
    assert "enemy_infantry=" in text
    assert "OptimiserBoard" in text
    assert "mode-chips" in text or "renderModeChips" in text
    html = HTML.read_text(encoding="utf-8")
    assert "opponent-apply" in html
    assert "optimiser_board.js" in html

