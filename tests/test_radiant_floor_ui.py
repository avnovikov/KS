"""Radiant Spire UI wires stage · round for MC + saved opponents."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "ks" / "heroes" / "ui" / "static" / "optimiser_radiant_spire.js"
HTML = ROOT / "ks" / "heroes" / "ui" / "templates" / "optimiser_radiant_spire.html"


def test_radiant_js_passes_stage_round_query() -> None:
    text = JS.read_text(encoding="utf-8")
    assert "stage=" in text
    assert "round=" in text
    assert "selectedStageRound" in text
    assert "/api/mystic-trial/radiant-opponents/" in text


def test_radiant_html_has_stage_round_inputs() -> None:
    text = HTML.read_text(encoding="utf-8")
    assert 'id="radiant-stage"' in text
    assert 'id="radiant-round"' in text
    assert 'id="mode-chips"' in text
    assert 'id="board"' in text
    assert "radiant-floor" not in text


def test_radiant_js_renders_opponent_bonuses() -> None:
    text = JS.read_text(encoding="utf-8")
    assert "renderSelectedBoard" in text or "renderMarchReport" in text
    assert "lethality_pct" in text
    assert "fmtBonus" in text
    assert "OptimiserBoard" in text
    assert "mode-chips" in text or "renderModeChips" in text
    assert "Select an opponent march below" in text
    assert 'data-field="level"' in text
    assert 'data-field="count"' in text
    html = HTML.read_text(encoding="utf-8")
    assert "opponent-apply" in html
    assert "opponent-copy-other" in html
    assert "opponent-troop-edit" in html
    assert "optimiser_board.js" in html
    assert "bonus only" in html.lower() or "on top of 1" in html
    assert "copyOpponentToOther" in text or "Copy to Opponent" in text
