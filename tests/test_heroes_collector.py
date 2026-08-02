from __future__ import annotations

import cv2
import numpy as np

from ks.device.fake import FakeDevice
from ks.heroes.collector import collect_heroes
from ks.heroes.config import load_heroes_config
from ks.heroes.models import HeroRecord
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
