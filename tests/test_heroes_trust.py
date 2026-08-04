from ks.heroes.assurance import field_assurance
from ks.heroes.models import HeroRecord
from ks.heroes.ui.trust import hero_row_incomplete


def test_hero_row_incomplete_when_any_assurance_field_is_low():
    hero = HeroRecord(
        name="Ayla",
        power=120,
        stars=5,
        level=42,
        pellets=3,
        assurance={"level": field_assurance("low", "manual_review")},
    )

    assert hero_row_incomplete(hero) is True


def test_hero_row_incomplete_when_power_attention_is_set():
    hero = HeroRecord(
        name="Bryn",
        power=120,
        stars=5,
        level=42,
        pellets=3,
    )
    object.__setattr__(hero, "power_attention", "blocked")

    assert hero_row_incomplete(hero) is True
