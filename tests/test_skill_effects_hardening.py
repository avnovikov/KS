"""OG-07: expedition kind links, utility exclusion, joiner effect_op stacking."""

from __future__ import annotations

import pytest

from ks.heroes.models import HeroRecord, SkillRecord
from ks.heroes.optimize.skill_effects import EXPEDITION, family_percents, kind_family
from ks.heroes.optimize.skillmod import (
    damage_up_skillmod,
    joiner_damage_up_from_entries,
)
from ks.heroes.optimize.types import CatalogEntry, CatalogSkill, EffectTag


def test_damage_taken_down_counts_in_expedition_family_percents() -> None:
    """Defense-style expedition buff must not vanish when effect_kind is linked."""
    entry = CatalogEntry(
        name="Helga",
        troop="infantry",
        effects=(
            EffectTag(
                kind="damage_taken_down",
                max_value=50.0,
                applies_to="expedition",
                effect_op=111,
                first_expedition=True,
            ),
        ),
        skills=(
            CatalogSkill(
                3, "Oath of Guardian", "expedition", effect_kind="damage_taken_down"
            ),
        ),
    )
    hero = HeroRecord(
        name="Helga",
        skills=(SkillRecord(slot=3, name="Oath of Guardian", level=5),),
    )
    percents, incomplete = family_percents(
        hero, entry, family=EXPEDITION, catalog={"Helga": entry}
    )
    assert incomplete is False
    assert percents.get("damage_taken_down") == 50.0


def test_oath_of_guardian_proc_is_remaining_mixture_not_guaranteed_50() -> None:
    """Leveled Oath of Guardian must not enter expedition percents as 50% DTD."""
    entry = CatalogEntry(
        name="Helga",
        troop="infantry",
        effects=(
            EffectTag(
                kind="damage_taken_down",
                max_value=50.0,
                applies_to="expedition",
                effect_op=111,
                first_expedition=True,
                proc_chance=0.4,
            ),
        ),
        skills=(
            CatalogSkill(
                3, "Oath of Guardian", "expedition", effect_kind="damage_taken_down"
            ),
        ),
    )
    hero = HeroRecord(
        name="Helga",
        skills=(SkillRecord(slot=3, name="Oath of Guardian", level=5),),
    )
    percents, incomplete = family_percents(
        hero, entry, family=EXPEDITION, catalog={"Helga": entry}
    )
    assert incomplete is False
    assert percents.get("damage_taken_down") == pytest.approx(20.0)


def test_utility_expedition_tags_do_not_inflate_combat_percents() -> None:
    """Stamina / march-speed tags must not enter expedition combat percents."""
    entry = CatalogEntry(
        name="Diana",
        troop="archer",
        effects=(
            EffectTag(kind="stamina_cost_down", max_value=20.0, applies_to="expedition"),
            EffectTag(
                kind="wilderness_march_speed", max_value=100.0, applies_to="expedition"
            ),
            EffectTag(kind="lethality_up", max_value=25.0, applies_to="expedition"),
        ),
    )
    hero = HeroRecord(name="Diana", stars=5, pellets=0)
    percents, _ = family_percents(
        hero, entry, family=EXPEDITION, catalog={"Diana": entry}
    )
    assert "stamina_cost_down" not in percents
    assert "wilderness_march_speed" not in percents
    assert percents.get("lethality_up") == 25.0
    assert kind_family("stamina_cost_down", {"Diana": entry}) is None
    assert kind_family("wilderness_march_speed", {"Diana": entry}) is None


def test_joiner_skillmod_mixed_effect_ops_beats_same_op() -> None:
    """Community stacking: same op adds; different ops multiply (2.25 > 2.0)."""
    same = damage_up_skillmod({102: 100.0})
    mixed = damage_up_skillmod({101: 50.0, 102: 50.0})
    assert abs(same - 2.0) < 1e-9
    assert abs(mixed - 2.25) < 1e-9
    assert mixed > same


def test_joiner_damage_up_uses_only_first_expedition_tags() -> None:
    amane = CatalogEntry(
        name="Amane",
        troop="archer",
        effects=(
            EffectTag(
                kind="attack_up",
                max_value=25.0,
                applies_to="expedition",
                effect_op=102,
                first_expedition=True,
            ),
            EffectTag(
                kind="attack_up",
                max_value=25.0,
                applies_to="expedition",
                effect_op=102,
                first_expedition=False,
            ),
        ),
    )
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
        ),
    )
    # Two joiners each contribute only their first_expedition DamageUp bucket.
    mixed = joiner_damage_up_from_entries([amane, amane, chenko, chenko])
    same = joiner_damage_up_from_entries([amane, amane, amane, amane])
    assert abs(same - 2.0) < 1e-9
    assert abs(mixed - 2.25) < 1e-9
