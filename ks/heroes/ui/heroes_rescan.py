"""ADB OCR rescan of hero roster into an existing HeroStore."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from ks.heroes.config import DEFAULT_HEROES_CONFIG, HeroesConfig, load_heroes_config
from ks.heroes.models import HeroRecord
from ks.heroes.store import HeroStore


def rescan_heroes_from_ocr(
    store: HeroStore,
    *,
    config_path: Path | None = None,
    serial: str | None = None,
    load_config_fn: Callable[[Path | None], HeroesConfig] | None = None,
    connect_fn: Callable[[str | None], object] | None = None,
    collect_fn: Callable[..., list[HeroRecord]] | None = None,
    on_progress: Callable[[str, object], None] | None = None,
) -> list[HeroRecord]:
    """Walk Heroes roster via ADB OCR and upsert into store (no full wipe).

    Requires the game already on the Heroes roster screen.
    """
    load_cfg = load_config_fn or load_heroes_config
    cfg = load_cfg(
        config_path if config_path is not None else DEFAULT_HEROES_CONFIG
    )

    if collect_fn is None:
        from ks.heroes.collector import collect_heroes

        collect_fn = collect_heroes
    if connect_fn is None:
        from ks.device.adb import AdbDevice

        connect_fn = lambda s: AdbDevice.connect(serial=s)  # noqa: E731

    device_serial = serial if serial is not None else cfg.adb_serial
    device = connect_fn(device_serial)
    kwargs: dict = {}
    if on_progress is not None:
        kwargs["on_progress"] = on_progress
    return list(collect_fn(device, cfg, store, **kwargs))
