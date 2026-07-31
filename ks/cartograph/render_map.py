"""Cartograph map: isometric SVG (game-like) + Excel-friendly tile grid."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from html import escape
from io import StringIO
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from ks.cartograph.h3_index import UI_PIN_KINDS
from ks.cartograph.icons import ICON_SVG, legend_items
from ks.cartograph.models import FOOTPRINTS, StructureHit

if TYPE_CHECKING:
    from ks.cartograph.entities import EntityCatalogEntry
    from ks.cartograph.mosaic import MosaicResult
    from ks.cartograph.registration import GlobalRegistration

MAX_DIGITAL_MAP_TILE_CANDIDATES = 100_000
DEFAULT_LATTICE_STEP = 2


@dataclass(frozen=True)
class MapEntity:
    kind: str
    x: int
    y: int
    label: str
    level: int | None = None
    w: int = 1
    h: int = 1
    identity: str | None = None
    confidence: float | None = None
    provenance: str | None = None
    source_frames: tuple[str, ...] = ()
    coordinate_residual_px: float | None = None
    popup_path: str | None = None

    @staticmethod
    def from_hit(hit: StructureHit, level: int | None = None) -> MapEntity:
        return MapEntity(
            kind=hit.kind,
            x=hit.x,
            y=hit.y,
            label=hit.label,
            level=level,
            w=hit.w,
            h=hit.h,
        )

    @staticmethod
    def from_catalog_entry(entry: EntityCatalogEntry) -> MapEntity:
        from ks.cartograph.entities import EntityCatalogEntry as _Entry

        if not isinstance(entry, _Entry):
            raise TypeError("entry must be an EntityCatalogEntry")
        return MapEntity(
            kind=entry.kind,
            x=entry.tile_x,
            y=entry.tile_y,
            label=entry.label or (entry.identity or entry.kind),
            level=entry.level,
            w=entry.w,
            h=entry.h,
            identity=entry.identity,
            confidence=entry.confidence,
            provenance=entry.provenance,
            source_frames=entry.source_frames,
            coordinate_residual_px=entry.coordinate_residual_px,
            popup_path=entry.popup_path,
        )


def _iso(x: float, y: float, tile_w: float, tile_h: float) -> tuple[float, float]:
    return (x - y) * (tile_w / 2.0), (x + y) * (tile_h / 2.0)


def _diamond(
    x: int, y: int, w: int, h: int, tile_w: float, tile_h: float, ox: float, oy: float
) -> str:
    pts = []
    for cx, cy in _footprint_world_corners(x, y, w, h):
        sx, sy = _iso(cx, cy, tile_w, tile_h)
        pts.append(f"{sx + ox:.1f},{sy + oy:.1f}")
    return " ".join(pts)


def _footprint_world_corners(
    x: float,
    y: float,
    w: float,
    h: float,
) -> tuple[tuple[float, float], ...]:
    left = x - 0.5
    top = y - 0.5
    right = x + w - 0.5
    bottom = y + h - 0.5
    return ((left, top), (right, top), (right, bottom), (left, bottom))


def _legacy_footprint_world_corners(
    x: float,
    y: float,
    w: float,
    h: float,
) -> tuple[tuple[float, float], ...]:
    return ((x, y), (x + w, y), (x + w, y + h), (x, y + h))


def _footprint_world_center(
    x: float,
    y: float,
    w: float,
    h: float,
) -> tuple[float, float]:
    return x + (w - 1.0) / 2.0, y + (h - 1.0) / 2.0


def _bounds(entities: list[MapEntity], center: tuple[int, int], pad: int) -> tuple[int, int, int, int]:
    xs = [center[0]]
    ys = [center[1]]
    for e in entities:
        xs += [e.x, e.x + e.w - 1]
        ys += [e.y, e.y + e.h - 1]
    return min(xs) - pad, max(xs) + pad, min(ys) - pad, max(ys) + pad


def _validate_center_matches_mosaic(
    center: tuple[int, int],
    mosaic: MosaicResult,
) -> None:
    if tuple(center) != tuple(mosaic.center):
        raise ValueError(
            f"center must match mosaic center; got {center} vs {mosaic.center}"
        )


def _mosaic_world_bounds(
    mosaic: MosaicResult,
) -> tuple[float, float, float, float]:
    from ks.cartograph.mosaic import panorama_world_bounds

    world_bounds = panorama_world_bounds(mosaic)
    numeric_bounds = np.asarray(world_bounds, dtype=float)
    if not np.isfinite(numeric_bounds).all():
        raise ValueError("panorama world bounds must contain finite values")
    return world_bounds


def _integer_mosaic_bounds(mosaic: MosaicResult) -> tuple[int, int, int, int]:
    min_x, min_y, max_x, max_y = _mosaic_world_bounds(mosaic)
    return (
        int(np.floor(min_x)),
        int(np.ceil(max_x)),
        int(np.floor(min_y)),
        int(np.ceil(max_y)),
    )


def _bounded_tile_centers(mosaic: MosaicResult) -> tuple[range, range]:
    min_x, min_y, max_x, max_y = _mosaic_world_bounds(mosaic)
    first_x, last_x = int(np.ceil(min_x)), int(np.floor(max_x))
    first_y, last_y = int(np.ceil(min_y)), int(np.floor(max_y))
    x_count = max(0, last_x - first_x + 1)
    y_count = max(0, last_y - first_y + 1)
    if x_count * y_count > MAX_DIGITAL_MAP_TILE_CANDIDATES:
        raise ValueError(
            "tile bounds exceed safe export limit; "
            f"candidate grid is {x_count}x{y_count}"
        )
    return range(first_x, last_x + 1), range(first_y, last_y + 1)


def _affine_pan_to_iso(
    mosaic: MosaicResult,
    *,
    ox: float,
    oy: float,
    tile_w: float,
    tile_h: float,
) -> str:
    """CSS/SVG matrix mapping panorama pixels → isometric SVG coords.

    Fits three world anchors so the unrotated bitmap sits under the diamond grid
    for completeness checks without warping the photo itself.
    """
    from ks.cartograph.mosaic import world_to_panorama

    cx, cy = mosaic.center
    anchors = [(cx, cy), (cx + 8, cy), (cx, cy + 8)]
    src: list[tuple[float, float]] = []
    dst: list[tuple[float, float]] = []
    for wx, wy in anchors:
        px, py = world_to_panorama(wx, wy, mosaic)
        sx, sy = _iso(wx, wy, tile_w, tile_h)
        src.append((px, py))
        dst.append((sx + ox, sy + oy))

    # Solve [x y 1 0 0 0; 0 0 0 x y 1] @ [a,c,e,b,d,f] = [u,v]
    A = np.zeros((6, 6), dtype=float)
    B = np.zeros(6, dtype=float)
    for i, ((x, y), (u, v)) in enumerate(zip(src, dst)):
        A[2 * i] = [x, y, 1, 0, 0, 0]
        A[2 * i + 1] = [0, 0, 0, x, y, 1]
        B[2 * i] = u
        B[2 * i + 1] = v
    sol, *_ = np.linalg.lstsq(A, B, rcond=None)
    a, c, e, b, d, f = sol
    # CSS matrix(a,b,c,d,e,f): x'=a*x+c*y+e, y'=b*x+d*y+f
    return f"matrix({a:.6f},{b:.6f},{c:.6f},{d:.6f},{e:.6f},{f:.6f})"


def render_isometric_work_svg(
    entities: list[MapEntity],
    *,
    center: tuple[int, int],
    kingdom: str = "",
    tile_w: float = 36,
    tile_h: float = 20,
    pad_tiles: int = 4,
    mosaic: MosaicResult | None = None,
    max_svg_px: float = 2800.0,
) -> tuple[str, float, float, float, float, str | None]:
    """Isometric diamond working grid. Bounds follow mosaic coverage when given."""
    min_x, max_x, min_y, max_y = _bounds(entities, center, pad_tiles)
    if mosaic is not None:
        _validate_center_matches_mosaic(center, mosaic)
        mosaic_min_x, mosaic_max_x, mosaic_min_y, mosaic_max_y = (
            _integer_mosaic_bounds(mosaic)
        )
        min_x = min(min_x, mosaic_min_x)
        max_x = max(max_x, mosaic_max_x)
        min_y = min(min_y, mosaic_min_y)
        max_y = max(max_y, mosaic_max_y)

    span_x = max(1, max_x - min_x + 1)
    span_y = max(1, max_y - min_y + 1)
    # Shrink diamond size so full mosaic coverage still fits on screen
    # Iso canvas ~ span*(tile_w+tile_h); keep under max_svg_px.
    est = max(span_x, span_y) * (tile_w + tile_h) * 0.55
    if est > max_svg_px:
        shrink = max_svg_px / est
        tile_w = max(8.0, tile_w * shrink)
        tile_h = max(5.0, tile_h * shrink)
    # Sparse minor grid when huge
    grid_step = 1 if max(span_x, span_y) <= 70 else 2

    corners = [
        _iso(min_x, min_y, tile_w, tile_h),
        _iso(max_x + 1, min_y, tile_w, tile_h),
        _iso(min_x, max_y + 1, tile_w, tile_h),
        _iso(max_x + 1, max_y + 1, tile_w, tile_h),
    ]
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    margin = 48.0
    ox = -min(xs) + margin
    oy = -min(ys) + margin
    width = max(xs) - min(xs) + 2 * margin
    height = max(ys) - min(ys) + 2 * margin + 28

    parts: list[str] = [
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{width:.0f}' height='{height:.0f}' "
        f"viewBox='0 0 {width:.0f} {height:.0f}' "
        f"style='position:absolute;left:0;top:0;pointer-events:none;background:transparent'>",
        "<defs>",
    ]
    for kind, body in ICON_SVG.items():
        parts.append(f'<g id="wicon-{kind}">{body}</g>')
    parts.append("</defs>")
    parts.append(
        "<style>text{font-family:ui-monospace,Menlo,monospace;font-size:11px;fill:#e8ffe8;"
        "paint-order:stroke;stroke:#0b120c;stroke-width:2.5px}</style>"
    )
    parts.append(
        f"<text x='14' y='20' fill='#9fd0ff'>"
        f"Kingdom #{escape(kingdom)} · isometric grid covering mosaic "
        f"[{min_x}..{max_x}]×[{min_y}..{max_y}] · center {center[0]},{center[1]}</text>"
    )

    for x in range(min_x, max_x + 1, grid_step):
        for y in range(min_y, max_y + 1, grid_step):
            poly = _diamond(x, y, grid_step, grid_step, tile_w, tile_h, ox, oy)
            stroke = "#9fd0ff" if ((x + y) // grid_step) % 2 == 0 else "#5ec8ff"
            parts.append(
                f"<polygon points='{poly}' fill='none' stroke='{stroke}' "
                f"stroke-opacity='0.28' stroke-width='0.8'/>"
            )

    label_step = 5 if grid_step == 1 else 10
    for x in range(min_x, max_x + 1):
        if x % label_step:
            continue
        sx, sy = _iso(x + 0.5, min_y - 0.2, tile_w, tile_h)
        parts.append(
            f"<text x='{sx + ox:.1f}' y='{sy + oy:.1f}' text-anchor='middle' "
            f"fill='#9fd0ff' font-size='9'>X{x}</text>"
        )
    for y in range(min_y, max_y + 1):
        if y % label_step:
            continue
        sx, sy = _iso(min_x - 0.2, y + 0.5, tile_w, tile_h)
        parts.append(
            f"<text x='{sx + ox:.1f}' y='{sy + oy:.1f}' text-anchor='end' "
            f"fill='#9fd0ff' font-size='9'>Y{y}</text>"
        )

    ccx, ccy = center
    poly = _diamond(ccx, ccy, 1, 1, tile_w, tile_h, ox, oy)
    parts.append(
        f"<polygon points='{poly}' fill='#1e3a5f' fill-opacity='0.4' "
        f"stroke='#5ec8ff' stroke-width='2.5'/>"
    )

    for e in entities:
        poly = _diamond(e.x, e.y, e.w, e.h, tile_w, tile_h, ox, oy)
        parts.append(
            f"<polygon points='{poly}' fill='#0b120c' fill-opacity='0.2' "
            f"stroke='#ffe9c8' stroke-width='1.6'/>"
        )
        entity_center = _footprint_world_center(e.x, e.y, e.w, e.h)
        sx, sy = _iso(*entity_center, tile_w, tile_h)
        kind = e.kind if e.kind in ICON_SVG else "rss"
        parts.append(
            f'<use href="#wicon-{kind}" x="{sx + ox - 16:.1f}" y="{sy + oy - 20:.1f}"/>'
        )
        lvl = f" L{e.level}" if e.level is not None else ""
        parts.append(
            f"<text x='{sx + ox:.1f}' y='{sy + oy + 18:.1f}' text-anchor='middle' "
            f"font-size='10' fill='#ffe9c8'>{escape(e.label)}{lvl}</text>"
        )
        parts.append(
            f"<text x='{sx + ox:.1f}' y='{sy + oy + 30:.1f}' text-anchor='middle' "
            f"font-size='9' fill='#cfe8d4'>{e.x},{e.y}</text>"
        )

    parts.append("</svg>")
    matrix = None
    if mosaic is not None:
        matrix = _affine_pan_to_iso(
            mosaic, ox=ox, oy=oy, tile_w=tile_w, tile_h=tile_h
        )
    return "\n".join(parts), width, height, ox, oy, matrix


def render_excel_grid_csv(
    entities: list[MapEntity],
    *,
    center: tuple[int, int],
    pad_tiles: int = 2,
) -> str:
    """Orthogonal X→columns, Y→rows for paste into Excel / Sheets."""
    min_x, max_x, min_y, max_y = _bounds(entities, center, pad_tiles)
    cell: dict[tuple[int, int], str] = {}
    for e in entities:
        code = e.kind.upper()[:3]
        lvl = f"L{e.level}" if e.level is not None else ""
        token = f"{code}{lvl}:{e.label}"
        for dx in range(e.w):
            for dy in range(e.h):
                key = (e.x + dx, e.y + dy)
                cell[key] = token if key not in cell else f"{cell[key]}|{token}"
    cell[(center[0], center[1])] = (
        "VIEW" if (center[0], center[1]) not in cell else f"VIEW|{cell[(center[0], center[1])]}"
    )

    buf = StringIO()
    writer = csv.writer(buf)
    header = ["Y\\X"] + [str(x) for x in range(min_x, max_x + 1)]
    writer.writerow(header)
    for y in range(min_y, max_y + 1):
        row = [str(y)]
        for x in range(min_x, max_x + 1):
            row.append(cell.get((x, y), ""))
        writer.writerow(row)
    return buf.getvalue()


def render_entities_csv(entities: list[MapEntity], *, center: tuple[int, int], kingdom: str) -> str:
    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "kingdom",
            "center_x",
            "center_y",
            "kind",
            "label",
            "level",
            "x",
            "y",
            "w",
            "h",
            "identity",
            "confidence",
            "provenance",
            "source_frames",
            "coordinate_residual_px",
            "popup_path",
        ]
    )
    for e in entities:
        writer.writerow(
            [
                kingdom,
                center[0],
                center[1],
                e.kind,
                e.label,
                e.level or "",
                e.x,
                e.y,
                e.w,
                e.h,
                e.identity or "",
                "" if e.confidence is None else f"{e.confidence:.4f}",
                e.provenance or "",
                "|".join(e.source_frames),
                ""
                if e.coordinate_residual_px is None
                else f"{e.coordinate_residual_px:.3f}",
                e.popup_path or "",
            ]
        )
    return buf.getvalue()


def render_isometric_svg(
    entities: list[MapEntity],
    *,
    center: tuple[int, int],
    kingdom: str = "",
    tile_w: float = 36,
    tile_h: float = 20,
    pad_tiles: int = 2,
) -> str:
    """Isometric diamond schematic (working grid only, no bitmap)."""
    svg, *_rest = render_isometric_work_svg(
        entities,
        center=center,
        kingdom=kingdom,
        tile_w=tile_w,
        tile_h=tile_h,
        pad_tiles=pad_tiles,
        mosaic=None,
    )
    # work svg uses absolute positioning style — use plain background for standalone
    return svg.replace(
        "style='position:absolute;left:0;top:0;pointer-events:none'",
        "style='background:#152418'",
    )


def _iso_diamond_on_panorama(
    x: float,
    y: float,
    w: float,
    h: float,
    mosaic: MosaicResult,
) -> str:
    """Render a centered footprint with affine or legacy panorama geometry."""
    from ks.cartograph.mosaic import mosaic_projection, world_to_panorama

    if mosaic.world_to_pixel_matrix is not None:
        world_corners = _footprint_world_corners(x, y, w, h)
        projection = mosaic_projection(mosaic)
        pts = [
            projection.pixel_from_world(world_x, world_y)
            for world_x, world_y in world_corners
        ]
    else:
        world_corners = _legacy_footprint_world_corners(x, y, w, h)
        origin_x, origin_y = world_to_panorama(x, y, mosaic)
        half_scale_x = mosaic.scale_x * 0.5
        half_scale_y = mosaic.scale_y * 0.5
        world_x_basis = (half_scale_x * 1.15, half_scale_y)
        world_y_basis = (-half_scale_x * 1.15, half_scale_y)
        pts = [
            (
                origin_x
                + (world_x - x) * world_x_basis[0]
                + (world_y - y) * world_y_basis[0],
                origin_y
                + (world_x - x) * world_x_basis[1]
                + (world_y - y) * world_y_basis[1],
            )
            for world_x, world_y in world_corners
        ]
    return " ".join(f"{px:.1f},{py:.1f}" for px, py in pts)


def filter_ui_pin_entities(entities: list[MapEntity]) -> list[MapEntity]:
    """Entities shown as panorama pins (cities + alliance buildings)."""
    return [entity for entity in entities if entity.kind in UI_PIN_KINDS]


def render_iso_overlay_unrotated(
    entities: list[MapEntity],
    *,
    mosaic: MosaicResult,
    kingdom: str = "",
    lattice_step: int = DEFAULT_LATTICE_STEP,
    pin_kinds: frozenset[str] | None = None,
) -> str:
    """Sparse isometric diamond grid + UI pins on the unrotated panorama."""
    from ks.cartograph.mosaic import world_to_panorama

    if lattice_step < 1:
        raise ValueError(f"lattice_step must be >= 1; got {lattice_step}")
    kinds = UI_PIN_KINDS if pin_kinds is None else frozenset(pin_kinds)
    pin_entities = [entity for entity in entities if entity.kind in kinds]

    h, w = mosaic.image.shape[:2]
    cx, cy = mosaic.center
    min_wx, max_wx, min_wy, max_wy = _integer_mosaic_bounds(mosaic)
    # Cap density for huge mosaics
    span = 55
    if max_wx - min_wx > span:
        min_wx, max_wx = cx - span // 2, cx + span // 2
    if max_wy - min_wy > span:
        min_wy, max_wy = cy - span // 2, cy + span // 2

    parts: list[str] = [
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{w}' height='{h}' "
        f"viewBox='0 0 {w} {h}' "
        f"style='position:absolute;left:0;top:0;width:100%;height:100%;pointer-events:none'>",
        "<defs>",
    ]
    for kind, body in ICON_SVG.items():
        parts.append(f'<g id="uicon-{kind}">{body}</g>')
    parts.append("</defs>")
    parts.append(
        "<style>text{font-family:ui-monospace,Menlo,monospace;font-size:12px;fill:#fff;"
        "paint-order:stroke;stroke:#0b120c;stroke-width:3px}</style>"
    )
    parts.append(
        f"<text x='12' y='22' fill='#9fd0ff' font-size='14'>"
        f"Kingdom #{escape(kingdom)} · sparse diamond grid (step {lattice_step}) · "
        f"pins cities/alliance · center {cx},{cy}</text>"
    )

    for x in range(min_wx, max_wx + 1):
        for y in range(min_wy, max_wy + 1):
            if (x - cx) % lattice_step or (y - cy) % lattice_step:
                continue
            poly = _iso_diamond_on_panorama(x, y, 1, 1, mosaic)
            stroke = "#9fd0ff" if (x + y) % 2 == 0 else "#5ec8ff"
            parts.append(
                f"<polygon points='{poly}' fill='none' stroke='{stroke}' "
                f"stroke-opacity='0.45' stroke-width='1.2'/>"
            )

    for x in range(min_wx, max_wx + 1):
        if (x - cx) % max(5, lattice_step * 2):
            continue
        px, py = world_to_panorama(x + 0.5, float(min_wy), mosaic)
        parts.append(
            f"<text x='{px:.1f}' y='{py:.1f}' text-anchor='middle' fill='#9fd0ff' font-size='11'>X{x}</text>"
        )
    for y in range(min_wy, max_wy + 1):
        if (y - cy) % max(5, lattice_step * 2):
            continue
        px, py = world_to_panorama(float(min_wx), y + 0.5, mosaic)
        parts.append(
            f"<text x='{px:.1f}' y='{py:.1f}' text-anchor='end' fill='#9fd0ff' font-size='11'>Y{y}</text>"
        )

    poly = _iso_diamond_on_panorama(cx, cy, 1, 1, mosaic)
    parts.append(
        f"<polygon points='{poly}' fill='#1e3a5f' fill-opacity='0.35' "
        f"stroke='#5ec8ff' stroke-width='2.5'/>"
    )

    for e in pin_entities:
        poly = _iso_diamond_on_panorama(e.x, e.y, e.w, e.h, mosaic)
        parts.append(
            f"<polygon points='{poly}' fill='#0b120c' fill-opacity='0.2' "
            f"stroke='#ffe9c8' stroke-width='1.8'/>"
        )
        if mosaic.world_to_pixel_matrix is not None:
            entity_center = _footprint_world_center(e.x, e.y, e.w, e.h)
            px, py = world_to_panorama(*entity_center, mosaic)
            icon_y = py - 20
            label_y = py + 18
        else:
            px, py = world_to_panorama(
                e.x + e.w / 2,
                e.y + e.h / 2,
                mosaic,
            )
            legacy_vertical_nudge = mosaic.scale_y * e.h * 0.35
            icon_y = py + legacy_vertical_nudge - 20
            label_y = py + legacy_vertical_nudge + 18
        ix, iy = px - 16, icon_y
        kind = e.kind if e.kind in ICON_SVG else "rss"
        parts.append(f'<use href="#uicon-{kind}" x="{ix:.1f}" y="{iy:.1f}"/>')
        lvl = f" L{e.level}" if e.level is not None else ""
        parts.append(
            f"<text x='{px:.1f}' y='{label_y:.1f}' text-anchor='middle'>"
            f"{escape(e.label)}{lvl}</text>"
        )
        parts.append(
            f"<text x='{px:.1f}' y='{label_y + 14:.1f}' text-anchor='middle' "
            f"font-size='11' fill='#cfe8d4'>{e.x},{e.y}</text>"
        )

    parts.append("</svg>")
    return "\n".join(parts)


def _content_mask(image: np.ndarray) -> np.ndarray:
    if image.ndim != 3 or image.shape[2] not in (3, 4):
        raise ValueError(
            "mosaic image must have shape HxWx3 or HxWx4; "
            f"got {image.shape}"
        )
    from ks.cartograph.mask import bluestacks_mask_config

    fill = np.asarray(bluestacks_mask_config().fill, dtype=image.dtype)
    has_rgb_content = ~np.all(image[..., :3] == fill, axis=2)
    if image.shape[2] == 4:
        return has_rgb_content & (image[..., 3] > 0)
    return has_rgb_content


def _sample_rgb_at_center(
    image: np.ndarray,
    content_mask: np.ndarray,
    pixel_x: float,
    pixel_y: float,
) -> list[int] | None:
    height, width = image.shape[:2]
    if not (0.0 <= pixel_x < width and 0.0 <= pixel_y < height):
        return None
    sample_x = min(width - 1, max(0, int(round(pixel_x))))
    sample_y = min(height - 1, max(0, int(round(pixel_y))))
    if not content_mask[sample_y, sample_x]:
        return None
    pixel = image[sample_y, sample_x]
    return [int(pixel[2]), int(pixel[1]), int(pixel[0])]


def _digital_tile_records(mosaic: MosaicResult) -> list[dict[str, object]]:
    from ks.cartograph.mosaic import mosaic_projection

    image = mosaic.image
    content_mask = _content_mask(image)
    projection = mosaic_projection(mosaic)
    world_x_values, world_y_values = _bounded_tile_centers(mosaic)
    tiles: list[dict[str, object]] = []
    for world_x in world_x_values:
        for world_y in world_y_values:
            pixel_x, pixel_y = projection.pixel_from_world(world_x, world_y)
            sampled_rgb = _sample_rgb_at_center(
                image,
                content_mask,
                pixel_x,
                pixel_y,
            )
            if sampled_rgb is None:
                continue
            polygon = [
                list(projection.pixel_from_world(*world_corner))
                for world_corner in _footprint_world_corners(
                    world_x,
                    world_y,
                    1,
                    1,
                )
            ]
            tiles.append(
                {
                    "x": world_x,
                    "y": world_y,
                    "pixel_center": [pixel_x, pixel_y],
                    "polygon": polygon,
                    "covered": True,
                    "terrain": "unknown",
                    "sampled_rgb": sampled_rgb,
                }
            )
    return tiles


def render_digital_map_json(
    entities: list[MapEntity],
    *,
    center: tuple[int, int],
    kingdom: str,
    mosaic: MosaicResult,
    registration: GlobalRegistration | None = None,
) -> str:
    """Serialize the canonical bounded, pixel-aligned digital map."""
    from ks.cartograph.mosaic import mosaic_projection

    _validate_center_matches_mosaic(center, mosaic)
    projection = mosaic_projection(mosaic)
    height, width = mosaic.image.shape[:2]
    document = {
        "kingdom": kingdom,
        "center": {"x": center[0], "y": center[1]},
        "projection": {
            "center": list(projection.center),
            "pixel_origin": list(projection.pixel_origin),
            "matrix": [list(row) for row in projection.matrix],
        },
        "panorama": {"width": width, "height": height},
        "tiles": _digital_tile_records(mosaic),
        "entities": [_entity_json(entity) for entity in entities],
    }
    if registration is not None:
        document["registration"] = _registration_json(registration)
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def _entity_json(entity: MapEntity) -> dict[str, object]:
    payload: dict[str, object] = {
        "kind": entity.kind,
        "label": entity.label,
        "level": entity.level,
        "x": entity.x,
        "y": entity.y,
        "w": entity.w,
        "h": entity.h,
    }
    if entity.identity is not None:
        payload["identity"] = entity.identity
    if entity.confidence is not None:
        payload["confidence"] = entity.confidence
    if entity.provenance is not None:
        payload["provenance"] = entity.provenance
    if entity.source_frames:
        payload["source_frames"] = list(entity.source_frames)
    if entity.coordinate_residual_px is not None:
        payload["coordinate_residual_px"] = entity.coordinate_residual_px
    if entity.popup_path is not None:
        payload["popup_path"] = entity.popup_path
    return payload


def registration_document(
    registration: object,
    *,
    matrix: tuple[tuple[float, float], tuple[float, float]] | None = None,
) -> dict[str, object]:
    """Serialize registration diagnostics for JSON/YAML export."""
    return _registration_json(registration, matrix=matrix)


def _registration_json(
    registration: object,
    *,
    matrix: tuple[tuple[float, float], tuple[float, float]] | None = None,
) -> dict[str, object]:
    metrics = getattr(registration, "metrics", None)
    graph = getattr(registration, "graph", None)
    diagnostics = getattr(registration, "diagnostics", ())
    offsets = getattr(registration, "frame_offsets", {})
    document: dict[str, object] = {
        "metrics": None
        if metrics is None
        else {
            "median_px": metrics.median_px,
            "p95_px": metrics.p95_px,
            "max_px": metrics.max_px,
            "connected_frames": list(metrics.connected_frames),
        },
        "graph": None
        if graph is None
        else {
            "connected": graph.connected,
            "expected_frame_count": graph.expected_frame_count,
            "connected_frame_count": graph.connected_frame_count,
            "constraint_count": graph.constraint_count,
            "accepted_count": graph.accepted_count,
            "rejected_count": graph.rejected_count,
        },
        "frame_offsets": {
            name: [float(offset[0]), float(offset[1])]
            for name, offset in dict(offsets).items()
        },
        "edges": [
            {
                "frame_a": item.constraint.frame_a,
                "frame_b": item.constraint.frame_b,
                "source": item.source,
                "inliers": item.inliers,
                "residual_px": item.residual_px,
                "accepted": item.accepted,
                "effective_weight": item.effective_weight,
            }
            for item in diagnostics
        ],
    }
    matrix_value = matrix
    if matrix_value is None:
        matrix_value = getattr(registration, "world_to_pixel_matrix", None)
    if matrix_value is not None:
        document["matrix"] = [list(row) for row in matrix_value]
    return document


def render_html(
    entities: list[MapEntity],
    *,
    center: tuple[int, int],
    kingdom: str,
    grid_csv: str,
    entities_csv: str,
    mosaic: MosaicResult | None = None,
    panorama_name: str = "panorama.png",
    map_json_name: str | None = None,
) -> str:
    """Isometric working schematic + separate rectangular mosaic for coverage QA."""
    if mosaic is not None:
        _validate_center_matches_mosaic(center, mosaic)
    legend = []
    for kind, body in legend_items():
        legend.append(
            f"<span class='leg'><svg width='28' height='28' viewBox='0 0 32 32'>{body}</svg>"
            f"{escape(kind)}</span>"
        )

    # Working layer = pure isometric diamonds + icons covering full mosaic world
    schematic, iso_w, iso_h, *_rest = render_isometric_work_svg(
        entities, center=center, kingdom=kingdom, mosaic=mosaic, pad_tiles=6
    )

    if mosaic is not None:
        mh, mw = mosaic.image.shape[:2]
        # Coverage fraction (non-fill pixels) for the QA caption
        content = mosaic.image
        content_mask = _content_mask(content)
        # Hull fill is the honest “is the capture solid?” metric (AABB always
        # under-reports for isometric parallelograms).
        import cv2

        c8 = content_mask.astype(np.uint8) * 255
        cnts, _ = cv2.findContours(c8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if cnts:
            hull = cv2.convexHull(np.vstack(cnts))
            hm = np.zeros_like(c8)
            cv2.fillConvexPoly(hm, hull, 255)
            content_frac = float(c8[hm > 0].mean() / 255.0)
        else:
            content_frac = float(content_mask.mean())
        bbox_frac = float(content_mask.mean())
        pan_disp_w = min(1200, mw)
        pan_disp_h = max(1, int(round(pan_disp_w * mh / max(mw, 1))))
        panorama_overlay = render_iso_overlay_unrotated(
            entities,
            mosaic=mosaic,
            kingdom=kingdom,
        )
        iso_block = f"""
  <h2>Projected panorama</h2>
  <p class="meta">
    Orthographic stitch with the affine diamond grid in the same pixel coordinate system.
    Solid coverage <strong>{content_frac:.0%}</strong> inside capture hull
    (bbox fill {bbox_frac:.0%}, {mw}×{mh}px).
    Remaining holes are mostly UI-mask cutouts or swipe gaps.
  </p>
  <div class="map photo" style="max-width:100%;overflow:auto;background:#0a100c">
    <div style="position:relative;width:{pan_disp_w}px;height:{pan_disp_h}px">
      <img src="{escape(panorama_name)}" alt="masked mosaic"
           style="width:100%;height:100%;image-rendering:auto;
                  background:#152418;display:block"/>
      {panorama_overlay}
    </div>
  </div>
  <h2>Isometric schematic (working layer)</h2>
  <p class="meta">
    Diamonds + SVG icons over mosaic world extent
    ({iso_w:.0f}×{iso_h:.0f}px). Separate from the bitmap so projections stay honest.
  </p>
  <div class="map" style="max-width:100%;max-height:85vh;overflow:auto;background:#152418">
    <div style="position:relative;width:{iso_w:.0f}px;height:{iso_h:.0f}px">
      {schematic}
    </div>
  </div>
