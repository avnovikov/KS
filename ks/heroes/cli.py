"""CLI: ks-heroes — scrape KingShot hero roster via ADB; recommend role/formation."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from ks.heroes.collector import capture_name_screenshots, collect_heroes
from ks.heroes.config import DEFAULT_HEROES_CONFIG, load_heroes_config
from ks.heroes.gear_collector import collect_gear
from ks.heroes.gear_config import DEFAULT_GEAR_CONFIG, load_gear_config
from ks.heroes.gear_store import GearStore
from ks.heroes.models import HeroRecord
from ks.heroes.store import HeroStore

ROOT = Path(__file__).resolve().parents[2]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ks-heroes",
        description="Collect KingShot heroes and recommend role/formation.",
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
        help="Also accepted for compatibility; name crops are always saved under out/names/.",
    )

    collect_gear_cmd = sub.add_parser(
        "collect-gear",
        help="Walk backpack Gear inventory and OCR each piece detail.",
    )
    collect_gear_cmd.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_GEAR_CONFIG,
        help="Path to gear.yaml (default: config/gear.yaml).",
    )
    collect_gear_cmd.add_argument(
        "--serial",
        type=str,
        default=None,
        help="ADB serial override (default: config adb.serial).",
    )
    collect_gear_cmd.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output directory (default: artifacts/gear/<timestamp>).",
    )
    collect_gear_cmd.add_argument(
        "--dry-run",
        action="store_true",
        help="Print gear collect plan without connecting to ADB.",
    )
    collect_gear_cmd.add_argument(
        "--save-screenshots",
        action="store_true",
        help="Force-save detail screenshots (default follows config save_screenshots).",
    )

    capture_names = sub.add_parser(
        "capture-names",
        help="Re-open each hero from heroes.json and save top-center name crop as names/<Name>.png.",
    )
    capture_names.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_HEROES_CONFIG,
        help="Path to heroes.yaml (default: config/heroes.yaml).",
    )
    capture_names.add_argument(
        "--serial",
        type=str,
        default=None,
        help="ADB serial override (default: config adb.serial).",
    )
    capture_names.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Existing collect output dir containing heroes.json (e.g. artifacts/heroes/full-run).",
    )

    train_names = sub.add_parser(
        "train-names",
        help="Evaluate/train name OCR from labeled names/<Hero>.png crops.",
    )
    train_names.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Collect output dir with names/ crops and heroes.json.",
    )

    recommend = sub.add_parser(
        "recommend",
        help="Pick role/mode + lineup + troops to max expected personal points.",
    )
    recommend.add_argument(
        "--heroes",
        type=Path,
        required=True,
        help="Path to heroes.json from collect.",
    )
    recommend.add_argument(
        "--troops",
        type=Path,
        default=ROOT / "config" / "troops.yaml",
        help="Manual troop inventory YAML.",
    )
    recommend.add_argument(
        "--catalog",
        type=Path,
        default=ROOT / "config" / "hero_catalog.yaml",
        help="Widget/effect overlay YAML.",
    )
    recommend.add_argument(
        "--pro-cache",
        type=Path,
        default=ROOT / "artifacts" / "heroes" / "catalog_cache" / "kingshotpro_heroes.json",
        help="Cached KingshotPro heroes.json (optional if missing).",
    )
    recommend.add_argument(
        "--scenarios",
        type=Path,
        default=ROOT / "config" / "point_scenarios.yaml",
        help="Personal-points scenario priors.",
    )
    recommend.add_argument(
        "--event",
        type=Path,
        default=ROOT / "config" / "events" / "swordland.yaml",
        help="Event feature-weight profile (default: Swordland).",
    )
    recommend.add_argument(
        "--troop-stats",
        type=Path,
        default=ROOT / "config" / "troop_stats.yaml",
        help="Battle base stats per troop type/tier/Truegold.",
    )
    recommend.add_argument(
        "--truegold",
        type=int,
        default=None,
        help="Truegold level for troop stats (default: from troops.yaml or 0).",
    )
    recommend.add_argument(
        "--force-role",
        type=str,
        default=None,
        dest="force_mode",
        help=(
            "Restrict to one mode: garrison|rally_lead|joiner|solo "
            "(aliases: starter=rally_lead for Bear Trap)."
        ),
    )
    recommend.add_argument(
        "--out",
        type=Path,
        default=ROOT / "artifacts" / "heroes" / "recommend_result.json",
        help="Write recommendation JSON here.",
    )
    return p


def _default_out_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return ROOT / "artifacts" / "heroes" / stamp


def _default_gear_out_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return ROOT / "artifacts" / "gear" / stamp


def _load_heroes_json(path: Path) -> list[HeroRecord]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "heroes" in data:
        items = data["heroes"]
    elif isinstance(data, list):
        items = data
    else:
        raise ValueError("heroes.json must be a list or {heroes: [...]}")
    return [HeroRecord.from_dict(item) for item in items]


def _cmd_collect(args: argparse.Namespace) -> int:
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
    print(f"  names: {store.names_dir}")
    return 0


def _cmd_collect_gear(args: argparse.Namespace) -> int:
    try:
        cfg = load_gear_config(args.config)
    except Exception as exc:  # noqa: BLE001
        print(f"Error loading config: {exc}", file=sys.stderr)
        return 1

    if args.save_screenshots:
        from dataclasses import replace

        cfg = replace(cfg, save_screenshots=True)

    if args.dry_run:
        print("gear collect dry-run")
        print(f"  config: {args.config}")
        print(f"  grid cells: {len(cfg.grid.cells)}")
        print(f"  max_pages: {cfg.grid.max_pages}")
        print(f"  adb serial: {args.serial or cfg.adb_serial or '(default device)'}")
        print("  assume Backpack > Gear tab is already open")
        return 0

    out_dir = args.out or _default_gear_out_dir()
    store = GearStore(out_dir)

    from ks.device.adb import AdbDevice

    serial = args.serial or cfg.adb_serial
    try:
        device = AdbDevice.connect(serial=serial)
    except Exception as exc:  # noqa: BLE001
        print(f"Error connecting ADB: {exc}", file=sys.stderr)
        return 1

    print(f"collecting gear → {out_dir}")
    print("tip: leave Backpack > Gear visible before starting")
    pieces = collect_gear(device, cfg, store)
    print(f"done: {len(pieces)} piece(s)")
    print(f"  json: {store.json_path}")
    print(f"  db:   {store.db_path}")
    print(f"  details: {store.details_dir}")
    return 0


def _cmd_capture_names(args: argparse.Namespace) -> int:
    try:
        cfg = load_heroes_config(args.config)
    except Exception as exc:  # noqa: BLE001
        print(f"Error loading config: {exc}", file=sys.stderr)
        return 1

    out_dir = args.out
    if not (out_dir / "heroes.json").is_file():
        print(f"Error: missing {out_dir / 'heroes.json'}", file=sys.stderr)
        return 1

    store = HeroStore(out_dir)
    from ks.device.adb import AdbDevice

    serial = args.serial or cfg.adb_serial
    try:
        device = AdbDevice.connect(serial=serial)
    except Exception as exc:  # noqa: BLE001
        print(f"Error connecting ADB: {exc}", file=sys.stderr)
        return 1

    print(f"capturing name screenshots → {store.names_dir}")
    print("Uses names already in heroes.json (manual fixes are kept).")
    updated = capture_name_screenshots(device, cfg, store)
    print(f"done: {len(updated)} name screenshot(s)")
    return 0


def _cmd_train_names(args: argparse.Namespace) -> int:
    from ks.heroes.name_templates import train_name_ocr_from_crops

    out_dir = args.out
    names_dir = out_dir / "names"
    if not names_dir.is_dir():
        print(f"Error: missing {names_dir} — run capture-names first", file=sys.stderr)
        return 1

    labels: dict[str, str] = {}
    json_path = out_dir / "heroes.json"
    if json_path.is_file():
        raw = json.loads(json_path.read_text(encoding="utf-8"))
        for hero in raw.get("heroes") or []:
            name = str(hero.get("name") or "")
            if name:
                labels[name] = name

    try:
        report = train_name_ocr_from_crops(names_dir, labels=labels)
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    total = max(1, int(report["total"]))
    print(f"trained on {report['total']} crop(s) in {names_dir}")
    print(
        f"  ocr_exact={report['ocr_exact']}/{report['total']} "
        f"ocr_fuzzy={report['ocr_fuzzy']}/{report['total']} "
        f"template_self={report['template_self']}/{report['total']}"
    )
    print(f"  report: {names_dir / 'ocr_train_report.json'}")
    for row in report["crops"]:
        ok = (
            "OK"
            if row["template"] == row["expected"] or row["ocr_fuzzy"] == row["expected"]
            else "MISS"
        )
        print(
            f"  [{ok}] {row['expected']}: "
            f"ocr={row['ocr_raw']!r} fuzzy={row['ocr_fuzzy']!r} "
            f"tmpl={row['template']!r}({row['template_score']})"
        )
    if report["template_self"] == report["total"] or report["ocr_fuzzy"] == report["total"]:
        return 0
    # Partial success is still useful — don't fail hard.
    return 0 if report["total"] else 1


def _cmd_recommend(args: argparse.Namespace) -> int:
    from ks.heroes.optimize.catalog import load_catalog
    from ks.heroes.optimize.events import load_event_profile
    from ks.heroes.optimize.recommend import recommend
    from ks.heroes.optimize.scenarios import load_scenarios
    from ks.heroes.optimize.troop_stats import load_troop_stats
    from ks.heroes.optimize.troops import load_troops_config

    try:
        heroes = _load_heroes_json(args.heroes)
        troops = load_troops_config(args.troops)
        scenarios = load_scenarios(args.scenarios)
        event = load_event_profile(args.event) if args.event else None
        troop_stats = load_troop_stats(args.troop_stats) if args.troop_stats else None
        # truegold: CLI > troops.yaml > stats default
        raw_troops = __import__("yaml").safe_load(args.troops.read_text(encoding="utf-8")) or {}
        tg = args.truegold
        if tg is None:
            tg = int(raw_troops.get("truegold", troop_stats.default_truegold if troop_stats else 0))
        force_mode = args.force_mode
        if force_mode == "starter":
            force_mode = "rally_lead"
        pro_path = args.pro_cache
        if not pro_path.exists():
            # Empty pro cache — YAML-only catalog still works.
            pro_path.parent.mkdir(parents=True, exist_ok=True)
            pro_path.write_text('{"heroes": []}\n', encoding="utf-8")
        catalog = load_catalog(pro_path, args.catalog)
        result = recommend(
            heroes,
            catalog,
            troops,
            scenarios,
            force_mode=force_mode,
            event=event,
            troop_stats=troop_stats,
            truegold=tg,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result.to_dict(), indent=2) + "\n", encoding="utf-8")
    print(f"recommended_mode: {result.recommended_mode}")
    print(f"expected_personal_points: {result.expected_personal_points:.1f}")
    print(f"heroes: {', '.join(h['name'] for h in result.heroes)}")
    print(
        "troops: "
        f"I={result.troops['infantry']} "
        f"C={result.troops['cavalry']} "
        f"A={result.troops['archers']}"
    )
    print(f"wrote: {args.out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "collect":
        return _cmd_collect(args)
    if args.command == "collect-gear":
        return _cmd_collect_gear(args)
    if args.command == "capture-names":
        return _cmd_capture_names(args)
    if args.command == "train-names":
        return _cmd_train_names(args)
    if args.command == "recommend":
        return _cmd_recommend(args)
    parser.error(f"unknown command {args.command!r}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
