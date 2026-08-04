# Stat Contributions Across Event Lineups & Optimisers — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split every hero's power and combat stats into hero / skills / gear shares for the event-correct family (conquest vs expedition), make every optimiser score from those shares, and surface them on the Event lineups cards and detail modal.

**Architecture:** Two new leaf modules own all estimation — `skill_effects.py` turns scraped skill text into family-tagged percent bonuses, `stat_contributions.py` composes hero + skills + gear into a `StatContribution` and exposes per-family strength scalars. Every scorer (`scoring`, `combat_formation`, `arena`, `conquest`, `front_survival`, `opponent_models`, `survival_pipeline`, `spend_xp`) drops its `effective_power` + `gear_bonus` heuristic pair and takes a `StatContribution` instead. `optimize_run.py` attaches `stat_family` / `formation_totals` / per-hero `contributions` to every section payload, and `optimize_events.html` renders them.

**Tech Stack:** Python 3.11+, dataclasses, `pulp` (CBC) ILP, PyYAML, pytest, FastAPI + Jinja2 templates, vanilla JS in the template.

## Global Constraints

- Branch / base worktree: `feature/stat-contributions-optimizers` at `/Users/alexei/KS/.worktrees/feature-stat-contributions-optimizers`. All task worktrees branch from it.
- Module layout follows `ks.<module>`; prefer small cohesive modules (repo convention).
- Test files mirror feature names: `tests/test_heroes_<area>.py`.
- No new runtime dependencies. `pulp`, `pyyaml` only.
- Run `pytest` from repo root with `.venv` active before claiming any task done.
- `estimated` is always `True` on every `StatContribution` produced by rule A — the in-game "from hero / from skills / from gear" popup scrape is explicitly out of scope.
- Conquest stat labels are exactly: `Hero Attack`, `Hero Defense`, `Hero Health`, `Escort Attack`, `Escort Defense`, `Escort Health`.
- Expedition stat labels are `<TroopPrefix> <Stat>` where TroopPrefix ∈ {`Infantry`, `Cavalry`, `Archer`} (note: **`Archer`**, singular — that is what gear OCR emits) and Stat ∈ {`Attack`, `Defense`, `Health`, `Lethality`}.
- Conquest shares are **flat ints/floats and sum**; expedition shares are **percent points and sum additively** (a formation rollup of `40.0` + `41.94` is `81.94`, meaning +81.94%).
- Invariant for every `Share`: `hero >= 0`, `skills >= 0`, `gear >= 0`, and `total == hero + skills + gear`.
- Tests assert wiring and invariants, never frozen pre-change score values.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `ks/heroes/optimize/skill_effects.py` | **New.** Parse scraped skill `upgrade_preview` labels → canonical effect kinds; sum `current_bonus` percents per kind; decide which kinds belong to which family, using catalog `applies_to` as source of truth. Nothing else knows how to read a skill. |
| `ks/heroes/optimize/stat_contributions.py` | **New.** `Share` / `StatContribution` types, event→family map, conquest + expedition label sets, rule-A estimator, formation rollup, per-family strength scalars. The only module that decides hero/skills/gear split. |
| `ks/heroes/optimize/scoring.py` | `hero_strength` takes a `StatContribution` instead of `effective_power` + `gear_bonus`. |
| `ks/heroes/optimize/model.py` | `solve_mode` builds expedition contributions per hero and feeds `hero_strength`. |
| `ks/heroes/optimize/recommend.py` | Builds contributions after final gear assignment; exposes `stat_family`, `formation_totals`, per-hero `contributions` on `RecommendResult`. |
| `ks/heroes/optimize/types.py` | `RecommendResult` gains `stat_family` / `formation_totals` / hero-row contributions in `to_dict`. |
| `ks/heroes/optimize/combat_formation.py` | `hero_base_score` takes a `StatContribution`; `_provisional_gear_bonus` → `_provisional_contributions`; result carries `contributions` + `formation_totals`. |
| `ks/heroes/optimize/arena.py`, `conquest.py` | Adapt `base_score_fn` protocol to `contribution=`; surface contributions in `to_dict`. |
| `ks/heroes/optimize/front_survival.py` | `hero_tau` / `formation_tau` read contribution-backed `Hero Health` / `Hero Defense` totals. |
| `ks/heroes/optimize/opponent_models.py` | Foe offense uses foe contributions instead of `_provisional_gear_bonus`. |
| `ks/heroes/optimize/survival_pipeline.py` | Threads contributions through `slot_utilities`, `roster_pressure_scale`, `evaluate_vs_foe`, `attach_survival`. |
| `ks/heroes/optimize/spend_xp.py` | `U(gear)` summaries carry `stat_family` + `formation_totals` rebuilt under candidate gear levels. |
| `ks/heroes/ui/optimize_run.py` | Bundle sections get `stat_family` + `formation_totals`; hero rows get `contributions`. |
| `ks/heroes/ui/templates/optimize_events.html` | Compact formation totals on cards; per-hero contribution table in the modal. |
| `tests/test_heroes_skill_effects.py` | **New.** Skill label parsing, percent summing, family filter. |
| `tests/test_heroes_stat_contributions.py` | **New.** Rule-A arithmetic, rollup, family map, strength scalars, edge cases. |
| `tests/test_heroes_optimize_contributions_wiring.py` | **New.** Integration: every optimiser path emits contributions and non-negative invariants hold. |

## Execution Waves (worktree parallelism)

| Wave | Tasks | Worktree(s) |
|------|-------|-------------|
| 0 (foundation, sequential) | 1, 2 | base worktree `feature-stat-contributions-optimizers` |
| 1 (parallel) | 3 (expedition path), 4 (conquest path) | `sc-expedition`, `sc-conquest` |
| 2 (parallel, after wave 1 merged) | 5 (survival), 6 (spend_xp) | `sc-survival`, `sc-spendxp` |
| 3 (parallel, after wave 2 merged) | 7 (API payload), 8 (UI) | `sc-api`, `sc-ui` |

Wave 3 tasks touch disjoint files and the JSON shape is frozen in Task 7's **Interfaces** block, so they are safe to run concurrently.

---

## Task 1: Skill effect extraction (`skill_effects.py`)

**Files:**
- Create: `ks/heroes/optimize/skill_effects.py`
- Test: `tests/test_heroes_skill_effects.py`

**Interfaces:**
- Consumes: `ks.heroes.models.HeroRecord`, `ks.heroes.optimize.types.CatalogEntry`, `ks.heroes.optimize.scoring.star_progress_factor`.
- Produces:
  - `CONQUEST: str = "conquest"`, `EXPEDITION: str = "expedition"`
  - `skill_kind(label: str | None) -> str | None`
  - `skill_percents(hero: HeroRecord) -> tuple[dict[str, float], bool]` → `(kind → summed percent, skills_incomplete)`
  - `catalog_percents(entry: CatalogEntry | None, stars: int | None, pellets: int | None) -> dict[str, float]`
  - `kind_family(kind: str, catalog: dict[str, CatalogEntry] | None = None) -> str | None`
  - `family_percents(hero, entry, *, family, catalog=None) -> tuple[dict[str, float], bool]`

- [ ] **Step 1: Write the failing test**

Create `tests/test_heroes_skill_effects.py`:

```python
import pytest

from ks.heroes.models import HeroRecord, SkillRecord
from ks.heroes.optimize.skill_effects import (
    CONQUEST,
    EXPEDITION,
    catalog_percents,
    family_percents,
    kind_family,
    skill_kind,
    skill_percents,
)
from ks.heroes.optimize.types import CatalogEntry, EffectTag


def _skill(slot: int, preview: str | None, bonus: float | None) -> SkillRecord:
    return SkillRecord(slot=slot, upgrade_preview=preview, current_bonus=bonus)


def test_skill_kind_maps_known_labels() -> None:
    assert skill_kind("Attack Up: 8%/12%/15%/20%/24%") == "attack_up"
    assert skill_kind("Damage Taken Chance Down: 8%/16%") == "damage_taken_down"
    assert skill_kind("Area of Effect Damage Up: 180%/198%") == "aoe_damage_up"
    assert skill_kind("Lethality Up:5%/10%/15%") == "lethality_up"


def test_skill_kind_ignores_economy_labels() -> None:
    assert skill_kind("Mill Income: 5%/10%/15%") is None
    assert skill_kind("Bread Gathering Speed: 5%/10%") is None
    assert skill_kind(None) is None
    assert skill_kind("") is None


def test_skill_percents_sums_per_kind_and_flags_missing() -> None:
    hero = HeroRecord(
        name="Forrest",
        skills=(
            _skill(2, "Attack Up: 8%/12%/15%/20%/24%", 16.0),
            _skill(3, "Lethality Up:5%/10%/15%/20%/25%", 15.0),
            _skill(1, "Defense Up: 25%/37.5%/50%", 50.0),
            _skill(5, "Damage Taken Down: 4%/8%/12%", 6.0),
        ),
    )
    percents, incomplete = skill_percents(hero)
    assert percents == {
        "attack_up": 16.0,
        "lethality_up": 15.0,
        "defense_up": 50.0,
        "damage_taken_down": 6.0,
    }
    assert incomplete is False


def test_skill_percents_flags_incomplete_when_bonus_missing() -> None:
    hero = HeroRecord(
        name="Quinn",
        skills=(
            _skill(0, "Damage Up: 400%/440%", None),
            _skill(2, "Attack Up: 8%/12%", 12.0),
        ),
    )
    percents, incomplete = skill_percents(hero)
    assert percents == {"attack_up": 12.0}
    assert incomplete is True


def test_skill_percents_flags_incomplete_when_no_skills() -> None:
    percents, incomplete = skill_percents(HeroRecord(name="Nobody"))
    assert percents == {}
    assert incomplete is True


def test_catalog_percents_scales_max_value_by_stars() -> None:
    entry = CatalogEntry(
        name="Amadeus",
        effects=(
            EffectTag("attack_up", 25.0, "expedition"),
            EffectTag("rally_attack", 15.0, "widget"),
        ),
    )
    full = catalog_percents(entry, 5, 0)
    assert full["attack_up"] == pytest.approx(25.0)
    assert "rally_attack" not in full
    half = catalog_percents(entry, 0, 0)
    assert half["attack_up"] < full["attack_up"]


def test_kind_family_uses_catalog_applies_to() -> None:
    catalog = {
        "A": CatalogEntry(name="A", effects=(EffectTag("attack_up", 25.0, "conquest"),)),
    }
    assert kind_family("attack_up", catalog) == CONQUEST
    assert kind_family("attack_up", None) == EXPEDITION


def test_kind_family_excludes_widget_only_kinds() -> None:
    catalog = {
        "A": CatalogEntry(name="A", effects=(EffectTag("rally_attack", 15.0, "widget"),)),
    }
    assert kind_family("rally_attack", catalog) is None


def test_family_percents_filters_to_requested_family() -> None:
    hero = HeroRecord(
        name="Forrest",
        stars=3,
        pellets=0,
        skills=(
            _skill(2, "Attack Up: 8%/12%", 16.0),
            _skill(0, "Area of Effect Damage Up: 55%/60%", 65.0),
        ),
    )
    entry = CatalogEntry(name="Forrest", effects=())
    exp, _ = family_percents(hero, entry, family=EXPEDITION)
    con, _ = family_percents(hero, entry, family=CONQUEST)
    assert exp == {"attack_up": 16.0}
    assert con == {"aoe_damage_up": 65.0}


def test_family_percents_falls_back_to_catalog_when_scrape_empty() -> None:
    hero = HeroRecord(name="Amadeus", stars=5, pellets=0, skills=())
    entry = CatalogEntry(
        name="Amadeus",
        effects=(EffectTag("attack_up", 25.0, "expedition"),),
    )
    percents, incomplete = family_percents(hero, entry, family=EXPEDITION)
    assert percents["attack_up"] == pytest.approx(25.0)
    assert incomplete is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_heroes_skill_effects.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ks.heroes.optimize.skill_effects'`

- [ ] **Step 3: Write the implementation**

Create `ks/heroes/optimize/skill_effects.py`:

```python
"""Turn scraped hero skills into family-tagged percent bonuses.

Scraped skills carry no machine-readable kind — only an ``upgrade_preview``
string such as ``"Attack Up: 8%/12%/15%/20%/24%"`` plus a ``current_bonus``
percent. This module is the single place that reads that text, so no scorer
has to guess what a skill does.

Family membership (conquest vs expedition) comes from the catalog's
``applies_to`` field when a kind appears there; kinds the catalog never
mentions fall back to ``_DEFAULT_KIND_FAMILY``. ``widget`` effects are march
/ rally buffs and belong to neither hero-stat family.
"""

from __future__ import annotations

from ks.heroes.models import HeroRecord
from ks.heroes.optimize.scoring import star_progress_factor
from ks.heroes.optimize.types import CatalogEntry

CONQUEST = "conquest"
EXPEDITION = "expedition"

# Skill preview label (lowercased, text before the first ":") → catalog kind.
# Labels absent here are economy/utility skills and contribute no combat stat.
_SKILL_LABEL_KINDS: dict[str, str] = {
    "attack up": "attack_up",
    "defense up": "defense_up",
    "health up": "health_up",
    "lethality up": "lethality_up",
    "damage taken down": "damage_taken_down",
    "damage taken chance down": "damage_taken_down",
    "enemy troops attack down": "opp_damage_down",
    "attack speed up": "attack_speed_up",
    "crit rate": "crit_rate_up",
    "damage up": "damage_up",
    "area of effect damage up": "aoe_damage_up",
    "2nd wave damage up": "damage_up",
    "heal up": "heal_up",
}

# Fallback family for kinds the catalog never tags with applies_to.
_DEFAULT_KIND_FAMILY: dict[str, str] = {
    "attack_up": EXPEDITION,
    "defense_up": EXPEDITION,
    "health_up": EXPEDITION,
    "lethality_up": EXPEDITION,
    "damage_taken_down": EXPEDITION,
    "opp_damage_down": EXPEDITION,
    "damage_up": CONQUEST,
    "aoe_damage_up": CONQUEST,
    "heal_up": CONQUEST,
    "attack_speed_up": CONQUEST,
    "crit_rate_up": CONQUEST,
    "defender_attack": CONQUEST,
    "defender_defense": CONQUEST,
    "defender_health": CONQUEST,
}

_WIDGET = "widget"


def skill_kind(label: str | None) -> str | None:
    """Canonical effect kind for a skill ``upgrade_preview`` line, or None."""
    if not label:
        return None
    head = label.split(":", 1)[0].strip().lower()
    if not head:
        return None
    return _SKILL_LABEL_KINDS.get(head)


def skill_percents(hero: HeroRecord) -> tuple[dict[str, float], bool]:
    """Sum scraped ``current_bonus`` per kind.

    Returns ``(kind → percent, skills_incomplete)``. ``skills_incomplete`` is
    True when the hero has no skills at all, or when any skill is missing its
    ``current_bonus`` (the split for that skill is unknowable from the scrape).
    """
    if not hero.skills:
        return {}, True
    out: dict[str, float] = {}
    incomplete = False
    for skill in hero.skills:
        kind = skill_kind(skill.upgrade_preview)
        if skill.current_bonus is None:
            incomplete = True
            continue
        if kind is None:
            continue
        out[kind] = out.get(kind, 0.0) + float(skill.current_bonus)
    return out, incomplete


def catalog_percents(
    entry: CatalogEntry | None,
    stars: int | None,
    pellets: int | None = None,
) -> dict[str, float]:
    """Star-scaled percent per kind from catalog effects (widget kinds dropped)."""
    if entry is None:
        return {}
    factor = star_progress_factor(stars, pellets)
    out: dict[str, float] = {}
    for tag in entry.effects:
        if tag.applies_to == _WIDGET:
            continue
        out[tag.kind] = out.get(tag.kind, 0.0) + float(tag.max_value) * factor
    return out


def kind_family(
    kind: str,
    catalog: dict[str, CatalogEntry] | None = None,
) -> str | None:
    """Family a kind contributes to, or None when it is widget-only/unknown.

    Catalog ``applies_to`` wins: if any catalog entry tags ``kind`` as
    conquest or expedition, that is the family. A kind the catalog only ever
    tags as ``widget`` returns None. Otherwise fall back to the default map.
    """
    if catalog:
        seen: set[str] = set()
        for entry in catalog.values():
            for tag in entry.effects:
                if tag.kind == kind:
                    seen.add(tag.applies_to)
        if CONQUEST in seen:
            return CONQUEST
        if EXPEDITION in seen:
            return EXPEDITION
        if seen == {_WIDGET}:
            return None
    return _DEFAULT_KIND_FAMILY.get(kind)


def family_percents(
    hero: HeroRecord,
    entry: CatalogEntry | None,
    *,
    family: str,
    catalog: dict[str, CatalogEntry] | None = None,
) -> tuple[dict[str, float], bool]:
    """Percents for ``family`` from the scrape, falling back to the catalog.

    Scraped ``current_bonus`` is preferred because it reflects the hero's
    actual skill levels. When the scrape yields nothing for a kind the catalog
    knows about, the star-scaled catalog value fills in and the result is
    flagged incomplete.
    """
    if family not in (CONQUEST, EXPEDITION):
        raise ValueError(f"unknown family {family!r}; want conquest|expedition")
    scraped, incomplete = skill_percents(hero)
    fallback = catalog_percents(entry, hero.stars, hero.pellets)
    merged: dict[str, float] = {}
    for kind, value in scraped.items():
        if kind_family(kind, catalog) == family:
            merged[kind] = value
    for kind, value in fallback.items():
        if kind in merged:
            continue
        if kind_family(kind, catalog) != family:
            continue
        merged[kind] = value
        incomplete = True
    return merged, incomplete
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_heroes_skill_effects.py -v`
Expected: PASS — 9 passed

