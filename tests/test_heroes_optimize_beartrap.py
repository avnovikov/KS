from pathlib import Path

from ks.heroes.models import ExclusiveGearRecord, HeroRecord
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
    hero = HeroRecord(
        name="x",
        stars=5,
        exclusive_gear=ExclusiveGearRecord(level=10),
    )
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


def test_beartrap_rally_lead_uses_damage_simulator() -> None:
    from ks.heroes.optimize.bear_damage import BeartrapBuffs, load_beartrap_buffs
    from ks.heroes.optimize.troop_stats import load_troop_stats

    root = Path(__file__).resolve().parents[1]
    event = load_event_profile(root / "config" / "events" / "beartrap.yaml")
    scenarios = load_scenarios(root / "config" / "point_scenarios_beartrap.yaml")
    troop_stats = load_troop_stats(root / "config" / "troop_stats.yaml")
    buffs = load_beartrap_buffs(root / "config" / "beartrap_buffs.yaml")
    assert isinstance(buffs, BeartrapBuffs)

    heroes = [
        HeroRecord(name="Amadeus", power=2000, escorts=100, stars=5),
        HeroRecord(name="Petra", power=1800, escorts=100, stars=5),
        HeroRecord(name="Marlin", power=1700, escorts=100, stars=5),
    ]
    catalog = {
        "Amadeus": CatalogEntry(
            name="Amadeus",
            troop="infantry",
            widget_type="attack",
            rally_widget_priority=5,
            effects=(EffectTag("rally_attack", 15.0, "widget"),),
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
    }
    troops = TroopsConfig(
        infantry=30_000,
        cavalry=30_000,
        archers=40_000,
        march_capacity=18_000,
        infantry_levels=((6, 30_000),),
        cavalry_levels=((6, 30_000),),
        archers_levels=((6, 40_000),),
    )
    result = recommend(
        heroes,
        catalog,
        troops,
        scenarios,
        force_mode="rally_lead",
        event=event,
        troop_stats=troop_stats,
        beartrap_buffs=buffs,
    )
    assert result.recommended_mode == "rally_lead"
    assert "bear_damage" in result.breakdown
    assert result.breakdown["skillmod"] > 0
    assert result.troops["archers"] >= result.troops["infantry"]
    assert sum(result.troops.values()) == result.effective_capacity
    assert result.expected_personal_points == result.breakdown["bear_damage"]
    assert result.effective_capacity == 18_000 + 300  # escorts

def test_beartrap_skillmod_rises_with_host_lethality_up() -> None:
    """Host catalog DamageUp must raise rally_lead skillmod and score."""
    from ks.heroes.optimize.bear_damage import BeartrapBuffs, load_beartrap_buffs
    from ks.heroes.optimize.troop_stats import load_troop_stats

    root = Path(__file__).resolve().parents[1]
    event = load_event_profile(root / "config" / "events" / "beartrap.yaml")
    scenarios = load_scenarios(root / "config" / "point_scenarios_beartrap.yaml")
    troop_stats = load_troop_stats(root / "config" / "troop_stats.yaml")
    # No assumed joiners — isolate host SkillMod.
    buffs = BeartrapBuffs(trap_level=5, research_skillmod=1.0, assumed_joiners=())

    base_heroes = [
        HeroRecord(name="Amadeus", power=2000, escorts=100, stars=5),
        HeroRecord(name="Petra", power=1800, escorts=100, stars=5),
        HeroRecord(name="Marlin", power=1700, escorts=100, stars=5),
    ]
    catalog_base = {
        "Amadeus": CatalogEntry(
            name="Amadeus",
            troop="infantry",
            widget_type="attack",
            rally_widget_priority=5,
            effects=(EffectTag("rally_attack", 15.0, "widget"),),
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
    }
    catalog_boosted = {
        **catalog_base,
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
    }
    troops = TroopsConfig(
        infantry=30_000,
        cavalry=30_000,
        archers=40_000,
        march_capacity=18_000,
        infantry_levels=((6, 30_000),),
        cavalry_levels=((6, 30_000),),
        archers_levels=((6, 40_000),),
    )
    bare = recommend(
        base_heroes, catalog_base, troops, scenarios,
        force_mode="rally_lead", event=event, troop_stats=troop_stats,
        beartrap_buffs=buffs,
    )
    boosted = recommend(
        base_heroes, catalog_boosted, troops, scenarios,
        force_mode="rally_lead", event=event, troop_stats=troop_stats,
        beartrap_buffs=buffs,
    )
    assert boosted.breakdown["skillmod"] > bare.breakdown["skillmod"]
    assert boosted.expected_personal_points > bare.expected_personal_points
    assert boosted.breakdown["host_damage_up"].get("101", 0) >= 25.0

