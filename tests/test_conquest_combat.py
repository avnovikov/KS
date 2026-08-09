"""Conquest sim-lite scoring and hybrid skill ladders (OG-01)."""

from __future__ import annotations

import pytest

from ks.heroes.models import HeroRecord, HeroStats, SkillRecord
from ks.heroes.optimize.conquest_combat import conquest_hero_score
from ks.heroes.optimize.skill_effects import leveled_effect_value
from ks.heroes.optimize.types import CatalogEntry, CatalogSkill, EffectTag


def test_leveled_effect_value_uses_ladder() -> None:
    ladder = [160.0, 176.0, 192.0, 208.0, 224.0]
    assert leveled_effect_value(224.0, 1, ladder) == 160.0
    assert leveled_effect_value(224.0, 5, ladder) == 224.0


def test_leveled_effect_value_linear_fallback() -> None:
    assert leveled_effect_value(100.0, 5, None) == 100.0
    assert leveled_effect_value(100.0, 1, None) == 20.0


def _amadeus_entry(*, hits: int = 3) -> CatalogEntry:
    return CatalogEntry(
        name="Amadeus",
        rarity="legendary",
        effects=(
            EffectTag(kind="damage_up", max_value=224.0, applies_to="conquest"),
        ),
        skills=(
            CatalogSkill(
                slot=0,
                name="Combo Slash",
                family="conquest",
                effect_kind="damage_up",
                ladder=(160.0, 176.0, 192.0, 208.0, 224.0),
                hits_per_cast=hits,
            ),
        ),
    )


def _hero_with_level(level: int, *, attack: int = 10_000) -> HeroRecord:
    return HeroRecord(
        name="Amadeus",
        stars=5,
        power=1_000_000,
        skills=(SkillRecord(slot=0, name="Combo Slash", level=level),),
        stats=HeroStats(
            conquest={
                "Hero Attack": attack,
                "Hero Defense": 5_000,
                "Hero Health": 50_000,
            }
        ),
    )


def test_conquest_hero_score_scales_with_coeff_ladder() -> None:
    entry = _amadeus_entry()
    low = conquest_hero_score(_hero_with_level(1), entry)
    high = conquest_hero_score(_hero_with_level(5), entry)
    assert high.skill_dps > low.skill_dps
    assert high.score > low.score


def test_conquest_hero_score_multi_hit_scales_dps() -> None:
    one_hit = conquest_hero_score(_hero_with_level(5), _amadeus_entry(hits=1))
    three_hit = conquest_hero_score(_hero_with_level(5), _amadeus_entry(hits=3))
    assert three_hit.skill_dps == pytest.approx(one_hit.skill_dps * 3.0)


def test_aoe_kind_multiplies_by_aoe_targets() -> None:
    entry = CatalogEntry(
        name="Vivian",
        skills=(
            CatalogSkill(
                slot=0,
                name="Gilded Barrage",
                family="conquest",
                effect_kind="aoe_damage_up",
                ladder=(180.0, 198.0, 216.0, 234.0, 252.0),
                hits_per_cast=1,
            ),
        ),
        effects=(
            EffectTag(kind="aoe_damage_up", max_value=252.0, applies_to="conquest"),
        ),
    )
    hero = HeroRecord(
        name="Vivian",
        skills=(SkillRecord(slot=0, name="Gilded Barrage", level=5),),
        stats=HeroStats(
            conquest={"Hero Attack": 10_000, "Hero Defense": 1, "Hero Health": 1}
        ),
    )
    scored = conquest_hero_score(hero, entry, aoe_targets=2.0)
    assert scored.skill_dps == pytest.approx(50_400.0)


def test_enemy_damage_taken_amplifies_skill_dps() -> None:
    entry = CatalogEntry(
        name="Zoe",
        skills=(
            CatalogSkill(
                slot=0,
                name="Shield Strike",
                family="conquest",
                effect_kind="damage_up",
                ladder=(84.0, 84.0, 84.0, 84.0, 84.0),
            ),
            CatalogSkill(
                slot=1,
                name="Web Amp",
                family="conquest",
                effect_kind="enemy_damage_taken_up",
                ladder=(30.0, 30.0, 30.0, 30.0, 30.0),
            ),
        ),
        effects=(
            EffectTag(kind="damage_up", max_value=84.0, applies_to="conquest"),
            EffectTag(
                kind="enemy_damage_taken_up", max_value=30.0, applies_to="conquest"
            ),
        ),
    )
    hero = HeroRecord(
        name="Zoe",
        skills=(
            SkillRecord(slot=0, name="Shield Strike", level=5),
            SkillRecord(slot=1, name="Web Amp", level=5),
        ),
        stats=HeroStats(
            conquest={"Hero Attack": 10_000, "Hero Defense": 1, "Hero Health": 1}
        ),
    )
    scored = conquest_hero_score(hero, entry)
    assert scored.skill_dps == pytest.approx(10_920.0)


