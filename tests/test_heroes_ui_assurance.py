"""TDD tests: update_hero_stars sets FieldAssurance on changed fields."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ks.heroes.assurance import FieldAssurance
from ks.heroes.models import HeroRecord
from ks.heroes.store import HeroStore


def _seed(tmp_path: Path, **overrides) -> HeroStore:
    defaults = dict(
        name="Helga",
        power=100_000,
        troop_type="infantry",
        rarity="legendary",
        stars=2,
        pellets=0,
        roster_page=0,
        roster_index=0,
        scraped_at="2026-08-04T00:00:00Z",
    )
    defaults.update(overrides)
    store = HeroStore(tmp_path)
    store.upsert(HeroRecord(**defaults))  # type: ignore[arg-type]
    return store


def _reload_hero(store: HeroStore, name: str) -> HeroRecord:
    store.reload()
    return next(h for h in store.all_heroes() if h.name == name)


# ---------------------------------------------------------------------------
# Explicit power PATCH → high / manual_confirm
# ---------------------------------------------------------------------------


def test_patch_power_sets_high_manual(tmp_path: Path) -> None:
    from ks.heroes.ui.app import update_hero_stars

    store = _seed(
        tmp_path,
        power=100_000,
        assurance={"power": FieldAssurance("medium", "roster_ocr")},
    )
    updated = update_hero_stars(store, "Helga", power=238_487)

    assert updated.assurance["power"] == FieldAssurance("high", "manual_confirm")


def test_patch_power_persisted_assurance(tmp_path: Path) -> None:
    from ks.heroes.ui.app import update_hero_stars

    store = _seed(tmp_path, power=100_000)
    update_hero_stars(store, "Helga", power=238_487)

    raw = json.loads((tmp_path / "heroes.json").read_text(encoding="utf-8"))
    row = next(h for h in raw["heroes"] if h["name"] == "Helga")
    assert row["assurance"]["power"]["level"] == "high"
    assert row["assurance"]["power"]["reason"] == "manual_confirm"


# ---------------------------------------------------------------------------
# Stars change without explicit power → power scaled, medium / scaled_from_stars
# ---------------------------------------------------------------------------


def test_star_change_scales_power_medium(tmp_path: Path) -> None:
    from ks.heroes.ui.app import update_hero_stars

    store = _seed(tmp_path, power=100_000, stars=2, pellets=0)
    updated = update_hero_stars(store, "Helga", stars=3)

    assert updated.stars == 3
    assert updated.power != 100_000, "power must have been rescaled"
    assert updated.assurance["power"].reason == "scaled_from_stars"
    assert updated.assurance["power"].level == "medium"
    assert updated.assurance["stars"].reason == "manual_confirm"
    assert updated.assurance["stars"].level == "high"


def test_pellet_change_scales_power_medium(tmp_path: Path) -> None:
    from ks.heroes.ui.app import update_hero_stars

    store = _seed(tmp_path, power=100_000, stars=3, pellets=0)
    updated = update_hero_stars(store, "Helga", pellets=2)

    assert updated.assurance["power"].reason == "scaled_from_stars"
    assert updated.assurance["pellets"].reason == "manual_confirm"


# ---------------------------------------------------------------------------
# Explicit power + stars → power gets high / manual_confirm (explicit wins)
# ---------------------------------------------------------------------------


def test_explicit_power_beats_scaled_assurance(tmp_path: Path) -> None:
    from ks.heroes.ui.app import update_hero_stars

    store = _seed(tmp_path, power=100_000, stars=2, pellets=0)
    updated = update_hero_stars(store, "Helga", stars=3, power=250_000)

    assert updated.assurance["power"] == FieldAssurance("high", "manual_confirm")
    assert updated.assurance["stars"].reason == "manual_confirm"


# ---------------------------------------------------------------------------
# Explicit level PATCH → level high / manual_confirm
# ---------------------------------------------------------------------------


def test_patch_level_sets_high_manual(tmp_path: Path) -> None:
    from ks.heroes.ui.app import update_hero_stars

    store = _seed(tmp_path)
    updated = update_hero_stars(store, "Helga", level=57)

    assert updated.assurance["level"] == FieldAssurance("high", "manual_confirm")


# ---------------------------------------------------------------------------
# Other assurance keys are preserved when unrelated fields change
# ---------------------------------------------------------------------------


def test_unchanged_field_assurance_preserved(tmp_path: Path) -> None:
    from ks.heroes.ui.app import update_hero_stars

    store = _seed(
        tmp_path,
        assurance={
            "power": FieldAssurance("high", "manual_confirm"),
            "stars": FieldAssurance("medium", "roster_ocr"),
        },
    )
    updated = update_hero_stars(store, "Helga", level=30)

    assert updated.assurance["power"] == FieldAssurance("high", "manual_confirm")
    assert updated.assurance["level"] == FieldAssurance("high", "manual_confirm")