- [ ] **Step 5: Commit**

```bash
git add ks/heroes/optimize/skill_effects.py tests/test_heroes_skill_effects.py
git commit -m "feat(heroes): parse scraped skills into family-tagged percents"
```

---

## Task 2: Contribution estimator (`stat_contributions.py`)

**Files:**
- Create: `ks/heroes/optimize/stat_contributions.py`
- Test: `tests/test_heroes_stat_contributions.py`

**Interfaces:**
- Consumes: `skill_effects.family_percents`, `gear_stats.expedition_stat_fraction`, `gear_assign.infer_slot`, `scoring.normalize_troop`.
- Produces:
  - `CONQUEST`, `EXPEDITION` (re-exported), `EVENT_FAMILY: dict[str, str]`, `family_for_event(event: str | None) -> str`
  - `CONQUEST_LABELS: tuple[str, ...]`, `EXPEDITION_STATS: tuple[str, ...]`, `expedition_labels(troop: str | None) -> tuple[str, ...]`
  - `Share(hero: float, skills: float, gear: float)` with `.total` property and `.to_dict()`
  - `StatContribution(family, estimated, skills_incomplete, power: Share, stats: dict[str, Share])` with `.to_dict()`
  - `hero_contribution(hero, entry, *, family, gear_pieces=None, power=None, catalog=None) -> StatContribution`
  - `formation_contribution(contributions: Sequence[StatContribution]) -> StatContribution`
  - `contribution_strength(contribution: StatContribution) -> float`
  - `EMPTY_CONTRIBUTION_FN` is **not** provided — callers that have no hero must build a `StatContribution` explicitly.

- [ ] **Step 1: Write the failing test**

Create `tests/test_heroes_stat_contributions.py`:

```python
import pytest

from ks.heroes.gear_models import GearRecord, GearStats
from ks.heroes.models import HeroRecord, HeroStats, SkillRecord
from ks.heroes.optimize.stat_contributions import (
    CONQUEST,
    CONQUEST_LABELS,
    EXPEDITION,
    Share,
    StatContribution,
    contribution_strength,
    expedition_labels,
    family_for_event,
    formation_contribution,
    hero_contribution,
)
from ks.heroes.optimize.types import CatalogEntry


def _hero(**kw) -> HeroRecord:
    base = dict(
        name="Forrest",
        power=217855,
        troop_type="infantry",
        stars=3,
        pellets=0,
        stats=HeroStats(
            conquest={
                "Hero Attack": 1297,
                "Hero Defense": 1324,
                "Hero Health": 11889,
                "Escort Attack": 432,
                "Escort Defense": 441,
                "Escort Health": 3963,
            }
        ),
        skills=(
            SkillRecord(slot=2, upgrade_preview="Attack Up: 8%/12%", current_bonus=16.0),
            SkillRecord(slot=1, upgrade_preview="Defense Up: 25%/50%", current_bonus=50.0),
            SkillRecord(
                slot=3, upgrade_preview="Lethality Up:5%/10%", current_bonus=15.0
            ),
        ),
    )
    base.update(kw)
    return HeroRecord(**base)


def _piece(**kw) -> GearRecord:
    base = dict(
        piece_id="p1",
        name="Judicator's Armet",
        troop_type="infantry",
        slot="helmet",
        rarity="mythic",
        enhancement_level=57,
        power=134807,
        stats=GearStats(
            conquest={"Hero Attack": 385, "Hero Health": 1926},
            expedition={"Infantry Lethality": 41.94},
            lethality=41.94,
        ),
    )
    base.update(kw)
    return GearRecord(**base)


def test_family_for_event_maps_all_four_screens() -> None:
    assert family_for_event("arena") == CONQUEST
    assert family_for_event("conquest") == CONQUEST
    assert family_for_event("swordland") == EXPEDITION
    assert family_for_event("beartrap") == EXPEDITION


def test_family_for_event_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="unknown event"):
        family_for_event("hall_of_chiefs")


def test_share_total_is_sum_of_parts() -> None:
    share = Share(hero=10.0, skills=2.0, gear=3.0)
    assert share.total == pytest.approx(15.0)
    assert share.to_dict() == {
        "hero": 10.0,
        "skills": 2.0,
        "gear": 3.0,
        "total": 15.0,
    }


def test_expedition_labels_use_singular_archer_prefix() -> None:
    assert expedition_labels("archers") == (
        "Archer Attack",
        "Archer Defense",
        "Archer Health",
        "Archer Lethality",
    )
    assert expedition_labels("infantry")[0] == "Infantry Attack"


def test_conquest_split_backs_skills_out_of_naked_value() -> None:
    hero = _hero()
    entry = CatalogEntry(name="Forrest", troop="infantry")
    c = hero_contribution(hero, entry, family=CONQUEST)
    attack = c.stats["Hero Attack"]
    # 16% attack skills → skills share is naked * 0.16 / 1.16.
    assert attack.skills == pytest.approx(1297 * 0.16 / 1.16)
    assert attack.hero == pytest.approx(1297 - attack.skills)
    assert attack.gear == 0.0
    assert attack.total == pytest.approx(1297.0)


def test_conquest_split_adds_gear_flats_on_top() -> None:
    hero = _hero()
    entry = CatalogEntry(name="Forrest", troop="infantry")
    c = hero_contribution(hero, entry, family=CONQUEST, gear_pieces=[_piece()])
    attack = c.stats["Hero Attack"]
    assert attack.gear == pytest.approx(385.0)
    assert attack.total == pytest.approx(1297.0 + 385.0)
    assert c.power.gear == pytest.approx(134807.0)
    assert c.power.hero == pytest.approx(217855.0)
    assert c.power.skills == 0.0


def test_every_conquest_label_present_even_when_scrape_missing() -> None:
    hero = _hero(stats=HeroStats(conquest={}))
    c = hero_contribution(hero, None, family=CONQUEST)
    assert tuple(c.stats) == CONQUEST_LABELS
    assert all(s.total == 0.0 for s in c.stats.values())


def test_expedition_split_uses_percent_points() -> None:
    hero = _hero()
    entry = CatalogEntry(name="Forrest", troop="infantry")
    c = hero_contribution(hero, entry, family=EXPEDITION, gear_pieces=[_piece()])
    assert c.stats["Infantry Attack"].skills == pytest.approx(16.0)
    assert c.stats["Infantry Defense"].skills == pytest.approx(50.0)
    assert c.stats["Infantry Lethality"].skills == pytest.approx(15.0)
    assert c.stats["Infantry Lethality"].gear == pytest.approx(41.94)
    assert c.stats["Infantry Attack"].hero == 0.0


def test_expedition_gear_falls_back_to_formula_when_ocr_missing() -> None:
    piece = _piece(stats=GearStats(conquest={}, expedition={}), slot="chest")
    hero = _hero()
    c = hero_contribution(
        hero, None, family=EXPEDITION, gear_pieces=[piece]
    )
    # chest → Health; mythic +57 formula fraction, expressed as percent points.
    assert c.stats["Infantry Health"].gear > 0.0


def test_shares_are_never_negative() -> None:
    hero = _hero(
        stats=HeroStats(conquest={"Hero Attack": 10}),
        skills=(
            SkillRecord(slot=0, upgrade_preview="Attack Up: 900%", current_bonus=900.0),
        ),
    )
    c = hero_contribution(hero, None, family=CONQUEST)
    attack = c.stats["Hero Attack"]
    assert attack.hero >= 0.0
    assert attack.skills >= 0.0
    assert attack.total == pytest.approx(10.0)


def test_skills_incomplete_flag_propagates() -> None:
    hero = _hero(skills=())
    c = hero_contribution(hero, None, family=CONQUEST)
    assert c.skills_incomplete is True
    assert c.estimated is True
    assert c.power.skills == 0.0
    assert c.power.hero == pytest.approx(217855.0)


def test_power_override_replaces_scraped_power() -> None:
    hero = _hero()
    c = hero_contribution(hero, None, family=CONQUEST, power=99_000)
    assert c.power.hero == pytest.approx(99_000.0)


def test_formation_contribution_sums_matching_labels() -> None:
    a = StatContribution(
        family=EXPEDITION,
        estimated=True,
        skills_incomplete=False,
        power=Share(1.0, 0.0, 2.0),
        stats={"Infantry Lethality": Share(0.0, 15.0, 41.94)},
    )
    b = StatContribution(
        family=EXPEDITION,
        estimated=True,
        skills_incomplete=True,
        power=Share(3.0, 0.0, 4.0),
        stats={
            "Infantry Lethality": Share(0.0, 10.0, 20.0),
            "Archer Health": Share(0.0, 5.0, 0.0),
        },
    )
    total = formation_contribution([a, b])
    assert total.power.hero == pytest.approx(4.0)
    assert total.power.gear == pytest.approx(6.0)
    assert total.stats["Infantry Lethality"].skills == pytest.approx(25.0)
    assert total.stats["Infantry Lethality"].gear == pytest.approx(61.94)
    assert total.stats["Archer Health"].skills == pytest.approx(5.0)
    assert total.skills_incomplete is True


def test_formation_contribution_rejects_mixed_families() -> None:
    a = StatContribution(CONQUEST, True, False, Share(0, 0, 0), {})
    b = StatContribution(EXPEDITION, True, False, Share(0, 0, 0), {})
    with pytest.raises(ValueError, match="same family"):
        formation_contribution([a, b])


def test_formation_contribution_of_empty_sequence_raises() -> None:
    with pytest.raises(ValueError, match="at least one"):
        formation_contribution([])


def test_contribution_strength_rises_with_gear() -> None:
    hero = _hero()
    bare = hero_contribution(hero, None, family=CONQUEST)
    geared = hero_contribution(hero, None, family=CONQUEST, gear_pieces=[_piece()])
    assert contribution_strength(geared) > contribution_strength(bare)


def test_contribution_strength_rises_with_expedition_percent() -> None:
    hero = _hero()
    bare = hero_contribution(hero, None, family=EXPEDITION)
    geared = hero_contribution(hero, None, family=EXPEDITION, gear_pieces=[_piece()])
    assert contribution_strength(geared) > contribution_strength(bare)


def test_to_dict_shape_matches_api_contract() -> None:
    c = hero_contribution(_hero(), None, family=CONQUEST)
    payload = c.to_dict()
    assert payload["family"] == CONQUEST
    assert payload["estimated"] is True
    assert set(payload["power"]) == {"hero", "skills", "gear", "total"}
    assert set(payload) == {
        "family",
        "estimated",
        "skills_incomplete",
        "power",
        "stats",
    }
    assert set(payload["stats"]["Hero Attack"]) == {
        "hero",
        "skills",
        "gear",
        "total",
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_heroes_stat_contributions.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ks.heroes.optimize.stat_contributions'`

- [ ] **Step 3: Write the implementation**

Create `ks/heroes/optimize/stat_contributions.py`:

