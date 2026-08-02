"""Walk backpack Gear grid and persist each piece."""

from __future__ import annotations

import time
from typing import Callable

from ks.heroes.gear_config import GearConfig
from ks.heroes.gear_models import GearRecord
from ks.heroes.gear_scrape import DeviceProtocol, close_gear_detail, scrape_gear_piece
from ks.heroes.gear_store import GearStore


def _open_and_scrape_gear_cell(
    device: DeviceProtocol,
    cfg: GearConfig,
    store: GearStore,
    scrape: Callable,
    ocr_fn: object,
    sleep: Callable[[float], None],
    *,
    page: int,
    index: int,
    cell,
) -> GearRecord | None:
    """Tap a gear cell and scrape it, then close (or wait out) the detail screen.

    On a scrape failure the detail screen may be half-open, so a Back tap is
    attempted regardless.
    """
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
        sleep(cfg.delays.after_tap_ms / 1000.0)

    return piece


def _store_new_gear_piece(
    store: GearStore,
    piece: GearRecord,
    *,
    page: int,
    index: int,
    seen: set[str],
    collected: list[GearRecord],
    on_progress: Callable[[str, object], None] | None,
) -> bool:
    """Dedupe, upsert, and log one scraped piece.

    Returns True when the piece was newly collected (not a duplicate).
    """
    dedupe_key = _dedupe_key(piece)
    if dedupe_key in seen:
        print(f"warn: gear dedupe skip page={page} index={index} key={dedupe_key}")
        if on_progress is not None:
            on_progress("duplicate", {"piece_id": piece.piece_id, "key": dedupe_key})
        return False
    seen.add(dedupe_key)

    # Capture OCR levels before merge so we can detect lock preservation.
    ocr_enh = piece.enhancement_level
    ocr_mastery = piece.mastery_level
    prev = store.get(piece.piece_id)

    stored = store.upsert(piece)
    collected.append(stored)
    label = stored.name or stored.piece_id
    print(
        f"collected [{len(collected)}] {label} "
        f"+{stored.enhancement_level} mastery={stored.mastery_level} "
        f"power={stored.power}"
    )

    if on_progress is not None:
        kept = _lock_was_preserved(prev, stored, ocr_enh, ocr_mastery)
        on_progress("kept" if kept else "piece", {"piece_id": stored.piece_id, "piece": stored})
    return True


def _scan_gear_page(
    device: DeviceProtocol,
    cfg: GearConfig,
    store: GearStore,
    scrape: Callable,
    ocr_fn: object,
    sleep: Callable[[float], None],
    seen: set[str],
    collected: list[GearRecord],
    *,
    page: int,
    on_progress: Callable[[str, object], None] | None,
) -> int:
    """Scan every cell on one gear page; upsert new pieces into ``collected``.

    Returns the count of newly collected pieces on this page.
    """
    page_new = 0
    for index, cell in enumerate(cfg.grid.cells):
        piece = _open_and_scrape_gear_cell(
            device, cfg, store, scrape, ocr_fn, sleep, page=page, index=index, cell=cell
        )
        if piece is None:
            continue
        if _store_new_gear_piece(
            store, piece, page=page, index=index, seen=seen, collected=collected, on_progress=on_progress
        ):
            page_new += 1
    return page_new


def collect_gear(
    device: DeviceProtocol,
    cfg: GearConfig,
    store: GearStore,
    *,
    ocr_fn=None,
    sleep_fn: Callable[[float], None] | None = None,
    scrape_fn=None,
    on_progress: Callable[[str, object], None] | None = None,
) -> list[GearRecord]:
    """Walk the gear grid with paging; upsert each scraped piece into store.

    Emits progress events via on_progress(event_type, payload):
      "piece"     — new or updated piece stored
      "kept"      — piece stored but locked level(s) preserved from prior record
      "duplicate" — piece skipped (same identity key already seen this run)
    """
    sleep = sleep_fn or time.sleep
    scrape = scrape_fn or scrape_gear_piece
    seen: set[str] = set()
    collected: list[GearRecord] = []

    for page in range(cfg.grid.max_pages):
        page_new = _scan_gear_page(
            device, cfg, store, scrape, ocr_fn, sleep, seen, collected, page=page, on_progress=on_progress
        )

        if page_new == 0:
            break
        if page + 1 >= cfg.grid.max_pages:
            break

        swipe = cfg.grid.page_swipe
        device.swipe(swipe.x1, swipe.y1, swipe.x2, swipe.y2, swipe.duration_ms)
        sleep(cfg.delays.after_open_ms / 1000.0)

    return collected


def _lock_was_preserved(
    prev: GearRecord | None,
    stored: GearRecord,
    ocr_enh: int | None,
    ocr_mastery: int | None,
) -> bool:
    """True when OCR missed a level but the prior locked value was kept."""
    if prev is None:
        return False
    enh_preserved = (
        ocr_enh is None
        and stored.enhancement_level is not None
        and stored.enhancement_level == prev.enhancement_level
    )
    mastery_preserved = (
        ocr_mastery is None
        and stored.mastery_level is not None
        and stored.mastery_level == prev.mastery_level
    )
    return enh_preserved or mastery_preserved


def _dedupe_key(piece: GearRecord) -> str:
    """Prefer identity fields; fall back to piece_id for partial OCR."""
    if piece.name and piece.enhancement_level is not None:
        return (
            f"{piece.name}|{piece.enhancement_level}|{piece.mastery_level}|"
            f"{piece.rarity}|{piece.power}"
        )
    return piece.piece_id
