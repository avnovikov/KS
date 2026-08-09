#!/usr/bin/env python3
"""Seed hero_catalog.yaml skills from kingshotmastery.com hero pages.

Usage:
  python scripts/seed_hero_catalog_skills.py [--heroes Helga,Chenko] [--all-catalog]
"""

from __future__ import annotations

import argparse
import html as html_lib
import json
import re
import ssl
import subprocess
import sys
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "config" / "hero_catalog.yaml"
SOURCE = "https://kingshotmastery.com/heroes/{slug}"
EXTRACTED_ON = "2026-08-09"

_BONUS_TO_KIND = {
    "lethality up": "lethality_up",
    "attack up": "attack_up",
    "defense up": "defense_up",
    "health up": "health_up",
    "damage taken down": "damage_taken_down",
    "damage up": "damage_up",
    "area of effect damage up": "aoe_damage_up",
    "squads' attack": "attack_up",
    "squads' lethality": "lethality_up",
    "squads' defense": "defense_up",
    "squads' health": "health_up",
}


def _slug(name: str) -> str:
    return (
        name.lower()
        .replace("&", "")
        .replace("  ", " ")
        .strip()
        .replace(" ", "-")
        .replace("'", "")
    )


def _fetch(url: str) -> str:
    try:
        proc = subprocess.run(
            ["curl", "-fsSL", "-A", "KS-catalog-seed/1.0", url],
            check=True,
            capture_output=True,
        )
        return proc.stdout.decode("utf-8", errors="replace")
    except (FileNotFoundError, subprocess.CalledProcessError):
        ctx = ssl.create_default_context()
        try:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        except Exception:
            pass
        req = urllib.request.Request(url, headers={"User-Agent": "KS-catalog-seed/1.0"})
        with urllib.request.urlopen(req, context=ctx, timeout=45) as resp:
            return resp.read().decode("utf-8", errors="replace")


def _headings(html: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for level, inner in re.findall(r"<h([34])[^>]*>(.*?)</h\1>", html, flags=re.I | re.S):
        text = re.sub(r"<[^>]+>", "", inner)
        text = html_lib.unescape(text)
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            out.append((int(level), text))
    return out


def _bonus_near(html: str, skill_name: str) -> str | None:
    """Find first bonus label after the skill's h4 in the HTML."""
    pat = re.compile(
        rf"<h4[^>]*>\s*{re.escape(html_lib.escape(skill_name))}\s*</h4>(.*?)<h[34]\b",
        re.I | re.S,
    )
    m = pat.search(html)
    chunk = m.group(1) if m else ""
    if not chunk:
        # Names may appear unescaped in HTML.
        pat2 = re.compile(
            rf"<h4[^>]*>[^<]*{re.escape(skill_name)}[^<]*</h4>(.*?)<h[34]\b",
            re.I | re.S,
        )
        m = pat2.search(html)
        chunk = m.group(1) if m else ""
    if not chunk:
        m2 = re.search(
            rf"<h4[^>]*>[^<]*{re.escape(skill_name)}[^<]*</h4>(.*)$",
            html,
            re.I | re.S,
        )
        chunk = (m2.group(1) if m2 else "")[:2500]
    for label, kind in _BONUS_TO_KIND.items():
        if re.search(re.escape(label), chunk, re.I):
            return kind
    return None


def parse_skills(html: str, *, effect_kinds: set[str] | None = None) -> list[dict]:
    headings = _headings(html)
    family: str | None = None
    skills: list[dict] = []
    slot = 0
    for level, text in headings:
        low = text.lower()
        if level == 3 and low in {"conquest", "expedition", "widget", "widgets"}:
            family = "widget" if low.startswith("widget") else low
            continue
        if level == 4 and family in {"conquest", "expedition", "widget"}:
            row: dict = {"slot": slot, "name": text, "family": family}
            kind = _bonus_near(html, text)
            if kind and (effect_kinds is None or kind in effect_kinds):
                # Prefer linking expedition skills used by optimisers.
                if family == "expedition" or kind in (effect_kinds or set()):
                    row["effect_kind"] = kind
            skills.append(row)
            slot += 1
    return skills


def _roster_names() -> list[str]:
    path = Path("/Users/alexei/KS/data/heroes/full-run/heroes.json")
    if not path.is_file():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    heroes = raw.get("heroes") if isinstance(raw, dict) else raw
    if isinstance(heroes, dict):
        heroes = list(heroes.values())
    return [str(h["name"]) for h in heroes if isinstance(h, dict) and h.get("name")]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--heroes", type=str, default="", help="Comma-separated names")
    parser.add_argument(
        "--all-catalog",
        action="store_true",
        help="Seed every hero already in hero_catalog.yaml",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print parsed skills; do not write YAML",
    )
    args = parser.parse_args(argv)

    raw = yaml.safe_load(CATALOG.read_text(encoding="utf-8")) or {}
    heroes_map = raw.get("heroes") or {}
    if not isinstance(heroes_map, dict):
        print("error: catalog heroes must be a mapping", file=sys.stderr)
        return 1

    if args.heroes.strip():
        names = [n.strip() for n in args.heroes.split(",") if n.strip()]
    elif args.all_catalog:
        names = sorted(heroes_map)
    else:
        names = _roster_names() or sorted(heroes_map)

    updated = 0
    for name in names:
        if name not in heroes_map:
            print(f"skip {name}: not in catalog")
            continue
        url = SOURCE.format(slug=_slug(name))
        try:
            html = _fetch(url)
        except Exception as exc:  # noqa: BLE001
            print(f"fail {name}: fetch {url}: {exc}")
            continue
        existing_effects = heroes_map[name].get("effects") or []
        kinds = {
            str(e.get("kind"))
            for e in existing_effects
            if isinstance(e, dict) and e.get("kind")
        }
        skills = parse_skills(html, effect_kinds=kinds or None)
        if not skills:
            print(f"fail {name}: no skills parsed from {url}")
            continue
        print(f"{name}: {len(skills)} skills from {url}")
        for s in skills:
            print(
                f"  [{s['slot']}] {s['family']}: {s['name']}"
                + (f" → {s['effect_kind']}" if s.get("effect_kind") else "")
            )
        if not args.dry_run:
            meta = dict(heroes_map[name])
            meta["skills"] = skills
            heroes_map[name] = meta
            updated += 1

    if args.dry_run:
        return 0

    from ruamel.yaml import YAML

    yaml_rt = YAML()
    yaml_rt.preserve_quotes = True
    yaml_rt.width = 100
    data = yaml_rt.load(CATALOG.read_text(encoding="utf-8"))
    if "heroes" not in data:
        print("error: catalog missing heroes", file=sys.stderr)
        return 1
    for name in names:
        if name in heroes_map and "skills" in heroes_map[name]:
            data["heroes"][name]["skills"] = heroes_map[name]["skills"]
    # Header note
    # ruamel may not keep plain comment edits; prepend via text if missing.
    with CATALOG.open("w", encoding="utf-8") as fh:
        yaml_rt.dump(data, fh)
    text = CATALOG.read_text(encoding="utf-8")
    if "skills extracted_on:" not in text:
        lines = text.splitlines(keepends=True)
        insert_at = 0
        for i, line in enumerate(lines[:40]):
            if "kingshotmastery.com/heroes" in line or line.startswith("heroes:"):
                insert_at = i + 1
                break
        lines.insert(
            insert_at,
            f"# skills extracted_on: {EXTRACTED_ON} from kingshotmastery.com/heroes/*\n",
        )
        CATALOG.write_text("".join(lines), encoding="utf-8")
    print(f"wrote {updated} heroes → {CATALOG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
