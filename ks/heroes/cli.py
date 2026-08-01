"""CLI: ks-heroes — scrape KingShot hero roster via ADB."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from ks.heroes.collector import collect_heroes
from ks.heroes.config import DEFAULT_HEROES_CONFIG, load_heroes_config
from ks.heroes.store import HeroStore

ROOT = Path(__file__).resolve().parents[2]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ks-heroes",
        description="Collect KingShot hero stats and skills via ADB.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    collect = sub.add_parser("collect", help="Walk roster and scrape heroes.")
    collect.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_HEROES_CONFIG,
        help="Path to heroes.yaml (default: config/heroes.yaml).",
    )
    collect.add_argument(
        "--serial",
        type=str,
        default=None,
        help="ADB serial override (default: config adb.serial).",
    )
    collect.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output directory (default: artifacts/heroes/<timestamp>).",
    )
    collect.add_argument(
        "--dry-run",
        action="store_true",
        help="Print roster plan without connecting to ADB.",
    )
    collect.add_argument(
        "--save-screenshots",
        action="store_true",
        help="Reserved: save debug screenshots under out/screens (v1 no-op flag).",
    )
    return p


def _default_out_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return ROOT / "artifacts" / "heroes" / stamp


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command != "collect":
        parser.error(f"unknown command {args.command!r}")

    try:
        cfg = load_heroes_config(args.config)
    except Exception as exc:  # noqa: BLE001
        print(f"Error loading config: {exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        print("heroes collect dry-run")
        print(f"  config: {args.config}")
        print(f"  roster cells: {len(cfg.roster.cells)}")
        print(f"  skill slots: {len(cfg.skill_slots)}")
        print(f"  max_pages: {cfg.roster.max_pages}")
        print(f"  adb serial: {args.serial or cfg.adb_serial or '(default device)'}")
        return 0

    out_dir = args.out or _default_out_dir()
    store = HeroStore(out_dir)

    from ks.device.adb import AdbDevice

    serial = args.serial or cfg.adb_serial
    try:
        device = AdbDevice.connect(serial=serial)
    except Exception as exc:  # noqa: BLE001
        print(f"Error connecting ADB: {exc}", file=sys.stderr)
        return 1

    print(f"collecting heroes → {out_dir}")
    heroes = collect_heroes(device, cfg, store)
    print(f"done: {len(heroes)} hero(s)")
    print(f"  json: {store.json_path}")
    print(f"  db:   {store.db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
