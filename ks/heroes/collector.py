from __future__ import annotations

import time
from dataclasses import replace
from typing import Callable

from ks.heroes.config import HeroesConfig
from ks.heroes.models import HeroRecord
from ks.heroes.name_shot import rename_name_screenshot, save_name_screenshot
from ks.heroes.scrape import DeviceProtocol, decode_screencap, scrape_hero
from ks.heroes.store import HeroStore


def _sanitize_power(power: int | None, *, previous: int | None) -> int | None:
    """Drop OCR leading-digit glitches (e.g. 8172650 → 172650).

    Prefer raw OCR when it is plausible. Only strip a leading digit when that
    looks like a glitch relative to a previous scrape — never by default for
    legitimate ≥1M powers.
    """
    if power is None:
        return None
    if power < 1_000_000:
        return power
    text = str(power)
    stripped = int(text[1:])
    leading = text[0]

    def _near(candidate: int, ref: int) -> bool:
        return ref / 3.0 <= candidate <= ref * 3.0

    if previous is not None and previous > 0:
        raw_near = _near(power, previous)
        stripped_near = _near(stripped, previous)
        stripped_close = abs(stripped - previous) <= max(int(previous * 0.2), 25_000)
        glitch = (
            leading in "23456789"
            and stripped_near
            and stripped_close
            and (not raw_near or abs(stripped - previous) < abs(power - previous))
        )
        if glitch:
            print(f"power OCR sanitize {power} → {stripped} (prev={previous})")
            return stripped
        if raw_near:
            return power
        print(f"power OCR reject {power} (prev={previous}); keeping previous")
        return previous
    # No prior value: keep raw (avoid corrupting legitimate ≥1M first scrapes).
    return power


def _is_placeholder_name(name: str) -> bool:
    return name.startswith("Hero_p")


def _manual_name_for_slot(
    store: HeroStore, page: int, index: int
) -> str | None:
    """Return a previously saved non-placeholder name for this roster cell."""
    for hero in store.all_heroes():
        if hero.roster_page == page and hero.roster_index == index:
            if hero.name and not _is_placeholder_name(hero.name):
                return hero.name
            return None
    return None


def collect_heroes(
    device: DeviceProtocol,
    cfg: HeroesConfig,
    store: HeroStore,
    *,
    ocr_fn=None,
    sleep_fn: Callable[[float], None] | None = None,
    scrape_fn=None,
) -> list[HeroRecord]:
    """Walk the roster grid with paging; upsert each new hero into store."""
    sleep = sleep_fn or time.sleep
    scrape = scrape_fn or scrape_hero
    seen: set[str] = set()
    collected: list[HeroRecord] = []

    for page in range(cfg.roster.max_pages):
        page_new = 0
        for index, cell in enumerate(cfg.roster.cells):
            device.tap(cell.x, cell.y)
            sleep(cfg.delays.after_open_ms / 1000.0)
            hero: HeroRecord | None = None
            opened_detail = False
            keep_name = _manual_name_for_slot(store, page, index)
            try:
                hero = scrape(
                    device,
                    cfg,
                    page=page,
                    index=index,
                    ocr_fn=ocr_fn,
                    sleep_fn=sleep,
                    names_dir=store.names_dir,
                    keep_name=keep_name,
                )
                opened_detail = hero is not None
            except Exception as exc:  # noqa: BLE001 — continue roster on single failure
                print(f"warn: scrape failed page={page} index={index}: {exc}")
                opened_detail = True  # best-effort back from a half-open detail

            if opened_detail:
                device.tap(cfg.nav.back.x, cfg.nav.back.y)
                sleep(cfg.delays.after_tap_ms / 1000.0)

            if hero is None:
                continue
            if hero.name in seen:
                print(
                    f"warn: duplicate hero skip page={page} index={index} "
                    f"name={hero.name!r}"
                )
                continue
            seen.add(hero.name)
            store.upsert(hero)
            collected.append(hero)
            page_new += 1
            shot = hero.name_screenshot or "-"
            print(
                f"collected [{len(collected)}] {hero.name} "
                f"power={hero.power} stars={hero.stars}+{hero.pellets}p "
                f"name_shot={shot}"
            )

        if page_new == 0:
            break
        if page + 1 >= cfg.roster.max_pages:
            break

        swipe = cfg.roster.page_swipe
        device.swipe(swipe.x1, swipe.y1, swipe.x2, swipe.y2, swipe.duration_ms)
        sleep(cfg.delays.after_open_ms / 1000.0)

    return collected


