"""Bidirectional KingShot diamond tile ↔ H3 index helper.

Synthetic WGS84 is an H3 API carrier only — not Earth GPS. Diamond tiles remain
the primary gameplay coordinate system. Always translate through this module.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Mapping

import h3

METERS_PER_DEGREE = 111_320.0
# Chosen so res-9 cell centres uniquely nearest-neighbour back to integer tiles
# for a local neighbourhood (verified by round-trip tests).
DEFAULT_METERS_PER_TILE = 400.0
UI_PIN_KINDS = frozenset({"city", "mill", "hq", "banner", "building", "trap"})


@dataclass(frozen=True)
class KingdomCrs:
    """Instrumental local CRS used only to feed/recover H3 indexes."""

    crs_id: str
    origin_tile_x: int
    origin_tile_y: int
    meters_per_tile: float
    carrier: str
    h3_detail_res: int
    h3_region_res: int
    kingdom: str = ""

    def __post_init__(self) -> None:
        if self.crs_id != "ks-local-v1":
            raise ValueError(f"unsupported crs_id {self.crs_id!r}")
        if self.carrier != "synthetic_wgs84":
            raise ValueError(f"unsupported carrier {self.carrier!r}")
        if self.meters_per_tile <= 0:
            raise ValueError(
                f"meters_per_tile must be positive; got {self.meters_per_tile}"
            )
        if not (0 <= self.h3_detail_res <= 15):
            raise ValueError(f"invalid h3_detail_res {self.h3_detail_res}")
        if not (0 <= self.h3_region_res <= 15):
            raise ValueError(f"invalid h3_region_res {self.h3_region_res}")

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_json(raw: Mapping[str, Any]) -> KingdomCrs:
        return KingdomCrs(
            crs_id=str(raw["crs_id"]),
            origin_tile_x=int(raw["origin_tile_x"]),
            origin_tile_y=int(raw["origin_tile_y"]),
            meters_per_tile=float(raw["meters_per_tile"]),
            carrier=str(raw["carrier"]),
            h3_detail_res=int(raw["h3_detail_res"]),
            h3_region_res=int(raw["h3_region_res"]),
            kingdom=str(raw.get("kingdom") or ""),
        )


def default_crs_for_center(
    center_x: int,
    center_y: int,
    *,
    kingdom: str,
    meters_per_tile: float = DEFAULT_METERS_PER_TILE,
) -> KingdomCrs:
    return KingdomCrs(
        crs_id="ks-local-v1",
        origin_tile_x=int(center_x),
        origin_tile_y=int(center_y),
        meters_per_tile=float(meters_per_tile),
        carrier="synthetic_wgs84",
        h3_detail_res=9,
        h3_region_res=7,
        kingdom=kingdom,
    )


def tile_to_carrier_latlng(
    tile_x: int,
    tile_y: int,
    crs: KingdomCrs,
) -> tuple[float, float]:
    """Map a diamond tile to synthetic lat/lng (instrumental carrier only)."""
    east_m = (tile_x - crs.origin_tile_x) * crs.meters_per_tile
    north_m = (tile_y - crs.origin_tile_y) * crs.meters_per_tile
    lat = north_m / METERS_PER_DEGREE
    lon = east_m / METERS_PER_DEGREE
    return float(lat), float(lon)


def carrier_latlng_to_tile(
    lat: float,
    lon: float,
    crs: KingdomCrs,
) -> tuple[int, int]:
    """Nearest diamond tile for a synthetic lat/lng carrier point."""
    north_m = lat * METERS_PER_DEGREE
    east_m = lon * METERS_PER_DEGREE
    tile_x = int(round(crs.origin_tile_x + east_m / crs.meters_per_tile))
    tile_y = int(round(crs.origin_tile_y + north_m / crs.meters_per_tile))
    return tile_x, tile_y


def game_tile_to_h3(
    kingdom: str,
    tile_x: int,
    tile_y: int,
    *,
    crs: KingdomCrs,
    res: int | None = None,
) -> str:
    if crs.kingdom and kingdom != crs.kingdom:
        raise ValueError(
            f"kingdom mismatch: got {kingdom!r}, crs has {crs.kingdom!r}"
        )
    resolution = crs.h3_detail_res if res is None else int(res)
    lat, lon = tile_to_carrier_latlng(tile_x, tile_y, crs)
    return str(h3.latlng_to_cell(lat, lon, resolution))


def h3_to_game_tile(
    kingdom: str,
    h3_index: str,
    *,
    crs: KingdomCrs,
) -> tuple[int, int]:
    if crs.kingdom and kingdom != crs.kingdom:
        raise ValueError(
            f"kingdom mismatch: got {kingdom!r}, crs has {crs.kingdom!r}"
        )
    if not h3_index:
        raise ValueError("h3_index must be non-empty")
    lat, lon = h3.cell_to_latlng(h3_index)
    return carrier_latlng_to_tile(float(lat), float(lon), crs)


def assert_round_trip_sample(
    crs: KingdomCrs,
    *,
    radius: int = 8,
    res: int | None = None,
) -> None:
    """Fail closed if any tile in the sample neighbourhood loses identity."""
    if radius < 0:
        raise ValueError(f"radius must be non-negative; got {radius}")
    resolution = crs.h3_detail_res if res is None else int(res)
    kingdom = crs.kingdom or "0"
    failures: list[str] = []
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            tx = crs.origin_tile_x + dx
            ty = crs.origin_tile_y + dy
            cell = game_tile_to_h3(kingdom, tx, ty, crs=crs, res=resolution)
            back = h3_to_game_tile(kingdom, cell, crs=crs)
            if back != (tx, ty):
                failures.append(f"{(tx, ty)} -> {cell} -> {back}")
    if failures:
        raise ValueError(
            "H3 round-trip disagreed for "
            f"{len(failures)} tile(s); first={failures[0]}"
        )


def is_ui_pin_kind(kind: str) -> bool:
    return kind in UI_PIN_KINDS