def test_catalog_loads_seeded_ultimate_ladders() -> None:
    from pathlib import Path

    from ks.heroes.optimize.catalog import load_catalog

    root = Path(__file__).resolve().parents[1]
    catalog = load_catalog(None, root / "config" / "hero_catalog.yaml")
    amadeus = catalog["Amadeus"].skills[0]
    assert amadeus.name == "Combo Slash"
    assert amadeus.ladder == (160.0, 176.0, 192.0, 208.0, 224.0)
    assert amadeus.hits_per_cast == 3
    vivian = next(s for s in catalog["Vivian"].skills if s.slot == 0)
    assert vivian.effect_kind == "aoe_damage_up"
    assert vivian.ladder == (180.0, 198.0, 216.0, 234.0, 252.0)
    petra = catalog["Petra"].skills[0]
    assert petra.ladder == (270.0, 297.0, 324.0, 351.0, 378.0)


def test_attack_up_raises_atk_eff_and_score() -> None:
    base_entry = CatalogEntry(
        name="Amadeus",
        rarity="legendary",
        effects=(
            EffectTag(kind="damage_up", max_value=224.0, applies_to="conquest"),
        ),
        skills=(
            CatalogSkill(
                slot=0,
                name="Combo Slash",
                family="conquest",
                effect_kind="damage_up",
                ladder=(224.0, 224.0, 224.0, 224.0, 224.0),
                hits_per_cast=3,
            ),
        ),
    )
    with_atk = CatalogEntry(
        name="Amadeus",
        rarity="legendary",
        effects=(
            EffectTag(kind="damage_up", max_value=224.0, applies_to="conquest"),
            EffectTag(kind="attack_up", max_value=48.0, applies_to="conquest"),
        ),
        skills=(
            CatalogSkill(
                slot=0,
                name="Combo Slash",
                family="conquest",
                effect_kind="damage_up",
                ladder=(224.0, 224.0, 224.0, 224.0, 224.0),
                hits_per_cast=3,
            ),
            CatalogSkill(
                slot=2,
                name="Onslaught",
                family="conquest",
                effect_kind="attack_up",
                ladder=(48.0, 48.0, 48.0, 48.0, 48.0),
            ),
        ),
    )
    hero_base = HeroRecord(
        name="Amadeus",
        skills=(SkillRecord(slot=0, name="Combo Slash", level=5),),
        stats=HeroStats(
            conquest={
                "Hero Attack": 10_000,
                "Hero Defense": 5_000,
                "Hero Health": 50_000,
            }
        ),
    )
    hero_buffed = HeroRecord(
        name="Amadeus",
        skills=(
            SkillRecord(slot=0, name="Combo Slash", level=5),
            SkillRecord(slot=2, name="Onslaught", level=5),
        ),
        stats=hero_base.stats,
    )
    plain = conquest_hero_score(hero_base, base_entry)
    buffed = conquest_hero_score(hero_buffed, with_atk)
    assert buffed.atk_eff > plain.atk_eff
    assert buffed.score > plain.score


def test_governor_defense_raises_toughness_and_score() -> None:
    from ks.heroes.governor_models import GovernorTroopBonuses

    entry = CatalogEntry(
        name="Amadeus",
        troop="infantry",
        rarity="legendary",
        effects=(
            EffectTag(kind="damage_up", max_value=224.0, applies_to="conquest"),
        ),
        skills=_amadeus_entry().skills,
    )
    hero = HeroRecord(
        name="Amadeus",
        stars=5,
        power=1_000_000,
        troop_type="infantry",
        skills=(SkillRecord(slot=0, name="Combo Slash", level=5),),
        stats=HeroStats(
            conquest={
                "Hero Attack": 10_000,
                "Hero Defense": 5_000,
                "Hero Health": 50_000,
                "Escort Defense": 4_000,
                "Escort Health": 20_000,
            }
        ),
    )
    gov = GovernorTroopBonuses(
        attack_pct={"infantry": 0.0, "cavalry": 0.0, "archers": 0.0},
        defense_pct={"infantry": 40.0, "cavalry": 0.0, "archers": 0.0},
        set_attack_pct=0.0,
        set_defense_pct=0.0,
        set_tier=None,
    )
    base = conquest_hero_score(hero, entry, governor=None)
    buffed = conquest_hero_score(hero, entry, governor=gov)
    assert buffed.toughness > base.toughness
    assert buffed.score > base.score
