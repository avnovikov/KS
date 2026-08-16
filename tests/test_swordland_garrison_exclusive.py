"""Swordland Garrison excludes Rally Lead heroes."""

from __future__ import annotations

from pathlib import Path

from ks.heroes.models import HeroRecord
from ks.heroes.optimize.catalog import load_catalog
from ks.heroes.ui.optimize_run import _event_bundle


ROOT = Path(__file__).resolve().parents[1]


def _hero(name: str, troop: str) -> HeroRecord:
    return HeroRecord(
        name=name,
        troop_type=troop,
        rarity="legendary",
        stars=5,
        pellets=0,
        power=1_000_000,
        level=50,
    )


def _roster_from_catalog(min_per_troop: int = 3) -> list[HeroRecord]:
    catalog = load_catalog(None, ROOT / "config" / "hero_catalog.yaml")
    by_troop: dict[str, list[str]] = {"infantry": [], "cavalry": [], "archers": [], "archer": []}
    for name, entry in catalog.items():
        troop = (entry.troop or "").lower()
        if troop in by_troop and len(by_troop[troop]) < min_per_troop:
            by_troop[troop].append(name)
    names: list[str] = []
    for key in ("infantry", "cavalry"):
        names.extend(by_troop[key])
    names.extend(by_troop["archers"] or by_troop["archer"])
    assert len(by_troop["infantry"]) >= 2
    assert len(by_troop["cavalry"]) >= 2
    assert (by_troop["archers"] or by_troop["archer"])
    return [
        _hero(n, catalog[n].troop or "infantry")
        for n in names
        if n in catalog
    ]


def test_swordland_garrison_excludes_rally_lead_heroes() -> None:
    heroes = _roster_from_catalog()
    catalog = load_catalog(None, ROOT / "config" / "hero_catalog.yaml")
    section = _event_bundle(
        "Swordland",
        heroes,
        catalog,
        troops_path=ROOT / "config" / "troops.yaml",
        event_path=ROOT / "config" / "events" / "swordland.yaml",
        scenarios_path=ROOT / "config" / "point_scenarios.yaml",
        troop_stats_path=ROOT / "config" / "troop_stats.yaml",
        gear=None,
        gear_profile="early_game_growth",
    )
    modes = section["modes"]
    assert "rally_lead" in modes
    assert "garrison" in modes
    lead = {h["name"] for h in modes["rally_lead"]["heroes"]}
    garrison = {h["name"] for h in modes["garrison"]["heroes"]}
    assert lead, "expected a Rally Lead lineup"
    assert garrison, "expected a Garrison lineup"
    assert lead.isdisjoint(garrison), f"overlap={lead & garrison}"