"""
    else:
        iso_block = f"""
  <h2>Isometric schematic</h2>
  <div class="map" style="position:relative;width:{iso_w:.0f}px;height:{iso_h:.0f}px;background:#152418">
    {schematic}
  </div>
"""

    pad = 8 if mosaic is not None else 2
    min_x, max_x, min_y, max_y = _bounds(entities, center, pad)
    if mosaic is not None:
        mosaic_min_x, mosaic_max_x, mosaic_min_y, mosaic_max_y = (
            _integer_mosaic_bounds(mosaic)
        )
        min_x = min(min_x, mosaic_min_x)
        max_x = max(max_x, mosaic_max_x)
        min_y = min(min_y, mosaic_min_y)
        max_y = max(max_y, mosaic_max_y)
        if max_x - min_x > 80:
            mid = (min_x + max_x) // 2
            min_x, max_x = mid - 40, mid + 40
        if max_y - min_y > 80:
            mid = (min_y + max_y) // 2
            min_y, max_y = mid - 40, mid + 40

    cell: dict[tuple[int, int], str] = {(center[0], center[1]): "VIEW"}
    for e in entities:
        code = e.kind[:1].upper() + (str(e.level) if e.level is not None else "")
        cell[(e.x, e.y)] = code

    rows = ["<tr><th>Y\\X</th>" + "".join(f"<th>{x}</th>" for x in range(min_x, max_x + 1)) + "</tr>"]
    for y in range(min_y, max_y + 1):
        tds = "".join(
            f"<td class='{'c' if (x, y) in cell else ''}'>{escape(cell.get((x, y), ''))}</td>"
            for x in range(min_x, max_x + 1)
        )
        rows.append(f"<tr><th>{y}</th>{tds}</tr>")

    json_link = (
        f' · <a href="{escape(map_json_name)}">map.json</a>'
        if map_json_name is not None
        else ""
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>Cartograph map — Kingdom #{escape(kingdom)}</title>
  <style>
    body {{ font-family: "IBM Plex Sans", "Segoe UI", sans-serif; background: #0f1410; color: #e8ffe8; margin: 1.25rem; }}
    h1 {{ font-size: 1.2rem; font-weight: 600; }}
    .meta {{ color: #9bb8d4; max-width: 52rem; line-height: 1.45; }}
    .leg {{ display: inline-flex; align-items: center; gap: 6px; margin: 4px 12px 4px 0; font-size: 12px; color: #cfe8d4; }}
    .map {{ overflow: auto; border: 1px solid #2a3d30; display: inline-block; margin: 0.75rem 0; background: #152418; }}
    .map.photo {{ max-width: 100%; }}
    h2 {{ font-size: 1rem; margin-top: 1.5rem; color: #b8d4c0; }}
    table.grid {{ border-collapse: collapse; font-family: ui-monospace, Menlo, monospace; font-size: 11px; }}
    table.grid th, table.grid td {{ border: 1px solid #2a3d30; min-width: 2.2rem; height: 1.6rem; text-align: center; padding: 2px; }}
    table.grid th {{ background: #1a2a1e; color: #9bb8d4; }}
    table.grid td.c {{ background: #243828; color: #ffe9c8; font-weight: 600; }}
    pre.csv {{ background: #1a2a1e; border: 1px solid #2a3d30; padding: 0.75rem; overflow: auto; max-height: 16rem; font-size: 11px; }}
    a {{ color: #7ec8ff; }}
  </style>
</head>
<body>
  <h1>Cartograph — Kingdom #{escape(kingdom)}</h1>
  <p class="meta">
    Viewport <strong>{center[0]},{center[1]}</strong>.
    Pure isometric schematic + icons; mosaic panel for coverage QA.
  </p>
  <p>{''.join(legend)}</p>
  {iso_block}
  <h2>Orthogonal grid (xls-type)</h2>
  <p class="meta">Codes: C=city, B=beast+level, R=rss, VIEW = viewport.</p>
  <div class="map"><table class="grid">{''.join(rows)}</table></div>
  <h2>CSV for Excel</h2>
  <p><a href="map-grid.csv">map-grid.csv</a> · <a href="entities.csv">entities.csv</a>
     · <a href="{escape(panorama_name)}">panorama.png</a>{json_link}</p>
  <h3>Grid CSV</h3>
  <pre class="csv">{escape(grid_csv)}</pre>
  <h3>Entities CSV</h3>
  <pre class="csv">{escape(entities_csv)}</pre>
</body>
</html>
"""


