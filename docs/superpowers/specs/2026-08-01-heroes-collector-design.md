# Heroes Collector Design

**Date:** 2026-08-01  
**Status:** Approved for implementation  
**Workspace:** `.worktrees/feature-heroes-collector`  
**Branch:** `feature/heroes-collector`

## Goal

ADB-driven tool that walks the KingShot hero roster (4×4 grid, paging through all pages), opens each owned hero, and scrapes identity, power, stats, and skills into JSON + SQLite under `artifacts/heroes/`.

## Locked decisions

| Topic | Decision |
|-------|----------|
| Approach | Config-driven ADB taps + fixed OCR crop boxes (Approach 1) |
| Roster scope | Full roster with page swipe; stop when a page yields zero new heroes |
| Start state | User leaves the game on the hero roster screen |
| Hero power | Detail screen, under the hero name |
| Stats popup | Tap list button to open → OCR → tap list button to close |
| Skills | Tap Skills tab, then each configured skill-icon slot; skip if panel text unchanged |
| Gear | Out of scope for v1 |
| Extras | Best-effort OCR: rarity, troop type, Escorts count, star level |
| Output | Both `heroes.json` and `heroes.db` per run |
| Navigation | ADB only (tap / swipe / screencap) |
| Empty cells | Open fails name OCR → treat as empty/locked, continue |

## Architecture

New package `ks/heroes/` with:

1. **config** — load `config/heroes.yaml` (tap points, OCR boxes, delays, swipe).
2. **parse** — turn OCR strings into structured ints/floats/percents.
3. **scrape** — one-hero sequence: identity → stats popup → skills.
4. **collector** — 4×4 page loop, back navigation, page swipe, name dedupe.
5. **store** — append/write JSON + SQLite continuously.
6. **cli** — `ks-heroes collect --config … [--serial …] [--out …]`.

Device boundary: any object with `screencap()`, `tap(x,y)`, `swipe(...)` (`AdbDevice` or `FakeDevice`).

## Data model

```text
HeroRecord
  name: str
  power: int | None
  rarity: str | None          # e.g. SSR
  troop_type: str | None      # e.g. Cavalry (best-effort)
  escorts: int | None
  stars: int | None
  stats: HeroStats | None
  skills: list[SkillRecord]
  roster_page: int
  roster_index: int           # 0..15 on page
  scraped_at: ISO-8601

HeroStats
  conquest: dict[str, int]    # Hero Attack, …
  expedition: dict[str, float]  # percent bonuses as floats (101.37)

SkillRecord
  slot: int
  name: str | None
  level: int | None
  description: str | None
  upgrade_preview: str | None
```

SQLite tables: `heroes` (one row per hero), `hero_stats` (key/value for conquest + expedition), `skills` (one row per skill slot).

## Per-hero flow

1. Tap roster cell → wait → screencap.
2. OCR name; if empty/unusable → back (if needed) / skip.
3. OCR power, rarity, troop type, Escorts, stars (configured boxes).
4. Tap list button → wait → OCR stats region → parse Conquest/Expedition → tap list to close.
5. Tap Skills tab → for each skill slot: tap → wait → OCR skill panel; if text equals previous, skip (empty); else parse and store.
6. Tap back → return to roster.
7. Persist hero immediately (JSON rewrite + SQLite upsert).

## Roster / paging

- Config lists exactly 16 cell taps (row-major).
- After 16 cells, swipe page (config `page_swipe`).
- Track seen names; stop when a full page adds zero new heroes **or** `max_pages` is hit.
- Failures on a single hero are logged and do not abort the run (continue to next cell).

## Config sketch (`config/heroes.yaml`)

Coordinates are placeholders for 1080×1920 BlueStacks portrait; calibrate before live use.

- `adb.serial`
- `delays_ms`: after_tap, after_open, after_tab, after_skill
- `roster.cells`: 16 `{x,y}`
- `roster.page_swipe`: `{x1,y1,x2,y2,duration_ms}`
- `roster.max_pages`
- `nav.back`, `nav.stats_tab`, `nav.skills_tab`, `nav.stats_list_button`
- `skills.slots`: list of `{x,y}` (typically 6)
- `ocr`: named boxes `{x,y,w,h}` for name, power, rarity, escorts, stats_panel, skill_panel, …

## Error handling

- Missing ADB → exit 1 with clear message.
- Invalid config (≠16 cells, missing required boxes) → fail fast at load.
- OCR parse miss → field `null`, keep raw text in debug when `--save-screenshots`.
- Unknown screen after open → skip hero, tap back once, continue.
- Never use non-ADB input.

## Testing

- Unit: parsers (stats block, skill panel, power/escorts ints).
- Unit: config validation.
- Unit: store JSON + SQLite round-trip.
- Unit: collector with `FakeDevice` + stubbed OCR (sequence of images / text) — verifies tap order, paging stop, dedupe.
- Live ADB is manual smoke only (not CI).

## Out of scope

- Gear tab
- Template / vision icon detection
- Upgrading heroes or spending resources
- Discord integration
