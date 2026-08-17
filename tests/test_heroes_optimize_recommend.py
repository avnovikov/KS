import pytest

from ks.heroes.gear_models import GearRecord, GearStats
from ks.heroes.models import HeroRecord
from ks.heroes.optimize.recommend import recommend
from ks.heroes.optimize.types import CatalogEntry, EffectTag, Scenario, TroopsConfig


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
