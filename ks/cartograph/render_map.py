"""Cartograph map: isometric SVG (game-like) + Excel-friendly tile grid."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from html import escape
from io import StringIO
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from ks.cartograph.icons import ICON_SVG, legend_items
from ks.cartograph.models import FOOTPRINTS, StructureHit

if TYPE_CHECKING:
    from ks.cartograph.mosaic import MosaicResult


@dataclass(frozen=True)
class MapEntity:
    kind: str
    x: int
    y: int
    label: str
    level: int | None = None
    w: int = 1
    h: int = 1

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


def _iso(x: float, y: float, tile_w: float, tile_h: float) -> tuple[float, float]:
    return (x - y) * (tile_w / 2.0), (x + y) * (tile_h / 2.0)


def _diamond(
    x: int, y: int, w: int, h: int, tile_w: float, tile_h: float, ox: float, oy: float
) -> str:
    corners = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    pts = []
    for cx, cy in corners:
        sx, sy = _iso(cx, cy, tile_w, tile_h)
        pts.append(f"{sx + ox:.1f},{sy + oy:.1f}")
    return " ".join(pts)


def _bounds(entities: list[MapEntity], center: tuple[int, int], pad: int) -> tuple[int, int, int, int]:
    xs = [center[0], center[0] + 1]
    ys = [center[1], center[1] + 1]
    for e in entities:
        xs += [e.x, e.x + e.w]
        ys += [e.y, e.y + e.h]
    return min(xs) - pad, max(xs) + pad, min(ys) - pad, max(ys) + pad


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
        # Full mosaic world footprint (so schematic covers the capture)
        min_x = min(
            min_x,
            int(np.floor(mosaic.center[0] - mosaic.origin_x / mosaic.scale_x)),
        )
        max_x = max(
            max_x,
            int(
                np.ceil(
                    mosaic.center[0]
                    + (mosaic.image.shape[1] - mosaic.origin_x) / mosaic.scale_x
                )
            ),
        )
        min_y = min(
            min_y,
            int(np.floor(mosaic.center[1] - mosaic.origin_y / mosaic.scale_y)),
        )
        max_y = max(
            max_y,
            int(
                np.ceil(
                    mosaic.center[1]
                    + (mosaic.image.shape[0] - mosaic.origin_y) / mosaic.scale_y
                )
            ),
        )

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
        sx, sy = _iso(e.x + e.w / 2, e.y + e.h / 2, tile_w, tile_h)
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
    writer.writerow(["kingdom", "center_x", "center_y", "kind", "label", "level", "x", "y", "w", "h"])
    for e in entities:
        writer.writerow(
            [kingdom, center[0], center[1], e.kind, e.label, e.level or "", e.x, e.y, e.w, e.h]
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
    """Isometric diamond for a world footprint, in unrotated panorama pixels.

    Places the diamond by projecting the four world corners with an iso shear
    in screen space (no transform on the bitmap itself).
    """
    from ks.cartograph.mosaic import world_to_panorama

    # Basis: +1 X / +1 Y as classic iso steps sized by mosaic tile scale.
    # sx,sy are px per world tile; iso diamond uses half-width / half-height.
    hx = mosaic.scale_x * 0.5
    hy = mosaic.scale_y * 0.5
    # Screen vectors for +1 world-X and +1 world-Y (isometric).
    ex = (hx + hx * 0.15, hy)   # right-downish
    ey = (-hx - hx * 0.15, hy)  # left-downish

    def corner(wx: float, wy: float) -> tuple[float, float]:
        # Origin at tile (x,y) mapped to panorama, then iso offset for (wx-x, wy-y)
        ox, oy = world_to_panorama(x, y, mosaic)
        dx, dy = wx - x, wy - y
        return (
            ox + dx * ex[0] + dy * ey[0],
            oy + dx * ex[1] + dy * ey[1],
        )

    pts = [corner(x, y), corner(x + w, y), corner(x + w, y + h), corner(x, y + h)]
    return " ".join(f"{px:.1f},{py:.1f}" for px, py in pts)


def render_iso_overlay_unrotated(
    entities: list[MapEntity],
    *,
    mosaic: MosaicResult,
    kingdom: str = "",
) -> str:
    """Isometric diamond grid + icons on top of unrotated panorama (same pixel size)."""
    from ks.cartograph.mosaic import world_to_panorama

    h, w = mosaic.image.shape[:2]
    cx, cy = mosaic.center
    min_wx = int(np.floor(cx - mosaic.origin_x / mosaic.scale_x))
    max_wx = int(np.ceil(cx + (w - mosaic.origin_x) / mosaic.scale_x))
    min_wy = int(np.floor(cy - mosaic.origin_y / mosaic.scale_y))
    max_wy = int(np.ceil(cy + (h - mosaic.origin_y) / mosaic.scale_y))
    # Cap density for huge mosaics
    span = 55
    if max_wx - min_wx > span:
        min_wx, max_wx = cx - span // 2, cx + span // 2
    if max_wy - min_wy > span:
        min_wy, max_wy = cy - span // 2, cy + span // 2

    parts: list[str] = [
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{w}' height='{h}' "
        f"viewBox='0 0 {w} {h}' style='position:absolute;left:0;top:0;pointer-events:none'>",
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
        f"Kingdom #{escape(kingdom)} · mosaic unrotated · isometric diamond grid overlay · "
        f"center {cx},{cy}</text>"
    )

    for x in range(min_wx, max_wx + 1):
        for y in range(min_wy, max_wy + 1):
            poly = _iso_diamond_on_panorama(x, y, 1, 1, mosaic)
            stroke = "#9fd0ff" if (x + y) % 2 == 0 else "#5ec8ff"
            parts.append(
                f"<polygon points='{poly}' fill='none' stroke='{stroke}' "
                f"stroke-opacity='0.32' stroke-width='1'/>"
            )

    for x in range(min_wx, max_wx + 1):
        if x % 5:
            continue
        px, py = world_to_panorama(x + 0.5, float(min_wy), mosaic)
        parts.append(
            f"<text x='{px:.1f}' y='{py:.1f}' text-anchor='middle' fill='#9fd0ff' font-size='11'>X{x}</text>"
        )
    for y in range(min_wy, max_wy + 1):
        if y % 5:
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

    for e in entities:
        poly = _iso_diamond_on_panorama(e.x, e.y, e.w, e.h, mosaic)
        parts.append(
            f"<polygon points='{poly}' fill='#0b120c' fill-opacity='0.2' "
            f"stroke='#ffe9c8' stroke-width='1.8'/>"
        )
        px, py = world_to_panorama(e.x + e.w / 2, e.y + e.h / 2, mosaic)
        # Nudge icon to iso diamond center
        hx = mosaic.scale_x * e.w * 0.25
        hy = mosaic.scale_y * e.h * 0.35
        ix, iy = px - 16, py + hy - 20
        kind = e.kind if e.kind in ICON_SVG else "rss"
        parts.append(f'<use href="#uicon-{kind}" x="{ix:.1f}" y="{iy:.1f}"/>')
        lvl = f" L{e.level}" if e.level is not None else ""
        parts.append(
            f"<text x='{px:.1f}' y='{py + hy + 18:.1f}' text-anchor='middle'>"
            f"{escape(e.label)}{lvl}</text>"
        )
        parts.append(
            f"<text x='{px:.1f}' y='{py + hy + 32:.1f}' text-anchor='middle' "
            f"font-size='11' fill='#cfe8d4'>{e.x},{e.y}</text>"
        )

    parts.append("</svg>")
    return "\n".join(parts)


def render_html(
    entities: list[MapEntity],
    *,
    center: tuple[int, int],
    kingdom: str,
    grid_csv: str,
    entities_csv: str,
    mosaic: MosaicResult | None = None,
    panorama_name: str = "panorama.png",
) -> str:
    """Isometric working schematic + separate rectangular mosaic for coverage QA."""
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
        from ks.cartograph.mask import bluestacks_mask_config

        fill = np.array(bluestacks_mask_config().fill, dtype=np.uint8)
        content = mosaic.image
        if content.ndim == 3 and content.shape[2] == 4:
            content_mask = content[:, :, 3] > 0
        else:
            content_mask = ~np.all(content[..., :3] == fill, axis=2)
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
        iso_block = f"""
  <h2>Masked mosaic (coverage QA)</h2>
  <p class="meta">
    Orthographic stitch from camera screens — no rotate.
    Solid coverage <strong>{content_frac:.0%}</strong> inside capture hull
    (bbox fill {bbox_frac:.0%}, {mw}×{mh}px).
    Remaining holes are mostly UI-mask cutouts or swipe gaps.
  </p>
  <div class="map photo" style="max-width:100%;overflow:auto;background:#0a100c">
    <img src="{escape(panorama_name)}" alt="masked mosaic"
         style="width:{pan_disp_w}px;height:{pan_disp_h}px;image-rendering:auto;
                background:#152418;display:block"/>
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
        h, w = mosaic.image.shape[:2]
        min_x = min(min_x, int(np.floor(center[0] - mosaic.origin_x / mosaic.scale_x)))
        max_x = max(max_x, int(np.ceil(center[0] + (w - mosaic.origin_x) / mosaic.scale_x)))
        min_y = min(min_y, int(np.floor(center[1] - mosaic.origin_y / mosaic.scale_y)))
        max_y = max(max_y, int(np.ceil(center[1] + (h - mosaic.origin_y) / mosaic.scale_y)))
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
     · <a href="{escape(panorama_name)}">panorama.png</a></p>
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
) -> tuple[Path, Path, Path]:
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
    if mosaic is not None:
        pan_path = out_dir / panorama_name
        if mosaic.path.resolve() != pan_path.resolve():
            import cv2

            cv2.imwrite(str(pan_path), mosaic.image)

    html = render_html(
        entities,
        center=center,
        kingdom=kingdom,
        grid_csv=grid_csv,
        entities_csv=ent_csv,
        mosaic=mosaic,
        panorama_name=panorama_name,
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