def capture_name_screenshots(
    device: DeviceProtocol,
    cfg: HeroesConfig,
    store: HeroStore,
    *,
    sleep_fn: Callable[[float], None] | None = None,
) -> list[HeroRecord]:
    """Open each stored hero by roster slot; save top-center name crop under their name.

    Does not re-OCR names — keeps whatever is already in the store (manual fixes).
    Skips a slot when the detail screen does not open (avoids training on HUD crops).
    """
    from ks.heroes.ocr_util import ocr_box_robust
    from ks.heroes.scrape import dismiss_blocking_overlays, is_hero_detail_screen

    sleep = sleep_fn or time.sleep
    heroes = store.all_heroes()
    if not heroes:
        return []

    def _on_roster(img) -> bool:
        if is_hero_detail_screen(img):
            return False
        h, w = img.shape[:2]
        # Broad bands — pointer-location overlay shifts OCR; keep matching loose.
        top = ocr_box_robust(img, (80, 0, min(920, w - 80), 160), psm=6).lower()
        bottom = ocr_box_robust(
            img, (20, max(0, h - 280), min(1040, w - 20), min(280, h)), psm=6
        ).lower()
        blob = f"{top} {bottom}"
        return (
            "hero" in blob
            or "recruit" in blob
            or "drill" in blob
            or "power" in top
        )

    def _ensure_roster() -> None:
        for _ in range(4):
            img = decode_screencap(device.screencap())
            if _on_roster(img):
                return
            device.tap(cfg.nav.back.x, cfg.nav.back.y)
            sleep(cfg.delays.after_tap_ms / 1000.0)
        raise RuntimeError("could not return to heroes roster")

    by_page: dict[int, list[HeroRecord]] = {}
    for hero in heroes:
        by_page.setdefault(hero.roster_page, []).append(hero)

    pages = sorted(by_page)
    # Assume the device is already on the first page that has heroes (no lead-in swipes).
    current_page = pages[0]
    updated: list[HeroRecord] = []

    for page in pages:
        while current_page < page:
            swipe = cfg.roster.page_swipe
            device.swipe(swipe.x1, swipe.y1, swipe.x2, swipe.y2, swipe.duration_ms)
            sleep(cfg.delays.after_open_ms / 1000.0)
            current_page += 1

        page_heroes = sorted(by_page.get(page, []), key=lambda h: h.roster_index)
        for hero in page_heroes:
            if hero.roster_index < 0 or hero.roster_index >= len(cfg.roster.cells):
                print(
                    f"warn: skip {hero.name}: roster_index={hero.roster_index} out of range"
                )
                continue
            try:
                _ensure_roster()
            except Exception as exc:  # noqa: BLE001
                print(f"warn: roster sync failed before {hero.name}: {exc}")
                break

            cell = cfg.roster.cells[hero.roster_index]
            tap_y = cell.y
            opened = False
            for attempt in range(2):
                device.tap(cell.x, tap_y)
                sleep(cfg.delays.after_open_ms / 1000.0)
                try:
                    img = decode_screencap(device.screencap())
                    img = dismiss_blocking_overlays(device, cfg, sleep_fn=sleep)
                    if not is_hero_detail_screen(img):
                        print(
                            f"warn: not detail for {hero.name} "
                            f"(page={page} idx={hero.roster_index} try={attempt+1})"
                        )
                        device.tap(cfg.nav.back.x, cfg.nav.back.y)
                        sleep(cfg.delays.after_tap_ms / 1000.0)
                        continue
                    rel = save_name_screenshot(
                        img, cfg.ocr.name, store.names_dir, hero.name
                    )
                    if hero.name_screenshot and hero.name_screenshot != rel:
                        rename_name_screenshot(
                            store.out_dir, hero.name_screenshot, hero.name
                        )
                    new_hero = replace(hero, name_screenshot=rel)
                    store.upsert(new_hero)
                    updated.append(new_hero)
                    print(f"name shot [{len(updated)}] {hero.name} → {rel}")
                    opened = True
                    device.tap(cfg.nav.back.x, cfg.nav.back.y)
                    sleep(cfg.delays.after_tap_ms / 1000.0)
                    _ensure_roster()
                    break
                except Exception as exc:  # noqa: BLE001
                    print(f"warn: name shot failed for {hero.name}: {exc}")
                    device.tap(cfg.nav.back.x, cfg.nav.back.y)
                    sleep(cfg.delays.after_tap_ms / 1000.0)
            if not opened:
                print(f"warn: gave up on {hero.name}")

    return updated


