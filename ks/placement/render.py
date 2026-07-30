"""Render placement layout to HTML/SVG map (isometric / axis views)."""

from __future__ import annotations

from pathlib import Path

from ks.placement.geometry import trap_rect
from ks.placement.sweep import LayoutResult


ROLE_COLORS = {
    "leader_t2": "#2b6cb0",
    "leader_t1": "#2f855a",
    "both": "#c9a227",
    "joiner": "#6b7280",
}

BLOCKER_COLORS = {
    "building": "#8b5a2b",
    "city": "#5c4d7a",
    "rss": "#6b5a2a",
    "terrain": "#4a3728",
}


def _bounds(layout: LayoutResult, pad: int = 2) -> tuple[int, int, int, int]:
    xs = [s.x for s in layout.seats] + [layout.trap1[0], layout.trap2[0]]
    ys = [s.y for s in layout.seats] + [layout.trap1[1], layout.trap2[1]]
    for b in layout.blockers:
        xs += [b.rect.x, b.rect.x + b.rect.w]
        ys += [b.rect.y, b.rect.y + b.rect.h]
    return min(xs) - pad, max(xs) + pad, min(ys) - pad, max(ys) + pad


def _iso_project(x: float, y: float, min_x: int, min_y: int, tile_w: int, tile_h: int) -> tuple[float, float]:
    """Map tile coords → screen; 45° diamond like the in-game camera."""
    lx = x - min_x
    ly = y - min_y
    sx = (lx - ly) * (tile_w / 2.0)
    sy = (lx + ly) * (tile_h / 2.0)
    return sx, sy


def _iso_diamond(x: int, y: int, w: int, h: int, min_x: int, min_y: int, tile_w: int, tile_h: int) -> str:
    """Polygon for an axis-aligned tile rect drawn in isometric space."""
    corners = [
        (x, y),
        (x + w, y),
        (x + w, y + h),
        (x, y + h),
    ]
    pts = []
    for cx, cy in corners:
        sx, sy = _iso_project(cx, cy, min_x, min_y, tile_w, tile_h)
        pts.append(f"{sx:.1f},{sy:.1f}")
    return " ".join(pts)


