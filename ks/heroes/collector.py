from __future__ import annotations

import time
from dataclasses import replace
from typing import Callable

from ks.heroes.config import HeroesConfig
from ks.heroes.models import HeroRecord
from ks.heroes.name_shot import rename_name_screenshot, save_name_screenshot
from ks.heroes.ocr_util import ocr_box_robust
from ks.heroes.parse import parse_power, parse_stats_panel
from ks.heroes.scrape import (
    DeviceProtocol,
    decode_screencap,
    dismiss_blocking_overlays,
    is_hero_detail_screen,
    scrape_hero,
)
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


def _close_detail_screen(
    device: DeviceProtocol, cfg: HeroesConfig, sleep: Callable[[float], None]
) -> None:
    device.tap(cfg.nav.back.x, cfg.nav.back.y)
    sleep(cfg.delays.after_tap_ms / 1000.0)


def _advance_roster_page(
    device: DeviceProtocol, cfg: HeroesConfig, sleep: Callable[[float], None]
) -> None:
    swipe = cfg.roster.page_swipe
    device.swipe(swipe.x1, swipe.y1, swipe.x2, swipe.y2, swipe.duration_ms)
    sleep(cfg.delays.after_open_ms / 1000.0)


def _open_and_scrape_cell(
    device: DeviceProtocol,
    cfg: HeroesConfig,
    store: HeroStore,
    scrape: Callable,
    ocr_fn: object,
    sleep: Callable[[float], None],
    *,
    page: int,
    index: int,
    cell,
) -> tuple[HeroRecord | None, bool]:
    """Tap a roster cell and scrape it; returns (hero_or_None, detail_was_opened).

    On a scrape failure the detail screen may be half-open, so the caller is
    told to attempt a Back tap regardless.
    """
    device.tap(cell.x, cell.y)
    sleep(cfg.delays.after_open_ms / 1000.0)
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
        return hero, hero is not None
    except Exception as exc:  # noqa: BLE001 — continue roster on single failure
        print(f"warn: scrape failed page={page} index={index}: {exc}")
        return None, True  # best-effort back from a half-open detail


def _resolve_duplicate_hero(
    hero: HeroRecord,
    *,
    device: DeviceProtocol,
    cfg: HeroesConfig,
    store: HeroStore,
    collected: list[HeroRecord],
    seen: set[str],
    opened_detail: bool,
    scrape: Callable,
    ocr_fn: object,
    sleep: Callable[[float], None],
    rematch_name_fn: Callable[..., str | None] | None,
    on_progress: Callable[[str, object], None] | None,
    page: int,
    index: int,
) -> HeroRecord | None:
    """Resolve a hero whose name has already been seen this session.

    Returns a replacement HeroRecord when a rematch finds a genuinely new
    name (caller should treat it like a freshly collected hero, detail screen
    already closed). Returns None when the cell should be counted as a
    duplicate — progress has already been emitted and the detail screen
    already closed.
    """
    prev_hero = next((h for h in collected if h.name == hero.name), None)
    if prev_hero is not None and not _same_power(hero.power, prev_hero.power):
        # Same name but different power → rematch (detail still open).
        rematched = _rematch_hero_name(
            hero,
            device,
            cfg,
            store,
            scrape_fn=scrape,
            ocr_fn=ocr_fn,
            sleep_fn=sleep,
            exclude_names=seen,
            rematch_name_fn=rematch_name_fn,
        )
        if rematched is not None and rematched.name not in seen:
            return rematched  # already closed by rematch
        if opened_detail:
            _close_detail_screen(device, cfg, sleep)
        if on_progress is not None:
            on_progress("rematch", {"name": hero.name, "page": page, "index": index})
        return None

    print(f"warn: duplicate hero skip page={page} index={index} name={hero.name!r}")
    if opened_detail:
        _close_detail_screen(device, cfg, sleep)
    if on_progress is not None:
        on_progress("duplicate", {"name": hero.name, "page": page, "index": index})
    return None


