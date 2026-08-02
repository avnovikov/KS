from __future__ import annotations

from dataclasses import replace

import cv2
import numpy as np
import pytest

from ks.device.fake import FakeDevice
from ks.heroes.collector import capture_name_screenshots, capture_star_progress, collect_heroes
from ks.heroes.config import load_heroes_config
from ks.heroes.models import HeroRecord
from ks.heroes.scrape import decode_screencap
from ks.heroes.store import HeroStore


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


class NavigatingDevice(FakeDevice):
    """Fake device with a simple roster/detail state machine driven by taps.

    Used to exercise ``capture_name_screenshots`` / ``capture_star_progress``,
    which (unlike ``collect_heroes``) drive screen-open detection through the
    live ``is_hero_detail_screen`` / roster-lookalike helpers rather than an
    injectable ``ocr_fn``.
    """

    def __init__(self, cfg, png_bytes: bytes) -> None:
        super().__init__(png_bytes=png_bytes)
        self.cfg = cfg
        self.state = "roster"

    def tap(self, x: int, y: int) -> None:
        super().tap(x, y)
        if (x, y) == (self.cfg.nav.back.x, self.cfg.nav.back.y):
            self.state = "roster"
        else:
            self.state = "detail"


def _patch_roster_detail_detection(monkeypatch, device: NavigatingDevice) -> None:
    """Route the collector's screen-classification helpers through ``device.state``."""
    monkeypatch.setattr(
        "ks.heroes.collector.is_hero_detail_screen", lambda img: device.state == "detail"
    )
    monkeypatch.setattr(
        "ks.heroes.collector._looks_like_hero_roster_screen",
        lambda img: device.state == "roster",
    )
    monkeypatch.setattr(
        "ks.heroes.collector.dismiss_blocking_overlays",
        lambda device, cfg, sleep_fn: decode_screencap(device.screencap()),
    )


def test_capture_name_screenshots_saves_and_updates_store(tmp_path, monkeypatch):
    cfg = load_heroes_config()
    store = HeroStore(tmp_path)
    store.upsert(HeroRecord(name="Diana", roster_page=0, roster_index=0, scraped_at="t0"))
    store.upsert(HeroRecord(name="Edwin", roster_page=0, roster_index=1, scraped_at="t0"))

    device = NavigatingDevice(cfg, png_bytes=_png())
    _patch_roster_detail_detection(monkeypatch, device)

    updated = capture_name_screenshots(device, cfg, store, sleep_fn=lambda _s: None)

    assert [h.name for h in updated] == ["Diana", "Edwin"]
    stored_by_name = {h.name: h for h in store.all_heroes()}
    for hero in updated:
        assert hero.name_screenshot == f"names/{hero.name}.png"
        assert (store.out_dir / hero.name_screenshot).is_file()
        assert stored_by_name[hero.name].name_screenshot == hero.name_screenshot
    assert device.state == "roster"


def test_capture_name_screenshots_returns_empty_for_empty_store(tmp_path):
    cfg = load_heroes_config()
    store = HeroStore(tmp_path)
    device = NavigatingDevice(cfg, png_bytes=_png())
    assert capture_name_screenshots(device, cfg, store, sleep_fn=lambda _s: None) == []
    assert device.taps == []


def test_capture_name_screenshots_skips_out_of_range_roster_index(tmp_path, monkeypatch):
    cfg = load_heroes_config()
    store = HeroStore(tmp_path)
    store.upsert(
        HeroRecord(name="Ghost", roster_page=0, roster_index=999, scraped_at="t0")
    )
    device = NavigatingDevice(cfg, png_bytes=_png())
    _patch_roster_detail_detection(monkeypatch, device)

    updated = capture_name_screenshots(device, cfg, store, sleep_fn=lambda _s: None)
    assert updated == []
    assert device.taps == []


