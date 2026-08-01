# Heroes Collector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an ADB hero roster scraper that collects name, power, stats, skills, and extras into JSON + SQLite.

**Architecture:** Config-driven taps/OCR boxes in `ks/heroes/`; collector loops 4×4 pages; per-hero scrape opens stats via list button and walks skill slots; store writes both formats continuously.

**Tech Stack:** Python 3.12+, adbutils, OpenCV/NumPy, pytesseract, PyYAML, sqlite3, pytest.

## Global Constraints

- ADB-only taps/swipes/screencaps (workspace ADB-first rule).
- No Gear tab in v1.
- Fail fast on invalid config; skip individual hero OCR failures without aborting the run.
- Coordinates in sample YAML are 1080×1920 placeholders — must be calibratable.

---

### Task 1: Models + OCR parsers

**Files:**
- Create: `ks/heroes/__init__.py`
- Create: `ks/heroes/models.py`
- Create: `ks/heroes/parse.py`
- Test: `tests/test_heroes_parse.py`

**Interfaces:**
- Produces: `HeroRecord`, `HeroStats`, `SkillRecord` dataclasses; `parse_int`, `parse_power`, `parse_percent`, `parse_stats_panel`, `parse_skill_panel`

- [ ] **Step 1: Write failing tests**

```python
from ks.heroes.parse import parse_int, parse_power, parse_stats_panel, parse_skill_panel

def test_parse_power_strips_commas():
    assert parse_power("1,234,567") == 1_234_567

def test_parse_stats_panel_conquest_and_expedition():
    text = """
    Hero Stats
    Conquest
    Hero Attack 1,619
    Hero Defense 1,316
    Hero Health 14,679
    Escort Attack 539
    Escort Defense 438
    Escort Health 4,893
    Expedition
    Cavalry Attack +101.37%
    Cavalry Defense +101.37%
    Cavalry Lethality +49.43%
    Cavalry Health +16.95%
    """
    stats = parse_stats_panel(text)
    assert stats.conquest["Hero Attack"] == 1619
    assert stats.expedition["Cavalry Attack"] == 101.37

def test_parse_skill_panel():
    text = "Rally Flag Lv. 3\nJabel has a 24% chance...\nDamage Taken Chance Down: 8%/16%/24%/32%/40%"
    skill = parse_skill_panel(text, slot=0)
    assert skill.name == "Rally Flag"
    assert skill.level == 3
    assert "24%" in (skill.description or "")
```

- [ ] **Step 2: Run tests — expect FAIL (import error)**

Run: `python3 -m pytest tests/test_heroes_parse.py -v`

- [ ] **Step 3: Implement models + parse**

```python
# ks/heroes/models.py — frozen dataclasses HeroStats, SkillRecord, HeroRecord
# ks/heroes/parse.py — regex parsers as tested
```

- [ ] **Step 4: Run tests — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add ks/heroes tests/test_heroes_parse.py
git commit -m "feat(heroes): add models and OCR parsers"
```

---

### Task 2: Config loader

**Files:**
- Create: `ks/heroes/config.py`
- Create: `config/heroes.yaml`
- Test: `tests/test_heroes_config.py`

**Interfaces:**
- Consumes: YAML path
- Produces: `HeroesConfig` with `TapPoint`, `OcrBox`, `roster.cells` (len 16), nav taps, skill slots, delays, `load_heroes_config(path) -> HeroesConfig`

- [ ] **Step 1: Write failing validation tests**

```python
def test_load_heroes_config_requires_16_cells(tmp_path):
    # write YAML with 15 cells → ValueError
```

- [ ] **Step 2: Implement loader + sample `config/heroes.yaml` (placeholder coords)**

- [ ] **Step 3: Tests pass; commit**

```bash
git commit -m "feat(heroes): add YAML config loader and sample config"
```

---

### Task 3: JSON + SQLite store

**Files:**
- Create: `ks/heroes/store.py`
- Test: `tests/test_heroes_store.py`

**Interfaces:**
- Produces: `HeroStore(out_dir)` with `upsert(hero: HeroRecord)`, `flush()`, paths `heroes.json` / `heroes.db`

- [ ] **Step 1: Failing round-trip test (write HeroRecord → reload JSON + query SQLite)**

- [ ] **Step 2: Implement store**

- [ ] **Step 3: Pass + commit**

```bash
git commit -m "feat(heroes): persist heroes to JSON and SQLite"
```

---

### Task 4: Single-hero scrape

**Files:**
- Create: `ks/heroes/scrape.py`
- Test: `tests/test_heroes_scrape.py`

**Interfaces:**
- Consumes: device protocol, `HeroesConfig`, optional `ocr_fn(image, box) -> str`
- Produces: `scrape_hero(device, cfg, *, page, index, ocr_fn=...) -> HeroRecord | None`

Flow in code: screencap → OCR identity → open stats list → OCR stats → close → Skills tab → each skill slot → compare panel text to skip empties. Does **not** tap roster cell or back (caller owns entry/exit).

- [ ] **Step 1: Fake device + scripted OCR map tests verifying tap order (list open/close, skills tab, skill slots)**

- [ ] **Step 2: Implement scrape**

- [ ] **Step 3: Pass + commit**

```bash
git commit -m "feat(heroes): scrape one hero stats and skills"
```

---

### Task 5: Roster collector + paging

**Files:**
- Create: `ks/heroes/collector.py`
- Test: `tests/test_heroes_collector.py`

**Interfaces:**
- Produces: `collect_heroes(device, cfg, store, *, ocr_fn=...) -> list[HeroRecord]`

- [ ] **Step 1: Test two pages — page0 yields 2 heroes, page1 yields 0 new → stops; verify swipe called; dedupe by name**

- [ ] **Step 2: Implement collector**

- [ ] **Step 3: Pass + commit**

```bash
git commit -m "feat(heroes): collect full roster with paging and dedupe"
```

---

### Task 6: CLI entry point

**Files:**
- Create: `ks/heroes/cli.py`
- Modify: `pyproject.toml` — add `ks-heroes = "ks.heroes.cli:main"`
- Test: `tests/test_heroes_cli.py`

**Interfaces:**
- `ks-heroes collect --config config/heroes.yaml [--serial] [--out DIR] [--dry-run] [--save-screenshots]`

- [ ] **Step 1: CLI dry-run prints plan (16 cells, max_pages) without ADB**

- [ ] **Step 2: Wire live path to `AdbDevice.connect` + `collect_heroes`**

- [ ] **Step 3: Pass + commit**

```bash
git commit -m "feat(heroes): add ks-heroes CLI"
```

---

### Task 7: Spec already written — link from plan footer; final verification

- [ ] Run: `python3 -m pytest tests/test_heroes_*.py -v`
- [ ] Expected: all pass
- [ ] Commit any leftover docs: design already at `docs/superpowers/specs/2026-08-01-heroes-collector-design.md`

---

## Spec coverage check

| Spec requirement | Task |
|------------------|------|
| 4×4 + paging stop | 5 |
| Name/power under name | 4 |
| Stats list open/close | 4 |
| Skills all slots | 4 |
| Extras best-effort | 4 |
| JSON + SQLite | 3 |
| ADB-first | 4–6 |
| Config-driven | 2 |
| Skip empty name | 5 |