```python
"""Per-hero power/stat split into hero / skills / gear shares (estimate A).

This module is the only place that decides how much of a hero's strength came
from the hero itself, from skills, and from gear. Every optimiser reads
``StatContribution`` totals instead of raw ``hero.power`` plus an ad-hoc gear
heuristic.

Estimation rule A (see the design doc):

1. **Skills** — family-filtered percents from the scrape (falling back to the
   catalog). Conquest is a *multiplicative* buff on the flat scraped stat, so
   the skills share of a naked value ``v`` under a total percent ``p`` is
   ``v * p / (1 + p)`` — which is always in ``[0, v)``, so the hero share can
   never go negative. Expedition percents are additive percent points.
2. **Hero** — naked scraped value minus the skills share.
3. **Gear** — summed from the assigned pieces: conquest flats from OCR,
   expedition percents from OCR when present, otherwise the calibrated
   ``expedition_stat_fraction`` formula, plus piece power.
4. **Total** — hero + skills + gear.

Skill power share is not estimable from any scraped field, so power is always
reported as ``hero = naked``, ``skills = 0``, and the result is flagged via
``skills_incomplete`` when the skill scrape is partial.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from ks.heroes.gear_models import GearRecord
from ks.heroes.models import HeroRecord
from ks.heroes.optimize.gear_assign import infer_slot
from ks.heroes.optimize.gear_stats import expedition_stat_fraction
from ks.heroes.optimize.scoring import normalize_troop
from ks.heroes.optimize.skill_effects import CONQUEST, EXPEDITION, family_percents
from ks.heroes.optimize.types import CatalogEntry

__all__ = [
    "CONQUEST",
    "EXPEDITION",
    "CONQUEST_LABELS",
    "EXPEDITION_STATS",
    "EVENT_FAMILY",
    "Share",
    "StatContribution",
    "contribution_strength",
    "expedition_labels",
    "family_for_event",
    "formation_contribution",
    "hero_contribution",
]

# Event key → stat family. Lives here so no scorer re-invents the mapping.
EVENT_FAMILY: dict[str, str] = {
    "arena": CONQUEST,
    "arena_attack": CONQUEST,
    "arena_defense": CONQUEST,
    "conquest": CONQUEST,
    "sword": EXPEDITION,
    "swordland": EXPEDITION,
    "bear": EXPEDITION,
    "beartrap": EXPEDITION,
    "bear_trap": EXPEDITION,
}

CONQUEST_LABELS: tuple[str, ...] = (
    "Hero Attack",
    "Hero Defense",
    "Hero Health",
    "Escort Attack",
    "Escort Defense",
    "Escort Health",
)

EXPEDITION_STATS: tuple[str, ...] = ("Attack", "Defense", "Health", "Lethality")

# Gear OCR emits the singular "Archer" prefix for archers pieces.
_TROOP_PREFIX: dict[str, str] = {
    "infantry": "Infantry",
    "cavalry": "Cavalry",
    "archers": "Archer",
}

# Conquest: a percent kind lifts these flat labels.
_CONQUEST_KIND_LABELS: dict[str, tuple[str, ...]] = {
    "attack_up": ("Hero Attack", "Escort Attack"),
    "damage_up": ("Hero Attack", "Escort Attack"),
    "aoe_damage_up": ("Hero Attack", "Escort Attack"),
    "crit_rate_up": ("Hero Attack",),
    "attack_speed_up": ("Hero Attack",),
    "defender_attack": ("Hero Attack", "Escort Attack"),
    "defense_up": ("Hero Defense", "Escort Defense"),
    "damage_taken_down": ("Hero Defense", "Escort Defense"),
    "opp_damage_down": ("Hero Defense", "Escort Defense"),
    "defender_defense": ("Hero Defense", "Escort Defense"),
    "health_up": ("Hero Health", "Escort Health"),
    "heal_up": ("Hero Health", "Escort Health"),
    "defender_health": ("Hero Health", "Escort Health"),
}

# Expedition: a percent kind adds to these troop stats.
_EXPEDITION_KIND_STATS: dict[str, tuple[str, ...]] = {
    "attack_up": ("Attack",),
    "damage_up": ("Attack",),
    "defense_up": ("Defense",),
    "damage_taken_down": ("Defense",),
    "opp_damage_down": ("Defense",),
    "health_up": ("Health",),
    "lethality_up": ("Lethality",),
}

# Gear slot → the expedition stat the formula fraction represents.
_SLOT_EXPEDITION_STAT: dict[str, str] = {
    "helmet": "Lethality",
    "boots": "Lethality",
    "chest": "Health",
    "gloves": "Health",
}

# contribution_strength normalizers — chosen so power, flat conquest stats and
# expedition percents land in comparable magnitudes for the ILP objective.
_POWER_SCALE = 1_000_000.0
_CONQUEST_COMBAT_SCALE = 10_000.0
_CONQUEST_HEALTH_SCALE = 100_000.0
_EXPEDITION_PERCENT_SCALE = 100.0


@dataclass(frozen=True)
class Share:
    """One stat's split. ``total`` is always the sum of the three parts."""

    hero: float = 0.0
    skills: float = 0.0
    gear: float = 0.0

    @property
    def total(self) -> float:
        return self.hero + self.skills + self.gear

    def to_dict(self) -> dict[str, float]:
        return {
            "hero": self.hero,
            "skills": self.skills,
            "gear": self.gear,
            "total": self.total,
        }


@dataclass(frozen=True)
class StatContribution:
    """One hero's (or one formation's) power + stat split for a family."""

    family: str
    estimated: bool
    skills_incomplete: bool
    power: Share
    stats: dict[str, Share] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "estimated": self.estimated,
            "skills_incomplete": self.skills_incomplete,
            "power": self.power.to_dict(),
            "stats": {k: v.to_dict() for k, v in self.stats.items()},
        }


def family_for_event(event: str | None) -> str:
    """Stat family for an event key (``arena``/``conquest``/``swordland``/…)."""
    key = (event or "").strip().lower().replace(" ", "_")
    family = EVENT_FAMILY.get(key)
    if family is None:
        raise ValueError(
            f"unknown event {event!r}; have {sorted(EVENT_FAMILY)}"
        )
    return family


def expedition_labels(troop: str | None) -> tuple[str, ...]:
    """Expedition stat labels for a hero's troop class."""
    key = normalize_troop(troop) or "infantry"
    prefix = _TROOP_PREFIX.get(key, key.title())
    return tuple(f"{prefix} {stat}" for stat in EXPEDITION_STATS)


def _hero_troop(hero: HeroRecord, entry: CatalogEntry | None) -> str:
    if entry is not None:
        troop = normalize_troop(entry.troop)
        if troop:
            return troop
    return normalize_troop(hero.troop_type) or "infantry"


def _conquest_stats(
    hero: HeroRecord,
    percents: Mapping[str, float],
    gear_pieces: Sequence[GearRecord],
) -> dict[str, Share]:
    naked = dict((hero.stats.conquest if hero.stats else None) or {})
    by_label: dict[str, float] = {label: 0.0 for label in CONQUEST_LABELS}
    for kind, percent in percents.items():
        for label in _CONQUEST_KIND_LABELS.get(kind, ()):
            by_label[label] = by_label.get(label, 0.0) + float(percent) / 100.0

    gear_by_label: dict[str, float] = {label: 0.0 for label in CONQUEST_LABELS}
    for piece in gear_pieces:
        flats = (piece.stats.conquest if piece.stats else None) or {}
        for label, value in flats.items():
            gear_by_label[label] = gear_by_label.get(label, 0.0) + float(value)

    out: dict[str, Share] = {}
    for label in CONQUEST_LABELS:
        base = float(naked.get(label) or 0.0)
        p = max(0.0, by_label.get(label, 0.0))
        skills = base * p / (1.0 + p) if base > 0 else 0.0
        out[label] = Share(
            hero=base - skills,
            skills=skills,
            gear=gear_by_label.get(label, 0.0),
        )
    return out


def _gear_expedition_percent(piece: GearRecord, labels: tuple[str, ...]) -> dict[str, float]:
    """Percent points this piece adds, keyed by expedition label."""
    out: dict[str, float] = {}
    stats = piece.stats
    if stats is not None and stats.expedition:
        for label, value in stats.expedition.items():
            if label in labels:
                out[label] = out.get(label, 0.0) + float(value)
    if out:
        return out
    slot = infer_slot(piece)
    stat = _SLOT_EXPEDITION_STAT.get(slot or "")
    if stat is None:
        return out
    frac = expedition_stat_fraction(
        piece.rarity, piece.enhancement_level, piece.mastery_level
    )
    if frac is None or frac <= 0:
        return out
    label = next((lb for lb in labels if lb.endswith(f" {stat}")), None)
    if label is None:
        return out
    out[label] = float(frac) * 100.0
    return out


def _expedition_stats(
    hero: HeroRecord,
    troop: str,
    percents: Mapping[str, float],
    gear_pieces: Sequence[GearRecord],
) -> dict[str, Share]:
    labels = expedition_labels(troop)
    scraped = dict((hero.stats.expedition if hero.stats else None) or {})
    hero_by_label = {lb: float(scraped.get(lb) or 0.0) for lb in labels}

    skills_by_label: dict[str, float] = {lb: 0.0 for lb in labels}
    by_stat: dict[str, float] = {}
    for kind, percent in percents.items():
        for stat in _EXPEDITION_KIND_STATS.get(kind, ()):
            by_stat[stat] = by_stat.get(stat, 0.0) + float(percent)
    for stat, value in by_stat.items():
        label = next((lb for lb in labels if lb.endswith(f" {stat}")), None)
        if label is not None:
            skills_by_label[label] = value

    gear_by_label: dict[str, float] = {lb: 0.0 for lb in labels}
    for piece in gear_pieces:
        for label, value in _gear_expedition_percent(piece, labels).items():
            gear_by_label[label] = gear_by_label.get(label, 0.0) + value

    return {
        lb: Share(
            hero=max(0.0, hero_by_label[lb]),
            skills=max(0.0, skills_by_label[lb]),
            gear=max(0.0, gear_by_label[lb]),
        )
        for lb in labels
    }


def hero_contribution(
    hero: HeroRecord,
    entry: CatalogEntry | None,
    *,
    family: str,
    gear_pieces: Sequence[GearRecord] | Mapping[str, GearRecord] | None = None,
    power: int | float | None = None,
    catalog: dict[str, CatalogEntry] | None = None,
) -> StatContribution:
    """Split one hero's power + family stats into hero / skills / gear shares.

    ``gear_pieces`` accepts either the slot→piece mapping produced by
    ``assign_exclusive_sets`` or a plain sequence of pieces. ``power``
    overrides the scraped value (callers pass sanitized power).
    """
    if family not in (CONQUEST, EXPEDITION):
        raise ValueError(f"unknown family {family!r}; want conquest|expedition")
    if isinstance(gear_pieces, Mapping):
        pieces: list[GearRecord] = list(gear_pieces.values())
    else:
        pieces = list(gear_pieces or ())

    percents, incomplete = family_percents(
        hero, entry, family=family, catalog=catalog
    )
    if family == CONQUEST:
        stats = _conquest_stats(hero, percents, pieces)
    else:
        stats = _expedition_stats(
            hero, _hero_troop(hero, entry), percents, pieces
        )

    naked_power = float(power if power is not None else (hero.power or 0))
    gear_power = float(sum(float(p.power or 0) for p in pieces))
    return StatContribution(
        family=family,
        estimated=True,
        skills_incomplete=incomplete,
        power=Share(hero=max(0.0, naked_power), skills=0.0, gear=gear_power),
        stats=stats,
    )


def formation_contribution(
    contributions: Sequence[StatContribution],
) -> StatContribution:
    """Sum contributions across a lineup; matching stat labels add together."""
    items = list(contributions)
    if not items:
        raise ValueError("formation_contribution needs at least one contribution")
    families = {c.family for c in items}
    if len(families) > 1:
        raise ValueError(
            f"all contributions must share the same family; got {sorted(families)}"
        )
    power = Share(
        hero=sum(c.power.hero for c in items),
        skills=sum(c.power.skills for c in items),
        gear=sum(c.power.gear for c in items),
    )
    stats: dict[str, Share] = {}
    for c in items:
        for label, share in c.stats.items():
            prev = stats.get(label, Share())
            stats[label] = Share(
                hero=prev.hero + share.hero,
                skills=prev.skills + share.skills,
                gear=prev.gear + share.gear,
            )
    return StatContribution(
        family=items[0].family,
        estimated=any(c.estimated for c in items),
        skills_incomplete=any(c.skills_incomplete for c in items),
        power=power,
        stats=stats,
    )


def contribution_strength(contribution: StatContribution) -> float:
    """Single scalar strength signal for ILP objectives.

    Conquest: power in millions + (attack + defense) / 10k + health / 100k.
    Expedition: power in millions + summed percent points / 100.

    The scales are calibration constants, not game formulas — they exist so
    power and stats land in the same order of magnitude in the objective.
    """
    power_term = contribution.power.total / _POWER_SCALE
    if contribution.family == CONQUEST:
        def _t(label: str) -> float:
            share = contribution.stats.get(label)
            return share.total if share else 0.0

        combat = (
            _t("Hero Attack")
            + _t("Escort Attack")
            + _t("Hero Defense")
            + _t("Escort Defense")
        )
        health = _t("Hero Health") + _t("Escort Health")
        return (
            power_term
            + combat / _CONQUEST_COMBAT_SCALE
            + health / _CONQUEST_HEALTH_SCALE
        )
    percent = sum(share.total for share in contribution.stats.values())
    return power_term + percent / _EXPEDITION_PERCENT_SCALE
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_heroes_stat_contributions.py -v`
Expected: PASS — 18 passed

- [ ] **Step 5: Run the existing suite to confirm nothing regressed**

Run: `pytest -q`
Expected: PASS — same counts as before Task 1 (the two new modules are not yet imported by any scorer).

- [ ] **Step 6: Commit**

```bash
git add ks/heroes/optimize/stat_contributions.py tests/test_heroes_stat_contributions.py
git commit -m "feat(heroes): add hero/skills/gear stat contribution estimator"
```

---

## Task 3: Expedition scoring path (`scoring`, `model`, `recommend`, `types`)

**Worktree:** `sc-expedition` — runs in parallel with Task 4.

**Files:**
- Modify: `ks/heroes/optimize/scoring.py:66-110` (`hero_strength`)
- Modify: `ks/heroes/optimize/model.py:52-69` (strength build in `solve_mode`)
- Modify: `ks/heroes/optimize/explain.py:175-290` (`leave_one_out_mode`, `explain_selected_heroes`)
- Modify: `ks/heroes/optimize/recommend.py:44-150`
- Modify: `ks/heroes/optimize/types.py:127-169` (`ModeSolution`, `RecommendResult`)
- Test: `tests/test_heroes_optimize_scoring.py` (update), `tests/test_heroes_optimize_recommend.py` (update), `tests/test_heroes_optimize_explain.py` (run only)

**Interfaces:**
- Consumes: `stat_contributions.hero_contribution`, `formation_contribution`, `contribution_strength`, `family_for_event`, `EXPEDITION`.
- Produces:
  - `hero_strength(hero, entry, mode, *, event=None, contribution=None) -> float` — the `effective_power` and `gear_bonus` keywords are **removed**.
  - `RecommendResult` gains fields `stat_family: str = "expedition"`, `formation_totals: dict[str, Any] | None = None`; each row in `RecommendResult.heroes` gains a `"contributions"` key.
  - `RecommendResult.to_dict()` emits `stat_family` and `formation_totals` at the top level.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_heroes_optimize_scoring.py`:

```python
from ks.heroes.optimize.stat_contributions import (
    EXPEDITION,
    Share,
    StatContribution,
    hero_contribution,
)


def _contribution(power: float, lethality: float = 0.0) -> StatContribution:
    return StatContribution(
        family=EXPEDITION,
        estimated=True,
        skills_incomplete=False,
        power=Share(hero=power, skills=0.0, gear=0.0),
        stats={"Infantry Lethality": Share(0.0, 0.0, lethality)},
    )


