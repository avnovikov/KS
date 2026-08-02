from __future__ import annotations

import cv2
import numpy as np

from ks.device.fake import FakeDevice
from ks.heroes.gear_collector import collect_gear
from ks.heroes.gear_config import load_gear_config
from ks.heroes.gear_models import GearRecord
from ks.heroes.gear_store import GearStore


class RecordingDevice(FakeDevice):
    def __init__(self, png_bytes: bytes) -> None:
        super().__init__(png_bytes=png_bytes)
        self.swipes: list[tuple[int, int, int, int, int]] = []

    def swipe(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration_ms: int = 300,
    ) -> None:
        self.swipes.append((x1, y1, x2, y2, duration_ms))


def _png() -> bytes:
    ok, buf = cv2.imencode(".png", np.zeros((1920, 1080, 3), dtype=np.uint8))
    assert ok
    return buf.tobytes()


def test_collect_gear_pages_then_stops(tmp_path):
    cfg = load_gear_config()
    # Config may set max_pages=1 for live runs; exercise paging explicitly.
    from dataclasses import replace

    cfg = replace(cfg, grid=replace(cfg.grid, max_pages=2))
    device = RecordingDevice(png_bytes=_png())
    store = GearStore(tmp_path)

    opens: list[tuple[int, int]] = []

    def fake_scrape(device, cfg, *, page, index, ocr_fn=None, sleep_fn=None, **_kw):
        opens.append((page, index))
        if page == 0 and index == 0:
            return GearRecord(
                piece_id="page0-cell0",
                name="Alpha Helm",
                enhancement_level=10,
                inventory_page=0,
                inventory_index=0,
                scraped_at="t0",
            )
        if page == 0 and index == 1:
            return GearRecord(
                piece_id="page0-cell1",
                name="Beta Chest",
                enhancement_level=20,
                inventory_page=0,
                inventory_index=1,
                scraped_at="t1",
            )
        return None

    pieces = collect_gear(
        device,
        cfg,
        store,
        sleep_fn=lambda _s: None,
        scrape_fn=fake_scrape,
    )
    assert [p.name for p in pieces] == ["Alpha Helm", "Beta Chest"]
    assert len(device.swipes) == 1
    swipe = cfg.grid.page_swipe
    assert device.swipes[0][:4] == (swipe.x1, swipe.y1, swipe.x2, swipe.y2)
    assert len(opens) == 2 * len(cfg.grid.cells)
    assert store.json_path.is_file()


def test_collect_gear_dedupes_same_identity(tmp_path):
    cfg = load_gear_config()
    device = RecordingDevice(png_bytes=_png())
    store = GearStore(tmp_path)

    def fake_scrape(device, cfg, *, page, index, ocr_fn=None, sleep_fn=None, **_kw):
        if page == 0 and index < 2:
            return GearRecord(
                piece_id=f"page0-cell{index}",
                name="Same Piece",
                enhancement_level=30,
                mastery_level=2,
                rarity="mythic",
                power=100,
                inventory_page=page,
                inventory_index=index,
                scraped_at="t",
            )
        return None

    pieces = collect_gear(
        device,
        cfg,
        store,
        sleep_fn=lambda _s: None,
        scrape_fn=fake_scrape,
    )
    assert len(pieces) == 1
    assert pieces[0].name == "Same Piece"


def test_collect_gear_emits_progress_events(tmp_path):
    cfg = load_gear_config()
    device = RecordingDevice(png_bytes=_png())
    store = GearStore(tmp_path)

    events: list[tuple[str, object]] = []

    def on_progress(ev: str, payload: object) -> None:
        events.append((ev, payload))

    def fake_scrape(device, cfg, *, page, index, ocr_fn=None, sleep_fn=None, **_kw):
        if page == 0 and index == 0:
            return GearRecord(
                piece_id="page0-cell0",
                name="Alpha Helm",
                enhancement_level=10,
                inventory_page=0,
                inventory_index=0,
            )
        return None

    collect_gear(
        device,
        cfg,
        store,
        sleep_fn=lambda _s: None,
        scrape_fn=fake_scrape,
        on_progress=on_progress,
    )
    piece_events = [e for e in events if e[0] in {"piece", "kept"}]
    assert len(piece_events) == 1
    ev_type, payload = piece_events[0]
    assert ev_type == "piece"
    assert isinstance(payload, dict)
    assert payload["piece_id"] == "page0-cell0"


def test_collect_gear_emits_kept_when_lock_preserved(tmp_path):
    """'kept' event emitted when OCR has None level but prior record has it locked."""
    cfg = load_gear_config()
    device = RecordingDevice(png_bytes=_png())
    store = GearStore(tmp_path)

    # Seed a prior record with enhancement_level=30
    store.upsert(
        GearRecord(
            piece_id="page0-cell0",
            name="Alpha Helm",
            enhancement_level=30,
            mastery_level=0,
            inventory_page=0,
            inventory_index=0,
        )
    )

    events: list[tuple[str, object]] = []

    def on_progress(ev: str, payload: object) -> None:
        events.append((ev, payload))

    def fake_scrape(device, cfg, *, page, index, ocr_fn=None, sleep_fn=None, **_kw):
        if page == 0 and index == 0:
            return GearRecord(
                piece_id="page0-cell0",
                name="Alpha Helm",
                enhancement_level=None,  # OCR missed enhancement
                inventory_page=0,
                inventory_index=0,
            )
        return None

    collect_gear(
        device,
        cfg,
        store,
        sleep_fn=lambda _s: None,
        scrape_fn=fake_scrape,
        on_progress=on_progress,
    )
    kept_events = [e for e in events if e[0] == "kept"]
    assert len(kept_events) == 1, "expected one 'kept' event"


def test_collect_gear_emits_duplicate_event(tmp_path):
    cfg = load_gear_config()
    device = RecordingDevice(png_bytes=_png())
    store = GearStore(tmp_path)

    events: list[tuple[str, object]] = []

    def on_progress(ev: str, payload: object) -> None:
        events.append((ev, payload))

    def fake_scrape(device, cfg, *, page, index, ocr_fn=None, sleep_fn=None, **_kw):
        if page == 0 and index < 2:
            return GearRecord(
                piece_id=f"page0-cell{index}",
                name="Same Piece",
                enhancement_level=30,
                mastery_level=2,
                rarity="mythic",
                power=100,
                inventory_page=0,
                inventory_index=index,
            )
        return None

    collect_gear(
        device,
        cfg,
        store,
        sleep_fn=lambda _s: None,
        scrape_fn=fake_scrape,
        on_progress=on_progress,
    )
    dup_events = [e for e in events if e[0] == "duplicate"]
    assert len(dup_events) == 1
