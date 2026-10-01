"""Radiant Spire UI wires stage · round for MC + saved opponents."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "ks" / "heroes" / "ui" / "static" / "optimiser_radiant_spire.js"
HTML = ROOT / "ks" / "heroes" / "ui" / "templates" / "optimiser_radiant_spire.html"


def test_radiant_html_has_stage_round_inputs() -> None:
    text = HTML.read_text(encoding="utf-8")
    assert 'id="radiant-stage"' in text
    assert 'id="radiant-round"' in text
    assert 'id="radiant-event-tier"' in text
    assert 'id="radiant-event-march-size"' in text
    assert 'id="mode-chips"' in text
    assert 'id="board"' in text
    assert "radiant-floor" not in text
    assert "radiant-player-bonuses" not in text
    assert "player-bonus" not in text
    assert "Generate" in text
    assert 'id="radiant-regen-inline"' in text


def test_radiant_js_passes_stage_round_query() -> None:
    text = JS.read_text(encoding="utf-8")
    assert "stage=" in text
    assert "round=" in text
    assert "selectedStageRound" in text
    assert "/api/mystic-trial/radiant-opponents/" in text
    assert "/api/mystic-trial/radiant-event-troops/" in text
    assert "putEventTroops" in text
    assert "loadOpponentDraft" in text
    assert "generate" in text
    assert "radiant-player-bonuses" not in text
    assert "player-bonus" not in text


def test_radiant_js_renders_opponent_bonuses() -> None:
    text = JS.read_text(encoding="utf-8")
    assert "renderSelectedBoard" in text or "renderMarchReport" in text
    assert "lethality_pct" in text
    assert "fmtBonus" in text
    assert "OptimiserBoard" in text
    assert "mountClassHeroPicker" in text
    assert "catalog_by_troop" in text
    assert "mode-chips" in text or "renderModeChips" in text
    assert "Select an opponent march below" in text
    assert 'data-field="level"' in text
    assert 'data-field="count"' in text
    html = HTML.read_text(encoding="utf-8")
    assert "opponent-apply" in html
    assert "opponent-copy-other" in html
    assert "opponent-troop-edit" in html
    assert "optimiser_board.js" in html
    assert "percent-points" in html
    assert "115" in html
    assert "copyOpponentToOther" in text or "Copy to Opponent" in text
    board = (
        ROOT / "ks" / "heroes" / "ui" / "static" / "optimiser_board.js"
    ).read_text(encoding="utf-8")
    assert "mountClassHeroPicker" in board
    assert "class-hero-cell" in board
