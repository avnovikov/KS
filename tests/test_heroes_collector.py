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


def test_collect_power_i_naked_is_authoritative_over_detail_garbage(tmp_path):
    """Power-i Level+Stars+Skills must replace detail-box OCR junk in the store."""
    from ks.heroes.power_breakdown import PowerBreakdown
    from ks.heroes.power_i_capture import PowerICapture
    from ks.heroes.power_history import load_points

    cfg = load_heroes_config()
    device = RecordingDevice(png_bytes=_png())
    store = HeroStore(tmp_path)

    naked = 71_045 + 131_690 + 15_120  # 217_855

    def fake_scrape(
        device,
        cfg,
        *,
        page,
        index,
        ocr_fn=None,
        sleep_fn=None,
        on_power_breakdown=None,
        **_kw,
    ):
        if page != 0 or index != 0:
            return None
        if on_power_breakdown is not None:
            on_power_breakdown(
                PowerICapture(
                    breakdown=PowerBreakdown(
                        hero_power=naked,
                        from_level=71_045,
                        from_stars=131_690,
                        from_skills=15_120,
                    ),
                    observed_name="Forrest",
                    raw_name="Forrest",
                )
            )
        return HeroRecord(
            name="Forrest",
            power=3_157_751,  # detail OCR garbage
            level=58,
            stars=3,
            pellets=0,
            roster_page=0,
            roster_index=0,
            scraped_at="t-forrest",
        )

    heroes = collect_heroes(
        device,
        cfg,
        store,
        sleep_fn=lambda _s: None,
        scrape_fn=fake_scrape,
    )
    assert len(heroes) == 1
    stored = next(h for h in store.all_heroes() if h.name == "Forrest")
    assert stored.power == naked
    points = load_points(tmp_path / "power_history", "Forrest")
    assert len(points) == 1
    assert points[0].from_level == 71_045
    assert points[0].from_stars == 131_690
    assert points[0].from_skills == 15_120


def test_collect_keeps_prior_naked_when_detail_is_million_glitch(tmp_path):
    """Without Power-i, absurd ≥1M detail OCR must not clobber stored naked power."""
    cfg = load_heroes_config()
    device = RecordingDevice(png_bytes=_png())
    store = HeroStore(tmp_path)
    store.upsert(
        HeroRecord(
            name="Forrest",
            power=217_855,
            level=58,
            stars=3,
            pellets=0,
            roster_page=0,
            roster_index=0,
            scraped_at="t0",
        )
    )

    def fake_scrape(device, cfg, *, page, index, ocr_fn=None, sleep_fn=None, **_kw):
        if page != 0 or index != 0:
            return None
        return HeroRecord(
            name="Forrest",
            power=3_157_751,
            level=58,
            stars=3,
            pellets=0,
            roster_page=0,
            roster_index=0,
            scraped_at="t1",
        )

    collect_heroes(
        device,
        cfg,
        store,
        sleep_fn=lambda _s: None,
        scrape_fn=fake_scrape,
        # Force re-collect: clear seen by using a fresh collect — name already in store
        # but not in seen, so first cell still upserts.
    )
    stored = next(h for h in store.all_heroes() if h.name == "Forrest")
    assert stored.power == 217_855


def test_roster_ocr_sets_medium_assurance(tmp_path):
    """Roster scrape marks non-None fields medium/roster_ocr in assurance."""
    cfg = load_heroes_config()
    device = RecordingDevice(png_bytes=_png())
    store = HeroStore(tmp_path)

    def fake_scrape(device, cfg, *, page, index, ocr_fn=None, sleep_fn=None, **_kw):
        if page == 0 and index == 0:
            return HeroRecord(
                name="Alice",
                power=100_000,
                level=50,
                stars=3,
                pellets=2,
                roster_page=0,
                roster_index=0,
                scraped_at="t0",
            )
        return None

    collect_heroes(device, cfg, store, sleep_fn=lambda _: None, scrape_fn=fake_scrape)

    stored = next(h for h in store.all_heroes() if h.name == "Alice")
    for field_name in ("power", "stars", "level", "pellets"):
        a = stored.assurance.get(field_name)
        assert a is not None, f"assurance[{field_name!r}] missing"
        assert a.level == "medium", f"expected medium for {field_name}, got {a.level!r}"
        assert a.reason == "roster_ocr", f"expected roster_ocr for {field_name}, got {a.reason!r}"


def test_roster_ocr_preserves_high_assurance(tmp_path):
    """Re-scraping a hero doesn't downgrade a field already at high assurance."""
    from ks.heroes.assurance import FieldAssurance

    cfg = load_heroes_config()
    device = RecordingDevice(png_bytes=_png())
    store = HeroStore(tmp_path)
    store.upsert(
        HeroRecord(
            name="Bob",
            power=90_000,
            roster_page=0,
            roster_index=0,
            scraped_at="t_prev",
            assurance={"power": FieldAssurance("high", "power_i_agree")},
        )
    )

    def fake_scrape(device, cfg, *, page, index, ocr_fn=None, sleep_fn=None, **_kw):
        if page == 0 and index == 0:
            return HeroRecord(
                name="Bob",
                power=91_000,
                roster_page=0,
                roster_index=0,
                scraped_at="t1",
            )
        return None

    collect_heroes(device, cfg, store, sleep_fn=lambda _: None, scrape_fn=fake_scrape)

    stored = next(h for h in store.all_heroes() if h.name == "Bob")
    assert stored.assurance["power"].level == "high", "high assurance must not be downgraded to medium"
    assert stored.assurance["power"].reason == "power_i_agree"