def test_capture_star_progress_updates_stars_and_pellets(tmp_path, monkeypatch):
    cfg = load_heroes_config()
    assert cfg.ocr.stars is not None
    store = HeroStore(tmp_path)
    store.upsert(HeroRecord(name="Fahd", roster_page=0, roster_index=0, scraped_at="t0"))

    device = NavigatingDevice(cfg, png_bytes=_png())
    _patch_roster_detail_detection(monkeypatch, device)

    updated = capture_star_progress(device, cfg, store, sleep_fn=lambda _s: None)

    assert [h.name for h in updated] == ["Fahd"]
    # Blank frame → vision finds no yellow star pixels.
    assert updated[0].stars == 0
    assert updated[0].pellets == 0
    assert store.all_heroes()[0].stars == 0
    assert device.state == "roster"


def test_capture_star_progress_requires_stars_box(tmp_path):
    cfg = load_heroes_config()
    cfg_without_stars = replace(cfg, ocr=replace(cfg.ocr, stars=None))
    device = FakeDevice(png_bytes=_png())
    store = HeroStore(tmp_path)

    with pytest.raises(ValueError, match="ocr.stars"):
        capture_star_progress(device, cfg_without_stars, store, sleep_fn=lambda _s: None)


def test_collect_heroes_pages_then_stops(tmp_path):
    cfg = load_heroes_config()
    device = RecordingDevice(png_bytes=_png())
    store = HeroStore(tmp_path)

    # First page: two named heroes at indices 0 and 1; rest empty.
    # Second page: all empty → stop. No third swipe.
    opens: list[tuple[int, int]] = []

    def fake_scrape(device, cfg, *, page, index, ocr_fn=None, sleep_fn=None, **_kw):
        opens.append((page, index))
        if page == 0 and index == 0:
            return HeroRecord(name="Alpha", roster_page=0, roster_index=0, scraped_at="t0")
        if page == 0 and index == 1:
            return HeroRecord(name="Beta", roster_page=0, roster_index=1, scraped_at="t1")
        return None

    heroes = collect_heroes(
        device,
        cfg,
        store,
        sleep_fn=lambda _s: None,
        scrape_fn=fake_scrape,
    )
    assert [h.name for h in heroes] == ["Alpha", "Beta"]
    assert len(device.swipes) == 1
    swipe = cfg.roster.page_swipe
    assert device.swipes[0][:4] == (swipe.x1, swipe.y1, swipe.x2, swipe.y2)
    # 16 cells page0 + 16 cells page1
    assert len(opens) == 32
    assert store.json_path.is_file()


def test_collect_heroes_dedupes_by_name(tmp_path):
    cfg = load_heroes_config()
    device = RecordingDevice(png_bytes=_png())
    store = HeroStore(tmp_path)

    def fake_scrape(device, cfg, *, page, index, ocr_fn=None, sleep_fn=None, **_kw):
        if page == 0 and index < 2:
            return HeroRecord(name="Same", roster_page=page, roster_index=index, scraped_at="t")
        return None

    heroes = collect_heroes(
        device,
        cfg,
        store,
        sleep_fn=lambda _s: None,
        scrape_fn=fake_scrape,
    )
    assert len(heroes) == 1
    assert heroes[0].name == "Same"


def test_collect_heroes_keeps_manual_name(tmp_path):
    cfg = load_heroes_config()
    device = RecordingDevice(png_bytes=_png())
    store = HeroStore(tmp_path)
    store.upsert(
        HeroRecord(
            name="Olive",
            power=150816,
            roster_page=0,
            roster_index=0,
            scraped_at="t0",
        )
    )

    kept: list[str | None] = []

    def fake_scrape(
        device,
        cfg,
        *,
        page,
        index,
        ocr_fn=None,
        sleep_fn=None,
        keep_name=None,
        **_kw,
    ):
        kept.append(keep_name)
        if page == 0 and index == 0:
            return HeroRecord(
                name=keep_name or "Hero_p0_i0",
                power=150816,
                roster_page=0,
                roster_index=0,
                scraped_at="t1",
                name_screenshot="names/Olive.png",
            )
        return None

    heroes = collect_heroes(
        device,
        cfg,
        store,
        sleep_fn=lambda _s: None,
        scrape_fn=fake_scrape,
    )
    assert kept[0] == "Olive"
    assert heroes[0].name == "Olive"


