import pytest

from ks.heroes.gear_models import GearRecord, GearStats
from ks.heroes.models import HeroRecord
from ks.heroes.optimize.recommend import recommend
from ks.heroes.optimize.types import CatalogEntry, EffectTag, EventProfile, Scenario, TroopsConfig


def _hero(name: str, *, power: int = 1000, escorts: int = 5) -> HeroRecord:
    return HeroRecord(name=name, power=power, escorts=escorts, stars=5)


def _cat(name: str, troop: str, widget: str, kind: str, value: float) -> CatalogEntry:
    return CatalogEntry(
        name=name,
        troop=troop,
        widget_type=widget,
        effects=(EffectTag(kind, value, "widget" if "rally" in kind or "defender" in kind else "expedition"),),
    )


def test_recommend_picks_garrison_for_defense_roster() -> None:
    heroes = [
        _hero("Zoe"),
        _hero("Saul"),
        _hero("Howard"),
        _hero("WeakAttack", power=10),
    ]
    catalog = {
        "Zoe": _cat("Zoe", "infantry", "defense", "defender_attack", 30),
        "Saul": _cat("Saul", "archer", "defense", "defense_up", 20),
        "Howard": _cat("Howard", "cavalry", "none", "damage_taken_down", 20),
        "WeakAttack": _cat("WeakAttack", "infantry", "attack", "rally_attack", 1),
    }
    troops = TroopsConfig(infantry=80, cavalry=40, archers=40, march_capacity=150)
    scenarios = {
        "garrison": Scenario(
            mode="garrison",
            combat_rate=40,
            minutes_held=40,
            personal_rate=600,
            enemy_power_scale=100000,
            require_widget="defense",
            formation_weights={"infantry": 1.2, "cavalry": 0.6, "archers": 0.8},
        ),
        "rally_lead": Scenario(
            mode="rally_lead",
            combat_rate=80,
            minutes_held=0,
            personal_rate=0,
            p_first=0.2,
            first_bonus=500,
            enemy_power_scale=100000,
            require_widget="attack",
            formation_weights={"infantry": 0.3, "cavalry": 0.6, "archers": 1.3},
        ),
    }
    result = recommend(heroes, catalog, troops, scenarios)
    assert result.recommended_mode == "garrison"
    assert result.expected_personal_points > 0
    assert len(result.heroes) == 3


def test_garrison_does_not_select_attack_widget_when_same_troop_alternative_exists() -> None:
    """Attack widgets only fire on rally lead — do not park Helga on garrison."""
    heroes = [
        _hero("Helga", power=250_000),
        _hero("Howard", power=380_000),
        _hero("Jabel"),
        _hero("Saul"),
    ]
    catalog = {
        "Helga": CatalogEntry(
            name="Helga",
            troop="infantry",
            widget_type="attack",
            rally_widget_priority=4,
            effects=(
                EffectTag("damage_taken_down", 50.0, "expedition", effect_op=111, first_expedition=True),
                EffectTag("attack_up", 25.0, "expedition"),
                EffectTag("lethality_up", 25.0, "expedition"),
                EffectTag("rally_lethality", 15.0, "widget"),
            ),
        ),
        "Howard": CatalogEntry(
            name="Howard",
            troop="infantry",
            widget_type="none",
            effects=(
                EffectTag("damage_taken_down", 20.0, "expedition", effect_op=111, first_expedition=True),
                EffectTag("opp_damage_down", 20.0, "expedition"),
            ),
        ),
        "Jabel": _cat("Jabel", "cavalry", "defense", "defender_attack", 15),
        "Saul": _cat("Saul", "archer", "defense", "defense_up", 25),
    }
    troops = TroopsConfig(infantry=80, cavalry=40, archers=40, march_capacity=150)
    scenarios = {
        "garrison": Scenario(
            mode="garrison",
            combat_rate=40,
            minutes_held=40,
            personal_rate=600,
            enemy_power_scale=100000,
            require_widget="defense",
        ),
    }
    result = recommend(heroes, catalog, troops, scenarios, force_mode="garrison")
    names = {h["name"] for h in result.heroes}
    assert "Howard" in names
    assert "Helga" not in names