def capture_star_progress(
    device: DeviceProtocol,
    cfg: HeroesConfig,
    store: HeroStore,
    *,
    sleep_fn: Callable[[float], None] | None = None,
) -> list[HeroRecord]:
    """Open each stored hero; update ``stars`` / ``pellets`` from the star strip."""
    from ks.heroes.ocr_util import ocr_box_robust
    from ks.heroes.scrape import dismiss_blocking_overlays, is_hero_detail_screen
    from ks.heroes.stars_vision import count_stars_pellets

    if cfg.ocr.stars is None:
        raise ValueError("ocr.stars box is required for star capture")

    sleep = sleep_fn or time.sleep
    heroes = store.all_heroes()
    if not heroes:
        return []

    def _on_roster(img) -> bool:
        if is_hero_detail_screen(img):
            return False
        h, w = img.shape[:2]
        top = ocr_box_robust(img, (80, 0, min(920, w - 80), 160), psm=6).lower()
        bottom = ocr_box_robust(
            img, (20, max(0, h - 280), min(1040, w - 20), min(280, h)), psm=6
        ).lower()
        blob = f"{top} {bottom}"
        return (
            "hero" in blob
            or "recruit" in blob
            or "drill" in blob
            or "power" in top
        )

    def _ensure_roster() -> None:
        for _ in range(4):
            img = decode_screencap(device.screencap())
            if _on_roster(img):
                return
            device.tap(cfg.nav.back.x, cfg.nav.back.y)
            sleep(cfg.delays.after_tap_ms / 1000.0)
        raise RuntimeError("could not return to heroes roster")

    by_page: dict[int, list[HeroRecord]] = {}
    for hero in heroes:
        by_page.setdefault(hero.roster_page, []).append(hero)

    pages = sorted(by_page)
    current_page = pages[0]
    updated: list[HeroRecord] = []

    for page in pages:
        while current_page < page:
            swipe = cfg.roster.page_swipe
            device.swipe(swipe.x1, swipe.y1, swipe.x2, swipe.y2, swipe.duration_ms)
            sleep(cfg.delays.after_open_ms / 1000.0)
            current_page += 1

        page_heroes = sorted(by_page.get(page, []), key=lambda h: h.roster_index)
        for hero in page_heroes:
            if hero.roster_index < 0 or hero.roster_index >= len(cfg.roster.cells):
                print(
                    f"warn: skip {hero.name}: roster_index={hero.roster_index} out of range"
                )
                continue
            try:
                _ensure_roster()
            except Exception as exc:  # noqa: BLE001
                print(f"warn: roster sync failed before {hero.name}: {exc}")
                break

            cell = cfg.roster.cells[hero.roster_index]
            opened = False
            for attempt in range(2):
                device.tap(cell.x, cell.y)
                sleep(cfg.delays.after_open_ms / 1000.0)
                try:
                    img = decode_screencap(device.screencap())
                    img = dismiss_blocking_overlays(device, cfg, sleep_fn=sleep)
                    if not is_hero_detail_screen(img):
                        print(
                            f"warn: not detail for {hero.name} "
                            f"(page={page} idx={hero.roster_index} try={attempt+1})"
                        )
                        device.tap(cfg.nav.back.x, cfg.nav.back.y)
                        sleep(cfg.delays.after_tap_ms / 1000.0)
                        continue
                    progress = count_stars_pellets(img, cfg.ocr.stars)
                    new_hero = replace(
                        hero, stars=progress.stars, pellets=progress.pellets
                    )
                    store.upsert(new_hero)
                    updated.append(new_hero)
                    print(
                        f"stars [{len(updated)}] {hero.name}: "
                        f"{progress.stars}* + {progress.pellets} pellets "
                        f"(slots={progress.per_slot})"
                    )
                    opened = True
                    device.tap(cfg.nav.back.x, cfg.nav.back.y)
                    sleep(cfg.delays.after_tap_ms / 1000.0)
                    _ensure_roster()
                    break
                except Exception as exc:  # noqa: BLE001
                    print(f"warn: stars failed for {hero.name}: {exc}")
                    device.tap(cfg.nav.back.x, cfg.nav.back.y)
                    sleep(cfg.delays.after_tap_ms / 1000.0)
            if not opened:
                print(f"warn: gave up on {hero.name}")

    return updated


