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
