"""CLI: ks-heroes — scrape KingShot hero roster via ADB; recommend role/formation."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from ks.heroes.collector import (
    capture_name_screenshots,
    capture_power_stats,
    capture_star_progress,
    collect_heroes,
)
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

    collect = sub.add_parser(
        "collect",
        help="Walk roster and scrape heroes (incl. stars/pellets vision).",
    )
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

    capture_stars = sub.add_parser(
        "capture-stars",
        help="Re-open each hero and update stars/pellets from the star strip.",
    )
    capture_stars.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_HEROES_CONFIG,
        help="Path to heroes.yaml (default: config/heroes.yaml).",
    )
    capture_stars.add_argument(
        "--serial",
        type=str,
        default=None,
        help="ADB serial override (default: config adb.serial).",
    )
    capture_stars.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Existing collect output dir containing heroes.json.",
    )

    capture_power = sub.add_parser(
        "capture-power-stats",
        help="Re-open each hero; update ONLY power + stats (use unequipped/naked).",
    )
    capture_power.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_HEROES_CONFIG,
        help="Path to heroes.yaml (default: config/heroes.yaml).",
    )
    capture_power.add_argument(
        "--serial",
        type=str,
        default=None,
        help="ADB serial override (default: config adb.serial).",
    )
    capture_power.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Existing collect output dir containing heroes.json.",
    )

    fetch_stats = sub.add_parser(
        "fetch-stats-catalog",
        help="Scrape ungared hero stats from kingshotdata.com into catalog_cache.",
    )
    fetch_stats.add_argument(
        "--out",
        type=Path,
        default=ROOT
        / "artifacts"
        / "heroes"
        / "catalog_cache"
        / "kingshotdata_stats.json",
        help="Write catalog JSON here.",
    )
    fetch_stats.add_argument(
        "--pause",
        type=float,
        default=0.25,
        help="Seconds to pause between hero page fetches.",
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
        "--gear",
        type=Path,
        default=None,
        help="Gear inventory JSON or collect dir (assigns best set per troop class).",
    )
    recommend.add_argument(
        "--gear-profile",
        type=str,
        default="early_game_growth",
        help="hero_gear_optimizer build profile (default: early_game_growth / Bear).",
    )
    recommend.add_argument(
        "--out",
        type=Path,
        default=ROOT / "artifacts" / "heroes" / "recommend_result.json",
        help="Write recommendation JSON here.",
    )
    recommend.add_argument(
        "--beartrap-buffs",
        type=Path,
        default=ROOT / "config" / "beartrap_buffs.yaml",
        help="Trap level / skillmod knobs for Bear damage scoring.",
    )

    bear_damage = sub.add_parser(
        "bear-damage",
        help="What-if Bear Trap damage score for a formation / skillmod.",
    )
    bear_damage.add_argument(
        "--troops",
        type=Path,
        default=ROOT / "config" / "troops.yaml",
        help="Troop inventory YAML.",
    )
    bear_damage.add_argument(
        "--troop-stats",
        type=Path,
        default=ROOT / "config" / "troop_stats.yaml",
        help="Battle base stats YAML.",
    )
    bear_damage.add_argument(
        "--buffs",
        type=Path,
        default=ROOT / "config" / "beartrap_buffs.yaml",
        help="Trap / skillmod knobs.",
    )
    bear_damage.add_argument(
        "--capacity",
        type=int,
        default=None,
        help="March size (default: troops.yaml march_capacity).",
    )
    bear_damage.add_argument(
        "--ratio",
        type=str,
        default="greedy",
        help="Formation: greedy | balanced | archers (10-10-80) | I:C:A e.g. 32:32:36.",
    )
    bear_damage.add_argument(
        "--skillmod",
        type=float,
        default=None,
        help="Override effective skillmod (default: from buffs.yaml).",
    )
    bear_damage.add_argument(
        "--truegold",
        type=int,
        default=None,
        help="Truegold level for troop stats.",
    )
    bear_damage.add_argument(
        "--observed",
        type=int,
        default=None,
        help="If set, print delta vs this observed single-rally score.",
    )

    arena = sub.add_parser(
        "arena",
        help="Pick Arena attack or defense formation (5 heroes, 2F+3B).",
    )
    arena.add_argument(
        "--heroes",
        type=Path,
        required=True,
        help="Path to heroes.json from collect.",
    )
    arena.add_argument(
        "--catalog",
        type=Path,
        default=ROOT / "config" / "hero_catalog.yaml",
        help="Widget/effect overlay YAML.",
    )
    arena.add_argument(
        "--pro-cache",
        type=Path,
        default=ROOT / "artifacts" / "heroes" / "catalog_cache" / "kingshotpro_heroes.json",
        help="Cached KingshotPro heroes.json (optional if missing).",
    )
    arena.add_argument(
        "--roles",
        type=Path,
        default=ROOT / "config" / "arena_roles.yaml",
        help="Arena role / placement weights YAML.",
    )
    arena.add_argument(
        "--side",
        type=str,
        default="attack",
        choices=["attack", "defense"],
        help="Arena side: attack (offense) or defense (offline).",
    )
    arena.add_argument(
        "--gear",
        type=Path,
        default=None,
        help="Gear inventory JSON or collect dir (assigns best set per troop class).",
    )
    arena.add_argument(
        "--gear-profile",
        type=str,
        default="early_game_combat",
        help="hero_gear_optimizer build profile (default: early_game_combat).",
    )
    arena.add_argument(
        "--out",
        type=Path,
        default=ROOT / "artifacts" / "heroes" / "arena_result.json",
        help="Write arena recommendation JSON here.",
    )

    ui = sub.add_parser(
        "ui",
        help="Local FastAPI UI for gear and/or heroes roster edits.",
    )
    ui.add_argument(
        "--gear",
        type=Path,
        default=None,
        help="Gear collect dir (or gear.json). Omit to disable /gear.",
    )
    ui.add_argument(
        "--heroes",
        type=Path,
        default=None,
        help="Heroes collect dir (or heroes.json). Omit to disable /heroes.",
    )
    ui.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_GEAR_CONFIG,
        help="Path to gear.yaml for gear OCR rescan (default: config/gear.yaml).",
    )
    ui.add_argument(
        "--heroes-config",
        type=Path,
        default=DEFAULT_HEROES_CONFIG,
        help="Path to heroes.yaml for heroes OCR rescan (default: config/heroes.yaml).",
    )
    ui.add_argument(
        "--troops",
        type=Path,
        default=None,
        help="Path to troops.yaml (default: config/troops.yaml).",
    )
    ui.add_argument(
        "--serial",
        type=str,
        default=None,
        help="ADB serial override for OCR rescan.",
    )
    ui.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Bind host (default: 127.0.0.1).",
    )
    ui.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Bind port (default: 8765).",
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
    print("  stars/pellets: counted from star strip on each detail screen")
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


def _cmd_capture_stars(args: argparse.Namespace) -> int:
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

    print(f"capturing stars/pellets → {store.json_path}")
    updated = capture_star_progress(device, cfg, store)
    print(f"done: {len(updated)} hero(s) updated")
    return 0


def _cmd_capture_power_stats(args: argparse.Namespace) -> int:
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

    print(f"capturing naked power/stats → {store.json_path}")
    print("tip: unequip all gear first; leave Heroes roster visible")
    print("updates ONLY power + stats (keeps level/stars/pellets/skills)")
    updated = capture_power_stats(device, cfg, store)
    print(f"done: {len(updated)} hero(s) updated")
    return 0


def _cmd_fetch_stats_catalog(args: argparse.Namespace) -> int:
    from ks.heroes.web_stats_catalog import scrape_catalog, write_catalog

    try:
        payload = scrape_catalog(pause_s=float(args.pause))
        path = write_catalog(payload, args.out)
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    meta = payload["_meta"]
    print(
        f"wrote {path} heroes={meta['count']} errors={len(meta.get('errors') or [])}"
    )
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
    from ks.heroes.optimize.bear_damage import load_beartrap_buffs
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
        gear_pieces = None
        if args.gear is not None:
            from ks.heroes.optimize.gear_assign import load_gear_pieces

            gear_pieces = load_gear_pieces(args.gear)
        buffs = None
        if event is not None and event.name == "beartrap":
            buffs_path = getattr(args, "beartrap_buffs", None)
            if buffs_path and Path(buffs_path).exists():
                buffs = load_beartrap_buffs(buffs_path)
        result = recommend(
            heroes,
            catalog,
            troops,
            scenarios,
            force_mode=force_mode,
            event=event,
            troop_stats=troop_stats,
            truegold=tg,
            gear=gear_pieces,
            gear_profile=args.gear_profile,
            beartrap_buffs=buffs,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result.to_dict(), indent=2) + "\n", encoding="utf-8")
    print(f"recommended_mode: {result.recommended_mode}")
    label = (
        "predicted_bear_damage"
        if "bear_damage" in result.breakdown
        else "expected_personal_points"
    )
    print(f"{label}: {result.expected_personal_points:.1f}")
    print(f"heroes: {', '.join(h['name'] for h in result.heroes)}")
    print(
        "troops: "
        f"I={result.troops['infantry']} "
        f"C={result.troops['cavalry']} "
        f"A={result.troops['archers']}"
    )
    if result.breakdown:
        interesting = (
            "skillmod",
            "trap_attack_bonus",
            "round_damage",
            "hero_strength",
            "archers_round_damage",
            "cavalry_round_damage",
            "infantry_round_damage",
        )
        bits = [
            f"{k}={result.breakdown[k]:.4g}"
            for k in interesting
            if k in result.breakdown
        ]
        if bits:
            print(f"breakdown: {', '.join(bits)}")
    if result.gear_assignment:
        print("gear:")
        for name, rows in result.gear_assignment.items():
            if not rows:
                print(f"  {name}: (no pieces for class)")
                continue
            bits = [
                f"{r['slot']}={r.get('name') or r['piece_id']}"
                f"+{r.get('enhancement_level') or 0}"
                for r in rows
            ]
            print(f"  {name}: {', '.join(bits)}")
    print(f"wrote: {args.out}")
    return 0


def _cmd_bear_damage(args: argparse.Namespace) -> int:
    from ks.heroes.optimize.bear_damage import (
        fill_ratio_march,
        greedy_fill_march,
        load_beartrap_buffs,
        simulate_from_units,
    )
    from ks.heroes.optimize.troop_stats import load_troop_stats
    from ks.heroes.optimize.troops import load_troops_config

    try:
        troops = load_troops_config(args.troops)
        table = load_troop_stats(args.troop_stats)
        buffs = load_beartrap_buffs(args.buffs)
        raw = __import__("yaml").safe_load(args.troops.read_text(encoding="utf-8")) or {}
        tg = args.truegold
        if tg is None:
            tg = int(raw.get("truegold", table.default_truegold))
        capacity = int(args.capacity) if args.capacity is not None else troops.march_capacity
        capacity = min(capacity, troops.infantry + troops.cavalry + troops.archers)
        inventory = {
            "infantry": troops.levels("infantry") or ({6: troops.infantry} if troops.infantry else {}),
            "cavalry": troops.levels("cavalry") or ({6: troops.cavalry} if troops.cavalry else {}),
            "archers": troops.levels("archers") or ({6: troops.archers} if troops.archers else {}),
        }
        skillmod = (
            float(args.skillmod)
            if args.skillmod is not None
            else buffs.effective_skillmod(0.0)
        )
        ratio = str(args.ratio).strip().lower()
        if ratio == "greedy":
            counts, _levels, result = greedy_fill_march(
                inventory,
                capacity=capacity,
                table=table,
                truegold=tg,
                skillmod=skillmod,
                trap_attack_bonus=buffs.trap_attack_bonus,
                host_attack_pct=buffs.host_attack_pct,
            )
        else:
            if ratio in {"balanced", "33-33-33", "1:1:1"}:
                ratios = {"infantry": 1.0, "cavalry": 1.0, "archers": 1.0}
            elif ratio in {"archers", "10-10-80", "archer"}:
                ratios = {"infantry": 10.0, "cavalry": 10.0, "archers": 80.0}
            elif ":" in ratio:
                parts = [float(p) for p in ratio.split(":")]
                if len(parts) != 3:
                    raise ValueError(f"ratio must be I:C:A; got {args.ratio!r}")
                ratios = {
                    "infantry": parts[0],
                    "cavalry": parts[1],
                    "archers": parts[2],
                }
            else:
                raise ValueError(
                    f"unknown --ratio {args.ratio!r}; use greedy|balanced|archers|I:C:A"
                )
            counts, _levels, units = fill_ratio_march(
                inventory,
                capacity=capacity,
                ratios=ratios,
                table=table,
                truegold=tg,
            )
            result = simulate_from_units(
                units,
                counts,
                skillmod=skillmod,
                trap_attack_bonus=buffs.trap_attack_bonus,
                host_attack_pct=buffs.host_attack_pct,
            )
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"score: {result.score}")
    print(
        "troops: "
        f"I={counts['infantry']} C={counts['cavalry']} A={counts['archers']} "
        f"(cap={capacity})"
    )
    print(
        f"skillmod={result.skillmod:.4g} "
        f"trap_attack_bonus={result.trap_attack_bonus:.4g} "
        f"round_damage={result.round_damage_total:.4g}"
    )
    for typ in ("infantry", "cavalry", "archers"):
        row = result.by_type[typ]
        print(
            f"  {typ}: n={row.count} army={row.army:.1f} "
            f"atk/troop={row.attack_per_troop:.4g} round={row.round_damage:.4g}"
        )
    if args.observed is not None:
        delta = result.score - int(args.observed)
        pct = 100.0 * delta / int(args.observed) if args.observed else 0.0
        print(f"delta_vs_observed: {delta:+d} ({pct:+.2f}%)")
    return 0


def _cmd_arena(args: argparse.Namespace) -> int:
    from ks.heroes.optimize.arena import load_arena_roles, optimize_arena
    from ks.heroes.optimize.catalog import load_catalog

    try:
        heroes = _load_heroes_json(args.heroes)
        pro_path = args.pro_cache
        if not pro_path.exists():
            pro_path.parent.mkdir(parents=True, exist_ok=True)
            pro_path.write_text('{"heroes": []}\n', encoding="utf-8")
        catalog = load_catalog(pro_path, args.catalog)
        roles = load_arena_roles(args.roles, catalog=catalog)
        gear_pieces = None
        if args.gear is not None:
            from ks.heroes.optimize.gear_assign import load_gear_pieces

            gear_pieces = load_gear_pieces(args.gear)
        result = optimize_arena(
            args.side,
            heroes,
            catalog,
            roles,
            gear=gear_pieces,
            gear_profile=args.gear_profile,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if result.status != "Optimal":
        print(f"Error: arena solve status={result.status}", file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result.to_dict(), indent=2) + "\n", encoding="utf-8")
    print(f"side: {result.side}")
    print(f"score: {result.score:.1f}")
    print("formation (2 front / 3 back):")
    for slot in ("F1", "F2", "B1", "B2", "B3"):
        name = result.formation.get(slot, "?")
        reason = result.reasons.get(name, "")
        print(f"  {slot}: {name}" + (f"  ({reason})" if reason else ""))
    if result.gear_assignment:
        print("gear:")
        for name, rows in result.gear_assignment.items():
            if not rows:
                print(f"  {name}: (no pieces for class)")
                continue
            bits = [
                f"{r['slot']}={r.get('name') or r['piece_id']}"
                f"+{r.get('enhancement_level') or 0}"
                for r in rows
            ]
            print(f"  {name}: {', '.join(bits)}")
    print(f"wrote: {args.out}")
    return 0


def _cmd_ui(args: argparse.Namespace) -> int:
    from ks.heroes.ui import run_ui

    gear = Path(args.gear) if args.gear is not None else None
    heroes = Path(args.heroes) if args.heroes is not None else None
    if gear is None and heroes is None:
        # Keep prior default when neither flag is passed.
        gear = ROOT / "artifacts" / "gear" / "full-run"

    if gear is not None:
        if not gear.exists():
            print(
                f"error: gear path not found: {gear}\n"
                "Re-run collect-gear or pass --gear <dir>.",
                file=sys.stderr,
            )
            return 1
        gear_json = gear if gear.is_file() else gear / "gear.json"
        if gear.is_dir() and not gear_json.is_file():
            print(
                f"error: missing {gear_json}\n"
                "Re-run collect-gear or pass --gear <dir-with-gear.json>.",
                file=sys.stderr,
            )
            return 1

    if heroes is not None:
        if not heroes.exists():
            print(
                f"error: heroes path not found: {heroes}\n"
                "Re-run collect or pass --heroes <dir>.",
                file=sys.stderr,
            )
            return 1
        heroes_json = heroes if heroes.is_file() else heroes / "heroes.json"
        if heroes.is_dir() and not heroes_json.is_file():
            print(
                f"error: missing {heroes_json}\n"
                "Re-run collect or pass --heroes <dir-with-heroes.json>.",
                file=sys.stderr,
            )
            return 1

    run_ui(
        gear,
        heroes_dir=heroes,
        troops_path=Path(args.troops) if args.troops is not None else None,
        host=str(args.host),
        port=int(args.port),
        gear_config=Path(args.config),
        heroes_config=Path(args.heroes_config),
        serial=args.serial,
    )
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
    if args.command == "capture-stars":
        return _cmd_capture_stars(args)
    if args.command == "capture-power-stats":
        return _cmd_capture_power_stats(args)
    if args.command == "fetch-stats-catalog":
        return _cmd_fetch_stats_catalog(args)
    if args.command == "train-names":
        return _cmd_train_names(args)
    if args.command == "recommend":
        return _cmd_recommend(args)
    if args.command == "bear-damage":
        return _cmd_bear_damage(args)
    if args.command == "arena":
        return _cmd_arena(args)
    if args.command == "ui":
        return _cmd_ui(args)
    parser.error(f"unknown command {args.command!r}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
