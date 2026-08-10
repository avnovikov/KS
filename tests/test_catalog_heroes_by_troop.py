"""Tests for catalog heroes_by_troop grouping."""

from __future__ import annotations

from ks.heroes.optimize.catalog import heroes_by_troop
from ks.heroes.optimize.types import CatalogEntry


def _entry(name: str, troop: str | None) -> CatalogEntry:
    return CatalogEntry(name=name, troop=troop)


def test_heroes_by_troop_normalizes_archer_and_sorts() -> None:
    catalog = {
        "Diana": _entry("Diana", "archer"),
        "Helga": _entry("Helga", "infantry"),
        "Jabel": _entry("Jabel", "cavalry"),
        "Quinn": _entry("Quinn", "archers"),
        "NoTroop": _entry("NoTroop", None),
    }
    grouped = heroes_by_troop(catalog)
    assert grouped["infantry"] == ["Helga"]
    assert grouped["cavalry"] == ["Jabel"]
    assert grouped["archers"] == ["Diana", "Quinn"]
    assert "NoTroop" not in grouped["infantry"]


def test_heroes_by_troop_uses_roster_fallback() -> None:
    catalog = {
        "Amadeus": _entry("Amadeus", None),
        "Helga": _entry("Helga", "infantry"),
    }
    grouped = heroes_by_troop(
        catalog, roster_troop={"Amadeus": "cavalry", "Helga": "archers"}
    )
    # Catalog troop wins over roster when set.
    assert grouped["infantry"] == ["Helga"]
    assert grouped["cavalry"] == ["Amadeus"]
