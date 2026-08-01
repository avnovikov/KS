"""Tests for star+pellet factor and best-in-class gear assignment."""

from ks.heroes.gear_models import GearRecord, GearStats
from ks.heroes.models import HeroRecord
from ks.heroes.optimize.gear_assign import (
    assign_best_sets,
    assign_exclusive_sets,
    best_sets_by_troop,
    piece_score,
)
from ks.heroes.optimize.scoring import hero_strength, star_progress_factor
from ks.heroes.optimize.types import CatalogEntry, EffectTag


def test_star_progress_factor_includes_pellets() -> None:
    assert star_progress_factor(2, 0) < star_progress_factor(2, 3)
    assert star_progress_factor(2, 6) == star_progress_factor(3, 0)
    assert star_progress_factor(None, None) == 0.5


def test_hero_strength_uses_pellets() -> None:
    entry = CatalogEntry(
        name="Chenko",
        troop="cavalry",
        effects=[EffectTag("lethality_up", 100.0, "expedition", first_expedition=True)],
    )
    low = HeroRecord(name="Chenko", stars=2, pellets=0)
    high = HeroRecord(name="Chenko", stars=2, pellets=5)
    assert hero_strength(high, entry, "joiner") > hero_strength(low, entry, "joiner")


def test_best_sets_picks_highest_score_per_slot() -> None:
    pieces = [
        GearRecord(
            piece_id="a",
            name="Mythic Helm",
            troop_type="archers",
            slot="helmet",
            stats=GearStats(lethality=30.0, expedition={"Archer Lethality": 30.0}),
        ),
        GearRecord(
            piece_id="b",
            name="Weak Helm",
            troop_type="archers",
            slot="helmet",
            stats=GearStats(lethality=10.0, expedition={"Archer Lethality": 10.0}),
        ),
        GearRecord(
            piece_id="c",
            name="Boots",
            troop_type="archers",
            slot="boots",
            stats=GearStats(lethality=20.0, expedition={"Archer Lethality": 20.0}),
        ),
    ]
    sets = best_sets_by_troop(pieces, profile="early_game_growth")
    assert sets["archers"]["helmet"].piece_id == "a"
    assert sets["archers"]["boots"].piece_id == "c"
    assert piece_score(pieces[0], profile="early_game_growth") > piece_score(
        pieces[1], profile="early_game_growth"
    )


def test_assign_best_sets_maps_selected_heroes() -> None:
    pieces = [
        GearRecord(
            piece_id="helm",
            name="Inf Helm",
            troop_type="infantry",
            slot="helmet",
            power=1000,
            stats=GearStats(lethality=5.0),
        ),
    ]
    heroes = [
        HeroRecord(name="Helga"),
        HeroRecord(name="Amane"),
        HeroRecord(name="Chenko"),
    ]
    catalog = {
        "Helga": CatalogEntry(name="Helga", troop="infantry"),
        "Amane": CatalogEntry(name="Amane", troop="archers"),
        "Chenko": CatalogEntry(name="Chenko", troop="cavalry"),
    }
    assigned = assign_best_sets(
        heroes, catalog, pieces, selected=["Helga", "Amane", "Chenko"]
    )
    assert "Helga" in assigned
    assert assigned["Helga"]["helmet"].piece_id == "helm"
    assert assigned["Amane"] == {}


def test_assign_exclusive_sets_does_not_double_book() -> None:
    pieces = [
        GearRecord(
            piece_id="best",
            name="Best Helm",
            troop_type="cavalry",
            slot="helmet",
            power=9000,
            stats=GearStats(lethality=30.0),
        ),
        GearRecord(
            piece_id="ok",
            name="Ok Helm",
            troop_type="cavalry",
            slot="helmet",
            power=1000,
            stats=GearStats(lethality=5.0),
        ),
    ]
    heroes = [
        HeroRecord(name="Jabel"),
        HeroRecord(name="Chenko"),
    ]
    catalog = {
        "Jabel": CatalogEntry(name="Jabel", troop="cavalry"),
        "Chenko": CatalogEntry(name="Chenko", troop="cavalry"),
    }
    assigned = assign_exclusive_sets(
        heroes,
        catalog,
        pieces,
        selected=["Jabel", "Chenko"],
        priority=["Jabel", "Chenko"],
        profile="early_game_combat",
    )
    assert assigned["Jabel"]["helmet"].piece_id == "best"
    assert assigned["Chenko"]["helmet"].piece_id == "ok"
