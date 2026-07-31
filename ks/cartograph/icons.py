"""Inline SVG icons for cartograph map (vector, not bitmaps)."""

from __future__ import annotations

# ViewBox 0 0 32 32 — drawn at tile centers on the iso map.
ICON_SVG: dict[str, str] = {
    "city": """
      <path d="M6 26 V14 L10 10 V14 L14 10 V14 L18 8 V14 L22 10 V26 Z"
            fill="#7c6b9a" stroke="#e8e0ff" stroke-width="1.2"/>
      <rect x="13" y="18" width="6" height="8" fill="#3d3550"/>
      <circle cx="16" cy="6" r="2.2" fill="#f0d878"/>
    """,
    "beast": """
      <ellipse cx="16" cy="18" rx="9" ry="7" fill="#5a3a2a" stroke="#f0c090" stroke-width="1.2"/>
      <circle cx="12" cy="16" r="1.6" fill="#f5e6d0"/>
      <circle cx="20" cy="16" r="1.6" fill="#f5e6d0"/>
      <path d="M8 12 L11 8 M24 12 L21 8" stroke="#f0c090" stroke-width="1.5" fill="none"/>
    """,
    "bread": """
      <ellipse cx="16" cy="18" rx="10" ry="7" fill="#d4a017" stroke="#fff0c0" stroke-width="1.2"/>
      <path d="M8 16 Q16 10 24 16" fill="none" stroke="#8a6010" stroke-width="1.2"/>
    """,
    "wood": """
      <path d="M16 6 L22 16 H10 Z" fill="#2f7d32" stroke="#b8f0b0" stroke-width="1"/>
      <path d="M16 12 L24 24 H8 Z" fill="#256b28" stroke="#b8f0b0" stroke-width="1"/>
      <rect x="14.5" y="22" width="3" height="6" fill="#6b4423"/>
    """,
    "stone": """
      <path d="M6 22 L10 10 L18 8 L26 14 L24 24 L10 26 Z"
            fill="#8a9098" stroke="#e0e4ea" stroke-width="1.2"/>
    """,
    "iron": """
      <path d="M16 6 L26 26 H6 Z" fill="#6a7a8a" stroke="#d0e0f0" stroke-width="1.2"/>
      <circle cx="16" cy="18" r="3" fill="#c0d0e0"/>
    """,
    "rss": """
      <rect x="8" y="12" width="16" height="12" rx="2" fill="#8b6914" stroke="#ffe9a0" stroke-width="1.2"/>
      <path d="M8 16 H24" stroke="#ffe9a0" stroke-width="1"/>
      <rect x="12" y="8" width="8" height="4" fill="#a07820"/>
    """,
    "mill": """
      <circle cx="16" cy="16" r="3" fill="#c4a574" stroke="#fff0d0" stroke-width="1"/>
      <path d="M16 16 L16 4 M16 16 L26 22 M16 16 L6 22" stroke="#e8d0a0" stroke-width="2.5" stroke-linecap="round"/>
      <rect x="14" y="22" width="4" height="6" fill="#6b4423"/>
    """,
    "banner": """
      <path d="M10 6 V26 M10 6 H22 L18 12 L22 18 H10" fill="#c43c3c" stroke="#ffd0d0" stroke-width="1"/>
    """,
    "trap": """
      <rect x="6" y="10" width="20" height="14" rx="2" fill="none" stroke="#5ec8ff" stroke-width="2"/>
      <text x="16" y="20" text-anchor="middle" font-size="8" fill="#5ec8ff" font-family="monospace">T</text>
    """,
    "hq": """
      <path d="M4 24 V12 L16 4 L28 12 V24 Z" fill="#2b4a6b" stroke="#9fd0ff" stroke-width="1.2"/>
      <rect x="13" y="14" width="6" height="10" fill="#1a3050"/>
    """,
    "building": """
      <rect x="8" y="10" width="16" height="16" fill="#8b5a2b" stroke="#e8c090" stroke-width="1.2"/>
      <path d="M8 10 L16 4 L24 10" fill="#a06830" stroke="#e8c090" stroke-width="1"/>
    """,
    "kingdom": """
      <path d="M6 22 L8 10 L12 16 L16 8 L20 16 L24 10 L26 22 Z"
            fill="#c9a227" stroke="#fff0b0" stroke-width="1.2"/>
    """,
}


def icon_for_kind(kind: str) -> str:
    if kind in ICON_SVG:
        return ICON_SVG[kind]
    if kind in ("woodmill",):
        return ICON_SVG["mill"]
    return ICON_SVG["rss"]


def legend_items() -> list[tuple[str, str]]:
    order = (
        "city",
        "beast",
        "bread",
        "wood",
        "stone",
        "iron",
        "rss",
        "mill",
        "banner",
        "trap",
        "hq",
        "kingdom",
    )
    return [(k, ICON_SVG[k]) for k in order if k in ICON_SVG]