def test_power_i_agree_sets_high_power_and_bucket_assurance(tmp_path):
    """Power-i agree sets power and non-None buckets to high/power_i_agree."""
    from ks.heroes.power_breakdown import PowerBreakdown
    from ks.heroes.power_i_capture import PowerICapture

    cfg = load_heroes_config()
    device = RecordingDevice(png_bytes=_png())
    store = HeroStore(tmp_path)

    naked = 71_045 + 131_690 + 15_120  # 217_855

    def fake_scrape(
        device, cfg, *, page, index, ocr_fn=None, sleep_fn=None, on_power_breakdown=None, **_kw
    ):
        if page != 0 or index != 0:
            return None
        if on_power_breakdown is not None:
            on_power_breakdown(
                PowerICapture(
                    breakdown=PowerBreakdown(
                        hero_power=naked,
                        from_level=71_045,
                        from_stars=131_690,
                        from_skills=15_120,
                    ),
                    observed_name="Charlie",
                    raw_name="Charlie",
                )
            )
        return HeroRecord(
            name="Charlie",
            power=999_999,
            level=58,
            stars=3,
            pellets=0,
            roster_page=0,
            roster_index=0,
            scraped_at="t0",
        )

    collect_heroes(device, cfg, store, sleep_fn=lambda _: None, scrape_fn=fake_scrape)

    stored = next(h for h in store.all_heroes() if h.name == "Charlie")
    assert stored.power == naked
    assert stored.assurance["power"].level == "high"
    assert stored.assurance["power"].reason == "power_i_agree"
    for bucket in ("from_level", "from_stars", "from_skills"):
        a = stored.assurance.get(bucket)
        assert a is not None, f"assurance[{bucket!r}] missing"
        assert a.level == "high", f"expected high for {bucket}, got {a.level!r}"
        assert a.reason == "power_i_agree"


def test_power_i_missing_naked_sets_low_power_assurance(tmp_path):
    """Power-i run with unresolvable naked sets power assurance to low/power_i_missing."""
    from ks.heroes.power_breakdown import PowerBreakdown
    from ks.heroes.power_i_capture import PowerICapture

    cfg = load_heroes_config()
    device = RecordingDevice(png_bytes=_png())
    store = HeroStore(tmp_path)

    def fake_scrape(
        device, cfg, *, page, index, ocr_fn=None, sleep_fn=None, on_power_breakdown=None, **_kw
    ):
        if page != 0 or index != 0:
            return None
        if on_power_breakdown is not None:
            on_power_breakdown(
                PowerICapture(
                    breakdown=PowerBreakdown(hero_power=100_000),  # no buckets → naked=None
                    observed_name="Diana",
                    raw_name="Diana",
                )
            )
        return HeroRecord(
            name="Diana",
            power=100_000,
            roster_page=0,
            roster_index=0,
            scraped_at="t0",
        )

    collect_heroes(device, cfg, store, sleep_fn=lambda _: None, scrape_fn=fake_scrape)

    stored = next(h for h in store.all_heroes() if h.name == "Diana")
    assert stored.assurance["power"].level == "low"
    assert stored.assurance["power"].reason == "power_i_missing"
    assert stored.power == 100_000  # numeric power must not be clobbered


def test_collect_applies_naked_to_slot_not_wrong_observed_hero(tmp_path):
    """Slot hero keeps Power-i naked even if tooltip name OCR points elsewhere."""
    from ks.heroes.power_breakdown import PowerBreakdown
    from ks.heroes.power_i_capture import PowerICapture

    cfg = load_heroes_config()
    device = RecordingDevice(png_bytes=_png())
    store = HeroStore(tmp_path)
    store.upsert(
        HeroRecord(
            name="Howard",
            power=269_680,
            roster_page=0,
            roster_index=2,
            scraped_at="t-howard",
        )
    )

    naked = 217_855

    def fake_scrape(
        device,
        cfg,
        *,
        page,
        index,
        ocr_fn=None,
        sleep_fn=None,
        on_power_breakdown=None,
        **_kw,
    ):
        if page != 0 or index != 0:
            return None
        if on_power_breakdown is not None:
            on_power_breakdown(
                PowerICapture(
                    breakdown=PowerBreakdown(
                        hero_power=naked,
                        from_level=71_045,
                        from_stars=131_690,
                        from_skills=15_120,
                    ),
                    observed_name="Howard",  # wrong OCR of on-screen name
                    raw_name="Howard",
                )
            )
        return HeroRecord(
            name="Forrest",
            power=3_157_751,
            roster_page=0,
            roster_index=0,
            scraped_at="t-forrest",
        )

    collect_heroes(
        device,
        cfg,
        store,
        sleep_fn=lambda _s: None,
        scrape_fn=fake_scrape,
    )
    forrest = next(h for h in store.all_heroes() if h.name == "Forrest")
    howard = next(h for h in store.all_heroes() if h.name == "Howard")
    assert forrest.power == naked
    assert howard.power == 269_680  # must not be clobbered
