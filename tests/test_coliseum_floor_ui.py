"""Coliseum UI wires stage · round like Radiant (opponents + Generate)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "ks" / "heroes" / "ui" / "static" / "optimiser_coliseum.js"
HTML = ROOT / "ks" / "heroes" / "ui" / "templates" / "optimiser_coliseum.html"


def test_coliseum_js_passes_stage_round_query() -> None:
    text = JS.read_text(encoding="utf-8")
    assert "stage=" in text
    assert "round=" in text
    assert "selectedStageRound" in text
    assert "/api/mystic-trial/coliseum-opponents/" in text
    assert "/api/mystic-trial/coliseum-event-troops/" in text
    assert "/api/optimize/coliseum" in text
    assert "putEventTroops" in text
    assert "loadOpponentDraft" in text
    assert "generate" in text
    assert "radiant-opponents" not in text
    assert "radiant-spire" not in text


def test_coliseum_html_has_stage_round_inputs() -> None:
    text = HTML.read_text(encoding="utf-8")
    assert 'id="coliseum-stage"' in text
    assert 'id="coliseum-round"' in text
    assert 'id="coliseum-event-tier"' in text
    assert 'id="coliseum-event-march-size"' in text
    assert 'id="mode-chips"' in text
    assert 'id="board"' in text
    assert "Generate" in text
    assert 'id="coliseum-regen-inline"' in text
    assert "opponent-apply" in text
    assert "opponent-copy-other" in text
    assert "optimiser_board.js" in text
    assert "160.2" in text


def test_coliseum_js_renders_opponent_picker() -> None:
    text = JS.read_text(encoding="utf-8")
    assert "mountClassHeroPicker" in text
    assert "catalog_by_troop" in text
    assert "Select an opponent march below" in text
    assert "copyOpponentToOther" in text or "Copy to Opponent" in text
