"""Walk backpack Gear grid and persist each piece."""

from __future__ import annotations

import time
from typing import Callable

from ks.heroes.gear_config import GearConfig
from ks.heroes.gear_models import GearRecord
from ks.heroes.gear_scrape import DeviceProtocol, close_gear_detail, scrape_gear_piece
from ks.heroes.gear_store import GearStore


def collect_gear(
    device: DeviceProtocol,
    cfg: GearConfig,
    store: GearStore,
    *,
    ocr_fn=None,
    sleep_fn: Callable[[float], None] | None = None,
    scrape_fn=None,
) -> list[GearRecord]:
    """Walk the gear grid with paging; upsert each scraped piece into store."""
    sleep = sleep_fn or time.sleep
    scrape = scrape_fn or scrape_gear_piece
    seen: set[str] = set()
    collected: list[GearRecord] = []

    for page in range(cfg.grid.max_pages):
        page_new = 0
        for index, cell in enumerate(cfg.grid.cells):
            device.tap(cell.x, cell.y)
            sleep(cfg.delays.after_open_ms / 1000.0)
            piece: GearRecord | None = None
            opened = False
            try:
                piece = scrape(
                    device,
                    cfg,
                    page=page,
                    index=index,
                    ocr_fn=ocr_fn,
                    sleep_fn=sleep,
                    details_dir=store.details_dir,
                )
                opened = piece is not None
            except Exception as exc:  # noqa: BLE001 — continue grid on single failure
                print(f"warn: gear scrape failed page={page} index={index}: {exc}")
                opened = True

            if opened:
                close_gear_detail(device, cfg, sleep_fn=sleep)
            else:
                # Empty cell or mis-tap — brief settle, no close needed
                sleep(cfg.delays.after_tap_ms / 1000.0)

            if piece is None:
                continue

            dedupe_key = _dedupe_key(piece)
            if dedupe_key in seen:
                print(
                    f"warn: gear dedupe skip page={page} index={index} "
                    f"key={dedupe_key}"
                )
                continue
            seen.add(dedupe_key)
            store.upsert(piece)
            collected.append(piece)
            page_new += 1
            label = piece.name or piece.piece_id
            print(
                f"collected [{len(collected)}] {label} "
                f"+{piece.enhancement_level} mastery={piece.mastery_level} "
                f"power={piece.power}"
            )

        if page_new == 0:
            break
        if page + 1 >= cfg.grid.max_pages:
            break

        swipe = cfg.grid.page_swipe
        device.swipe(swipe.x1, swipe.y1, swipe.x2, swipe.y2, swipe.duration_ms)
        sleep(cfg.delays.after_open_ms / 1000.0)

    return collected


def _dedupe_key(piece: GearRecord) -> str:
    """Prefer identity fields; fall back to piece_id for partial OCR."""
    if piece.name and piece.enhancement_level is not None:
        return (
            f"{piece.name}|{piece.enhancement_level}|{piece.mastery_level}|"
            f"{piece.rarity}|{piece.power}"
        )
    return piece.piece_id