def test_garrison_may_select_attack_widget_if_only_hero_of_that_troop() -> None:
    heroes = [_hero("Helga"), _hero("Jabel"), _hero("Saul")]
    catalog = {
        "Helga": CatalogEntry(
            name="Helga",
            troop="infantry",
            widget_type="attack",
            effects=(EffectTag("rally_lethality", 15.0, "widget"),),
        ),
        "Jabel": _cat("Jabel", "cavalry", "defense", "defender_attack", 15),
        "Saul": _cat("Saul", "archer", "defense", "defense_up", 25),
    }
    troops = TroopsConfig(infantry=80, cavalry=40, archers=40, march_capacity=150)
    scenarios = {
        "garrison": Scenario(
            mode="garrison",
            combat_rate=40,
            minutes_held=40,
            personal_rate=600,
            enemy_power_scale=100000,
            require_widget="defense",
        ),
    }
    result = recommend(heroes, catalog, troops, scenarios, force_mode="garrison")
    names = {h["name"] for h in result.heroes}
    assert names == {"Helga", "Jabel", "Saul"}


def test_recommend_force_mode() -> None:
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
        "rally_lead": Scenario(
            mode="rally_lead",
            combat_rate=80,
            require_widget="attack",
            enemy_power_scale=50000,
            formation_weights={"infantry": 1.0, "cavalry": 1.0, "archers": 1.0},
        ),
    }
    result = recommend(heroes, catalog, troops, scenarios, force_mode="rally_lead")
    assert result.recommended_mode == "rally_lead"
    assert [h["name"] for h in result.heroes][0] == "Amadeus"


def test_rally_lead_lists_attack_widget_first_even_when_name_sorts_last() -> None:
    """In-game march slot 1 is the rally lead; Helga must not trail Chenko/Diana."""
    heroes = [_hero("Chenko"), _hero("Diana"), _hero("Helga"), _hero("Howard")]
    catalog = {
        "Chenko": _cat("Chenko", "cavalry", "none", "attack_up", 20),
        "Diana": _cat("Diana", "archer", "none", "lethality_up", 20),
        "Helga": _cat("Helga", "infantry", "attack", "rally_lethality", 15),
        "Howard": _cat("Howard", "infantry", "none", "damage_taken_down", 20),
    }
    troops = TroopsConfig(infantry=80, cavalry=40, archers=40, march_capacity=150)
    scenarios = {
        "rally_lead": Scenario(
            mode="rally_lead",
            combat_rate=80,
            require_widget="attack",
            enemy_power_scale=50000,
            formation_weights={"infantry": 1.0, "cavalry": 1.0, "archers": 1.0},
        ),
    }
    result = recommend(heroes, catalog, troops, scenarios, force_mode="rally_lead")
    names = [h["name"] for h in result.heroes]
    assert names[0] == "Helga"
    assert set(names) == {"Helga", "Chenko", "Diana"}
    assert result.heroes[0]["widget_type"] == "attack"


def test_joiner_puts_best_first_expedition_hero_in_slot_one() -> None:
    """Bear Trap joiner only counts slot 1's first expedition skill."""
    from ks.heroes.optimize.model import order_march_hero_names

    ordered = order_march_hero_names(
        ["Amane", "Chenko", "Helga"],
        {"Amane": "none", "Chenko": "none", "Helga": "attack"},
        "joiner",
        strengths={"Chenko": 155.0, "Amane": 138.0, "Helga": 24.0},
    )
    assert ordered[0] == "Chenko"
    assert ordered == ("Chenko", "Amane", "Helga")


def test_beartrap_rally_lead_puts_chenko_ahead_of_helga_widget() -> None:
    """Bear Trap host captain is first-expedition lethality, not Helga's widget."""
    from ks.heroes.optimize.model import order_march_hero_names

    ordered = order_march_hero_names(
        ["Chenko", "Diana", "Helga"],
        {"Chenko": "none", "Diana": "none", "Helga": "attack"},
        "rally_lead",
        strengths={"Chenko": 155.0, "Diana": 73.0, "Helga": 24.0},
        event=EventProfile(name="beartrap"),
    )
    assert ordered[0] == "Chenko"
    assert ordered == ("Chenko", "Diana", "Helga")