def render_svg_isometric(layout: LayoutResult, tile_w: int = 18, tile_h: int = 10, trap_size: int = 3) -> str:
    seats = layout.seats
    if not seats and not layout.blockers:
        return "<svg xmlns='http://www.w3.org/2000/svg'></svg>"

    min_x, max_x, min_y, max_y = _bounds(layout)
    # Iso extents
    corners = [
        _iso_project(min_x, min_y, min_x, min_y, tile_w, tile_h),
        _iso_project(max_x + 1, min_y, min_x, min_y, tile_w, tile_h),
        _iso_project(min_x, max_y + 1, min_x, min_y, tile_w, tile_h),
        _iso_project(max_x + 1, max_y + 1, min_x, min_y, tile_w, tile_h),
    ]
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    pad = 40.0
    origin_x = -min(xs) + pad
    origin_y = -min(ys) + pad
    width = max(xs) - min(xs) + 2 * pad
    height = max(ys) - min(ys) + 2 * pad

    def shift(x: float, y: float) -> tuple[float, float]:
        return x + origin_x, y + origin_y

    parts = [
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{width:.0f}' height='{height:.0f}' "
        f"viewBox='0 0 {width:.0f} {height:.0f}' style='background:#152418'>",
        "<style>text{font-family:ui-monospace,Menlo,monospace;font-size:10px;fill:#e8ffe8}</style>",
        "<text x='12' y='18' fill='#9bb8d4'>Isometric view (~45° like in-game) · tile X/Y still orthogonal under the hood</text>",
    ]

    # Light iso grid
    for x in range(min_x, max_x + 1, 2):
        for y in range(min_y, max_y + 1, 2):
            poly = _iso_diamond(x, y, 1, 1, min_x, min_y, tile_w, tile_h)
            shifted = []
            for pair in poly.split():
                a, b = pair.split(",")
                sx, sy = shift(float(a), float(b))
                shifted.append(f"{sx:.1f},{sy:.1f}")
            parts.append(
                f"<polygon points='{' '.join(shifted)}' fill='none' stroke='#1f3324' stroke-width='0.5'/>"
            )

    for b in layout.blockers:
        poly = _iso_diamond(b.rect.x, b.rect.y, b.rect.w, b.rect.h, min_x, min_y, tile_w, tile_h)
        shifted = []
        for pair in poly.split():
            a, c = pair.split(",")
            sx, sy = shift(float(a), float(c))
            shifted.append(f"{sx:.1f},{sy:.1f}")
        fill = BLOCKER_COLORS.get(b.kind, "#4a3728")
        parts.append(
            f"<polygon points='{' '.join(shifted)}' fill='{fill}' stroke='#d4a574' "
            f"stroke-width='1.5' opacity='0.9'><title>{b.id} ({b.kind}) "
            f"{b.rect.w}x{b.rect.h} @ {b.rect.x},{b.rect.y}</title></polygon>"
        )
        cx, cy = shift(*_iso_project(b.rect.x + b.rect.w / 2, b.rect.y + b.rect.h / 2, min_x, min_y, tile_w, tile_h))
        parts.append(f"<text x='{cx}' y='{cy}' text-anchor='middle' fill='#ffe9c8'>{b.id}</text>")

    for s in seats:
        color = ROLE_COLORS.get(s.role, "#555")
        poly = _iso_diamond(s.x, s.y, 2, 2, min_x, min_y, tile_w, tile_h)
        shifted = []
        for pair in poly.split():
            a, c = pair.split(",")
            sx, sy = shift(float(a), float(c))
            shifted.append(f"{sx:.1f},{sy:.1f}")
        parts.append(
            f"<polygon points='{' '.join(shifted)}' fill='{color}' stroke='#0b120c' "
            f"stroke-width='1'><title>{s.role} ({s.x},{s.y})</title></polygon>"
        )

    for label, (cx, cy), stroke in (
        ("T2", layout.trap2, "#5ec8ff"),
        ("T1", layout.trap1, "#7dffb3"),
    ):
        r = trap_rect(cx, cy, trap_size)
        poly = _iso_diamond(r.x, r.y, r.w, r.h, min_x, min_y, tile_w, tile_h)
        shifted = []
        for pair in poly.split():
            a, c = pair.split(",")
            sx, sy = shift(float(a), float(c))
            shifted.append(f"{sx:.1f},{sy:.1f}")
        parts.append(
            f"<polygon points='{' '.join(shifted)}' fill='none' stroke='{stroke}' stroke-width='3'/>"
        )
        tx, ty = shift(*_iso_project(cx, cy, min_x, min_y, tile_w, tile_h))
        parts.append(
            f"<text x='{tx}' y='{ty}' text-anchor='middle' fill='{stroke}' font-weight='700'>"
            f"{label} {cx},{cy}</text>"
        )

    parts.append("</svg>")
    return "\n".join(parts)


def render_svg(layout: LayoutResult, tile_px: int = 14, trap_size: int = 3) -> str:
    """Axis-aligned debug view (not how the game looks)."""
    seats = layout.seats
    if not seats and not layout.blockers:
        return "<svg xmlns='http://www.w3.org/2000/svg'></svg>"

    min_x, max_x, min_y, max_y = _bounds(layout)
    width = (max_x - min_x + 1) * tile_px
    height = (max_y - min_y + 1) * tile_px

    def tx(x: float) -> float:
        return (x - min_x) * tile_px

    def ty(y: float) -> float:
        return (y - min_y) * tile_px

    parts = [
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}' "
        f"viewBox='0 0 {width} {height}' style='background:#152418'>",
        "<style>text{font-family:ui-monospace,Menlo,monospace;font-size:9px;fill:#e8ffe8}</style>",
        "<text x='4' y='12' fill='#9bb8d4'>Axis view (debug) — prefer isometric above</text>",
    ]

    for b in layout.blockers:
        fill = BLOCKER_COLORS.get(b.kind, "#4a3728")
        parts.append(
            f"<rect x='{tx(b.rect.x)}' y='{ty(b.rect.y)}' width='{b.rect.w * tile_px}' "
            f"height='{b.rect.h * tile_px}' fill='{fill}' stroke='#a67c52' "
            f"stroke-width='1' opacity='0.85'><title>{b.id}</title></rect>"
        )

    for s in seats:
        color = ROLE_COLORS.get(s.role, "#555")
        parts.append(
            f"<rect x='{tx(s.x)}' y='{ty(s.y)}' width='{2 * tile_px - 1}' "
            f"height='{2 * tile_px - 1}' fill='{color}' stroke='#0b120c' "
            f"stroke-width='1' rx='2'><title>{s.role} ({s.x},{s.y})</title></rect>"
        )

    for label, (cx, cy), stroke in (
        ("T2", layout.trap2, "#5ec8ff"),
        ("T1", layout.trap1, "#7dffb3"),
    ):
        r = trap_rect(cx, cy, trap_size)
        parts.append(
            f"<rect x='{tx(r.x)}' y='{ty(r.y)}' width='{r.w * tile_px}' "
            f"height='{r.h * tile_px}' fill='none' stroke='{stroke}' stroke-width='3' rx='4'/>"
        )
        parts.append(
            f"<text x='{tx(cx) + tile_px * 0.2}' y='{ty(cy) + tile_px * 0.7}' "
            f"fill='{stroke}' font-weight='700'>{label} {cx},{cy}</text>"
        )

    parts.append("</svg>")
    return "\n".join(parts)


