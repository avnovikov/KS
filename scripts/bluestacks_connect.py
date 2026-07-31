#!/usr/bin/env python3
"""Connect to BlueStacks ADB and optionally write a smoke screencap."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ks.device.adb import AdbDevice  # noqa: E402
from ks.device.bluestacks import DEFAULT_PORTS, try_connect_bluestacks  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Connect BlueStacks via ADB")
    parser.add_argument(
        "--port",
        type=int,
        action="append",
        default=None,
        help="ADB port to try (repeatable). Default: common BlueStacks ports.",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Write artifacts/smoke.png after connect.",
    )
    args = parser.parse_args()
    ports = tuple(args.port) if args.port else DEFAULT_PORTS

    try:
        serial = try_connect_bluestacks(ports=ports)
    except RuntimeError as exc:
        print(f"BLOCKED: {exc}")
        print(
            "1. Launch BlueStacks\n"
            "2. Settings → Advanced → enable Android Debug Bridge (ADB)\n"
            "3. Note the port and re-run: python scripts/bluestacks_connect.py --port PORT --smoke"
        )
        return 1

    print(f"Connected serial: {serial}")
    print(f"Tip: set config/params.yaml  adb.serial: {serial!r}")

    if args.smoke:
        device = AdbDevice.connect(serial=serial)
        out = ROOT / "artifacts" / "smoke.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        png = device.screencap()
        out.write_bytes(png)
        print(f"Wrote {out} ({len(png):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
