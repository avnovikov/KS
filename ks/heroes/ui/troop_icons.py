"""Troop type×tier icon URLs for the troops inventory UI."""

from __future__ import annotations

from pathlib import Path

_STATIC_TROOPS = Path(__file__).resolve().parent / "static" / "troops"

_TYPE_FILL = {
    "infantry": "#5d6d7e",
    "cavalry": "#7d6608",
    "archers": "#1a5276",
}

_TYPE_LETTER = {
    "infantry": "I",
    "cavalry": "C",
    "archers": "A",
}


def troop_icon_filename(troop_type: str, tier: int, ext: str) -> str:
    return f"{troop_type}-t{int(tier)}.{ext}"


def troop_icon_url(troop_type: str, tier: int) -> str:
    """Return `/static/troops/...` URL; write SVG badge if no image vendored."""
    key = troop_type.strip().lower()
    if key not in _TYPE_FILL:
        raise KeyError(f"unknown troop type: {troop_type!r}")
    n = int(tier)
    if n < 1 or n > 11:
        raise KeyError(f"unknown troop tier: {tier!r}")

    _STATIC_TROOPS.mkdir(parents=True, exist_ok=True)
    for ext in ("webp", "png", "svg"):
        name = troop_icon_filename(key, n, ext)
        candidate = _STATIC_TROOPS / name
        if candidate.is_file():
            return f"/static/troops/{name}"

    name = troop_icon_filename(key, n, "svg")
    dest = _STATIC_TROOPS / name
    dest.write_text(_svg_badge(key, n), encoding="utf-8")
    return f"/static/troops/{name}"


def ensure_all_troop_icons() -> dict[str, dict[int, str]]:
    return {
        troop_type: {
            tier: troop_icon_url(troop_type, tier) for tier in range(1, 12)
        }
        for troop_type in _TYPE_FILL
    }


def _svg_badge(troop_type: str, tier: int) -> str:
    fill = _TYPE_FILL[troop_type]
    letter = _TYPE_LETTER[troop_type]
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" '
        'viewBox="0 0 64 64">'
        f'<rect width="64" height="64" rx="10" fill="{fill}"/>'
        f'<text x="32" y="28" text-anchor="middle" fill="#e8eaed" '
        f'font-family="IBM Plex Sans,Segoe UI,sans-serif" font-size="18" '
        f'font-weight="700">{letter}</text>'
        f'<text x="32" y="48" text-anchor="middle" fill="#e8eaed" '
        f'font-family="IBM Plex Sans,Segoe UI,sans-serif" font-size="14">'
        f"T{tier}</text>"
        "</svg>\n"
    )
