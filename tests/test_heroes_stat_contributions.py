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
    weighted_expedition_totals,
)
from ks.heroes.optimize.types import CatalogEntry


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
    # No catalog needed: the conquest split trusts _CONQUEST_KIND_LABELS's
    # own key set for which skill kinds count, not skill_effects.kind_family
    # (which would default "attack_up" to EXPEDITION absent a catalog
    # override — an override no real hero's catalog entry ever provides;
    # see test_conquest_split_counts_defense_up_without_a_catalog_override).
    hero = _hero()
    c = hero_contribution(hero, None, family=CONQUEST)
    attack = c.stats["Hero Attack"]
    # 16% attack skills → skills share is naked * 0.16 / 1.16.
    assert attack.skills == pytest.approx(1297 * 0.16 / 1.16)
    assert attack.hero == pytest.approx(1297 - attack.skills)
    assert attack.gear == 0.0
    assert attack.total == pytest.approx(1297.0)


def test_conquest_split_counts_defense_up_without_a_catalog_override() -> None:
    """config/hero_catalog.yaml never tags defense_up/health_up/
    damage_taken_down/opp_damage_down as conquest for any hero — every
    occurrence is "expedition" — so kind_family's catalog lookup can never
    actually let these kinds through family_percents(family=CONQUEST). A
    Defense Up skill has to count toward the conquest split on its own
    merits (stat_contributions.py's own _CONQUEST_KIND_LABELS already maps
    it to Hero/Escort Defense), not only when some catalog entry happens to
    override it — which in practice never happens."""
    hero = _hero()  # default skills include "Defense Up: 25%/50%" -> 50.0
    c = hero_contribution(hero, None, family=CONQUEST)
    defense = c.stats["Hero Defense"]
    assert defense.skills == pytest.approx(1324 * 0.50 / 1.50)
    assert defense.hero == pytest.approx(1324 - defense.skills)
    escort_defense = c.stats["Escort Defense"]
    assert escort_defense.skills == pytest.approx(441 * 0.50 / 1.50)


def test_conquest_split_counts_health_and_damage_taken_skills_without_a_catalog_override() -> None:
    hero = _hero(
        skills=(
            SkillRecord(slot=0, upgrade_preview="Health Up: 10%/20%", current_bonus=20.0),
            SkillRecord(
                slot=1, upgrade_preview="Damage Taken Down: 10%/20%", current_bonus=20.0
            ),
            SkillRecord(
                slot=2,
                upgrade_preview="Enemy Troops Attack Down: 10%/20%",
                current_bonus=20.0,
            ),
        )
    )
    c = hero_contribution(hero, None, family=CONQUEST)
    health = c.stats["Hero Health"]
    assert health.skills == pytest.approx(11889 * 0.20 / 1.20)
    # damage_taken_down (20%) and opp_damage_down (20%) both lift Hero/Escort
    # Defense — combined percent is 40%, not 20%.
    defense = c.stats["Hero Defense"]
    assert defense.skills == pytest.approx(1324 * 0.40 / 1.40)


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
    # Attack Up maps into Hero Attack flats; extreme percent must clamp so
    # skills share stays below the naked flat (multiplicative split).
    hero = _hero(
        stats=HeroStats(conquest={"Hero Attack": 10}),
        skills=(
            SkillRecord(slot=0, upgrade_preview="Attack Up: 900%", current_bonus=900.0),
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


def test_weighted_expedition_totals_are_share_weighted() -> None:
    """Unit Attack/Defense/… collapse to Σ (troop% × share); not a raw sum."""
    stats = {
        "Infantry Attack": Share(40.0, 0.0, 0.0),
        "Cavalry Attack": Share(100.0, 0.0, 0.0),
        "Archer Attack": Share(10.0, 0.0, 0.0),
    }
    out = weighted_expedition_totals(
        stats, {"infantry": 0.5, "cavalry": 0.1, "archers": 0.4}
    )
    # 40*0.5 + 100*0.1 + 10*0.4 = 34
    assert out["Attack"].total == pytest.approx(34.0)
    assert "Infantry Attack" not in out


def test_formation_contribution_sums_power_and_weights_unit_stats() -> None:
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
    # Equal weight over infantry + archers present in the lineup.
    total = formation_contribution([a, b])
    assert total.power.hero == pytest.approx(4.0)
    assert total.power.gear == pytest.approx(6.0)
    # Inf Lethality summed 86.94, then × 0.5 → 43.47; Arch Health 5 × 0.5 → 2.5
    assert total.stats["Lethality"].total == pytest.approx(43.47)
    assert total.stats["Health"].skills == pytest.approx(2.5)
    assert "Infantry Lethality" not in total.stats
    assert total.skills_incomplete is True


def test_formation_contribution_weights_by_troop_share() -> None:
    a = StatContribution(
        family=EXPEDITION,
        estimated=False,
        skills_incomplete=False,
        power=Share(0, 0, 0),
        stats={
            "Infantry Attack": Share(40.0, 0.0, 0.0),
            "Cavalry Attack": Share(100.0, 0.0, 0.0),
            "Archer Attack": Share(10.0, 0.0, 0.0),
        },
    )
    total = formation_contribution(
        [a],
        troop_shares={"infantry": 0.5, "cavalry": 0.1, "archers": 0.4},
    )
    assert total.stats["Attack"].total == pytest.approx(34.0)
    assert "Infantry Attack" not in total.stats


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
