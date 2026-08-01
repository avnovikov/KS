"""Gear UI icon generation."""

from __future__ import annotations

from pathlib import Path

from ks.heroes.gear_models import GearRecord
from ks.heroes.ui.icons import ensure_all_icons, ensure_piece_icon


def test_bundled_web_icons_preferred(tmp_path: Path) -> None:
    pieces = [
        GearRecord(
            piece_id="page0-cell0",
            name="Judicator's Armet",
            troop_type="cavalry",
            slot="helmet",
            rarity="mythic",
            enhancement_level=51,
        ),
        GearRecord(
            piece_id="page0-cell1",
            name="Berserker's Boots",
            troop_type="archers",
            slot="boots",
            rarity="epic",
            enhancement_level=17,
        ),
    ]
    mapping = ensure_all_icons(pieces, tmp_path)
    assert mapping["page0-cell0"] == "/static/gear-pieces/cavalry-helm.png"
    assert mapping["page0-cell1"] == "/static/gear-pieces/archer-boots.png"
    assert (tmp_path / "icons" / "page0-cell0.png").is_file()


def test_icon_url_stable(tmp_path: Path) -> None:
    piece = GearRecord(
        piece_id="x",
        name="Warrior's Helm",
        troop_type="infantry",
        slot="helmet",
        rarity="green",
    )
    a = ensure_piece_icon(piece, tmp_path)
    b = ensure_piece_icon(piece, tmp_path)
    assert a == b
    assert a == "/static/gear-pieces/infantry-helm.png"