def _log_collected_hero(hero: HeroRecord, count: int) -> None:
    shot = hero.name_screenshot or "-"
    print(
        f"collected [{count}] {hero.name} "
        f"power={hero.power} stars={hero.stars}+{hero.pellets}p "
        f"name_shot={shot}"
    )


def _scan_roster_page(
    device: DeviceProtocol,
    cfg: HeroesConfig,
    store: HeroStore,
    scrape: Callable,
    ocr_fn: object,
    sleep: Callable[[float], None],
    seen: set[str],
    collected: list[HeroRecord],
    *,
    page: int,
    on_progress: Callable[[str, object], None] | None,
    rematch_name_fn: Callable[..., str | None] | None,
    max_consecutive_duplicates: int,
) -> int:
    """Scan every cell on one roster page; upsert new heroes into ``collected``.

    Returns the count of newly collected heroes on this page.
    """
    page_new = 0
    consecutive_dups = 0
    for index, cell in enumerate(cfg.roster.cells):
        hero, opened_detail = _open_and_scrape_cell(
            device, cfg, store, scrape, ocr_fn, sleep, page=page, index=index, cell=cell
        )

        if hero is None:
            if opened_detail:
                _close_detail_screen(device, cfg, sleep)
            continue

        if hero.name in seen:
            resolved = _resolve_duplicate_hero(
                hero,
                device=device,
                cfg=cfg,
                store=store,
                collected=collected,
                seen=seen,
                opened_detail=opened_detail,
                scrape=scrape,
                ocr_fn=ocr_fn,
                sleep=sleep,
                rematch_name_fn=rematch_name_fn,
                on_progress=on_progress,
                page=page,
                index=index,
            )
            if resolved is None:
                consecutive_dups += 1
                if consecutive_dups >= max_consecutive_duplicates:
                    if on_progress is not None:
                        on_progress(
                            "stopped",
                            {"page": page, "index": index, "reason": "consecutive_duplicates"},
                        )
                    break
                continue
            hero = resolved
            opened_detail = False  # already closed by rematch

        if opened_detail:
            _close_detail_screen(device, cfg, sleep)

        consecutive_dups = 0
        seen.add(hero.name)
        store.upsert(hero)
        collected.append(hero)
        page_new += 1
        _log_collected_hero(hero, len(collected))
        if on_progress is not None:
            on_progress("hero", {"name": hero.name, "power": hero.power, "page": page, "index": index})

    return page_new


def collect_heroes(
    device: DeviceProtocol,
    cfg: HeroesConfig,
    store: HeroStore,
    *,
    ocr_fn=None,
    sleep_fn: Callable[[float], None] | None = None,
    scrape_fn=None,
    on_progress: Callable[[str, object], None] | None = None,
    max_consecutive_duplicates: int = 3,
    rematch_name_fn: Callable[..., str | None] | None = None,
) -> list[HeroRecord]:
    """Walk the roster grid with paging; upsert each new hero into store.

    Emits progress events via on_progress(event_type, payload):
      "hero"      — new hero collected
      "duplicate" — same name + same power seen again
      "rematch"   — same name but different power → re-OCR to find true name
      "stopped"   — consecutive-duplicate cap triggered; cell loop broken
      "done"      — page scan finished
    """
    sleep = sleep_fn or time.sleep
    scrape = scrape_fn or scrape_hero
    seen: set[str] = set()
    collected: list[HeroRecord] = []

    for page in range(cfg.roster.max_pages):
        page_new = _scan_roster_page(
            device,
            cfg,
            store,
            scrape,
            ocr_fn,
            sleep,
            seen,
            collected,
            page=page,
            on_progress=on_progress,
            rematch_name_fn=rematch_name_fn,
            max_consecutive_duplicates=max_consecutive_duplicates,
        )

        if page_new == 0:
            break
        if page + 1 >= cfg.roster.max_pages:
            break

        _advance_roster_page(device, cfg, sleep)

    return collected


