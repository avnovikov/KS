"""ADB smoke test: verify device connectivity and write a screencap to artifacts/smoke.png."""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure the project root is on the path so `ks` can be imported from anywhere.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from ks.device.adb import AdbDevice  # noqa: E402


ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"
SMOKE_IMAGE = ARTIFACTS_DIR / "smoke.png"


def main() -> None:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

    print("Connecting to ADB device …")
    try:
        device = AdbDevice.connect()
    except RuntimeError as exc:
        print(f"BLOCKED: {exc}")
        print(
            "Manual steps required:\n"
            "  1. Install BlueStacks (Apple Silicon) or Google Play Games.\n"
            "  2. Enable ADB in BlueStacks → Settings → Advanced → ADB.\n"
            "  3. brew install android-platform-tools\n"
            "  4. adb connect 127.0.0.1:<port>   (port shown in BlueStacks)\n"
            "  5. Re-run:  source .venv/bin/activate && python scripts/adb_smoke.py"
        )
        sys.exit(1)

    serial: str = device._device.serial
    print(f"Device serial : {serial}")

    print("Capturing screenshot …")
    png_bytes = device.screencap()
    assert len(png_bytes) > 0, "screencap returned empty bytes"

    SMOKE_IMAGE.write_bytes(png_bytes)
    print(f"Wrote {len(png_bytes):,} bytes → {SMOKE_IMAGE}")

    # Derive screen dimensions from PNG IHDR (bytes 16-24).
    if len(png_bytes) >= 24:
        width = int.from_bytes(png_bytes[16:20], "big")
        height = int.from_bytes(png_bytes[20:24], "big")
        print(f"Screen size   : {width} × {height} px")
    else:
        print("Screen size   : could not parse PNG header")

    print("Smoke OK ✓")


if __name__ == "__main__":
    main()
