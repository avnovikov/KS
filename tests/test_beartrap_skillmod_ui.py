"""Tests for lineup SkillMod detail (first-expedition Attack/Lethality)."""

from __future__ import annotations

from ks.heroes.models import HeroRecord
from ks.heroes.optimize.types import CatalogEntry, EffectTag


def _entry(*tags: EffectTag) -> CatalogEntry:
    return CatalogEntry(name="X", troop="cavalry", effects=tags)


def test_lineup_skillmod_detail_joiner_only_first_expedition() -> None:
    from ks.heroes.optimize.skillmod import lineup_skillmod_detail

    chenko = CatalogEntry(
        name="Chenko",
        troop="cavalry",
        effects=(
            EffectTag(
                kind="lethality_up",
                max_value=25.0,
                applies_to="expedition",
                effect_op=101,
                first_expedition=True,
            ),
            EffectTag(
                kind="damage_taken_down",
                max_value=20.0,
                applies_to="expedition",
                effect_op=111,
                first_expedition=False,
            ),
        ),
    )
    detail = lineup_skillmod_detail(
        ["Chenko"],
        {"Chenko": chenko},
        joiner_only=True,
    )
    assert detail["joiner_only"] is True
    assert detail["by_op"]["101"] == 25.0
    assert "111" not in detail["by_op"]
    assert abs(detail["damage_up"] - 1.25) < 1e-9
    assert detail["by_hero"][0]["name"] == "Chenko"
    assert detail["by_hero"][0]["kind"] == "lethality_up"


def test_lineup_skillmod_detail_stacks_same_op() -> None:
    from ks.heroes.optimize.skillmod import lineup_skillmod_detail

    a = _entry(
        EffectTag(
            kind="lethality_up",
            max_value=25.0,
            applies_to="expedition",
            effect_op=101,
            first_expedition=True,
        )
    )
    b = _entry(
        EffectTag(
            kind="lethality_up",
            max_value=25.0,
            applies_to="expedition",
            effect_op=101,
            first_expedition=True,
        )
    )
    a = CatalogEntry(name="A", troop="cavalry", effects=a.effects)
    b = CatalogEntry(name="B", troop="cavalry", effects=b.effects)
    detail = lineup_skillmod_detail(["A", "B"], {"A": a, "B": b}, joiner_only=True)
    assert detail["by_op"]["101"] == 50.0
    assert abs(detail["damage_up"] - 1.5) < 1e-9


def test_recommend_bear_joiner_includes_skillmod_detail() -> None:
    from pathlib import Path

    from ks.heroes.optimize.catalog import load_catalog
    from ks.heroes.optimize.events import load_event_profile
    from ks.heroes.optimize.recommend import recommend
    from ks.heroes.optimize.scenarios import load_scenarios
    from ks.heroes.optimize.troop_stats import load_troop_stats
    from ks.heroes.optimize.troops import load_troops_config

    root = Path(__file__).resolve().parents[1]
    catalog = load_catalog(None, root / "config" / "hero_catalog.yaml")
    # Prefer known first-expedition lethality hero if present
    names = [n for n, e in catalog.items() if any(
        t.kind == "lethality_up" and t.first_expedition for t in e.effects
    )][:1]
    assert names, "catalog needs a first-expedition lethality hero"
    # Build a minimal 3-troop roster around that hero
    need = {"infantry": None, "cavalry": None, "archers": None}
    for n, e in catalog.items():
        troop = (e.troop or "").lower().replace("archer", "archers")
        if troop == "archer":
            troop = "archers"
        if troop in need and need[troop] is None:
            need[troop] = n
        if all(need.values()):
            break
    heroes = [
        HeroRecord(
            name=n,
            troop_type=catalog[n].troop,
            rarity=catalog[n].rarity or "legendary",
            stars=5,
            pellets=0,
            power=1_000_000,
            level=50,
        )
        for n in need.values()
        if n
    ]
    result = recommend(
        heroes,
        catalog,
        load_troops_config(root / "config" / "troops.yaml"),
        load_scenarios(root / "config" / "point_scenarios_beartrap.yaml"),
        force_mode="joiner",
        event=load_event_profile(root / "config" / "events" / "beartrap.yaml"),
        troop_stats=load_troop_stats(root / "config" / "troop_stats.yaml"),
    )
    payload = result.to_dict()
    assert "skillmod_detail" in payload
    assert payload["skillmod_detail"]["joiner_only"] is True
    assert payload["skillmod_detail"]["damage_up"] >= 1.0