def _same_power(a: int | None, b: int | None, tol: int = 500) -> bool:
    """True when two power values are close enough to be the same hero."""
    if a is None or b is None:
        return True  # can't distinguish
    return abs(a - b) <= tol


def _rematch_hero_name(
    hero: HeroRecord,
    device: DeviceProtocol,
    cfg: HeroesConfig,
    store: HeroStore,
    *,
    scrape_fn: Callable,
    ocr_fn: object,
    sleep_fn: Callable[[float], None],
    exclude_names: set[str],
    rematch_name_fn: Callable[..., str | None] | None,
) -> HeroRecord | None:
    """Re-OCR hero name on the open detail screen, excluding already-seen names.

    Returns an updated HeroRecord with new name, or None if rematch failed.
    Detail screen is closed before returning.
    """
    try:
        if rematch_name_fn is not None:
            new_name = rematch_name_fn(hero, exclude_names=exclude_names)
        else:
            new_name = None

        if new_name is not None and new_name != hero.name and new_name not in exclude_names:
            from dataclasses import replace as _replace
            device.tap(cfg.nav.back.x, cfg.nav.back.y)
            sleep_fn(cfg.delays.after_tap_ms / 1000.0)
            return _replace(hero, name=new_name)
    except Exception as exc:  # noqa: BLE001
        print(f"warn: rematch failed for {hero.name!r}: {exc}")
    device.tap(cfg.nav.back.x, cfg.nav.back.y)
    sleep_fn(cfg.delays.after_tap_ms / 1000.0)
    return None


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


def _looks_like_hero_roster_screen(img) -> bool:
    """True when ``img`` looks like the roster grid rather than a detail view."""
    if is_hero_detail_screen(img):
        return False
    h, w = img.shape[:2]
    top = ocr_box_robust(img, (80, 0, min(920, w - 80), 160), psm=6).lower()
    bottom = ocr_box_robust(
        img, (20, max(0, h - 280), min(1040, w - 20), min(280, h)), psm=6
    ).lower()
    blob = f"{top} {bottom}"
    return "hero" in blob or "recruit" in blob or "drill" in blob or "power" in top


def _wait_for_roster_screen(
    device: DeviceProtocol, cfg: HeroesConfig, sleep: Callable[[float], None]
) -> None:
    """Tap Back until the roster grid is visible again; raises if it never is."""
    for _ in range(4):
        img = decode_screencap(device.screencap())
        if _looks_like_hero_roster_screen(img):
            return
        _close_detail_screen(device, cfg, sleep)
    raise RuntimeError("could not return to heroes roster")


def _group_by_roster_page(heroes: list[HeroRecord]) -> dict[int, list[HeroRecord]]:
    by_page: dict[int, list[HeroRecord]] = {}
    for hero in heroes:
        by_page.setdefault(hero.roster_page, []).append(hero)
    return by_page


def _swipe_to_roster_page(
    device: DeviceProtocol,
    cfg: HeroesConfig,
    sleep: Callable[[float], None],
    current_page: int,
    target_page: int,
) -> int:
    """Swipe forward from ``current_page`` to ``target_page``; returns the new page."""
    while current_page < target_page:
        _advance_roster_page(device, cfg, sleep)
        current_page += 1
    return current_page


