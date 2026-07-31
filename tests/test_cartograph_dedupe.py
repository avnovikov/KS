"""Tests for cartograph dedupe."""

from ks.cartograph.dedupe import dedupe_hits
from ks.cartograph.models import StructureHit


def test_merge_nearby_same_label() -> None:
    hits = [
        StructureHit.from_kind("Alliance Iron Mine", "building", 704, 830, source="a"),
        StructureHit.from_kind("Alliance Iron Mine", "building", 704, 831, source="b"),
    ]
    out = dedupe_hits(hits, tile_tol=1)
    assert len(out) == 1


def test_banners_not_merged() -> None:
    hits = [
        StructureHit.from_kind("Banner A", "banner", 695, 820, source="a"),
        StructureHit.from_kind("Banner A", "banner", 695, 820, source="b"),
    ]
    out = dedupe_hits(hits, tile_tol=1)
    assert len(out) == 2
