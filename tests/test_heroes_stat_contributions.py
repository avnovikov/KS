import pytest

from ks.heroes.gear_models import GearRecord, GearStats
from ks.heroes.models import HeroRecord, HeroStats, SkillRecord
from ks.heroes.optimize.stat_contributions import (
    CONQUEST,
    CONQUEST_LABELS,
    EXPEDITION,
    Share,
    StatContribution,
    contribution_strength,
    expedition_labels,
    family_for_event,
    formation_contribution,
    hero_contribution,
)
from ks.heroes.optimize.types import CatalogEntry, EffectTag


def _hero(**kw) -> HeroRecord:
    base = dict(
        name="Forrest",
        power=217855,
        troop_type="infantry",
        stars=3,
        pellets=0,
        stats=HeroStats(
            conquest={
                "Hero Attack": 1297,
                "Hero Defense": 1324,
                "Hero Health": 11889,
                "Escort Attack": 432,
                "Escort Defense": 441,
                "Escort Health": 3963,
            }
        ),
        skills=(
            SkillRecord(slot=2, upgrade_preview="Attack Up: 8%/12%", current_bonus=16.0),
            SkillRecord(slot=1, upgrade_preview="Defense Up: 25%/50%", current_bonus=50.0),
            SkillRecord(
                slot=3, upgrade_preview="Lethality Up:5%/10%", current_bonus=15.0
            ),
        ),
    )
    base.update(kw)
    return HeroRecord(**base)


def _piece(**kw) -> GearRecord:
    base = dict(
        piece_id="p1",
        name="Judicator's Armet",
        troop_type="infantry",
        slot="helmet",
        rarity="mythic",
        enhancement_level=57,
        power=134807,
        stats=GearStats(
            conquest={"Hero Attack": 385, "Hero Health": 1926},
            expedition={"Infantry Lethality": 41.94},
            lethality=41.94,
        ),
    )
    base.update(kw)
    return GearRecord(**base)


def test_family_for_event_maps_all_four_screens() -> None:
    assert family_for_event("arena") == CONQUEST
    assert family_for_event("conquest") == CONQUEST
    assert family_for_event("swordland") == EXPEDITION
    assert family_for_event("beartrap") == EXPEDITION


def test_family_for_event_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="unknown event"):
        family_for_event("hall_of_chiefs")


def test_share_total_is_sum_of_parts() -> None:
    share = Share(hero=10.0, skills=2.0, gear=3.0)
    assert share.total == pytest.approx(15.0)
    assert share.to_dict() == {
        "hero": 10.0,
        "skills": 2.0,
        "gear": 3.0,
        "total": 15.0,
    }


def test_expedition_labels_use_singular_archer_prefix() -> None:
    assert expedition_labels("archers") == (
        "Archer Attack",
        "Archer Defense",
        "Archer Health",
        "Archer Lethality",
    )
    assert expedition_labels("infantry")[0] == "Infantry Attack"


def test_conquest_split_backs_skills_out_of_naked_value() -> None:
    hero = _hero()
    # skill_effects.kind_family defaults "attack_up" to EXPEDITION when no
    # catalog says otherwise (see test_heroes_skill_effects.py); tag it
    # "conquest" here via the catalog override so this hero's scraped 16%
    # Attack Up counts toward the conquest split under test.
    entry = CatalogEntry(
        name="Forrest",
        troop="infantry",
        effects=(EffectTag("attack_up", 16.0, CONQUEST),),
    )
    catalog = {"Forrest": entry}
    c = hero_contribution(hero, entry, family=CONQUEST, catalog=catalog)
    attack = c.stats["Hero Attack"]
    # 16% attack skills → skills share is naked * 0.16 / 1.16.
    assert attack.skills == pytest.approx(1297 * 0.16 / 1.16)
    assert attack.hero == pytest.approx(1297 - attack.skills)
    assert attack.gear == 0.0
    assert attack.total == pytest.approx(1297.0)


def test_conquest_split_adds_gear_flats_on_top() -> None:
    hero = _hero()
    entry = CatalogEntry(name="Forrest", troop="infantry")
    c = hero_contribution(hero, entry, family=CONQUEST, gear_pieces=[_piece()])
    attack = c.stats["Hero Attack"]
    assert attack.gear == pytest.approx(385.0)
    assert attack.total == pytest.approx(1297.0 + 385.0)
    assert c.power.gear == pytest.approx(134807.0)
    assert c.power.hero == pytest.approx(217855.0)
    assert c.power.skills == 0.0


def test_every_conquest_label_present_even_when_scrape_missing() -> None:
    hero = _hero(stats=HeroStats(conquest={}))
    c = hero_contribution(hero, None, family=CONQUEST)
    assert tuple(c.stats) == CONQUEST_LABELS
    assert all(s.total == 0.0 for s in c.stats.values())


def test_expedition_split_uses_percent_points() -> None:
    hero = _hero()
    entry = CatalogEntry(name="Forrest", troop="infantry")
    c = hero_contribution(hero, entry, family=EXPEDITION, gear_pieces=[_piece()])
    assert c.stats["Infantry Attack"].skills == pytest.approx(16.0)
    assert c.stats["Infantry Defense"].skills == pytest.approx(50.0)
    assert c.stats["Infantry Lethality"].skills == pytest.approx(15.0)
    assert c.stats["Infantry Lethality"].gear == pytest.approx(41.94)
    assert c.stats["Infantry Attack"].hero == 0.0


