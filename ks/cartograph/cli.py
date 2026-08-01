"""CLI: ks-cartograph — map ±R tiles around current / fixture viewport."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ks.cartograph.pipeline import (
    dry_run_plan,
    format_dry_run,
    load_viewports_yaml,
    mask_config_from_calibration,
    register_and_digitize_capture,
    resolve_capture_stitch_route,
    run_fixture_dir,
    run_live_frames,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CAL = ROOT / "assets" / "reference" / "bear-trap" / "ocr-calibration.yaml"
DEFAULT_VP = ROOT / "assets" / "reference" / "bear-trap" / "viewport-coords-batch3.yaml"
LIVE_CAPTURE_DIR = ROOT / "artifacts" / "cartograph-live"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ks-cartograph",
        description="Cartograph a local KingShot map region into blockers YAML.",
    )
    p.add_argument("--radius", type=int, default=30, help="Tiles around center (20..50).")
    p.add_argument("--step", type=int, default=10, help="Coarse coord-jump step in tiles.")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print jump plan only (needs --center or --fixture-dir viewports).",
    )
    p.add_argument(
        "--center",
        type=str,
        default=None,
        metavar="X,Y",
        help="World center for dry-run when not using fixtures (e.g. 698,816).",
    )
    p.add_argument(
        "--fixture-dir",
        type=Path,
        default=None,
        help="Offline PNG folder (e.g. batch3 or batch3-cropped).",
    )
    p.add_argument(
        "--viewports",
        type=Path,
        default=DEFAULT_VP,
        help="YAML with per-shot viewport centers.",
    )
    p.add_argument(
        "--calibration",
        type=Path,
        default=DEFAULT_CAL,
        help="ocr-calibration.yaml (mask + MAT hints).",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=ROOT / "assets" / "reference" / "bear-trap" / "blockers-cartograph.yaml",
        help="Output blockers YAML path.",
    )
    p.add_argument(
        "--live",
        action="store_true",
        help="Use BlueStacks ADB.",
    )
    p.add_argument(
        "--around",
        type=int,
        default=0,
        metavar="N",
        help="With --live: filled (2N+1)² screen grid (e.g. 3 → 7×7).",
    )
    p.add_argument(
        "--rays",
        action="store_true",
        help="With --around: capture cardinal rays only (legacy), not a filled grid.",
    )
    p.add_argument(
        "--no-open-world",
        action="store_true",
        help="Skip tapping the world-map button (already on world map).",
    )
    p.add_argument(
        "--swipe-px",
        type=int,
        default=200,
        metavar="PX",
        help="Finger swipe length for each screen step (default 200; small → name overlap).",
    )
    p.add_argument(
        "--capture-dir",
        type=Path,
        default=LIVE_CAPTURE_DIR,
        help="Where to save live capture PNGs.",
    )
    p.add_argument(
        "--map",
        action="store_true",
        help=(
            "Build/render map in --capture-dir. Prefers exact-click registration "
            "when exact-coordinate-calibration*.yaml exists; otherwise weak "
            "viewport-OCR fallback."
        ),
    )
    p.add_argument(
        "--require-registration",
        action="store_true",
        help=(
            "With --map: fail if no exact-click seed YAML (do not use viewport "
            "OCR fallback)."
        ),
    )
    return p


def _render_map_from_entities(
    capture_dir: Path, *, require_registration: bool = False
) -> int:
    import yaml
    from ks.cartograph.mosaic import MosaicResult, stitch_viewport_mosaic
    from ks.cartograph.live_capture import CapturedFrame
    from ks.cartograph.render_map import MapEntity, write_map_bundle
    from ks.cartograph.viewport import ocr_viewport_from_image
    import cv2

    route = resolve_capture_stitch_route(capture_dir)
    print(f"stitch_route={route.mode}: {route.detail}")
    if route.mode == "register":
        assert route.seed_path is not None
        result = register_and_digitize_capture(
            capture_dir,
            seed_calibration_path=route.seed_path,
        )
        print(
            f"registered mosaic {result.mosaic.image.shape[1]}x"
            f"{result.mosaic.image.shape[0]} → {result.mosaic.path} "
            f"entities={len(result.entities)}"
        )
        return 0
    if require_registration:
        print(
            f"Error: {route.detail}",
            file=sys.stderr,
        )
        return 1

    path = capture_dir / "entities.yaml"
    if not path.is_file():
        print(f"Error: missing {path}", file=sys.stderr)
        return 1
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    ents = [
        MapEntity(
            kind=e["kind"],
            x=int(e["x"]),
            y=int(e["y"]),
            label=str(e["label"]),
            level=e.get("level"),
            w=int(e.get("w", 1)),
            h=int(e.get("h", 1)),
        )
        for e in raw.get("entities") or []
    ]
    center = (int(raw["center"]["x"]), int(raw["center"]["y"]))
    kingdom = str(raw.get("kingdom", ""))

    mosaic = None
    pan = capture_dir / "panorama.png"
    # Prefer rebuilding mosaic from grid/ray captures if present
    capture_pngs = (
        list(capture_dir.glob("c0_center.png"))
        + list(capture_dir.glob("g_*.png"))
        + list(capture_dir.glob("[ENWS][1-8].png"))
    )
    frames: list[CapturedFrame] = []
    seen: set[str] = set()
    for png in sorted(capture_pngs, key=lambda p: p.name):
        if png.stem in seen or png.stem == "g_0_0":
            # g_0_0 duplicates c0_center
            if png.stem == "g_0_0" and "c0_center" in seen:
                continue
        seen.add(png.stem)
        img = cv2.imread(str(png))
        if img is None:
            continue
        vp, raw_ocr = ocr_viewport_from_image(img)
        frames.append(
            CapturedFrame(
                name=png.stem, path=png, viewport=vp, viewport_raw=raw_ocr, image=img
            )
        )
    if len(frames) >= 2 and any(f.viewport for f in frames):
        print(
            "WARNING: viewport-OCR fallback stitch (not canonical scale); "
            "add exact-coordinate-calibration*.yaml from live clicks",
            file=sys.stderr,
        )
        mosaic = stitch_viewport_mosaic(frames, pan)
        print(
            f"mosaic {mosaic.image.shape[1]}x{mosaic.image.shape[0]} "
            f"scale=({mosaic.scale_x:.1f},{mosaic.scale_y:.1f}) → {pan}"
        )
    elif pan.is_file():
        img = cv2.imread(str(pan))
        assert img is not None
        # Minimal mosaic metadata for overlay if only panorama exists
        mosaic = MosaicResult(
            image=img,
            path=pan,
            center=center,
            scale_x=55.0,
            scale_y=55.0,
            origin_x=img.shape[1] / 2,
            origin_y=img.shape[0] / 2,
            band_w=1080,
            band_h=1200,
        )

    html, grid, ent = write_map_bundle(
        capture_dir, ents, center=center, kingdom=kingdom, mosaic=mosaic
    )
    print(f"map={html}\ngrid={grid}\nentities={ent}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.map:
        return _render_map_from_entities(
            args.capture_dir,
            require_registration=args.require_registration,
        )

    if not (20 <= args.radius <= 50):
        print(f"Error: --radius must be 20..50; got {args.radius}", file=sys.stderr)
        return 1

    if args.live:
        from ks.device.adb import AdbDevice
        from ks.device.bluestacks import try_connect_bluestacks
        from ks.cartograph.live_capture import screencap_bgr
        from ks.cartograph.mosaic import (
            capture_grid,
            capture_rays,
            stitch_viewport_mosaic,
        )
        from ks.cartograph.viewport import ocr_viewport_from_image
        from ks.cartograph.render_map import MapEntity, write_map_bundle
        import yaml

        try:
            serial = try_connect_bluestacks(ports=(5555,))
            print(f"BlueStacks serial: {serial}")
            device = AdbDevice.connect(serial=serial)

            if args.around:
                if not (1 <= args.around <= 8):
                    print("Error: --around must be 1..8", file=sys.stderr)
                    return 1
                depth = args.around
                if args.rays:
                    print(
                        f"Capturing center + {depth} screens × E/N/W/S (rays) "
                        f"→ {args.capture_dir}"
                    )
                    frames = capture_rays(
                        device,
                        args.capture_dir,
                        depth=depth,
                        open_world=not args.no_open_world,
                        swipe_px=args.swipe_px,
                    )
                else:
                    side = 2 * depth + 1
                    print(
                        f"Capturing filled {side}×{side} screen grid "
                        f"({side * side} shots) → {args.capture_dir}"
                    )
                    frames = capture_grid(
                        device,
                        args.capture_dir,
                        depth=depth,
                        open_world=not args.no_open_world,
                        swipe_px=args.swipe_px,
                    )
                for fr in frames:
                    print(
                        f"  {fr.name}: vp={fr.viewport} raw={fr.viewport_raw!r} "
                        f"→ {fr.path.name}"
                    )
                vps = [fr.viewport for fr in frames if fr.viewport]
                if not vps:
                    print("Error: no viewport OCR on captures", file=sys.stderr)
                    return 1
                cx = int(round(sum(v[0] for v in vps) / len(vps)))
                cy = int(round(sum(v[1] for v in vps) / len(vps)))
                # Prefer center frame OCR as map center
                center_fr = next(
                    (f for f in frames if f.name == "c0_center" and f.viewport), None
                )
                if center_fr and center_fr.viewport:
                    cx, cy = center_fr.viewport

                if args.dry_run:
                    print(format_dry_run(dry_run_plan(cx, cy, args.radius, args.step)))
                    return 0

                pan = args.capture_dir / "panorama.png"
                route = resolve_capture_stitch_route(args.capture_dir)
                print(f"stitch_route={route.mode}: {route.detail}")
                if route.mode == "register":
                    digitized = register_and_digitize_capture(
                        args.capture_dir,
                        seed_calibration_path=route.seed_path,
                    )
                    mosaic = digitized.mosaic
                    print(
                        f"registered mosaic {mosaic.image.shape[1]}x"
                        f"{mosaic.image.shape[0]} → {pan}"
                    )
                    cx, cy = digitized.center
                    html = args.capture_dir / "map.html"
                else:
                    print(
                        "WARNING: live capture has no exact-click seed; "
                        "viewport-OCR mosaic is non-canonical until clicks",
                        file=sys.stderr,
                    )
                    mosaic = stitch_viewport_mosaic(frames, pan)
                    print(
                        f"mosaic {mosaic.image.shape[1]}x{mosaic.image.shape[0]} "
                        f"→ {pan}"
                    )

                    # Keep / seed entities.yaml
                    ent_path = args.capture_dir / "entities.yaml"
                    if ent_path.is_file():
                        raw = yaml.safe_load(ent_path.read_text(encoding="utf-8"))
                        ents = [
                            MapEntity(
                                kind=e["kind"],
                                x=int(e["x"]),
                                y=int(e["y"]),
                                label=str(e["label"]),
                                level=e.get("level"),
                                w=int(e.get("w", 1)),
                                h=int(e.get("h", 1)),
                            )
                            for e in raw.get("entities") or []
                        ]
                        kingdom = str(raw.get("kingdom", ""))
                    else:
                        ents = []
                        kingdom = ""
                        # Update center in a fresh yaml
                        ent_path.write_text(
                            yaml.safe_dump(
                                {
                                    "kingdom": kingdom,
                                    "center": {"x": cx, "y": cy},
                                    "entities": [],
                                },
                                sort_keys=False,
                            ),
                            encoding="utf-8",
                        )

                    # Refresh center in entities.yaml
                    if ent_path.is_file():
                        raw = yaml.safe_load(ent_path.read_text(encoding="utf-8")) or {}
                        raw["center"] = {"x": cx, "y": cy}
                        if "kingdom" not in raw:
                            raw["kingdom"] = kingdom
                        ent_path.write_text(
                            yaml.safe_dump(raw, sort_keys=False), encoding="utf-8"
                        )

                    html, grid, ent = write_map_bundle(
                        args.capture_dir,
                        ents,
                        center=(cx, cy),
                        kingdom=kingdom or "?",
                        mosaic=mosaic,
                    )
                result = run_live_frames(
                    frames,
                    radius=args.radius,
                    step=args.step,
                    out_yaml=args.out,
                )
                print(
                    f"center={cx},{cy} hits={len(result.hits)} "
                    f"map={html} mosaic={pan}"
                )
                for h in result.hits:
                    print(
                        f"  [{h.kind}] {h.label} @ {h.x},{h.y} ({h.w}x{h.h}) "
                        f"from {h.source}"
                    )
                return 0

            img = screencap_bgr(device)
            coords, raw = ocr_viewport_from_image(img)
            if coords is None:
                print(f"Error: viewport OCR failed ({raw!r})", file=sys.stderr)
                return 1
            cx, cy = coords
            print(f"viewport OCR: {cx},{cy}  raw={raw!r}")
            print(format_dry_run(dry_run_plan(cx, cy, args.radius, args.step)))
            if args.dry_run:
                return 0
            print("Pass --around 3 for a filled 7×7 screen grid (or --rays for cardinals).")
            return 0
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    if args.dry_run and args.center:
        try:
            xs, ys = args.center.split(",")
            cx, cy = int(xs.strip()), int(ys.strip())
        except ValueError:
            print("Error: --center must be X,Y", file=sys.stderr)
            return 1
        print(format_dry_run(dry_run_plan(cx, cy, args.radius, args.step)))
        return 0

    if args.fixture_dir:
        viewports = load_viewports_yaml(args.viewports)
        norm = {Path(k).stem: v for k, v in viewports.items()}
        mask_cfg = mask_config_from_calibration(args.calibration)
        if args.dry_run:
            cx = int(round(sum(v[0] for v in norm.values()) / len(norm)))
            cy = int(round(sum(v[1] for v in norm.values()) / len(norm)))
            print(format_dry_run(dry_run_plan(cx, cy, args.radius, args.step)))
            return 0
        result = run_fixture_dir(
            args.fixture_dir,
            viewports=norm,
            mask_cfg=mask_cfg,
            radius=args.radius,
            step=args.step,
            out_yaml=args.out,
        )
        print(
            f"center={result.center} hits={len(result.hits)} "
            f"jumps={len(result.plan.jumps)} out={result.out_yaml}"
        )
        return 0

    print(
        "Error: pass --dry-run --center X,Y  or  --fixture-dir DIR  or  --live [--around 4]",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