def _try_read_power_stats(
    device: DeviceProtocol,
    cfg: HeroesConfig,
    store: HeroStore,
    hero: HeroRecord,
    sleep: Callable[[float], None],
    *,
    page: int,
    attempt: int,
) -> tuple[HeroRecord, int | None] | None:
    """One capture attempt on the (assumed open) detail screen.

    Returns (updated_hero, sanitized_power) on success — already upserted
    into ``store`` — or None when the detail screen never opened or both
    power and stats OCR came back empty (caller decides whether to retry).
    """
    img = decode_screencap(device.screencap())
    img = dismiss_blocking_overlays(device, cfg, sleep_fn=sleep)
    if not is_hero_detail_screen(img):
        print(
            f"warn: not detail for {hero.name} "
            f"(page={page} idx={hero.roster_index} try={attempt + 1})"
        )
        return None

    power = parse_power(ocr_box_robust(img, cfg.ocr.power.as_tuple(), whitelist="0123456789,", psm=7))
    power = _sanitize_power(power, previous=hero.power)
    device.tap(cfg.nav.stats_list_button.x, cfg.nav.stats_list_button.y)
    sleep(cfg.delays.after_tap_ms / 1000.0)
    stats_img = decode_screencap(device.screencap())
    stats = parse_stats_panel(ocr_box_robust(stats_img, cfg.ocr.stats_panel.as_tuple(), psm=6))
    device.tap(cfg.nav.stats_list_button.x, cfg.nav.stats_list_button.y)
    sleep(cfg.delays.after_tap_ms / 1000.0)

    if power is None and (stats is None or (not stats.conquest and not stats.expedition)):
        print(f"warn: empty power/stats OCR for {hero.name}")
        return None

    new_hero = replace(
        hero,
        power=power if power is not None else hero.power,
        stats=stats if stats is not None else hero.stats,
    )
    store.upsert(new_hero)
    return new_hero, power


def _log_power_stats_update(
    hero: HeroRecord, new_hero: HeroRecord, power: int | None, count: int
) -> None:
    delta = ""
    if power is not None and hero.power is not None:
        delta = f" Δ={power - hero.power:+d}"
    conquest_n = len((new_hero.stats.conquest if new_hero.stats else {}) or {})
    print(
        f"power/stats [{count}] {hero.name}: "
        f"{hero.power} → {new_hero.power}{delta} "
        f"conquest={conquest_n}"
    )


def _capture_power_stats_for_hero(
    device: DeviceProtocol,
    cfg: HeroesConfig,
    store: HeroStore,
    hero: HeroRecord,
    sleep: Callable[[float], None],
    *,
    page: int,
) -> tuple[HeroRecord, int | None] | None:
    """Open one hero's detail screen and refresh power/stats; up to 2 attempts.

    Returns (updated_hero, sanitized_power) on success, or None if every
    attempt failed (already logged). The roster is back in view either way.
    """
    cell = cfg.roster.cells[hero.roster_index]
    for attempt in range(2):
        device.tap(cell.x, cell.y)
        sleep(cfg.delays.after_open_ms / 1000.0)
        try:
            result = _try_read_power_stats(device, cfg, store, hero, sleep, page=page, attempt=attempt)
        except Exception as exc:  # noqa: BLE001
            print(f"warn: power/stats failed for {hero.name}: {exc}")
            result = None
        _close_detail_screen(device, cfg, sleep)
        if result is not None:
            _wait_for_roster_screen(device, cfg, sleep)
            return result
    print(f"warn: gave up on {hero.name}")
    return None


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
    sleep = sleep_fn or time.sleep
    heroes = store.all_heroes()
    if not heroes:
        return []

    by_page = _group_by_roster_page(heroes)
    pages = sorted(by_page)
    current_page = pages[0]
    updated: list[HeroRecord] = []

    for page in pages:
        current_page = _swipe_to_roster_page(device, cfg, sleep, current_page, page)

        page_heroes = sorted(by_page.get(page, []), key=lambda h: h.roster_index)
        for hero in page_heroes:
            if hero.roster_index < 0 or hero.roster_index >= len(cfg.roster.cells):
                print(
                    f"warn: skip {hero.name}: roster_index={hero.roster_index} out of range"
                )
                continue
            try:
                _wait_for_roster_screen(device, cfg, sleep)
            except Exception as exc:  # noqa: BLE001
                print(f"warn: roster sync failed before {hero.name}: {exc}")
                break

            result = _capture_power_stats_for_hero(device, cfg, store, hero, sleep, page=page)
            if result is not None:
                new_hero, power = result
                updated.append(new_hero)
                _log_power_stats_update(hero, new_hero, power, len(updated))

    return updated