def test_beartrap_joiner_recommend_lists_chenko_before_amane() -> None:
    """Alphabetical Amane-first would waste Chenko's lethality joiner skill."""
    from pathlib import Path

    from ks.heroes.optimize.events import load_event_profile
    from ks.heroes.optimize.scenarios import load_scenarios

    root = Path(__file__).resolve().parents[1]
    heroes = [
        _hero("Amane", power=400_000),
        _hero("Chenko", power=500_000),
        _hero("Helga", power=300_000),
    ]
    catalog = {
        "Amane": CatalogEntry(
            name="Amane",
            troop="archer",
            widget_type="none",
            effects=(
                EffectTag("attack_up", 25.0, "expedition", effect_op=102, first_expedition=True),
            ),
        ),
        "Chenko": CatalogEntry(
            name="Chenko",
            troop="cavalry",
            widget_type="none",
            effects=(
                EffectTag("lethality_up", 25.0, "expedition", effect_op=101, first_expedition=True),
            ),
        ),
        "Helga": CatalogEntry(
            name="Helga",
            troop="infantry",
            widget_type="attack",
            effects=(
                EffectTag(
                    "damage_taken_down",
                    50.0,
                    "expedition",
                    effect_op=111,
                    first_expedition=True,
                    proc_chance=0.4,
                ),
            ),
        ),
    }
    troops = TroopsConfig(infantry=80, cavalry=40, archers=40, march_capacity=150)
    scenarios = load_scenarios(root / "config" / "point_scenarios_beartrap.yaml")
    event = load_event_profile(root / "config" / "events" / "beartrap.yaml")
    result = recommend(
        heroes,
        catalog,
        troops,
        scenarios,
        force_mode="joiner",
        event=event,
    )
    names = [h["name"] for h in result.heroes]
    assert names[0] == "Chenko"
    assert set(names) == {"Chenko", "Amane", "Helga"}


def test_beartrap_rally_lead_recommend_lists_chenko_before_helga() -> None:
    """Helga's attack widget must not steal Bear Trap host slot 1 from Chenko."""
    from pathlib import Path

    from ks.heroes.optimize.events import load_event_profile
    from ks.heroes.optimize.scenarios import load_scenarios

    root = Path(__file__).resolve().parents[1]
    heroes = [
        _hero("Chenko", power=500_000),
        _hero("Diana", power=400_000),
        _hero("Helga", power=300_000),
    ]
    catalog = {
        "Chenko": CatalogEntry(
            name="Chenko",
            troop="cavalry",
            widget_type="none",
            effects=(
                EffectTag("lethality_up", 25.0, "expedition", effect_op=101, first_expedition=True),
            ),
        ),
        "Diana": CatalogEntry(
            name="Diana",
            troop="archer",
            widget_type="none",
            effects=(
                EffectTag("attack_up", 10.0, "expedition", effect_op=102, first_expedition=False),
            ),
        ),
        "Helga": CatalogEntry(
            name="Helga",
            troop="infantry",
            widget_type="attack",
            rally_widget_priority=4,
            effects=(
                EffectTag(
                    "damage_taken_down",
                    50.0,
                    "expedition",
                    effect_op=111,
                    first_expedition=True,
                    proc_chance=0.4,
                ),
                EffectTag("rally_lethality", 15.0, "widget"),
            ),
        ),
    }
    troops = TroopsConfig(infantry=80, cavalry=40, archers=40, march_capacity=150)
    scenarios = load_scenarios(root / "config" / "point_scenarios_beartrap.yaml")
    event = load_event_profile(root / "config" / "events" / "beartrap.yaml")
    result = recommend(
        heroes,
        catalog,
        troops,
        scenarios,
        force_mode="rally_lead",
        event=event,
    )
    names = [h["name"] for h in result.heroes]
    assert names[0] == "Chenko"
    assert set(names) == {"Chenko", "Diana", "Helga"}


def _piece(pid: str, troop: str, slot: str, lethality: float) -> GearRecord:
    prefix = "Archer" if troop == "archers" else troop.title()
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
            expedition={f"{prefix} Lethality": lethality},
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
    assert set(payload["formation_totals"]["power"]) == {
        "hero", "skills", "gear", "total"
    }
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


def test_recommend_formation_totals_are_share_weighted() -> None:
    """Expedition formation totals collapse to Attack/Defense/… weighted by
    troop ratio — not a raw sum of Infantry+Cavalry+Archer labels."""
    from ks.heroes.optimize.stat_contributions import (
        Share,
        StatContribution,
        formation_contribution,
    )

    payload = _run_recommend().to_dict()
    totals = payload["formation_totals"]
    rows = [r["contributions"] for r in payload["heroes"] if r.get("contributions")]
    assert totals["power"]["gear"] == pytest.approx(
        sum(c["power"]["gear"] for c in rows)
    )
    assert payload["stat_family"] == "expedition"
    for label in totals["stats"]:
        assert label in {"Attack", "Defense", "Health", "Lethality"}
    rebuilt = formation_contribution(
        [
            StatContribution(
                family="expedition",
                estimated=bool(c.get("estimated")),
                skills_incomplete=bool(c.get("skills_incomplete")),
                power=Share(
                    c["power"]["hero"], c["power"]["skills"], c["power"]["gear"]
                ),
                stats={
                    lab: Share(s["hero"], s["skills"], s["gear"])
                    for lab, s in c["stats"].items()
                },
            )
            for c in rows
        ],
        troop_shares=payload.get("ratios"),
    ).to_dict()
    assert totals["stats"] == rebuilt["stats"]
