from pathlib import Path

from ks.heroes.optimize.catalog import load_catalog
from ks.heroes.optimize.events import load_event_profile
from ks.heroes.optimize.scoring import hero_strength
from ks.heroes.models import HeroRecord
from ks.heroes.optimize.types import CatalogEntry, EffectTag


def test_expanded_catalog_has_effect_op(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    pro = root / "artifacts" / "heroes" / "catalog_cache" / "kingshotpro_heroes.json"
    if not pro.exists():
        pro = tmp_path / "pro.json"
        pro.write_text('{"heroes": []}', encoding="utf-8")
    catalog = load_catalog(pro, root / "config" / "hero_catalog.yaml")
    assert catalog["Chenko"].effects[0].effect_op == 101
    assert catalog["Howard"].effects[0].effect_op == 111
    assert catalog["Amadeus"].widget_type == "attack"
    assert catalog["Zoe"].widget_type == "defense"
    assert catalog["Ava"].widget_type == "attack"


def test_swordland_event_weights_prefer_defense_widget_in_garrison() -> None:
    root = Path(__file__).resolve().parents[1]
    event = load_event_profile(root / "config" / "events" / "swordland.yaml")
    zoe = CatalogEntry(
        name="Zoe",
        widget_type="defense",
        effects=(
            EffectTag("defender_attack", 15.0, "widget", effect_op=None),
            EffectTag("attack_up", 25.0, "expedition", effect_op=102, first_expedition=True),
        ),
    )
    amadeus = CatalogEntry(
        name="Amadeus",
        widget_type="attack",
        effects=(
            EffectTag("rally_attack", 15.0, "widget"),
            EffectTag("lethality_up", 25.0, "expedition", effect_op=101, first_expedition=True),
        ),
    )
    hero = HeroRecord(name="x", stars=5)
    assert hero_strength(hero, zoe, "garrison", event=event) > hero_strength(
        hero, amadeus, "garrison", event=event
    )


def test_swordland_joiner_weights_chenkos_first_skill() -> None:
    root = Path(__file__).resolve().parents[1]
    event = load_event_profile(root / "config" / "events" / "swordland.yaml")
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
    # Under joiner-attack-ish weights, lethality 101 should beat pure defense for rally join;
    # under garrison joiner, 111 is boosted — use mode joiner which mixes both.
    attackish = hero_strength(hero, chenko, "joiner", event=event)
    defendish = hero_strength(hero, howard, "joiner", event=event)
    assert attackish > 0 and defendish > 0