def test_collect_heroes_stops_after_3_consecutive_duplicates(tmp_path):
    """After 3 consecutive duplicate name+power combos, cell loop breaks."""
    cfg = load_heroes_config()
    device = RecordingDevice(png_bytes=_png())
    store = HeroStore(tmp_path)

    # Seed "Alpha" so subsequent same-name scrapes are duplicates.
    from ks.heroes.models import HeroRecord as _HR
    store.upsert(_HR(name="Alpha", roster_page=0, roster_index=0, power=1000, scraped_at="t0"))

    events: list[tuple[str, object]] = []

    def on_progress(ev, payload):
        events.append((ev, payload))

    def fake_scrape(device, cfg, *, page, index, ocr_fn=None, sleep_fn=None, **_kw):
        # Return "Alpha" with same power for all cells → consecutive duplicates.
        return _HR(name="Alpha", roster_page=page, roster_index=index, power=1000, scraped_at="t")

    from ks.heroes.collector import collect_heroes

    collect_heroes(
        device,
        cfg,
        store,
        sleep_fn=lambda _s: None,
        scrape_fn=fake_scrape,
        on_progress=on_progress,
        max_consecutive_duplicates=3,
    )
    stopped_events = [e for e in events if e[0] == "stopped"]
    assert len(stopped_events) >= 1, "expected 'stopped' event after 3 consecutive duplicates"
    dup_events = [e for e in events if e[0] == "duplicate"]
    assert len(dup_events) >= 3


def test_collect_heroes_emits_hero_and_progress_events(tmp_path):
    cfg = load_heroes_config()
    device = RecordingDevice(png_bytes=_png())
    store = HeroStore(tmp_path)
    events: list[tuple[str, object]] = []

    def on_progress(ev, payload):
        events.append((ev, payload))

    def fake_scrape(device, cfg, *, page, index, ocr_fn=None, sleep_fn=None, **_kw):
        if page == 0 and index == 0:
            from ks.heroes.models import HeroRecord as _HR2
            return _HR2(name="Gamma", roster_page=0, roster_index=0, scraped_at="t")
        return None

    from ks.heroes.collector import collect_heroes

    heroes = collect_heroes(
        device,
        cfg,
        store,
        sleep_fn=lambda _s: None,
        scrape_fn=fake_scrape,
        on_progress=on_progress,
    )
    assert [h.name for h in heroes] == ["Gamma"]
    hero_events = [e for e in events if e[0] == "hero"]
    assert len(hero_events) == 1
    assert hero_events[0][1]["name"] == "Gamma"


def test_collect_heroes_rematch_replaces_name(tmp_path):
    """When same name but different power is encountered, rematch_name_fn is called."""
    cfg = load_heroes_config()
    device = RecordingDevice(png_bytes=_png())
    store = HeroStore(tmp_path)
    events: list[tuple[str, object]] = []

    def on_progress(ev, payload):
        events.append((ev, payload))

    call_count = [0]

    def fake_scrape(device, cfg, *, page, index, ocr_fn=None, sleep_fn=None, **_kw):
        from ks.heroes.models import HeroRecord as _HR3
        call_count[0] += 1
        if page == 0 and index == 0:
            return _HR3(name="Beta", roster_page=0, roster_index=0, power=5000, scraped_at="t0")
        if page == 0 and index == 1:
            # Same name, different power → should trigger rematch.
            return _HR3(name="Beta", roster_page=0, roster_index=1, power=9999, scraped_at="t1")
        return None

    def fake_rematch(hero, *, exclude_names):
        # Return a different name when rematching.
        return "Delta"

    from ks.heroes.collector import collect_heroes

    heroes = collect_heroes(
        device,
        cfg,
        store,
        sleep_fn=lambda _s: None,
        scrape_fn=fake_scrape,
        on_progress=on_progress,
        rematch_name_fn=fake_rematch,
    )
    names = [h.name for h in heroes]
    assert "Beta" in names
    assert "Delta" in names