def test_expedition_gear_falls_back_to_formula_when_ocr_missing() -> None:
    piece = _piece(stats=GearStats(conquest={}, expedition={}), slot="chest")
    hero = _hero()
    c = hero_contribution(
        hero, None, family=EXPEDITION, gear_pieces=[piece]
    )
    # chest → Health; mythic +57 formula fraction, expressed as percent points.
    assert c.stats["Infantry Health"].gear > 0.0


def test_shares_are_never_negative() -> None:
    # "Damage Up" maps to kind damage_up, which defaults to the conquest
    # family — so the extreme 900% actually reaches the conquest split.
    hero = _hero(
        stats=HeroStats(conquest={"Hero Attack": 10}),
        skills=(
            SkillRecord(slot=0, upgrade_preview="Damage Up: 900%", current_bonus=900.0),
        ),
    )
    c = hero_contribution(hero, None, family=CONQUEST)
    attack = c.stats["Hero Attack"]
    assert attack.skills > 0.0, "900% skill must actually reach the split"
    assert attack.skills < 10.0
    assert attack.hero >= 0.0
    assert attack.total == pytest.approx(10.0)


def test_gear_pieces_accepts_slot_mapping_from_assignment() -> None:
    as_list = hero_contribution(
        _hero(), None, family=CONQUEST, gear_pieces=[_piece()]
    )
    as_mapping = hero_contribution(
        _hero(), None, family=CONQUEST, gear_pieces={"helmet": _piece()}
    )
    assert as_mapping.power.gear == pytest.approx(as_list.power.gear)
    assert as_mapping.stats["Hero Attack"].gear == pytest.approx(
        as_list.stats["Hero Attack"].gear
    )


def test_skills_incomplete_flag_propagates() -> None:
    hero = _hero(skills=())
    c = hero_contribution(hero, None, family=CONQUEST)
    assert c.skills_incomplete is True
    assert c.estimated is True
    assert c.power.skills == 0.0
    assert c.power.hero == pytest.approx(217855.0)


def test_power_override_replaces_scraped_power() -> None:
    hero = _hero()
    c = hero_contribution(hero, None, family=CONQUEST, power=99_000)
    assert c.power.hero == pytest.approx(99_000.0)


def test_formation_contribution_sums_matching_labels() -> None:
    a = StatContribution(
        family=EXPEDITION,
        estimated=True,
        skills_incomplete=False,
        power=Share(1.0, 0.0, 2.0),
        stats={"Infantry Lethality": Share(0.0, 15.0, 41.94)},
    )
    b = StatContribution(
        family=EXPEDITION,
        estimated=True,
        skills_incomplete=True,
        power=Share(3.0, 0.0, 4.0),
        stats={
            "Infantry Lethality": Share(0.0, 10.0, 20.0),
            "Archer Health": Share(0.0, 5.0, 0.0),
        },
    )
    total = formation_contribution([a, b])
    assert total.power.hero == pytest.approx(4.0)
    assert total.power.gear == pytest.approx(6.0)
    assert total.stats["Infantry Lethality"].skills == pytest.approx(25.0)
    assert total.stats["Infantry Lethality"].gear == pytest.approx(61.94)
    assert total.stats["Archer Health"].skills == pytest.approx(5.0)
    assert total.skills_incomplete is True


def test_formation_contribution_rejects_mixed_families() -> None:
    a = StatContribution(CONQUEST, True, False, Share(0, 0, 0), {})
    b = StatContribution(EXPEDITION, True, False, Share(0, 0, 0), {})
    with pytest.raises(ValueError, match="same family"):
        formation_contribution([a, b])


def test_formation_contribution_of_empty_sequence_raises() -> None:
    with pytest.raises(ValueError, match="at least one"):
        formation_contribution([])


def test_contribution_strength_rises_with_gear() -> None:
    hero = _hero()
    bare = hero_contribution(hero, None, family=CONQUEST)
    geared = hero_contribution(hero, None, family=CONQUEST, gear_pieces=[_piece()])
    assert contribution_strength(geared) > contribution_strength(bare)


def test_contribution_strength_rises_with_expedition_percent() -> None:
    hero = _hero()
    bare = hero_contribution(hero, None, family=EXPEDITION)
    geared = hero_contribution(hero, None, family=EXPEDITION, gear_pieces=[_piece()])
    assert contribution_strength(geared) > contribution_strength(bare)


def test_to_dict_shape_matches_api_contract() -> None:
    c = hero_contribution(_hero(), None, family=CONQUEST)
    payload = c.to_dict()
    assert payload["family"] == CONQUEST
    assert payload["estimated"] is True
    assert set(payload["power"]) == {"hero", "skills", "gear", "total"}
    assert set(payload) == {
        "family",
        "estimated",
        "skills_incomplete",
        "power",
        "stats",
    }
    assert set(payload["stats"]["Hero Attack"]) == {
        "hero",
        "skills",
        "gear",
        "total",
    }
