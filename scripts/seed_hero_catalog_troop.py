#!/usr/bin/env python3
"""Fill missing hero_catalog.yaml troop/gen/rarity from kingshotdata.com.

Uses ks.heroes.web_stats_catalog (same source as ungared stats).

Usage:
  PYTHONPATH=. python scripts/seed_hero_catalog_troop.py
  PYTHONPATH=. python scripts/seed_hero_catalog_troop.py --heroes Amadeus,Zoe --dry-run
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

from ruamel.yaml import YAML

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "config" / "hero_catalog.yaml"
EXTRACTED_ON = date.today().isoformat()

# Catalog display name → kingshotdata slug when auto-slug would miss.
_SLUG_ALIASES = {
    "Wee & Woo": "wee-woo",
    "Long Fei": "long-fei",
}


def _slug(name: str) -> str:
    if name in _SLUG_ALIASES:
        return _SLUG_ALIASES[name]
    s = name.lower().replace("&", " ").replace("'", "")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


def _normalize_troop(raw: str | None) -> str | None:
    if not raw:
        return None
    key = str(raw).strip().lower()
    if key in ("archer", "archers"):
        return "archers"
    if key in ("infantry", "cavalry"):
        return key
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--heroes", type=str, default="", help="Comma-separated names")
    parser.add_argument(
        "--all-missing",
        action="store_true",
        help="Only heroes in catalog that lack troop (default)",
    )
    parser.add_argument(
        "--all-catalog",
        action="store_true",
        help="Refresh troop/gen/rarity for every catalog hero",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--pause", type=float, default=0.35)
    args = parser.parse_args(argv)

    sys.path.insert(0, str(ROOT))
    from ks.heroes.web_stats_catalog import scrape_hero_slug

    yaml_rt = YAML()
    yaml_rt.preserve_quotes = True
    yaml_rt.width = 100
    data = yaml_rt.load(CATALOG.read_text(encoding="utf-8"))
    heroes_map = data.get("heroes")
    if not isinstance(heroes_map, dict):
        print("error: catalog heroes must be a mapping", file=sys.stderr)
        return 1

    if args.heroes.strip():
        names = [n.strip() for n in args.heroes.split(",") if n.strip()]
    elif args.all_catalog:
        names = list(heroes_map.keys())
    else:
        names = [
            name
            for name, meta in heroes_map.items()
            if not isinstance(meta, dict) or not _normalize_troop(meta.get("troop"))
        ]

    if not names:
        print("nothing to seed")
        return 0

    updated = 0
    failed: list[str] = []
    for name in names:
        if name not in heroes_map:
            print(f"skip {name}: not in catalog")
            continue
        meta = heroes_map[name]
        if not isinstance(meta, dict):
            print(f"skip {name}: bad meta")
            continue
        slug = _slug(name)
        try:
            web = scrape_hero_slug(slug, pause_s=args.pause)
        except Exception as exc:  # noqa: BLE001
            print(f"fail {name}: {slug}: {exc}")
            failed.append(name)
            continue
        troop = _normalize_troop(web.troop)
        if not troop:
            print(f"fail {name}: no troop on {web.source_url}")
            failed.append(name)
            continue
        changes: list[str] = []
        if args.all_catalog or not _normalize_troop(meta.get("troop")):
            if meta.get("troop") != troop:
                meta["troop"] = troop
                changes.append(f"troop={troop}")
        if web.generation is not None and meta.get("gen") is None:
            meta["gen"] = int(web.generation)
            changes.append(f"gen={web.generation}")
        if web.rarity and meta.get("rarity") is None:
            meta["rarity"] = str(web.rarity)
            changes.append(f"rarity={web.rarity}")
        print(f"ok {name}: {', '.join(changes) or 'unchanged'} ← {web.source_url}")
        if changes:
            updated += 1

    if args.dry_run:
        print(f"dry-run: would update {updated}; failed {len(failed)}")
        return 0 if not failed else 1

    with CATALOG.open("w", encoding="utf-8") as fh:
        yaml_rt.dump(data, fh)
    text = CATALOG.read_text(encoding="utf-8")
    note = (
        f"# troop/gen/rarity filled_on: {EXTRACTED_ON} "
        f"from kingshotdata.com/heroes/*\n"
    )
    if "troop/gen/rarity filled_on:" not in text:
        lines = text.splitlines(keepends=True)
        insert_at = 0
        for i, line in enumerate(lines[:40]):
            if "kingshotdata.com" in line or line.startswith("heroes:"):
                insert_at = i + 1
                break
        lines.insert(insert_at, note)
        CATALOG.write_text("".join(lines), encoding="utf-8")

    print(f"wrote {updated} heroes → {CATALOG}")
    if failed:
        print(f"failed ({len(failed)}): {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