def capture_power_stats(
    device: DeviceProtocol,
    cfg: HeroesConfig,
    store: HeroStore,
    *,
    sleep_fn: Callable[[float], None] | None = None,
) -> list[HeroRecord]:
    """Open each stored hero; update only ``power`` and ``stats`` (naked scrape).

    Leaves level / stars / pellets / skills / rarity / troop untouched.
    """
    from ks.heroes.ocr_util import ocr_box_robust
    from ks.heroes.parse import parse_power, parse_stats_panel
    from ks.heroes.scrape import dismiss_blocking_overlays, is_hero_detail_screen

    sleep = sleep_fn or time.sleep
    heroes = store.all_heroes()
    if not heroes:
        return []

    def _ocr_digits(image, box: tuple[int, int, int, int]) -> str:
        return ocr_box_robust(image, box, whitelist="0123456789,", psm=7)

    def _ocr_text(image, box: tuple[int, int, int, int]) -> str:
        return ocr_box_robust(image, box, psm=6)

    def _on_roster(img) -> bool:
        if is_hero_detail_screen(img):
            return False
        h, w = img.shape[:2]
        top = ocr_box_robust(img, (80, 0, min(920, w - 80), 160), psm=6).lower()
        bottom = ocr_box_robust(
            img, (20, max(0, h - 280), min(1040, w - 20), min(280, h)), psm=6
        ).lower()
        blob = f"{top} {bottom}"
        return (
            "hero" in blob
            or "recruit" in blob
            or "drill" in blob
            or "power" in top
        )

    def _ensure_roster() -> None:
        for _ in range(4):
            img = decode_screencap(device.screencap())
            if _on_roster(img):
                return
            device.tap(cfg.nav.back.x, cfg.nav.back.y)
            sleep(cfg.delays.after_tap_ms / 1000.0)
        raise RuntimeError("could not return to heroes roster")

    by_page: dict[int, list[HeroRecord]] = {}
    for hero in heroes:
        by_page.setdefault(hero.roster_page, []).append(hero)

    pages = sorted(by_page)
    current_page = pages[0]
    updated: list[HeroRecord] = []

    for page in pages:
        while current_page < page:
            swipe = cfg.roster.page_swipe
            device.swipe(swipe.x1, swipe.y1, swipe.x2, swipe.y2, swipe.duration_ms)
            sleep(cfg.delays.after_open_ms / 1000.0)
            current_page += 1

        page_heroes = sorted(by_page.get(page, []), key=lambda h: h.roster_index)
        for hero in page_heroes:
            if hero.roster_index < 0 or hero.roster_index >= len(cfg.roster.cells):
                print(
                    f"warn: skip {hero.name}: roster_index={hero.roster_index} out of range"
                )
                continue
            try:
                _ensure_roster()
            except Exception as exc:  # noqa: BLE001
                print(f"warn: roster sync failed before {hero.name}: {exc}")
                break

            cell = cfg.roster.cells[hero.roster_index]
            opened = False
            for attempt in range(2):
                device.tap(cell.x, cell.y)
                sleep(cfg.delays.after_open_ms / 1000.0)
                try:
                    img = decode_screencap(device.screencap())
                    img = dismiss_blocking_overlays(device, cfg, sleep_fn=sleep)
                    if not is_hero_detail_screen(img):
                        print(
                            f"warn: not detail for {hero.name} "
                            f"(page={page} idx={hero.roster_index} try={attempt+1})"
                        )
                        device.tap(cfg.nav.back.x, cfg.nav.back.y)
                        sleep(cfg.delays.after_tap_ms / 1000.0)
                        continue

                    power = parse_power(_ocr_digits(img, cfg.ocr.power.as_tuple()))
                    power = _sanitize_power(power, previous=hero.power)
                    device.tap(cfg.nav.stats_list_button.x, cfg.nav.stats_list_button.y)
                    sleep(cfg.delays.after_tap_ms / 1000.0)
                    stats_img = decode_screencap(device.screencap())
                    stats = parse_stats_panel(
                        _ocr_text(stats_img, cfg.ocr.stats_panel.as_tuple())
                    )
                    device.tap(cfg.nav.stats_list_button.x, cfg.nav.stats_list_button.y)
                    sleep(cfg.delays.after_tap_ms / 1000.0)

                    if power is None and (
                        stats is None
                        or (not stats.conquest and not stats.expedition)
                    ):
                        print(f"warn: empty power/stats OCR for {hero.name}")
                        device.tap(cfg.nav.back.x, cfg.nav.back.y)
                        sleep(cfg.delays.after_tap_ms / 1000.0)
                        continue

                    new_hero = replace(
                        hero,
                        power=power if power is not None else hero.power,
                        stats=stats if stats is not None else hero.stats,
                    )
                    store.upsert(new_hero)
                    updated.append(new_hero)
                    delta = ""
                    if power is not None and hero.power is not None:
                        delta = f" Δ={power - hero.power:+d}"
                    conquest_n = len(
                        (new_hero.stats.conquest if new_hero.stats else {}) or {}
                    )
                    print(
                        f"power/stats [{len(updated)}] {hero.name}: "
                        f"{hero.power} → {new_hero.power}{delta} "
                        f"conquest={conquest_n}"
                    )
                    opened = True
                    device.tap(cfg.nav.back.x, cfg.nav.back.y)
                    sleep(cfg.delays.after_tap_ms / 1000.0)
                    _ensure_roster()
                    break
                except Exception as exc:  # noqa: BLE001
                    print(f"warn: power/stats failed for {hero.name}: {exc}")
                    device.tap(cfg.nav.back.x, cfg.nav.back.y)
                    sleep(cfg.delays.after_tap_ms / 1000.0)
            if not opened:
                print(f"warn: gave up on {hero.name}")

    return updated
