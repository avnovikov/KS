"""Event lineups troopsLine shows % of march capacity."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVENTS_JS = ROOT / "ks" / "heroes" / "ui" / "static" / "optimiser_events.js"


def test_events_troops_line_uses_capacity_percent() -> None:
    text = EVENTS_JS.read_text(encoding="utf-8")
    chunk = text.split("function troopsLine")[1].split("function breakdownLine")[0]
    assert 'Math.round((100 * Number(v)) / cap) + "%"' in chunk
    assert "effective_capacity" in chunk
    assert "joiner-without-lead-btn" in text
    assert "solveJoinerWithoutLead" in text
