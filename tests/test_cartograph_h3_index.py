"""Tests for KingShot diamond tile ↔ H3 translation helper."""

from __future__ import annotations

import pytest

from ks.cartograph.h3_index import (
    KingdomCrs,
    assert_round_trip_sample,
    default_crs_for_center,
    game_tile_to_h3,
    h3_to_game_tile,
    tile_to_carrier_latlng,
)


def test_default_crs_uses_local_v1_and_detail_res_9() -> None:
    crs = default_crs_for_center(1116, 287, kingdom="2379")
    assert crs.crs_id == "ks-local-v1"
    assert crs.carrier == "synthetic_wgs84"
    assert crs.origin_tile_x == 1116
    assert crs.origin_tile_y == 287
    assert crs.h3_detail_res == 9
    assert crs.h3_region_res == 7
    assert crs.meters_per_tile > 0


def test_game_tile_h3_round_trip_neighborhood() -> None:
    crs = default_crs_for_center(1116, 287, kingdom="2379")
    for dx in range(-8, 9):
        for dy in range(-8, 9):
            tx, ty = 1116 + dx, 287 + dy
            cell = game_tile_to_h3("2379", tx, ty, crs=crs, res=crs.h3_detail_res)
            back = h3_to_game_tile("2379", cell, crs=crs)
            assert back == (tx, ty), f"round-trip failed for {(tx, ty)} -> {cell} -> {back}"


def test_assert_round_trip_sample_fails_closed_on_bad_scale() -> None:
    crs = KingdomCrs(
        crs_id="ks-local-v1",
        origin_tile_x=100,
        origin_tile_y=100,
        meters_per_tile=1.0,  # far too fine vs res 9 → collisions
        carrier="synthetic_wgs84",
        h3_detail_res=9,
        h3_region_res=7,
        kingdom="2379",
    )
    with pytest.raises(ValueError, match=r"H3 round-trip"):
        assert_round_trip_sample(crs, radius=3)


def test_carrier_latlng_is_instrumental_not_identity() -> None:
    crs = default_crs_for_center(0, 0, kingdom="2379")
    lat, lon = tile_to_carrier_latlng(10, 5, crs)
    assert (lat, lon) != (10.0, 5.0)
    assert abs(lat) < 1.0 and abs(lon) < 1.0
