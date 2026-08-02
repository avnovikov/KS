"""ADB OCR rescan of backpack gear into an existing GearStore."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable

from ks.heroes.gear_config import DEFAULT_GEAR_CONFIG, GearConfig, load_gear_config
from ks.heroes.gear_models import GearRecord
from ks.heroes.gear_store import GearStore


def _wipe_dir(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def rescan_gear_from_ocr(
    store: GearStore,
    *,
    config_path: Path | None = None,
    serial: str | None = None,
    load_config_fn: Callable[[Path | None], GearConfig] | None = None,
    connect_fn: Callable[[str | None], object] | None = None,
    collect_fn: Callable[..., list[GearRecord]] | None = None,
    on_progress: Callable[[str, object], None] | None = None,
) -> list[GearRecord]:
    """Walk Backpack > Gear via ADB OCR and merge into store.

    Preserves locked levels from prior records. After collection, any piece_id
    not seen in this run is deleted so removed pieces do not linger.
    """
    load_cfg = load_config_fn or load_gear_config
    cfg = load_cfg(config_path if config_path is not None else DEFAULT_GEAR_CONFIG)

    _wipe_dir(store.details_dir)
    _wipe_dir(store.out_dir / "icons")

    if collect_fn is None:
        from ks.heroes.gear_collector import collect_gear

        collect_fn = collect_gear
    if connect_fn is None:
        from ks.device.adb import AdbDevice

        connect_fn = lambda s: AdbDevice.connect(serial=s)  # noqa: E731

    device_serial = serial if serial is not None else cfg.adb_serial
    device = connect_fn(device_serial)
    collected = list(collect_fn(device, cfg, store, on_progress=on_progress))

    # Remove pieces from prior scans that were not seen this run.
    collected_ids = {p.piece_id for p in collected}
    for stale_id in list(store._pieces.keys()):
        if stale_id not in collected_ids:
            store.delete(stale_id)

    return collected