def render_html(layout: LayoutResult, ranked_summary: list[LayoutResult] | None = None) -> str:
    svg_iso = render_svg_isometric(layout)
    svg_axis = render_svg(layout)
    rows = ""
    if ranked_summary:
        for i, r in enumerate(ranked_summary[:12], 1):
            rows += (
                f"<tr><td>{i}</td><td>{r.d}</td><td>{r.direction}</td><td>{r.lateral}</td>"
                f"<td>{r.score:.1f}</td><td>{r.n_l2}</td><td>{r.n_l1}</td>"
                f"<td>{r.n_flex}</td><td>{r.n_join_ok}</td>"
                f"<td>{r.trap1[0]},{r.trap1[1]}</td></tr>"
            )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>Bear Trap Placement Map — UTD #2339</title>
  <style>
    body {{ font-family: system-ui, sans-serif; background: #0f1410; color: #e8ffe8; margin: 1.5rem; }}
    h1 {{ font-size: 1.25rem; }}
    .meta {{ color: #9bb8d4; margin-bottom: 1rem; max-width: 70rem; }}
    .legend span {{ display: inline-block; padding: 2px 8px; margin-right: 8px; border-radius: 4px; font-size: 12px; }}
    table {{ border-collapse: collapse; margin-top: 1rem; font-size: 13px; }}
    th, td {{ border: 1px solid #2a3d30; padding: 4px 8px; }}
    th {{ background: #1a2a1e; }}
    .map {{ overflow: auto; border: 1px solid #2a3d30; display: inline-block; margin-bottom: 1rem; }}
    h2 {{ margin-top: 1.5rem; font-size: 1.05rem; }}
  </style>
</head>
<body>
  <h1>Bear Trap hive map — Trap 2 fixed, new trap swept</h1>
  <p class="meta">
    Best: D={layout.d} {layout.direction} lateral={layout.lateral} ·
    score={layout.score:.1f} · L2={layout.n_l2} L1={layout.n_l1} ·
    flex={layout.n_flex} join_ok={layout.n_join_ok}<br/>
    Game view is ~45° isometric — primary map below matches that.<br/>
    <strong>City seats = 2×2</strong> (packing quantum; same zoom ruler). Mills/banner = 1×1.
    V3-style gap ≈ two cities between traps (preferred D≈7).
  </p>
  <p class="legend">
    <span style="background:#2b6cb0">Leader T2</span>
    <span style="background:#2f855a">Leader T1</span>
    <span style="background:#c9a227;color:#111">BOTH</span>
    <span style="background:#6b7280">Joiner</span>
    <span style="background:#8b5a2b">Building</span>
    <span style="background:#5c4d7a">City</span>
  </p>
  <h2>Isometric (game-like)</h2>
  <div class="map">{svg_iso}</div>
  <h2>Axis debug (not how the game looks)</h2>
  <div class="map">{svg_axis}</div>
  <h2>Top D options</h2>
  <table>
    <tr><th>#</th><th>D</th><th>Dir</th><th>Lat</th><th>Score</th><th>L2</th><th>L1</th><th>Flex</th><th>JoinOK</th><th>New trap</th></tr>
    {rows}
  </table>
</body>
</html>
"""


def write_map(path: Path, layout: LayoutResult, ranked: list[LayoutResult] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_html(layout, ranked), encoding="utf-8")