def test_hero_strength_uses_contribution_power() -> None:
    entry = _entry("Zoe", "defense")
    hero = HeroRecord(name="Zoe", stars=3, power=100_000)
    low = hero_strength(hero, entry, "solo", contribution=_contribution(100_000))
    high = hero_strength(hero, entry, "solo", contribution=_contribution(900_000))
    assert high > low


def test_hero_strength_uses_contribution_gear_percent() -> None:
    entry = _entry("Zoe", "defense")
    hero = HeroRecord(name="Zoe", stars=3, power=100_000)
    bare = hero_strength(hero, entry, "solo", contribution=_contribution(100_000))
    geared = hero_strength(
        hero, entry, "solo", contribution=_contribution(100_000, lethality=40.0)
    )
    assert geared > bare


def test_hero_strength_without_contribution_ignores_power_term() -> None:
    entry = _entry("Zoe", "defense")
    hero = HeroRecord(name="Zoe", stars=3, power=100_000)
    assert hero_strength(hero, entry, "solo") == hero_strength(
        hero, entry, "solo", contribution=None
    )


def test_hero_strength_rejects_wrong_family() -> None:
    entry = _entry("Zoe", "defense")
    hero = HeroRecord(name="Zoe", stars=3)
    conquest = StatContribution(
        family="conquest",
        estimated=True,
        skills_incomplete=False,
        power=Share(1.0, 0.0, 0.0),
        stats={},
    )
    with pytest.raises(ValueError, match="expedition"):
        hero_strength(hero, entry, "solo", contribution=conquest)
```

Append to `tests/test_heroes_optimize_recommend.py` (the file already defines `_hero` and `_cat`; add the imports and helper below):

```python
import pytest

from ks.heroes.gear_models import GearRecord, GearStats


def _piece(pid: str, troop: str, slot: str, lethality: float) -> GearRecord:
    return GearRecord(
        piece_id=pid,
        name=f"{troop} {slot}",
        troop_type=troop,
        slot=slot,
        rarity="mythic",
        enhancement_level=40,
        power=50_000,
        stats=GearStats(
            conquest={"Hero Attack": 300},
            expedition={f"{'Archer' if troop == 'archers' else troop.title()} Lethality": lethality},
            lethality=lethality,
        ),
    )


def _run_recommend():
    heroes = [_hero("Zoe"), _hero("Saul"), _hero("Howard"), _hero("Amadeus")]
    catalog = {
        "Zoe": _cat("Zoe", "infantry", "defense", "defender_attack", 30),
        "Saul": _cat("Saul", "archer", "defense", "defense_up", 20),
        "Howard": _cat("Howard", "cavalry", "none", "damage_taken_down", 20),
        "Amadeus": _cat("Amadeus", "infantry", "attack", "rally_attack", 30),
    }
    troops = TroopsConfig(infantry=80, cavalry=40, archers=40, march_capacity=150)
    scenarios = {
        "garrison": Scenario(
            mode="garrison",
            combat_rate=40,
            minutes_held=50,
            personal_rate=600,
            require_widget="defense",
            enemy_power_scale=50000,
            formation_weights={"infantry": 1.0, "cavalry": 1.0, "archers": 1.0},
        ),
    }
    gear = [
        _piece("i1", "infantry", "helmet", 30.0),
        _piece("c1", "cavalry", "helmet", 25.0),
        _piece("a1", "archers", "helmet", 28.0),
    ]
    return recommend(
        heroes, catalog, troops, scenarios, force_mode="garrison", gear=gear
    )


def test_recommend_result_carries_expedition_contributions() -> None:
    payload = _run_recommend().to_dict()
    assert payload["stat_family"] == "expedition"
    totals = payload["formation_totals"]
    assert set(totals["power"]) == {"hero", "skills", "gear", "total"}
    for row in payload["heroes"]:
        contrib = row["contributions"]
        assert contrib["family"] == "expedition"
        assert contrib["estimated"] is True
        for share in contrib["stats"].values():
            assert share["hero"] >= 0
            assert share["skills"] >= 0
            assert share["gear"] >= 0
            assert share["total"] == pytest.approx(
                share["hero"] + share["skills"] + share["gear"]
            )