def write_map_bundle(
    out_dir: Path,
    entities: list[MapEntity],
    *,
    center: tuple[int, int],
    kingdom: str,
    mosaic: MosaicResult | None = None,
    registration: GlobalRegistration | None = None,
) -> tuple[Path, Path, Path]:
    if mosaic is not None:
        _validate_center_matches_mosaic(center, mosaic)
    out_dir.mkdir(parents=True, exist_ok=True)
    pad = 2
    if mosaic is not None:
        pad = max(
            2,
            int(round(mosaic.band_w / mosaic.scale_x / 2)),
            int(round(mosaic.band_h / mosaic.scale_y / 2)),
        )
        pad = min(pad, 25)
    grid_csv = render_excel_grid_csv(entities, center=center, pad_tiles=pad)
    ent_csv = render_entities_csv(entities, center=center, kingdom=kingdom)
    panorama_name = "panorama.png"
    map_json_name = None
    if mosaic is not None:
        pan_path = out_dir / panorama_name
        if mosaic.path.resolve() != pan_path.resolve():
            import cv2

            cv2.imwrite(str(pan_path), mosaic.image)
        map_json_name = "map.json"
        map_json = render_digital_map_json(
            entities,
            center=center,
            kingdom=kingdom,
            mosaic=mosaic,
            registration=registration,
        )
        (out_dir / map_json_name).write_text(map_json, encoding="utf-8")

    html = render_html(
        entities,
        center=center,
        kingdom=kingdom,
        grid_csv=grid_csv,
        entities_csv=ent_csv,
        mosaic=mosaic,
        panorama_name=panorama_name,
        map_json_name=map_json_name,
    )
    html_path = out_dir / "map.html"
    grid_path = out_dir / "map-grid.csv"
    ent_path = out_dir / "entities.csv"
    html_path.write_text(html, encoding="utf-8")
    grid_path.write_text(grid_csv, encoding="utf-8")
    ent_path.write_text(ent_csv, encoding="utf-8")
    return html_path, grid_path, ent_path


def entities_from_hits(hits: list[StructureHit]) -> list[MapEntity]:
    out: list[MapEntity] = []
    for h in hits:
        level = None
        import re

        m = re.search(r"(?:Lv\.?\s*|L|level\s*)(\d{1,2})\b", h.label, re.I)
        if not m:
            m = re.search(r"\b(\d{1,2})\s*$", h.label)
        if m:
            level = int(m.group(1))
        kind = h.kind
        if kind not in FOOTPRINTS:
            kind = "rss"
        out.append(
            MapEntity(
                kind=kind,
                x=h.x,
                y=h.y,
                label=h.label,
                level=level,
                w=FOOTPRINTS[kind][0],
                h=FOOTPRINTS[kind][1],
            )
        )
    return out


# Late import type for annotations — removed; see TYPE_CHECKING at top.
