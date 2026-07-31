"""BlueStacks ADB connect helpers."""

from __future__ import annotations

import re
import subprocess
from typing import Iterable

# Common BlueStacks / HD-Player ADB ports observed on macOS installs.
DEFAULT_PORTS: tuple[int, ...] = (5555, 5556, 5565, 5575, 5585, 5595, 5037)


def _run_adb(args: list[str], timeout: float = 10.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["adb", *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def list_device_serials() -> list[str]:
    proc = _run_adb(["devices"])
    serials: list[str] = []
    for line in proc.stdout.splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            serials.append(parts[0])
    return serials


def connect_port(port: int, host: str = "127.0.0.1") -> str:
    """``adb connect host:port`` → serial string ``host:port`` if device is online."""
    target = f"{host}:{port}"
    proc = _run_adb(["connect", target])
    text = ((proc.stdout or "") + (proc.stderr or "")).lower()
    if "connected" not in text and "already connected" not in text:
        raise RuntimeError(f"adb connect {target} failed: {text.strip()}")
    # Require the device to show as 'device' (not offline / unauthorized).
    serials = list_device_serials()
    if target not in serials:
        raise RuntimeError(
            f"adb connect {target} reported success but device is not online "
            f"(devices={serials})"
        )
    return target


def try_connect_bluestacks(
    ports: Iterable[int] | None = None,
    host: str = "127.0.0.1",
) -> str:
    """Return a serial for an already-connected device or first successful connect.

    Raises RuntimeError if nothing works.
    """
    existing = list_device_serials()
    for s in existing:
        if s.startswith("emulator-") or re.match(r"127\.0\.0\.1:\d+", s):
            return s
    if existing:
        return existing[0]

    errors: list[str] = []
    for port in ports or DEFAULT_PORTS:
        try:
            return connect_port(port, host=host)
        except RuntimeError as exc:
            errors.append(str(exc))
    raise RuntimeError(
        "Could not connect to BlueStacks ADB. Enable ADB in BlueStacks "
        "Settings → Advanced, then retry. Tried ports: "
        + ", ".join(str(p) for p in (ports or DEFAULT_PORTS))
        + ("; " + "; ".join(errors) if errors else "")
    )