def test_recommend_formation_totals_sum_hero_contributions() -> None:
    payload = _run_recommend().to_dict()
    totals = payload["formation_totals"]
    rows = [r["contributions"] for r in payload["heroes"] if r.get("contributions")]
    assert totals["power"]["gear"] == pytest.approx(
        sum(c["power"]["gear"] for c in rows)
    )
    for label, share in totals["stats"].items():
        assert share["total"] == pytest.approx(
            sum((c["stats"].get(label) or {}).get("total", 0.0) for c in rows)
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_heroes_optimize_scoring.py tests/test_heroes_optimize_recommend.py -v`
Expected: FAIL — `TypeError: hero_strength() got an unexpected keyword argument 'contribution'` and `KeyError: 'stat_family'`

- [ ] **Step 3: Rewrite `hero_strength`**

Replace `ks/heroes/optimize/scoring.py:66-110` with:

```python
def hero_strength(
    hero: HeroRecord,
    entry: CatalogEntry,
    mode: str,
    *,
    event: EventProfile | None = None,
    contribution: StatContribution | None = None,
) -> float:
    """Mode-weighted effect score plus the hero's expedition contribution.

    ``contribution`` must be an expedition-family ``StatContribution`` built by
    ``stat_contributions.hero_contribution``; it replaces the old
    ``effective_power`` + ``gear_bonus`` pair as the strength signal.
    """
    defaults = default_kind_weights()
    if event and event.mode_kind_weights and mode in event.mode_kind_weights:
        weights = event.mode_kind_weights[mode]
    else:
        weights = defaults.get(mode) or defaults["solo"]

    op_weights: dict[int, float] = {}
    if event and event.effect_op_weights and mode in event.effect_op_weights:
        op_weights = event.effect_op_weights[mode]

    total = 0.0
    for tag in entry.effects:
        if mode == "solo" and tag.applies_to == "widget":
            continue
        if mode == "joiner" and tag.applies_to == "widget":
            continue
        if mode == "joiner" and not tag.first_expedition and tag.applies_to == "expedition":
            w = 0.15 * weights.get(tag.kind, 0.5)
        else:
            w = weights.get(tag.kind, 0.5)
        value = w * _effect_value(tag, hero.stars, hero.pellets)
        if tag.effect_op is not None and tag.first_expedition:
            value *= op_weights.get(tag.effect_op, 1.0)
        total += value

    if entry.widget_type == "defense" and mode == "garrison" and entry.garrison_widget_priority:
        total += 5.0 * entry.garrison_widget_priority
    if entry.widget_type == "attack" and mode == "rally_lead" and entry.rally_widget_priority:
        total += 5.0 * entry.rally_widget_priority

    if contribution is not None:
        if contribution.family != EXPEDITION:
            raise ValueError(
                f"hero_strength needs an expedition contribution; got {contribution.family!r}"
            )
        total += contribution_strength(contribution)
    return total
```

Add these imports at the top of `scoring.py`, **below** the existing imports (they must be local imports inside the function if a circular import appears — `stat_contributions` imports `normalize_troop` and `star_progress_factor` from `scoring`, so import lazily):

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover — stat_contributions imports from this module
    from ks.heroes.optimize.stat_contributions import StatContribution
```

and inside `hero_strength`, immediately before the `if contribution is not None:` block:

```python
    from ks.heroes.optimize.stat_contributions import EXPEDITION, contribution_strength
```

- [ ] **Step 4: Build contributions in `solve_mode`**

Replace `ks/heroes/optimize/model.py:52-69` with:

```python
    troop_of = {
        h.name: (normalize_troop(catalog[h.name].troop) or "") for h in usable
    }
    # Gear is fungible within troop class: score power using best geared hero
    # of that class (widgets / skills / stars stay on the selected hero).
    class_power = max_power_by_troop(usable, catalog)
    contributions = {
        h.name: hero_contribution(
            h,
            catalog[h.name],
            family=EXPEDITION,
            gear_pieces=(gear_by_troop or {}).get(troop_of[h.name]),
            power=class_power.get(troop_of[h.name], h.power),
            catalog=catalog,
        )
        for h in usable
    }
    strengths = {
        h.name: hero_strength(
            h,
            catalog[h.name],
            scenario.mode,
            event=event,
            contribution=contributions[h.name],
        )
        for h in usable
    }
```

Change the `solve_mode` signature — replace the `gear_bonus_by_troop: dict[str, float] | None = None` keyword with:

```python
    gear_by_troop: dict[str, dict[str, GearRecord]] | None = None,
```

and add imports at the top of `model.py`:

```python
from ks.heroes.gear_models import GearRecord
from ks.heroes.optimize.stat_contributions import EXPEDITION, hero_contribution
```

Also attach the contributions to the returned `ModeSolution` so `recommend` does not recompute them. Add a field to `ModeSolution` in `types.py`:

```python
@dataclass(frozen=True)
class ModeSolution:
    mode: str
    hero_names: tuple[str, ...]
    troops: dict[str, int]
    effective_capacity: int
    expected_personal_points: float
    breakdown: dict[str, float]
    status: str = "Optimal"
    contributions: dict[str, Any] | None = None  # name → StatContribution
```

and pass `contributions={n: contributions[n] for n in chosen}` on the Optimal return path of `solve_mode`.

- [ ] **Step 5: Update `explain.py` to the new keywords**

`explain.py` is the only other caller of `solve_mode` and `hero_strength`. In `ks/heroes/optimize/explain.py`:

Rename the keyword on both `leave_one_out_mode` (line 185) and `explain_selected_heroes` (line 246):

```python
    gear_by_troop: dict[str, dict[str, GearRecord]] | None = None,
```

and forward it as `gear_by_troop=gear_by_troop` at the `solve_mode` call (line 202) and the `leave_one_out_mode` call (line 258).

Replace the `hero_strength` call at lines 267-278 with:

```python
            strength = hero_strength(
                hero,
                entry,
                scenario.mode,
                event=event,
                contribution=hero_contribution(
                    hero,
                    entry,
                    family=EXPEDITION,
                    gear_pieces=(gear_by_troop or {}).get(
                        normalize_troop(entry.troop) or ""
                    ),
                    catalog=catalog,
                ),
            )
```

Add imports at the top of `explain.py`:

```python
from ks.heroes.gear_models import GearRecord
from ks.heroes.optimize.stat_contributions import EXPEDITION, hero_contribution
```

- [ ] **Step 6: Run tests to verify scoring passes**

Run: `pytest tests/test_heroes_optimize_scoring.py tests/test_heroes_optimize_model.py tests/test_heroes_optimize_explain.py -v`
Expected: PASS

- [ ] **Step 7: Commit the scorer half**

```bash
git add ks/heroes/optimize/scoring.py ks/heroes/optimize/model.py ks/heroes/optimize/explain.py ks/heroes/optimize/types.py tests/test_heroes_optimize_scoring.py
git commit -m "feat(heroes): score expedition modes from stat contributions"
```

- [ ] **Step 8: Wire `recommend` to emit contributions**

In `ks/heroes/optimize/recommend.py`, replace the `gear_bonus` block at lines 44-46:

```python
    gear_by_troop = (
        best_sets_by_troop(gear, profile=gear_profile) if gear else None
    )
```

Change the import at lines 5-9 to:

```python
from ks.heroes.optimize.gear_assign import (
    assign_best_sets,
    assignment_to_dict,
    best_sets_by_troop,
)
```

Replace both `gear_bonus_by_troop=gear_bonus` call-site keywords (in `solve_mode` and `explain_selected_heroes`) with `gear_by_troop=gear_by_troop`.

After `gear_assignment = assignment_to_dict(assigned)` (line 138), compute final contributions from the **assigned** gear and attach them:

```python
    stat_family = family_for_event(event.name if event else "swordland")
    contributions: dict[str, StatContribution] = {}
    for name in best.hero_names:
        hero = next((h for h in heroes if h.name == name), None)
        if hero is None:
            continue
        contributions[name] = hero_contribution(
            hero,
            catalog.get(name),
            family=stat_family,
            gear_pieces=(assigned or {}).get(name) if gear else None,
            catalog=catalog,
        )
    hero_rows = tuple(
        {
            **row,
            "contributions": (
                contributions[row["name"]].to_dict()
                if row.get("name") in contributions
                else None
            ),
        }
        for row in hero_rows
    )
    formation_totals = (
        formation_contribution(list(contributions.values())).to_dict()
        if contributions
        else None
    )
```

`assigned` is only defined inside `if gear:` — hoist it by initialising `assigned: dict[str, dict[str, GearRecord]] = {}` before that block.

Pass the two new fields on the `RecommendResult(...)` construction:

```python
        stat_family=stat_family,
        formation_totals=formation_totals,
```

Add imports at the top of `recommend.py`:

```python
from ks.heroes.optimize.stat_contributions import (
    StatContribution,
    family_for_event,
    formation_contribution,
    hero_contribution,
)
```

- [ ] **Step 8b: Delete the now-dead gear-bonus heuristic**

`gear_assign.gear_bonus_by_troop` was the `0.15 * set_score` heuristic that success criterion 4 retires. After Step 8 nothing imports it. Delete `ks/heroes/optimize/gear_assign.py:162-169` entirely:

```python
def gear_bonus_by_troop(
    pieces: list[GearRecord],
    *,
    profile: str = "early_game_growth",
) -> dict[str, float]:
    """Linear strength nudge from best transferable set per troop class."""
    sets = best_sets_by_troop(pieces, profile=profile)
    return {troop: set_score(slots, profile=profile) * 0.15 for troop, slots in sets.items()}
```

`set_score` and `best_sets_by_troop` stay — `best_sets_by_troop` is what `recommend` now calls.

Run: `grep -rn "gear_bonus_by_troop" ks tests`
Expected: no output.

- [ ] **Step 9: Extend `RecommendResult`**

In `ks/heroes/optimize/types.py`, add to `RecommendResult` after `gear_assignment`:

```python
    stat_family: str = "expedition"
    formation_totals: dict[str, Any] | None = None
```

and in `to_dict`, add to the `out` literal:

```python
            "stat_family": self.stat_family,
            "formation_totals": self.formation_totals,
```

- [ ] **Step 10: Run the tests**

Run: `pytest tests/test_heroes_optimize_recommend.py tests/test_heroes_recommend_all_modes.py tests/test_heroes_optimize_events.py -v`
Expected: PASS

- [ ] **Step 11: Run the full suite**

Run: `pytest -q`
Expected: PASS, except failures confined to arena/conquest/survival/spend_xp/UI suites that Tasks 4-8 own. Record which ones fail and hand the list to the reviewer; do not "fix" them here.

- [ ] **Step 12: Commit**

```bash
git add ks/heroes/optimize/recommend.py ks/heroes/optimize/types.py tests/test_heroes_optimize_recommend.py
git commit -m "feat(heroes): attach stat contributions to recommend results"
```

---

## Task 4: Conquest scoring path (`combat_formation`, `arena`, `conquest`)

**Worktree:** `sc-conquest` — runs in parallel with Task 3.

**Files:**
- Modify: `ks/heroes/optimize/combat_formation.py:100-138` (`hero_base_score`), `:175-201` (`_provisional_gear_bonus`), `:240-413` (`solve_combat_formation`), `:35-66` (`CombatFormationResult`)
- Modify: `ks/heroes/optimize/arena.py:26-107`
- Modify: `ks/heroes/optimize/conquest.py:40-57`
- Test: `tests/test_heroes_optimize_combat_formation.py`, `tests/test_heroes_optimize_arena.py`, `tests/test_heroes_optimize_conquest.py`

**Interfaces:**
- Consumes: `stat_contributions.hero_contribution`, `formation_contribution`, `contribution_strength`, `family_for_event`, `CONQUEST`.
- Produces (every downstream task depends on these exact signatures):
  - `hero_base_score(hero, entry, roles, *, effective_power, contribution, side) -> float` — `gear_bonus` is **removed**, `contribution: StatContribution | None` replaces it.
  - `base_score_fn` protocol: `fn(hero, entry, roles, *, effective_power, contribution) -> float`.
  - `_provisional_contributions(usable, catalog, gear, gear_profile, *, family=CONQUEST, power_by_name=None) -> dict[str, StatContribution]` replaces `_provisional_gear_bonus`.
  - `CombatFormationResult` gains `stat_family: str = "conquest"`, `contributions: dict[str, dict[str, Any]] | None = None`, `formation_totals: dict[str, Any] | None = None`; all three appear in `to_dict()`.
  - `ArenaResult` gains the same three fields and emits them in `to_dict()`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_heroes_optimize_combat_formation.py`:

```python
import pytest

from ks.heroes.gear_models import GearRecord, GearStats
from ks.heroes.models import HeroRecord, HeroStats
from ks.heroes.optimize.combat_formation import hero_base_score, solve_combat_formation
from ks.heroes.optimize.stat_contributions import (
    CONQUEST,
    Share,
    StatContribution,
)
from ks.heroes.optimize.types import CatalogEntry


def _conq(power: float, attack: float = 0.0, health: float = 0.0) -> StatContribution:
    return StatContribution(
        family=CONQUEST,
        estimated=True,
        skills_incomplete=False,
        power=Share(hero=power, skills=0.0, gear=0.0),
        stats={
            "Hero Attack": Share(attack, 0.0, 0.0),
            "Hero Health": Share(health, 0.0, 0.0),
        },
    )


def _roles() -> dict:
    return {"heroes": {}, "placement": {}, "slots": {"carry_slot": "B2"}}


def test_hero_base_score_rises_with_contribution_power() -> None:
    hero = HeroRecord(name="A", stars=3, power=100_000)
    entry = CatalogEntry(name="A", arena_value=50.0)
    low = hero_base_score(
        hero, entry, _roles(), effective_power=100_000,
        contribution=_conq(100_000), side="attack",
    )
    high = hero_base_score(
        hero, entry, _roles(), effective_power=100_000,
        contribution=_conq(900_000), side="attack",
    )
    assert high > low


def test_hero_base_score_rises_with_conquest_stats() -> None:
    hero = HeroRecord(name="A", stars=3, power=100_000)
    entry = CatalogEntry(name="A", arena_value=50.0)
    bare = hero_base_score(
        hero, entry, _roles(), effective_power=100_000,
        contribution=_conq(100_000), side="attack",
    )
    statted = hero_base_score(
        hero, entry, _roles(), effective_power=100_000,
        contribution=_conq(100_000, attack=5000.0, health=40_000.0), side="attack",
    )
    assert statted > bare


def test_hero_base_score_rejects_expedition_contribution() -> None:
    hero = HeroRecord(name="A", stars=3)
    entry = CatalogEntry(name="A")
    wrong = StatContribution("expedition", True, False, Share(1.0, 0.0, 0.0), {})
    with pytest.raises(ValueError, match="conquest"):
        hero_base_score(
            hero, entry, _roles(), effective_power=None,
            contribution=wrong, side="attack",
        )


def _roster() -> tuple[list[HeroRecord], dict[str, CatalogEntry]]:
    names = ["A", "B", "C", "D", "E"]
    heroes = [
        HeroRecord(
            name=n,
            power=100_000 + 10_000 * i,
            troop_type="infantry" if i < 2 else "archer",
            stars=3,
            stats=HeroStats(
                conquest={
                    "Hero Attack": 1000 + i,
                    "Hero Defense": 900 + i,
                    "Hero Health": 9000 + i,
                }
            ),
        )
        for i, n in enumerate(names)
    ]
    catalog = {
        n: CatalogEntry(
            name=n,
            troop="infantry" if i < 2 else "archers",
            arena_value=50.0,
        )
        for i, n in enumerate(names)
    }
    return heroes, catalog


def test_solve_combat_formation_emits_contributions() -> None:
    heroes, catalog = _roster()
    result = solve_combat_formation(
        "conquest", heroes, catalog, _roles(),
        gear_slot_order=("F1", "F2", "B2", "B1", "B3"),
        with_explanations=False,
    )
    assert result.status == "Optimal"
    assert result.stat_family == "conquest"
    assert set(result.contributions) == set(result.heroes)
    totals = result.formation_totals
    assert totals["power"]["total"] == pytest.approx(
        sum(c["power"]["total"] for c in result.contributions.values())
    )
    payload = result.to_dict()
    assert payload["stat_family"] == "conquest"
    assert payload["formation_totals"] == totals
```

Append to `tests/test_heroes_optimize_conquest.py` (reuses the file's existing `_catalog()` / `_heroes()` helpers):

```python
def test_conquest_result_dict_carries_contributions() -> None:
    roles = load_combat_roles("config/conquest_roles.yaml", catalog=_catalog())
    payload = optimize_conquest(_heroes(), _catalog(), roles).to_dict()
    assert payload["stat_family"] == "conquest"
    assert set(payload["contributions"]) == set(payload["heroes"])
    for contrib in payload["contributions"].values():
        assert contrib["family"] == "conquest"
        assert contrib["estimated"] is True
        for share in contrib["stats"].values():
            assert share["hero"] >= 0
            assert share["skills"] >= 0
            assert share["gear"] >= 0
            assert share["total"] == pytest.approx(
                share["hero"] + share["skills"] + share["gear"]
            )
    totals = payload["formation_totals"]
    assert totals["power"]["total"] == pytest.approx(
        sum(c["power"]["total"] for c in payload["contributions"].values())
    )
```

Append the analogous test to `tests/test_heroes_optimize_arena.py`, using that file's own roster/catalog/roles helpers and `optimize_arena("attack", ...).to_dict()` in place of `optimize_conquest(...)`. Add `import pytest` to either file if it is not already imported.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_heroes_optimize_combat_formation.py tests/test_heroes_optimize_arena.py tests/test_heroes_optimize_conquest.py -v`
Expected: FAIL — `TypeError: hero_base_score() got an unexpected keyword argument 'contribution'`

- [ ] **Step 3: Rewrite `hero_base_score`**

Replace `ks/heroes/optimize/combat_formation.py:100-138` with:

```python
def hero_base_score(
    hero: HeroRecord,
    entry: CatalogEntry | None,
    roles: dict[str, Any],
    *,
    effective_power: int | None,
    contribution: StatContribution | None,
    side: str,
) -> float:
    """Compute a hero's base ILP score before placement multipliers.

    Strength comes from ``contribution`` (a conquest-family
    ``StatContribution``) — power plus the hero's conquest stat totals,
    including whatever gear is provisionally assigned. ``effective_power`` is
    kept only as the fallback when no contribution is available.
    """
    meta = _meta_for(hero.name, roles)
    if entry is not None and entry.arena_value is not None:
        arena_value = float(entry.arena_value)
    else:
        arena_value = float(meta.get("arena_value") or 40.0)
    star = star_progress_factor(hero.stars, hero.pellets)
    if contribution is not None:
        if contribution.family != CONQUEST:
            raise ValueError(
                f"hero_base_score needs a conquest contribution; got {contribution.family!r}"
            )
        strength_term = 40.0 * contribution_strength(contribution)
    else:
        power = effective_power if effective_power is not None else hero.power
        strength_term = 40.0 * (float(power) / 1_000_000.0) if power else 0.0
    rarity_bonus = 0.0
    rarity = (entry.rarity if entry else hero.rarity) or ""
    rarity = rarity.lower()
    if rarity in {"legendary", "mythic"}:
        rarity_bonus = 8.0
    elif rarity == "epic":
        rarity_bonus = 4.0
    base = arena_value * star + strength_term + rarity_bonus

    if side == "defense":
        place = roles.get("defense_placement") or roles.get("placement") or {}
        tags = _hero_tags(hero.name, roles)
        if "tank" in tags:
            base *= float(place.get("tank_tag_bonus", 1.15))
        if "heal" in tags:
            base *= float(place.get("heal_tag_bonus", 1.25))
        if "team_def" in tags:
            base *= float(place.get("team_def_tag_bonus", 1.1))
        if "dps" in tags and "tank" not in tags and "heal" not in tags:
            base *= float(place.get("glass_dps_penalty", 0.92))
    return base
```

Add to the imports at the top of `combat_formation.py`:

```python
from ks.heroes.optimize.stat_contributions import (
    CONQUEST,
    StatContribution,
    contribution_strength,
    family_for_event,
    formation_contribution,
    hero_contribution,
)
```

and drop `load_profile_weights` / `piece_score` from the `gear_assign` import (they were only used by `_provisional_gear_bonus`).

- [ ] **Step 4: Replace `_provisional_gear_bonus`**

Replace `ks/heroes/optimize/combat_formation.py:175-201` with:

```python
def _provisional_contributions(
    usable: list[HeroRecord],
    catalog: dict[str, CatalogEntry],
    gear: list[GearRecord] | None,
    gear_profile: str,
    *,
    family: str = CONQUEST,
    power_by_name: dict[str, int | None] | None = None,
) -> dict[str, StatContribution]:
    """Contributions under a provisional exclusive gear assignment.

    The ILP needs a strength signal before it knows the formation, so gear is
    provisionally handed out best-first by scraped power. The final assignment
    (and final contributions) are recomputed once the formation is solved.
    """
    provisional: dict[str, dict[str, GearRecord]] = {}
    if gear:
        score_priority = [
            h.name for h in sorted(usable, key=lambda row: -(row.power or 0))
        ]
        provisional = assign_exclusive_sets(
            usable,
            catalog,
            gear,
            selected=[h.name for h in usable],
            priority=score_priority,
            profile=gear_profile,
        )
    powers = power_by_name or {}
    return {
        h.name: hero_contribution(
            h,
            catalog.get(h.name),
            family=family,
            gear_pieces=provisional.get(h.name),
            power=powers.get(h.name, h.power),
            catalog=catalog,
        )
        for h in usable
    }
```

- [ ] **Step 5: Extend `CombatFormationResult`**

Replace `ks/heroes/optimize/combat_formation.py:35-66` with:

```python
@dataclass(frozen=True)
class CombatFormationResult:
    """Solver output for any 5-hero 2F+3B formation (Arena or Conquest)."""

    mode: str
    side: str | None
    formation: dict[str, str]
    heroes: tuple[str, ...]
    score: float
    gear_assignment: dict[str, list[dict[str, Any]]] | None
    reasons: dict[str, str]
    status: str = "Optimal"
    explanations: dict[str, dict[str, Any]] | None = None
    stat_family: str = CONQUEST
    contributions: dict[str, dict[str, Any]] | None = None
    formation_totals: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "mode": self.mode,
            "formation": dict(self.formation),
            "heroes": list(self.heroes),
            "score": self.score,
            "gear_assignment": self.gear_assignment,
            "reasons": dict(self.reasons),
            "status": self.status,
            "stat_family": self.stat_family,
            "contributions": self.contributions,
            "formation_totals": self.formation_totals,
        }
        if self.side is not None:
            out["side"] = self.side
        if self.explanations is not None:
            out["explanations"] = self.explanations
        survival = (self.explanations or {}).get("survival")
        if survival is not None:
            out["survival"] = survival
        return out
```

`_infeasible_result` needs no change — the three new fields default correctly.

- [ ] **Step 6: Rewire `solve_combat_formation`**

In `ks/heroes/optimize/combat_formation.py`, inside `solve_combat_formation`:

Replace line 274 (`gear_bonus_by_hero = _provisional_gear_bonus(...)`) and the power sanitize block that follows so the sanitize runs **first**:

```python
    # Sanitize OCR power blow-ups before they dominate the ILP objective.
    from ks.heroes.optimize.survival_pipeline import sanitize_hero_powers

    power_by_name = sanitize_hero_powers(usable, roles=roles)
    family = family_for_event(mode)
    contributions = _provisional_contributions(
        usable,
        catalog,
        gear,
        gear_profile,
        family=family,
        power_by_name=power_by_name,
    )
```

Replace the `_base_score_fn` default and the `base[...]` loop (lines 281-303) with:

```python
    _base_score_fn = base_score_fn or (
        lambda h, entry, roles, *, effective_power, contribution: hero_base_score(
            h, entry, roles,
            effective_power=effective_power,
            contribution=contribution,
            side=effective_side,
        )
    )
    _placement_mult_fn = placement_mult_fn or (
        lambda troop, slot, hero_name, roles: placement_mult(
            troop, slot, hero_name, roles, side=effective_side
        )
    )

    base: dict[str, float] = {}
    for h in usable:
        base[h.name] = _base_score_fn(
            h,
            catalog.get(h.name),
            roles,
            effective_power=power_by_name.get(h.name, h.power),
            contribution=contributions.get(h.name),
        )
```

After the final `gear_assignment = assignment_to_dict(assigned)` block (line 355), recompute contributions from the **final** assignment and roll them up:

```python
    final_contributions = {
        name: hero_contribution(
            next(h for h in usable if h.name == name),
            catalog.get(name),
            family=family,
            gear_pieces=(assigned or {}).get(name) if gear else None,
            power=power_by_name.get(name),
            catalog=catalog,
        )
        for name in ordered
    }
    formation_totals = formation_contribution(
        list(final_contributions.values())
    ).to_dict()
    contributions_payload = {
        name: c.to_dict() for name, c in final_contributions.items()
    }
```

`assigned` is defined only inside `if gear:` — initialise `assigned: dict[str, dict[str, GearRecord]] = {}` just before that block.

Pass the three new fields on the final `CombatFormationResult(...)`:

```python
        stat_family=family,
        contributions=contributions_payload,
        formation_totals=formation_totals,
```

- [ ] **Step 7: Update `arena.py`**

In `ks/heroes/optimize/arena.py`, add the three fields to `ArenaResult`:

```python
@dataclass(frozen=True)
class ArenaResult:
    side: str
    formation: dict[str, str]
    heroes: tuple[str, ...]
    score: float
    gear_assignment: dict[str, list[dict[str, Any]]] | None
    reasons: dict[str, str]
    status: str = "Optimal"
    explanations: dict[str, dict[str, Any]] | None = None
    stat_family: str = "conquest"
    contributions: dict[str, dict[str, Any]] | None = None
    formation_totals: dict[str, Any] | None = None
```

carry them through `from_combat`:

```python
            stat_family=result.stat_family,
            contributions=result.contributions,
            formation_totals=result.formation_totals,
```

and add them to `to_dict`'s `out` literal:

```python
            "stat_family": self.stat_family,
            "contributions": self.contributions,
            "formation_totals": self.formation_totals,
```

Update `_attach_arena_survival`'s inner `_base` to the new protocol:

```python
    def _base(hero, entry, roles, *, effective_power, contribution):
        return hero_base_score(
            hero,
            entry,
            roles,
            effective_power=effective_power,
            contribution=contribution,
            side=side,
        )
```

- [ ] **Step 8: Update `conquest.py`**

Replace `_conquest_base_score` in `ks/heroes/optimize/conquest.py:40-57`:

```python
def _conquest_base_score(
    hero: HeroRecord,
    entry: CatalogEntry | None,
    roles: dict[str, Any],
    *,
    effective_power: int | None,
    contribution: StatContribution | None = None,
) -> float:
    """Base ILP score for Conquest: attack scoring amplified by ultimate level."""
    base = hero_base_score(
        hero,
        entry,
        roles,
        effective_power=effective_power,
        contribution=contribution,
        side="attack",
    )
    return base * ultimate_level_multiplier(hero)
```

Add the import:

```python
from ks.heroes.optimize.stat_contributions import StatContribution
```

- [ ] **Step 9: Run the tests**

Run: `pytest tests/test_heroes_optimize_combat_formation.py tests/test_heroes_optimize_arena.py tests/test_heroes_optimize_arena_defense.py tests/test_heroes_optimize_conquest.py -v`
Expected: PASS

- [ ] **Step 10: Run the full suite**

Run: `pytest -q`
Expected: PASS, except failures confined to survival / spend_xp / UI suites that Tasks 5-8 own (they still call the removed `gear_bonus=` keyword). Record the failing list for the reviewer; do not fix them here.

- [ ] **Step 11: Commit**

```bash
git add ks/heroes/optimize/combat_formation.py ks/heroes/optimize/arena.py ks/heroes/optimize/conquest.py tests/test_heroes_optimize_combat_formation.py tests/test_heroes_optimize_arena.py tests/test_heroes_optimize_conquest.py
git commit -m "feat(heroes): score Arena/Conquest formations from stat contributions"
```

---

## Task 5: Survival path (`front_survival`, `opponent_models`, `survival_pipeline`)

**Worktree:** `sc-survival` — runs in parallel with Task 6, after waves 0-1 are merged.

**Files:**
- Modify: `ks/heroes/optimize/front_survival.py:76-132`
- Modify: `ks/heroes/optimize/opponent_models.py:139-189`, `:209-357`
- Modify: `ks/heroes/optimize/survival_pipeline.py:90-197`, `:294-434`
- Modify: `ks/heroes/optimize/sensitivity.py` (call sites only)
- Test: `tests/test_heroes_front_survival.py`, `tests/test_heroes_sensitivity.py`

**Interfaces:**
- Consumes: `hero_base_score(..., contribution=...)` and `_provisional_contributions` from Task 4; `hero_contribution`, `CONQUEST` from Task 2.
- Produces:
  - `hero_tau(hero, *, contribution=None, gear_pieces=None) -> float`
  - `formation_tau(formation, heroes_by_name, gear_by_hero=None, contributions=None) -> tuple[float, float, dict[str, float]]`
  - `slot_utilities(..., contributions: dict[str, StatContribution] | None = None)`
  - `roster_pressure_scale(..., contributions=None)`
  - `_heuristic_offense(..., contributions=None)` in `opponent_models`
  - `OpponentLineup` gains `contributions: dict[str, dict[str, Any]] | None = None`, emitted in `to_dict()`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_heroes_front_survival.py`:

```python
import pytest

from ks.heroes.models import HeroRecord, HeroStats
from ks.heroes.optimize.front_survival import formation_tau, hero_tau
from ks.heroes.optimize.stat_contributions import (
    CONQUEST,
    Share,
    StatContribution,
)


def _contrib(health: float, defense: float) -> StatContribution:
    return StatContribution(
        family=CONQUEST,
        estimated=True,
        skills_incomplete=False,
        power=Share(0.0, 0.0, 0.0),
        stats={
            "Hero Health": Share(health * 0.6, health * 0.1, health * 0.3),
            "Hero Defense": Share(defense * 0.6, defense * 0.1, defense * 0.3),
        },
    )


def test_hero_tau_uses_contribution_totals() -> None:
    hero = HeroRecord(
        name="A", stats=HeroStats(conquest={"Hero Health": 100, "Hero Defense": 10})
    )
    tau = hero_tau(hero, contribution=_contrib(500.0, 50.0))
    assert tau == pytest.approx(500.0 * 50.0)


def test_hero_tau_falls_back_to_scrape_without_contribution() -> None:
    hero = HeroRecord(
        name="A", stats=HeroStats(conquest={"Hero Health": 100, "Hero Defense": 10})
    )
    assert hero_tau(hero) == pytest.approx(100.0 * 10.0)


def test_hero_tau_never_below_one() -> None:
    hero = HeroRecord(name="A")
    assert hero_tau(hero, contribution=_contrib(0.0, 0.0)) >= 1.0


def test_formation_tau_prefers_contributions_over_gear_pieces() -> None:
    heroes = {
        n: HeroRecord(
            name=n, stats=HeroStats(conquest={"Hero Health": 10, "Hero Defense": 2})
        )
        for n in ("a", "b", "c", "d", "e")
    }
    formation = {"F1": "a", "F2": "b", "B1": "c", "B2": "d", "B3": "e"}
    contributions = {n: _contrib(100.0, 10.0) for n in heroes}
    tau_f, tau_b, by_hero = formation_tau(
        formation, heroes, None, contributions=contributions
    )
    assert tau_f == pytest.approx(2 * 100.0 * 10.0)
    assert tau_b == pytest.approx(3 * 100.0 * 10.0)
    assert set(by_hero) == set(heroes)
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_heroes_front_survival.py -v`
Expected: FAIL — `TypeError: hero_tau() got an unexpected keyword argument 'contribution'`

- [ ] **Step 3: Rewrite `hero_tau` / `formation_tau`**

Replace `ks/heroes/optimize/front_survival.py:100-132` with:

```python
def hero_tau(
    hero: HeroRecord,
    *,
    contribution: "StatContribution | None" = None,
    gear_pieces: Mapping[str, GearRecord] | None = None,
) -> float:
    """Toughness proxy: health × defense, with expedition gear health on top.

    When ``contribution`` is supplied the health/defense totals already carry
    the hero + skills + gear conquest flats; the expedition health fraction
    from chest/gloves is still applied as a multiplier because it is a percent
    buff, not a flat.
    """
    if contribution is not None:
        hp = max(1.0, _share_total(contribution, "Hero Health"))
        defense = max(1.0, _share_total(contribution, "Hero Defense"))
    else:
        hp = float(max(1, conquest_stat(hero, "Hero Health")))
        defense = float(max(1, conquest_stat(hero, "Hero Defense")))
    g = gear_health_bonus(gear_pieces)
    return hp * defense * (1.0 + g)


def formation_tau(
    formation: Mapping[str, str],
    heroes_by_name: Mapping[str, HeroRecord],
    gear_by_hero: Mapping[str, Mapping[str, GearRecord]] | None = None,
    contributions: Mapping[str, "StatContribution"] | None = None,
) -> tuple[float, float, dict[str, float]]:
    gear_by_hero = gear_by_hero or {}
    contributions = contributions or {}
    by_hero: dict[str, float] = {}
    tau_f = 0.0
    tau_b = 0.0
    for slot, name in formation.items():
        hero = heroes_by_name.get(name)
        if hero is None:
            raise ValueError(
                f"formation references unknown hero {name!r} in slot {slot!r}"
            )
        tau = hero_tau(
            hero,
            contribution=contributions.get(name),
            gear_pieces=gear_by_hero.get(name),
        )
        by_hero[name] = tau
        if slot in FRONT:
            tau_f += tau
        elif slot in BACK:
            tau_b += tau
    return tau_f, tau_b, by_hero
```

Add above `hero_tau`:

```python
def _share_total(contribution: "StatContribution", label: str) -> float:
    share = contribution.stats.get(label)
    return share.total if share is not None else 0.0
```

and at the top of the file, under `from typing import Any, Mapping`:

```python
from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:  # pragma: no cover
    from ks.heroes.optimize.stat_contributions import StatContribution
```

**Note:** when `contribution` is supplied, `gear_by_hero` must still be passed so the expedition health multiplier survives — the conquest flats and the expedition percent are different buffs and both count.

- [ ] **Step 4: Run and commit the front_survival half**

Run: `pytest tests/test_heroes_front_survival.py -v`
Expected: PASS

```bash
git add ks/heroes/optimize/front_survival.py tests/test_heroes_front_survival.py
git commit -m "feat(heroes): compute toughness from contribution totals"
```

- [ ] **Step 5: Rewire `opponent_models.py`**

Replace `_gear_bonus_map` (lines 139-157) with:

```python
def _contribution_map(
    formation: dict[str, str],
    heroes: list[HeroRecord],
    catalog: dict[str, CatalogEntry],
    gear_asg: dict[str, dict[str, GearRecord]],
    *,
    power_by_name: dict[str, float] | None = None,
) -> dict[str, StatContribution]:
    """Conquest contributions for a foe lineup under its own gear assignment."""
    powers = power_by_name or {}
    selected = [formation[s] for s in ALL_SLOTS if s in formation]
    by_name = {h.name: h for h in heroes}
    out: dict[str, StatContribution] = {}
    for name in selected:
        hero = by_name.get(name)
        if hero is None:
            continue
        power = powers.get(name)
        out[name] = hero_contribution(
            hero,
            catalog.get(name),
            family=CONQUEST,
            gear_pieces=gear_asg.get(name),
            power=int(round(power)) if power else hero.power,
            catalog=catalog,
        )
    return out
```

Replace the `gear_bonus_by_hero` parameter of `_heuristic_offense` (lines 160-189) with `contributions: dict[str, StatContribution] | None = None`, and change the `hero_base_score` call to:

```python
        base = hero_base_score(
            hero,
            entry,
            roles,
            effective_power=int(round(eff_power)) if eff_power else hero.power,
            contribution=(contributions or {}).get(name),
            side=side,
        )
```

In all three builders (`build_naive_max_power`, `build_troop_balanced_naive`, `opponent_from_formation`), replace

```python
    gear_bonus = _gear_bonus_map(formation, usable, catalog, gear_asg, profile=gear_profile)
```

with

```python
    contributions = _contribution_map(
        formation, usable, catalog, gear_asg, power_by_name=power_map
    )
```

and the offense call's `gear_bonus_by_hero=gear_bonus` with `contributions=contributions`. Pass `contributions={n: c.to_dict() for n, c in contributions.items()}` to each `OpponentLineup(...)`.

Add to `OpponentLineup`:

```python
    contributions: dict[str, dict[str, Any]] | None = None
```

and to its `to_dict()`:

```python
            "contributions": self.contributions,
```

Update imports at the top of `opponent_models.py`:

```python
from ks.heroes.optimize.stat_contributions import (
    CONQUEST,
    StatContribution,
    hero_contribution,
)
```

and drop the `from ks.heroes.optimize.combat_formation import _provisional_gear_bonus` local import inside the old `_gear_bonus_map`.

- [ ] **Step 6: Rewire `survival_pipeline.py`**

In `slot_utilities` (lines 90-129), add a `contributions: dict[str, StatContribution] | None = None` keyword and change the `base_score_fn` call to:

```python
        base = base_score_fn(
            hero,
            entry,
            roles,
            effective_power=power,
            contribution=(contributions or {}).get(name),
        )
```

In `roster_pressure_scale` (lines 132-155), add the same keyword; pass `contribution=(contributions or {}).get(name)` to `base_score_fn` and `contribution=(contributions or {}).get(name)` to `hero_tau`.

In `build_self_play_foes` (lines 200-291), update the default `score_fn` lambda:

```python
    score_fn = base_score_fn or (
        lambda h, entry, roles, *, effective_power, contribution: hero_base_score(
            h,
            entry,
            roles,
            effective_power=effective_power,
            contribution=contribution,
            side=heuristic_side or "attack",
        )
    )
```

In `evaluate_vs_foe` (lines 158-197), add `contributions: dict[str, StatContribution] | None = None` and thread it into both `formation_tau(..., contributions=contributions)` and `slot_utilities(..., contributions=contributions)`.

In `attach_survival` (lines 294-434), build our contributions once from the final gear assignment and thread them everywhere:

```python
    our_contributions = {
        name: hero_contribution(
            next(h for h in heroes if h.name == name),
            catalog.get(name),
            family=CONQUEST,
            gear_pieces=our_gear.get(name),
            power=power_by_name.get(name),
            catalog=catalog,
        )
        for name in result.formation.values()
        if any(h.name == name for h in heroes)
    }
```

placed right after `our_gear = gear_maps_for_formation(...)`, then pass `contributions=our_contributions` to `evaluate_vs_foe`, `formation_tau`, `slot_utilities`, and `build_sensitivity`. Add `"stat_family": CONQUEST` and `"contributions": {n: c.to_dict() for n, c in our_contributions.items()}` to the `survival["our"]` dict.

Add imports at the top of `survival_pipeline.py`:

```python
from ks.heroes.optimize.stat_contributions import (
    CONQUEST,
    StatContribution,
    hero_contribution,
)
```

- [ ] **Step 7: Update `sensitivity.py` call sites**

Add a `contributions: dict[str, StatContribution] | None = None` keyword to `build_sensitivity` and forward it to every `slot_utilities` / `formation_tau` / `hero_tau` / `base_score_fn` call inside. Where `sensitivity.py` rebuilds a formation with a hero swapped, recompute that hero's contribution with `hero_contribution(...)` rather than reusing a stale entry.

- [ ] **Step 7b: Update the sensitivity test's scorer stub**

`tests/test_heroes_sensitivity.py` defines a fake `base_score_fn` that still takes `gear_bonus`. Change its signature to the new protocol:

```python
    def _base(hero, entry, roles, *, effective_power, contribution):
        return float(effective_power or 0) / 1000.0
```

and update any call site in that file that passes `gear_bonus=`.

- [ ] **Step 8: Run the tests**

Run: `pytest tests/test_heroes_front_survival.py tests/test_heroes_sensitivity.py tests/test_heroes_optimize_arena.py tests/test_heroes_optimize_conquest.py tests/test_heroes_optimize_hardening.py -v`
Expected: PASS

- [ ] **Step 9: Run the full suite**

Run: `pytest -q`
Expected: PASS except spend_xp / UI suites owned by Tasks 6-8.

- [ ] **Step 10: Commit**

```bash
git add ks/heroes/optimize/opponent_models.py ks/heroes/optimize/survival_pipeline.py ks/heroes/optimize/sensitivity.py tests/
git commit -m "feat(heroes): base survival + foe models on stat contributions"
```

---

## Task 6: Gear XP spend (`spend_xp.py`)

**Worktree:** `sc-spendxp` — runs in parallel with Task 5, after waves 0-1 are merged.

**Files:**
- Modify: `ks/heroes/optimize/spend_xp.py:99-211`
- Test: `tests/test_heroes_spend_xp.py`

**Interfaces:**
- Consumes: `RecommendResult.stat_family` / `.formation_totals` (Task 3), `ArenaResult.stat_family` / `.formation_totals` (Task 4).
- Produces: every `_arena` / `_event` summary dict gains `"stat_family": str` and `"formation_totals": dict | None`. `SpendResult.to_dict()` therefore exposes them under `baseline_summary` and `best_summary`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_heroes_spend_xp.py` (the file already defines `_piece`; add the imports and helpers below):

```python
from pathlib import Path

import pytest

from ks.heroes.models import HeroRecord, HeroStats
from ks.heroes.optimize.spend_xp import build_event_utility

_ROOT = Path(__file__).resolve().parents[1]

# Names must exist in config/hero_catalog.yaml so the real catalog resolves.
_ROSTER = [
    ("Helga", "infantry", "legendary", 3, 500_000),
    ("Howard", "infantry", "epic", 3, 390_000),
    ("Jabel", "cavalry", "legendary", 4, 650_000),
    ("Chenko", "cavalry", "epic", 3, 400_000),
    ("Saul", "archer", "legendary", 2, 250_000),
    ("Diana", "archer", "epic", 3, 450_000),
    ("Gordon", "cavalry", "epic", 2, 230_000),
]


def _heroes() -> list[HeroRecord]:
    return [
        HeroRecord(
            name=name,
            troop_type=troop,
            rarity=rarity,
            stars=stars,
            pellets=0,
            power=power,
            escorts=5,
            stats=HeroStats(
                conquest={
                    "Hero Attack": power // 300,
                    "Hero Defense": power // 350,
                    "Hero Health": power // 40,
                    "Escort Attack": power // 900,
                    "Escort Defense": power // 1050,
                    "Escort Health": power // 120,
                }
            ),
        )
        for name, troop, rarity, stars, power in _ROSTER
    ]


def _gear() -> list[GearRecord]:
    out: list[GearRecord] = []
    for troop in ("infantry", "cavalry", "archers"):
        for slot in ("helmet", "chest", "gloves", "boots"):
            out.append(
                _piece(f"{troop}-{slot}", level=20, troop=troop, slot=slot)
            )
    return out


def test_arena_utility_summary_carries_contributions() -> None:
    utility = build_event_utility("arena_attack", _heroes(), config_root=_ROOT)
    _util, summary = utility(_gear())
    assert summary["stat_family"] == "conquest"
    totals = summary["formation_totals"]
    assert set(totals["power"]) == {"hero", "skills", "gear", "total"}
    assert totals["power"]["total"] == pytest.approx(
        totals["power"]["hero"] + totals["power"]["skills"] + totals["power"]["gear"]
    )


def test_event_utility_summary_carries_contributions() -> None:
    utility = build_event_utility("swordland", _heroes(), config_root=_ROOT)
    _util, summary = utility(_gear())
    assert summary["stat_family"] == "expedition"
    assert summary["formation_totals"] is not None


def test_levelling_gear_raises_gear_share_of_totals() -> None:
    utility = build_event_utility("arena_attack", _heroes(), config_root=_ROOT)
    base_gear = _gear()
    _u0, s0 = utility(base_gear)
    bumped = apply_levels(
        base_gear, {p.piece_id: (p.enhancement_level or 0) + 20 for p in base_gear}
    )
    _u1, s1 = utility(bumped)
    assert s1["formation_totals"]["power"]["gear"] > s0["formation_totals"]["power"]["gear"]
```

If any `_ROSTER` name is missing from `config/hero_catalog.yaml`, swap it for one that is present — `optimize_arena` drops heroes the catalog does not know and needs at least five.

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_heroes_spend_xp.py -v`
Expected: FAIL — `KeyError: 'stat_family'`

- [ ] **Step 3: Add contributions to the arena utility summary**

In `ks/heroes/optimize/spend_xp.py`, replace the `_arena` return (lines 133-140) with:

```python
            util = float(result.score) if result.status == "Optimal" else float("-inf")
            return util, {
                "status": result.status,
                "side": side,
                "formation": dict(result.formation),
                "heroes": list(result.heroes),
                "score": result.score if result.status == "Optimal" else None,
                "stat_family": result.stat_family,
                "formation_totals": result.formation_totals,
                "contributions": result.contributions,
            }
```

- [ ] **Step 4: Add contributions to the event utility summary**

Replace the two `_event` returns (lines 185-209) with:

```python
        if mode:
            result = recommend(
                heroes,
                catalog,
                troops,
                scenarios,
                force_mode=mode,
                event=event_profile,
                troop_stats=troop_stats,
                truegold=truegold,
                gear=gear,
                gear_profile=gear_profile,
            )
            return float(result.expected_personal_points), {
                "mode": result.recommended_mode,
                "heroes": [h["name"] for h in result.heroes],
                "expected_personal_points": result.expected_personal_points,
                "stat_family": result.stat_family,
                "formation_totals": result.formation_totals,
            }
        results = recommend_all_modes(
            heroes,
            catalog,
            troops,
            scenarios,
            event=event_profile,
            troop_stats=troop_stats,
            truegold=truegold,
            gear=gear,
            gear_profile=gear_profile,
        )
        best = max(results.values(), key=lambda r: r.expected_personal_points)
        return float(best.expected_personal_points), {
            "mode": best.recommended_mode,
            "heroes": [h["name"] for h in best.heroes],
            "expected_personal_points": best.expected_personal_points,
            "stat_family": best.stat_family,
            "formation_totals": best.formation_totals,
            "modes": {
                m: r.expected_personal_points for m, r in results.items()
            },
        }
```

- [ ] **Step 5: Run the tests**

Run: `pytest tests/test_heroes_spend_xp.py -v`
Expected: PASS

- [ ] **Step 6: Run the full suite**

Run: `pytest -q`
Expected: PASS except UI suites owned by Tasks 7-8.

- [ ] **Step 7: Commit**

```bash
git add ks/heroes/optimize/spend_xp.py tests/test_heroes_spend_xp.py
git commit -m "feat(heroes): report contribution totals from gear XP utility"
```

---

## Task 7: API payload (`optimize_run.py`)

**Worktree:** `sc-api` — runs in parallel with Task 8.

**Files:**
- Modify: `ks/heroes/ui/optimize_run.py:29-78` (`_event_bundle`), `:81-82` (`_section_error`), `:148-222` (arena/conquest error shapes)
- Test: `tests/test_heroes_optimize_ui.py`

**Interfaces (frozen contract — Task 8 renders exactly this):**

Every Sword/Bear **mode row** (`bundle["sword"]["modes"][<mode>]`) and every **formation row** (`bundle["arena"]["attack"]`, `bundle["arena"]["defense"]`, `bundle["conquest"]`) carries:

```json
{
  "stat_family": "conquest",
  "formation_totals": {
    "family": "conquest",
    "estimated": true,
    "skills_incomplete": false,
    "power": { "hero": 0.0, "skills": 0.0, "gear": 0.0, "total": 0.0 },
    "stats": {
      "Hero Attack": { "hero": 0.0, "skills": 0.0, "gear": 0.0, "total": 0.0 }
    }
  },
  "contributions": {
    "Howard": {
      "family": "conquest",
      "estimated": true,
      "skills_incomplete": false,
      "power": { "hero": 0.0, "skills": 0.0, "gear": 0.0, "total": 0.0 },
      "stats": { "Hero Attack": { "hero": 0.0, "skills": 0.0, "gear": 0.0, "total": 0.0 } }
    }
  }
}
```

Sword/Bear rows additionally keep per-hero contributions inline on each `heroes[]` row under the key `"contributions"` (from Task 3). Task 7 normalises that into the same top-level `"contributions"` name→payload map so the UI has one shape for all four screens.

Each section (`bundle["sword"]`, `bundle["bear"]`) also carries a section-level `"stat_family"`. `bundle["arena"]` is a plain `{attack, defense}` mapping and gets no section-level key. Error rows carry `"stat_family"` and `"formation_totals": null` and `"contributions": null` so the UI never has to branch on presence.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_heroes_optimize_ui.py` (the file already defines `ROOT` and `_seed_roster`; the helpers below build the same roster as plain records so `run_optimize_bundle` can be called directly):

```python
from ks.heroes.gear_models import GearRecord, GearStats
from ks.heroes.models import HeroStats
from ks.heroes.ui.optimize_run import run_optimize_bundle

_SHARE_KEYS = {"hero", "skills", "gear", "total"}


def _heroes() -> list[HeroRecord]:
    rows = [
        ("Helga", "infantry", "legendary", 3, 500_000),
        ("Howard", "infantry", "epic", 3, 390_000),
        ("Jabel", "cavalry", "legendary", 4, 650_000),
        ("Chenko", "cavalry", "epic", 3, 400_000),
        ("Saul", "archer", "legendary", 2, 250_000),
        ("Diana", "archer", "epic", 3, 450_000),
        ("Gordon", "cavalry", "epic", 2, 230_000),
    ]
    return [
        HeroRecord(
            name=name,
            troop_type=troop,
            rarity=rarity,
            stars=stars,
            pellets=0,
            power=power,
            escorts=5,
            roster_page=0,
            roster_index=i,
            scraped_at="t",
            stats=HeroStats(
                conquest={
                    "Hero Attack": power // 300,
                    "Hero Defense": power // 350,
                    "Hero Health": power // 40,
                    "Escort Attack": power // 900,
                    "Escort Defense": power // 1050,
                    "Escort Health": power // 120,
                }
            ),
        )
        for i, (name, troop, rarity, stars, power) in enumerate(rows)
    ]


def _gear() -> list[GearRecord]:
    prefix = {"infantry": "Infantry", "cavalry": "Cavalry", "archers": "Archer"}
    out: list[GearRecord] = []
    for troop in ("infantry", "cavalry", "archers"):
        for slot in ("helmet", "chest", "gloves", "boots"):
            stat = "Lethality" if slot in ("helmet", "boots") else "Health"
            out.append(
                GearRecord(
                    piece_id=f"{troop}-{slot}",
                    name=f"{troop} {slot}",
                    troop_type=troop,
                    slot=slot,
                    rarity="mythic",
                    enhancement_level=40,
                    power=60_000,
                    stats=GearStats(
                        conquest={"Hero Attack": 300, "Hero Health": 1500},
                        expedition={f"{prefix[troop]} {stat}": 32.0},
                    ),
                )
            )
    return out


def _assert_contribution(payload: dict) -> None:
    assert payload["family"] in {"conquest", "expedition"}
    assert payload["estimated"] is True
    assert set(payload["power"]) == _SHARE_KEYS
    assert payload["power"]["total"] == pytest.approx(
        payload["power"]["hero"] + payload["power"]["skills"] + payload["power"]["gear"]
    )
    for share in payload["stats"].values():
        assert set(share) == _SHARE_KEYS
        assert share["hero"] >= 0
        assert share["skills"] >= 0
        assert share["gear"] >= 0
        assert share["total"] == pytest.approx(
            share["hero"] + share["skills"] + share["gear"]
        )


def test_bundle_event_sections_carry_expedition_contributions() -> None:
    bundle = run_optimize_bundle(_heroes(), gear=_gear(), config_root=ROOT)
    for section in ("sword", "bear"):
        assert bundle[section]["stat_family"] == "expedition"
        for row in bundle[section]["modes"].values():
            assert row["stat_family"] == "expedition"
            _assert_contribution(row["formation_totals"])
            assert row["contributions"]
            for contrib in row["contributions"].values():
                _assert_contribution(contrib)


def test_bundle_combat_sections_carry_conquest_contributions() -> None:
    bundle = run_optimize_bundle(_heroes(), gear=_gear(), config_root=ROOT)
    rows = [bundle["arena"]["attack"], bundle["arena"]["defense"], bundle["conquest"]]
    for row in rows:
        if row["status"] != "Optimal":
            continue
        assert row["stat_family"] == "conquest"
        _assert_contribution(row["formation_totals"])
        for contrib in row["contributions"].values():
            _assert_contribution(contrib)


def test_error_rows_still_declare_stat_family() -> None:
    # An empty roster makes every section infeasible; the shape must still hold.
    bundle = run_optimize_bundle([], gear=None, config_root=ROOT)
    for row in (bundle["arena"]["attack"], bundle["arena"]["defense"], bundle["conquest"]):
        assert row["stat_family"] == "conquest"
        assert row["formation_totals"] is None
        assert row["contributions"] is None
    for section in ("sword", "bear"):
        assert bundle[section]["stat_family"] == "expedition"
```

Note: with an empty roster the arena/conquest solvers return `status="Infeasible"` (not an exception), so those rows come from `CombatFormationResult.to_dict()` / `ArenaResult.to_dict()` with the dataclass defaults — `stat_family="conquest"`, `formation_totals=None`, `contributions=None`. That is exactly what the assertion checks; no extra branch is needed in `optimize_run.py` for the infeasible case, only for the `except` blocks.

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_heroes_optimize_ui.py -v`
Expected: FAIL — `KeyError: 'stat_family'`

- [ ] **Step 3: Normalise event bundle rows**

In `ks/heroes/ui/optimize_run.py`, inside `_event_bundle`, after `modes[mode] = result.to_dict()`, replace that line with:

```python
            payload = result.to_dict()
            payload["contributions"] = {
                row["name"]: row["contributions"]
                for row in payload.get("heroes") or []
                if row.get("name") and row.get("contributions")
            } or None
            modes[mode] = payload
```

and add `"stat_family"` to the section `out` dict:

```python
    out: dict[str, Any] = {
        "label": label,
        "event": event.name,
        "status": "ok",
        "stat_family": family_for_event(event.name),
        "modes": modes,
    }
```

Update `_section_error` so failed sections still declare their family:

```python
def _section_error(label: str, message: str, *, stat_family: str) -> dict[str, Any]:
    return {
        "label": label,
        "modes": {},
        "status": "Error",
        "error": message,
        "stat_family": stat_family,
    }
```

and pass `stat_family="expedition"` at all four `_section_error` call sites.

- [ ] **Step 4: Normalise the arena/conquest error shapes**

Add the three keys to every arena and conquest error dict in `run_optimize_bundle` (four literals in total):

```python
                "stat_family": "conquest",
                "formation_totals": None,
                "contributions": None,
```

Add the import at the top of `optimize_run.py`:

```python
from ks.heroes.optimize.stat_contributions import family_for_event
```

- [ ] **Step 5: Run the tests**

Run: `pytest tests/test_heroes_optimize_ui.py -v`
Expected: PASS

- [ ] **Step 6: Run the full suite**

Run: `pytest -q`
Expected: PASS (all tasks 1-7 landed).

- [ ] **Step 7: Commit**

```bash
git add ks/heroes/ui/optimize_run.py tests/test_heroes_optimize_ui.py
git commit -m "feat(heroes-ui): expose stat contributions on the optimize API"
```

---

## Task 8: Event lineups UI (`optimize_events.html`)

**Worktree:** `sc-ui` — runs in parallel with Task 7 against the frozen contract in Task 7's Interfaces block.

**Files:**
- Modify: `ks/heroes/ui/templates/optimize_events.html` (styles block ~line 90-260; `renderModes` ~597; `renderFormationCard` ~639; `openGearModal` ~549)
- Test: `tests/test_heroes_optimize_ui.py` (template smoke assertions)

**Interfaces:**
- Consumes: the frozen JSON contract from Task 7.
- Produces: two new JS helpers — `renderContributionSummary(row)` (compact, for cards) and `renderContributionTable(row)` (per-hero table, for the modal).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_heroes_optimize_ui.py`:

```python
from pathlib import Path

_TEMPLATE = (
    Path(__file__).resolve().parents[1]
    / "ks"
    / "heroes"
    / "ui"
    / "templates"
    / "optimize_events.html"
)


def test_template_defines_contribution_renderers() -> None:
    text = _TEMPLATE.read_text(encoding="utf-8")
    assert "function renderContributionSummary(" in text
    assert "function renderContributionTable(" in text


def test_template_cards_and_modal_call_the_renderers() -> None:
    text = _TEMPLATE.read_text(encoding="utf-8")
    assert text.count("renderContributionSummary(") >= 3  # def + modes + formation
    assert text.count("renderContributionTable(") >= 2  # def + modal


def test_template_styles_contribution_blocks() -> None:
    text = _TEMPLATE.read_text(encoding="utf-8")
    assert ".contrib" in text
    assert ".contrib-table" in text
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_heroes_optimize_ui.py -k contribution -v`
Expected: FAIL — assertion errors on the missing function names

- [ ] **Step 3: Add the styles**

Insert into the `<style>` block of `ks/heroes/ui/templates/optimize_events.html`, immediately after the `.formation` rule (~line 122-142):

```css
    .contrib {
      margin: 6px 0 2px;
      font-size: 12px;
      color: var(--muted);
      display: flex;
      flex-wrap: wrap;
      gap: 4px 10px;
    }
    .contrib .k { color: var(--fg); font-weight: 600; }
    .contrib .est { font-style: italic; opacity: 0.75; }
    .contrib-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 12px;
      margin: 6px 0 12px;
    }
    .contrib-table th,
    .contrib-table td {
      text-align: right;
      padding: 3px 6px;
      border-bottom: 1px solid var(--border, #2a2a2a);
      white-space: nowrap;
    }
    .contrib-table th:first-child,
    .contrib-table td:first-child { text-align: left; }
    .contrib-table thead th { color: var(--muted); font-weight: 600; }
    .contrib-table tbody tr.total-row td { font-weight: 600; }
```

If `--border` is not already defined in `:root`, the fallback `#2a2a2a` applies — no other change needed.

- [ ] **Step 4: Add the JS renderers**

Insert immediately before `function renderModes(` (~line 597):

```javascript
    function fmtShare(n, family) {
      if (n == null || !isFinite(n)) return "—";
      if (family === "expedition") return `${Number(n).toFixed(1)}%`;
      return Math.round(Number(n)).toLocaleString();
    }
    function contributionOf(row) {
      const totals = row && row.formation_totals;
      if (!totals || !totals.power) return null;
      return totals;
    }
    function renderContributionSummary(row) {
      const totals = contributionOf(row);
      if (!totals) return "";
      const family = row.stat_family || totals.family || "conquest";
      const p = totals.power;
      const bits = [
        `<span><span class="k">power</span> ${esc(Math.round(p.total).toLocaleString())}</span>`,
        `<span><span class="k">hero</span> ${esc(Math.round(p.hero).toLocaleString())}</span>`,
        `<span><span class="k">skills</span> ${esc(Math.round(p.skills).toLocaleString())}</span>`,
        `<span><span class="k">gear</span> ${esc(Math.round(p.gear).toLocaleString())}</span>`,
      ];
      const stats = Object.keys(totals.stats || {});
      const top = stats
        .map((label) => [label, totals.stats[label]])
        .filter(([, s]) => s && s.total > 0)
        .sort((a, b) => b[1].total - a[1].total)
        .slice(0, 3)
        .map(
          ([label, s]) =>
            `<span><span class="k">${esc(label)}</span> ${esc(fmtShare(s.total, family))}</span>`
        );
      const flags = [];
      if (totals.estimated) flags.push("estimated");
      if (totals.skills_incomplete) flags.push("skills partial");
      const note = flags.length
        ? `<span class="est">${esc(flags.join(" · "))}</span>`
        : "";
      return `<div class="contrib">${bits.concat(top).join("")}${note}</div>`;
    }
    function renderContributionTable(row) {
      const contributions = (row && row.contributions) || null;
      if (!contributions) return "";
      const family = row.stat_family || "conquest";
      const names = orderedHeroNames(row).filter((n) => contributions[n]);
      if (!names.length) return "";
      const labels = [];
      for (const name of names) {
        for (const label of Object.keys(contributions[name].stats || {})) {
          if (!labels.includes(label)) labels.push(label);
        }
      }
      const head =
        `<tr><th>hero</th><th>power</th>` +
        labels.map((l) => `<th>${esc(l)}</th>`).join("") +
        `</tr>`;
      const cell = (share) =>
        share
          ? `${esc(fmtShare(share.total, family))}` +
            `<br><span class="est">${esc(fmtShare(share.hero, family))} · ` +
            `${esc(fmtShare(share.skills, family))} · ` +
            `${esc(fmtShare(share.gear, family))}</span>`
          : "—";
      const rows = names
        .map((name) => {
          const c = contributions[name];
          return (
            `<tr><td>${esc(name)}</td>` +
            `<td>${esc(Math.round(c.power.total).toLocaleString())}` +
            `<br><span class="est">${esc(Math.round(c.power.hero).toLocaleString())} · ` +
            `${esc(Math.round(c.power.skills).toLocaleString())} · ` +
            `${esc(Math.round(c.power.gear).toLocaleString())}</span></td>` +
            labels.map((l) => `<td>${cell((c.stats || {})[l])}</td>`).join("") +
            `</tr>`
          );
        })
        .join("");
      const totals = contributionOf(row);
      const totalRow = totals
        ? `<tr class="total-row"><td>formation</td>` +
          `<td>${esc(Math.round(totals.power.total).toLocaleString())}</td>` +
          labels
            .map((l) => `<td>${esc(fmtShare(((totals.stats || {})[l] || {}).total, family))}</td>`)
            .join("") +
          `</tr>`
        : "";
      return (
        `<h3>Stat contributions · ${esc(family)}` +
        `<span class="est"> (hero · skills · gear)</span></h3>` +
        `<table class="contrib-table"><thead>${head}</thead>` +
        `<tbody>${rows}${totalRow}</tbody></table>`
      );
    }
```

`fmtShare` uses `Number.toFixed(1)` for expedition so percent points read as `81.9%`, and `toLocaleString()` for conquest flats.

- [ ] **Step 5: Call the renderers from the cards**

In `renderModes` (~line 616), insert the summary before the card hint:

```javascript
        card.innerHTML =
          `<h3>${esc(mode.replaceAll("_", " "))}</h3>` +
          `<div class="points">${esc(fmtPoints(row.expected_personal_points))} pts</div>` +
          `<p class="heroes"><strong>${esc(heroNames(row))}</strong></p>` +
          `<p class="troops">${esc(troopsLine(row))}</p>` +
          renderContributionSummary(row) +
          `<p class="card-hint">Click for why + gear + stat contributions</p>`;
```

In `renderFormationCard` (~line 664), insert it after `survHtml`:

```javascript
      card.innerHTML =
        `<h3>${esc(title)}</h3>` +
        `<div class="points">${scoreLine}</div>` +
        `<p class="formation">status: ${esc(row.status || "—")}</p>` +
        (ok ? `<div class="slot-row">${slots}</div>` : "") +
        survHtml +
        (ok ? renderContributionSummary(row) : "") +
        (ok
          ? `<p class="card-hint">Click for why + gear + survival + stat contributions</p>`
          : `<p class="heroes">${esc(row.error || "No optimal formation")}</p>`);
```

- [ ] **Step 6: Call the table from the modal**

In `openGearModal` (~line 572-588), insert the table between the survival block and the per-hero gear cards:

```javascript
      let contribHtml = "";
      try {
        contribHtml = renderContributionTable(row);
      } catch (e) {
        contribHtml =
          `<p class="heroes" style="color:var(--err)">Stat contributions unavailable</p>`;
      }
      if (!names.length) {
        body.innerHTML =
          (survHtml || "") + contribHtml ||
          '<p class="empty">No heroes in this result.</p>';
      } else {
        body.innerHTML =
          survHtml +
          contribHtml +
          names.map((name) => {
```

(the rest of the `names.map` body is unchanged)

- [ ] **Step 7: Run the tests**

Run: `pytest tests/test_heroes_optimize_ui.py -v`
Expected: PASS

- [ ] **Step 8: Verify in the running app**

Run:

```bash
python -m ks.heroes.cli ui --heroes data/heroes/full-run --gear data/gear/full-run
```

Open `http://127.0.0.1:8000/optimize/events`. Confirm: each Swordland/Bear mode card shows a `power / hero / skills / gear` line plus up to three top expedition percents; each Arena/Conquest card shows the same with conquest flats; clicking any card shows a "Stat contributions" table with one row per hero, a `formation` total row, and `hero · skills · gear` under each total. Stop the server when done.

- [ ] **Step 9: Commit**

```bash
git add ks/heroes/ui/templates/optimize_events.html tests/test_heroes_optimize_ui.py
git commit -m "feat(heroes-ui): show stat contributions on cards and detail modal"
```

---

## Task 9: Cross-optimiser wiring regression suite

**Worktree:** base worktree, after every wave is merged.

**Files:**
- Create: `tests/test_heroes_optimize_contributions_wiring.py`

**Interfaces:**
- Consumes: everything above. Produces no new production code.

- [ ] **Step 1: Write the test**

Create `tests/test_heroes_optimize_contributions_wiring.py`:

```python
"""Every optimiser surface derives strength from stat contributions.

These are wiring + invariant assertions, deliberately not frozen score
values — the whole point of the rewrite is that the numbers changed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ks.heroes.gear_models import GearRecord
from ks.heroes.models import HeroRecord
from ks.heroes.ui.optimize_run import run_optimize_bundle

_ROOT = Path(__file__).resolve().parents[1]
_SHARE_KEYS = {"hero", "skills", "gear", "total"}


def _load(path: Path, key: str, cls):
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw.get(key) if isinstance(raw, dict) else raw
    return [cls.from_dict(item) for item in items]


@pytest.fixture(scope="module")
def bundle() -> dict:
    heroes_path = _ROOT / "data" / "heroes" / "full-run" / "heroes.json"
    gear_path = _ROOT / "data" / "gear" / "full-run" / "gear.json"
    if not heroes_path.is_file() or not gear_path.is_file():
        pytest.skip("live scrape fixtures not present")
    heroes = _load(heroes_path, "heroes", HeroRecord)
    gear = _load(gear_path, "gear", GearRecord)
    return run_optimize_bundle(heroes, gear=gear, config_root=_ROOT)


def _check(contribution: dict) -> None:
    assert contribution["estimated"] is True
    assert set(contribution["power"]) == _SHARE_KEYS
    for block in [contribution["power"]] + list(contribution["stats"].values()):
        assert block["hero"] >= 0
        assert block["skills"] >= 0
        assert block["gear"] >= 0
        assert block["total"] == pytest.approx(
            block["hero"] + block["skills"] + block["gear"]
        )


def test_every_optimal_section_reports_contributions(bundle: dict) -> None:
    seen = 0
    for section in ("sword", "bear"):
        for row in (bundle[section].get("modes") or {}).values():
            assert row["stat_family"] == "expedition"
            _check(row["formation_totals"])
            for contrib in (row["contributions"] or {}).values():
                assert contrib["family"] == "expedition"
                _check(contrib)
            seen += 1
    for row in (bundle["arena"]["attack"], bundle["arena"]["defense"], bundle["conquest"]):
        if row.get("status") != "Optimal":
            continue
        assert row["stat_family"] == "conquest"
        _check(row["formation_totals"])
        for contrib in (row["contributions"] or {}).values():
            assert contrib["family"] == "conquest"
            _check(contrib)
        seen += 1
    assert seen >= 3, "expected at least three optimal sections to check"


def test_formation_totals_equal_sum_of_hero_contributions(bundle: dict) -> None:
    for row in (bundle["arena"]["attack"], bundle["conquest"]):
        if row.get("status") != "Optimal":
            continue
        totals = row["formation_totals"]
        contribs = list((row["contributions"] or {}).values())
        assert totals["power"]["total"] == pytest.approx(
            sum(c["power"]["total"] for c in contribs)
        )
        for label, share in totals["stats"].items():
            assert share["total"] == pytest.approx(
                sum((c["stats"].get(label) or {}).get("total", 0.0) for c in contribs)
            )


def test_no_scorer_still_uses_the_gear_bonus_heuristic() -> None:
    """Success criterion 4: naked power + heuristic gear bonus is gone."""
    optimize_dir = _ROOT / "ks" / "heroes" / "optimize"
    offenders = []
    for path in sorted(optimize_dir.glob("*.py")):
        if "gear_bonus" in path.read_text(encoding="utf-8"):
            offenders.append(path.name)
    assert offenders == [], f"heuristic gear bonus still referenced in {offenders}"
```

- [ ] **Step 2: Run the test**

Run: `pytest tests/test_heroes_optimize_contributions_wiring.py -v`
Expected: PASS (or `skip` on machines without the scrape fixtures)

- [ ] **Step 3: Run the full suite**

Run: `pytest -q`
Expected: PASS — all suites green.

- [ ] **Step 4: Commit**

```bash
git add tests/test_heroes_optimize_contributions_wiring.py
git commit -m "test(heroes): assert every optimiser reads stat contributions"
```

---

## Success criteria check

| Design criterion | Task |
|------------------|------|
| 1. Cards show formation-level hero/skills/gear totals for the correct family | 7 (payload), 8 (`renderContributionSummary`) |
| 2. Detail modal shows the same split per hero | 8 (`renderContributionTable`) |
| 3. Arena/Conquest/Swordland/Bear/Gear-XP derive strength from contributions | 3, 4, 5, 6 |
| 4. No scorer remains on naked power + heuristic gear bonus | 4 (removes `_provisional_gear_bonus`), 9 (guard test) |
