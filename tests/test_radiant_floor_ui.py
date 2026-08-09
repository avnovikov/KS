"""Radiant Spire UI wires floor query param for MC ranking."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "ks" / "heroes" / "ui" / "static" / "optimiser_radiant_spire.js"
HTML = ROOT / "ks" / "heroes" / "ui" / "templates" / "optimiser_radiant_spire.html"


def test_radiant_js_passes_floor_query() -> None:
    text = JS.read_text(encoding="utf-8")
    assert "?floor=" in text
    assert "selectedFloor" in text


def test_radiant_html_has_floor_select() -> None:
    text = HTML.read_text(encoding="utf-8")
    assert 'id="radiant-floor"' in text
    assert "Proxy only" in text
