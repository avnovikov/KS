"""Gear icons for the UI: bundled web icons, detail crops, then SVG fallback."""

from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path

from ks.heroes.gear_models import GearRecord

# Detail-modal icon region (1080×1920 portrait calibrations in gear.yaml).
_DETAIL_ICON_BOX = (100, 280, 200, 200)  # x, y, w, h

_STATIC_GEAR_PIECES = Path(__file__).resolve().parent / "static" / "gear-pieces"

_RARITY_COLORS = {
    "mythic": ("#f0c674", "#8a6a20"),
    "gold": ("#f0c674", "#8a6a20"),
    "epic": ("#c39bd3", "#5b2c6f"),
    "purple": ("#c39bd3", "#5b2c6f"),
    "blue": ("#85c1e9", "#1a5276"),
    "rare": ("#85c1e9", "#1a5276"),
    "green": ("#82e0aa", "#196f3d"),
    "uncommon": ("#82e0aa", "#196f3d"),
    "red": ("#f1948a", "#7b241c"),
}

_TROOP_FILL = {
    "infantry": "#4a6741",
    "cavalry": "#6b4c2a",
    "archers": "#2a4a6b",
    "archer": "#2a4a6b",
}

_SLOT_GLYPH = {
    "helmet": "H",
    "helm": "H",
    "chest": "C",
    "gloves": "G",
    "boots": "B",
}

_SLOT_FILE = {
    "helmet": "helm",
    "helm": "helm",
    "chest": "chest",
    "gloves": "gloves",
    "boots": "boots",
}


def icons_dir_for(gear_dir: Path) -> Path:
    path = gear_dir / "icons"
    path.mkdir(parents=True, exist_ok=True)
    return path


def icon_filename(piece_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", piece_id)
    return f"{safe}.svg"


def _normalize_troop_key(troop: str | None) -> str | None:
    if not troop:
        return None
    key = troop.strip().lower()
    if key in ("archer", "archers"):
        return "archer"
    if key in ("infantry", "cavalry"):
        return key
    return None


def bundled_piece_icon(piece: GearRecord) -> Path | None:
    """Path to downloaded troop+slot PNG from Kingshot Optimizer, if present."""
    troop = _normalize_troop_key(piece.troop_type)
    slot = _SLOT_FILE.get((piece.slot or "").lower())
    if troop is None or slot is None:
        # Infer slot from name when OCR slot missing
        name = (piece.name or "").lower()
        for needle, key in (
            ("armet", "helm"),
            ("faceplate", "helm"),
            ("helm", "helm"),
            ("hel", "helm"),
            ("shroud", "chest"),
            ("leatherwear", "chest"),
            ("breastplate", "chest"),
            ("gloves", "gloves"),
            ("gauntlet", "gloves"),
            ("bracers", "gloves"),
            ("boots", "boots"),
            ("greaves", "boots"),
            ("riders", "boots"),
        ):
            if needle in name:
                slot = key
                break
    if troop is None or slot is None:
        return None
    path = _STATIC_GEAR_PIECES / f"{troop}-{slot}.png"
    return path if path.is_file() else None


def ensure_piece_icon(piece: GearRecord, gear_dir: Path) -> str:
    """Ensure an icon is available; return URL path under /static or /icons."""
    bundled = bundled_piece_icon(piece)
    if bundled is not None:
        # Also copy into gear_dir/icons for offline browse of that inventory
        out_dir = icons_dir_for(gear_dir)
        dest = out_dir / f"{piece.piece_id}.png"
        if not dest.is_file() or dest.stat().st_size != bundled.stat().st_size:
            shutil.copy2(bundled, dest)
        return f"/static/gear-pieces/{bundled.name}"

    out_dir = icons_dir_for(gear_dir)
    png_override = out_dir / f"{piece.piece_id}.png"
    if png_override.is_file():
        return f"/icons/{png_override.name}"

    cropped = _try_crop_detail_icon(piece, gear_dir, out_dir)
    if cropped is not None:
        return f"/icons/{cropped.name}"

    name = icon_filename(piece.piece_id)
    dest = out_dir / name
    dest.write_text(_svg_for_piece(piece), encoding="utf-8")
    return f"/icons/{name}"


def ensure_all_icons(pieces: list[GearRecord], gear_dir: Path) -> dict[str, str]:
    """Build icons for every piece; map piece_id → URL path."""
    return {p.piece_id: ensure_piece_icon(p, gear_dir) for p in pieces}


def _try_crop_detail_icon(
    piece: GearRecord, gear_dir: Path, out_dir: Path
) -> Path | None:
    rel = piece.detail_screenshot
    if not rel:
        return None
    src = gear_dir / rel
    if not src.is_file():
        return None
    try:
        import cv2
    except ImportError:
        return None
    img = cv2.imread(str(src))
    if img is None:
        return None
    x, y, w, h = _DETAIL_ICON_BOX
    x1, y1 = max(0, x), max(0, y)
    x2, y2 = min(img.shape[1], x + w), min(img.shape[0], y + h)
    crop = img[y1:y2, x1:x2]
    if crop.size == 0:
        return None
    dest = out_dir / f"{piece.piece_id}.png"
    cv2.imwrite(str(dest), crop)
    return dest


def _svg_for_piece(piece: GearRecord) -> str:
    rarity = (piece.rarity or "blue").lower()
    edge, _ink = _RARITY_COLORS.get(rarity, ("#9aa0a6", "#3a3f4b"))
    troop = (piece.troop_type or "").lower()
    fill = _TROOP_FILL.get(troop, "#3a3f4b")
    slot = (piece.slot or "").lower()
    glyph = _SLOT_GLYPH.get(slot, "?")
    label = _set_abbrev(piece.name)
    digest = hashlib.md5((piece.name or piece.piece_id).encode()).hexdigest()
    accent = f"#{digest[:6]}"
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{fill}"/>
      <stop offset="100%" stop-color="{accent}"/>
    </linearGradient>
  </defs>
  <rect x="2" y="2" width="60" height="60" rx="10" fill="url(#g)" stroke="{edge}" stroke-width="3"/>
  <text x="32" y="28" text-anchor="middle" font-family="Georgia, serif" font-size="18" font-weight="700" fill="{edge}">{glyph}</text>
  <text x="32" y="48" text-anchor="middle" font-family="system-ui,sans-serif" font-size="9" font-weight="600" fill="#e8eaed">{label}</text>
</svg>
"""


def _set_abbrev(name: str | None) -> str:
    if not name:
        return "??"
    cleaned = re.sub(r"[^A-Za-z0-9\s]", " ", name)
    parts = [p for p in cleaned.split() if p]
    if not parts:
        return "??"
    if len(parts[0]) <= 3 and len(parts) == 1:
        return parts[0].upper()[:3]
    skip = {
        "armet",
        "helm",
        "hel",
        "faceplate",
        "shroud",
        "gloves",
        "gauntlets",
        "bracers",
        "boots",
        "greaves",
        "leatherwear",
        "riders",
        "battle",
        "tae",
    }
    for part in parts:
        if part.lower() not in skip:
            return part[:3].upper()
    return parts[0][:3].upper()
