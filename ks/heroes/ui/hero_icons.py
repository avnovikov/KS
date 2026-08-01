"""Hero portrait resolution for the roster UI."""

from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path

from ks.heroes.models import HeroRecord

_STATIC_HEROES = Path(__file__).resolve().parent / "static" / "heroes"
_TROOP_FILL = {
    "infantry": "#5d6d7e",
    "cavalry": "#7d6608",
    "archer": "#1a5276",
    "archers": "#1a5276",
}


def hero_slug(name: str) -> str:
    slug = name.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-") or "hero"


def icons_dir_for(heroes_dir: Path) -> Path:
    path = heroes_dir / "icons"
    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_hero_icon(hero: HeroRecord, heroes_dir: Path) -> str:
    """Return URL path under /static/heroes or /hero-icons."""
    slug = hero_slug(hero.name)
    for candidate in (
        _STATIC_HEROES / f"{slug}.webp",
        _STATIC_HEROES / f"{slug}.png",
    ):
        if candidate.is_file():
            return f"/static/heroes/{candidate.name}"

    out_dir = icons_dir_for(heroes_dir)
    name_shot = _copy_name_screenshot(hero, heroes_dir, out_dir)
    if name_shot is not None:
        return f"/hero-icons/{name_shot.name}"

    dest = out_dir / f"{slug}.svg"
    dest.write_text(_svg_for_hero(hero), encoding="utf-8")
    return f"/hero-icons/{dest.name}"


def ensure_all_hero_icons(
    heroes: list[HeroRecord], heroes_dir: Path
) -> dict[str, str]:
    return {h.name: ensure_hero_icon(h, heroes_dir) for h in heroes}


def _copy_name_screenshot(
    hero: HeroRecord, heroes_dir: Path, out_dir: Path
) -> Path | None:
    rel = hero.name_screenshot
    if not rel:
        return None
    # Refuse path escape
    if ".." in rel.replace("\\", "/").split("/"):
        return None
    src = (heroes_dir / rel).resolve()
    try:
        src.relative_to(heroes_dir.resolve())
    except ValueError:
        return None
    if not src.is_file():
        return None
    dest = out_dir / f"{hero_slug(hero.name)}{src.suffix or '.png'}"
    if not dest.is_file() or dest.stat().st_mtime < src.stat().st_mtime:
        shutil.copy2(src, dest)
    return dest


def _svg_for_hero(hero: HeroRecord) -> str:
    troop = (hero.troop_type or "").lower()
    fill = _TROOP_FILL.get(troop, "#3a3f4b")
    letter = (hero.name.strip()[:1] or "?").upper()
    digest = hashlib.md5(hero.name.encode()).hexdigest()
    accent = f"#{digest[:6]}"
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{fill}"/>
      <stop offset="100%" stop-color="{accent}"/>
    </linearGradient>
  </defs>
  <rect x="2" y="2" width="60" height="60" rx="12" fill="url(#g)" stroke="#6cb2ff" stroke-width="2"/>
  <text x="32" y="40" text-anchor="middle" font-family="Georgia, serif" font-size="28" font-weight="700" fill="#e8eaed">{letter}</text>
</svg>
"""
