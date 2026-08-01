"""Gear UI icon generation."""

from __future__ import annotations

from pathlib import Path

from ks.heroes.gear_models import GearRecord
from ks.heroes.ui.icons import ensure_all_icons, ensure_piece_icon


def test_svg_icon_created_for_each_piece(tmp_path: Path) -> None:
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
    assert len(mapping) == 2
    for piece_id, url in mapping.items():
        assert url.startswith("/icons/")
        disk = tmp_path / "icons" / url.rsplit("/", 1)[-1]
        assert disk.is_file()
        text = disk.read_text(encoding="utf-8")
        assert "<svg" in text


def test_icon_url_stable(tmp_path: Path) -> None:
    piece = GearRecord(piece_id="x", name="Warrior's Helm", slot="helmet", rarity="green")
    a = ensure_piece_icon(piece, tmp_path)
    b = ensure_piece_icon(piece, tmp_path)
    assert a == b
