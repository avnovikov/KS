from __future__ import annotations

import time
from typing import Callable

from ks.heroes.config import HeroesConfig
from ks.heroes.models import HeroRecord
from ks.heroes.scrape import DeviceProtocol, scrape_hero
from ks.heroes.store import HeroStore


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
            try:
                hero = scrape(
                    device,
                    cfg,
                    page=page,
                    index=index,
                    ocr_fn=ocr_fn,
                    sleep_fn=sleep,
                )
            except Exception as exc:  # noqa: BLE001 — continue roster on single failure
                print(f"warn: scrape failed page={page} index={index}: {exc}")
                hero = None

            device.tap(cfg.nav.back.x, cfg.nav.back.y)
            sleep(cfg.delays.after_tap_ms / 1000.0)

            if hero is None:
                continue
            if hero.name in seen:
                continue
            seen.add(hero.name)
            store.upsert(hero)
            collected.append(hero)
            page_new += 1

        if page_new == 0:
            break
        if page + 1 >= cfg.roster.max_pages:
            break

        swipe = cfg.roster.page_swipe
        device.swipe(swipe.x1, swipe.y1, swipe.x2, swipe.y2, swipe.duration_ms)
        sleep(cfg.delays.after_open_ms / 1000.0)

    return collected
