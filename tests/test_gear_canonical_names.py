"""Canonical gear names come from troop + slot + rarity, not OCR titles."""

from __future__ import annotations

from pathlib import Path

import pytest

from ks.heroes.gear_names import canonical_gear_name
from ks.heroes.gear_parse import parse_gear_detail
from ks.heroes.gear_store import GearStore
from ks.heroes.gear_models import GearRecord


def test_cavalry_epic_gloves_are_gauntlets_not_boots() -> None:
    assert (
        canonical_gear_name(troop="cavalry", slot="gloves", rarity="epic")
        == "Crusader's Gauntlets"
    )
    assert (
        canonical_gear_name(troop="cavalry", slot="boots", rarity="epic")
        == "Crusader Battle Boots"
    )


def test_aliases_normalize_before_lookup() -> None:
    assert (
        canonical_gear_name(troop="cavalry", slot="helm", rarity="purple")
        == "Crusader's Armet"
    )
    assert (
        canonical_gear_name(troop="archer", slot="helmet", rarity="gold")
        == "Berserker's Faceplate"
    )


def test_parse_prefers_canonical_over_ocr_boots_title_on_gloves() -> None:
    """OCR bled 'Crusader Battle Boots' onto a gloves piece — table wins."""
    text = """
    Crusader Battle Boots
    Epic
    16,374
    Conquest Stats
    Hero Attack 111
    Expedition Stats
    Cavalry Health +9.00%
    Gloves
    """
    piece = parse_gear_detail(text, page=0, index=17)
    assert piece.slot == "gloves"
    assert piece.troop_type == "cavalry"
    assert piece.rarity == "epic"
    assert piece.name == "Crusader's Gauntlets"


def test_store_upsert_rewrites_name_from_table(tmp_path: Path) -> None:
    store = GearStore(tmp_path)
    store.upsert(
        GearRecord(
            piece_id="page0-cell17",
            name="Crusader Battle Boots",
            troop_type="cavalry",
            slot="gloves",
            rarity="epic",
        )
    )
    got = store.get("page0-cell17")
    assert got is not None
    assert got.name == "Crusader's Gauntlets"
    # Both persistence backends agree.
    reloaded = GearStore(tmp_path).get("page0-cell17")
    assert reloaded is not None
    assert reloaded.name == "Crusader's Gauntlets"


def test_unknown_combo_returns_none() -> None:
    assert canonical_gear_name(troop="cavalry", slot="gloves", rarity="grey") is None
