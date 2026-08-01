from pathlib import Path

from ks.heroes.models import HeroRecord
from ks.heroes.optimize.events import load_event_profile
from ks.heroes.optimize.recommend import recommend
from ks.heroes.optimize.scenarios import load_scenarios
from ks.heroes.optimize.scoring import hero_strength
from ks.heroes.optimize.types import CatalogEntry, EffectTag, TroopsConfig


def test_beartrap_joiner_prefers_chenkos_over_howard() -> None:
    root = Path(__file__).resolve().parents[1]
    event = load_event_profile(root / "config" / "events" / "beartrap.yaml")
    chenko = CatalogEntry(
        name="Chenko",
        widget_type="none",
        effects=(
            EffectTag(
                "lethality_up",
                25.0,
                "expedition",
                effect_op=101,
                first_expedition=True,
            ),
        ),
    )
    howard = CatalogEntry(
        name="Howard",
        widget_type="none",
        effects=(
            EffectTag(
                "damage_taken_down",
                20.0,
                "expedition",
                effect_op=111,
                first_expedition=True,
            ),
        ),
    )
    hero = HeroRecord(name="x", stars=5)
    assert hero_strength(hero, chenko, "joiner", event=event) > hero_strength(
        hero, howard, "joiner", event=event
    )


def test_beartrap_starter_prefers_attack_widget() -> None:
    root = Path(__file__).resolve().parents[1]
    event = load_event_profile(root / "config" / "events" / "beartrap.yaml")
    amadeus = CatalogEntry(
        name="Amadeus",
        widget_type="attack",
        rally_widget_priority=5,
        effects=(
            EffectTag("rally_attack", 15.0, "widget"),
            EffectTag(
                "lethality_up",
                25.0,
                "expedition",
                effect_op=101,
                first_expedition=True,
            ),
        ),
    )
    zoe = CatalogEntry(
        name="Zoe",
        widget_type="defense",
        garrison_widget_priority=5,
        effects=(
            EffectTag("defender_attack", 15.0, "widget"),
            EffectTag("attack_up", 25.0, "expedition", effect_op=102, first_expedition=True),
        ),
    )
    hero = HeroRecord(name="x", stars=5)
    assert hero_strength(hero, amadeus, "rally_lead", event=event) > hero_strength(
        hero, zoe, "rally_lead", event=event
    )


def test_beartrap_recommend_only_starter_or_joiner() -> None:
    root = Path(__file__).resolve().parents[1]
    event = load_event_profile(root / "config" / "events" / "beartrap.yaml")
    scenarios = load_scenarios(root / "config" / "point_scenarios_beartrap.yaml")
    assert set(scenarios) == {"rally_lead", "joiner"}

    heroes = [
        HeroRecord(name="Amadeus", power=2000, escorts=10, stars=5),
        HeroRecord(name="Petra", power=1800, escorts=10, stars=5),
        HeroRecord(name="Marlin", power=1700, escorts=10, stars=5),
        HeroRecord(name="Chenko", power=900, escorts=5, stars=5),
        HeroRecord(name="Amane", power=850, escorts=5, stars=5),
        HeroRecord(name="Howard", power=800, escorts=5, stars=5),
    ]
    catalog = {
        "Amadeus": CatalogEntry(
            name="Amadeus",
            troop="infantry",
            widget_type="attack",
            rally_widget_priority=5,
            effects=(
                EffectTag("rally_attack", 15.0, "widget"),
                EffectTag(
                    "lethality_up",
                    25.0,
                    "expedition",
                    effect_op=101,
                    first_expedition=True,
                ),
            ),
        ),
        "Petra": CatalogEntry(
            name="Petra",
            troop="cavalry",
            widget_type="attack",
            rally_widget_priority=4,
            effects=(EffectTag("rally_attack", 15.0, "widget"),),
        ),
        "Marlin": CatalogEntry(
            name="Marlin",
            troop="archer",
            widget_type="attack",
            rally_widget_priority=3,
            effects=(EffectTag("rally_lethality", 15.0, "widget"),),
        ),
        "Chenko": CatalogEntry(
            name="Chenko",
            troop="cavalry",
            widget_type="none",
            effects=(
                EffectTag(
                    "lethality_up",
                    25.0,
                    "expedition",
                    effect_op=101,
                    first_expedition=True,
                ),
            ),
        ),
        "Amane": CatalogEntry(
            name="Amane",
            troop="archer",
            widget_type="none",
            effects=(
                EffectTag(
                    "attack_up",
                    25.0,
                    "expedition",
                    effect_op=102,
                    first_expedition=True,
                ),
            ),
        ),
        "Howard": CatalogEntry(
            name="Howard",
            troop="infantry",
            widget_type="none",
            effects=(
                EffectTag(
                    "damage_taken_down",
                    20.0,
                    "expedition",
                    effect_op=111,
                    first_expedition=True,
                ),
            ),
        ),
    }
    troops = TroopsConfig(infantry=80, cavalry=40, archers=40, march_capacity=150)
    result = recommend(heroes, catalog, troops, scenarios, event=event)
    assert result.recommended_mode in {"rally_lead", "joiner"}
    assert result.expected_personal_points > 0
