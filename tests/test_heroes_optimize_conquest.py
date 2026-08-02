from ks.heroes.models import HeroRecord, SkillRecord
from ks.heroes.optimize.combat_formation import load_combat_roles
from ks.heroes.optimize.conquest import (
    optimize_conquest,
    ultimate_level_multiplier,
)
from ks.heroes.optimize.types import CatalogEntry


def _catalog() -> dict[str, CatalogEntry]:
    return {
        "Helga": CatalogEntry(
            name="Helga", troop="infantry", rarity="legendary",
            arena_role="front_fighter", arena_value=90, arena_tags=("cc", "aoe", "tank"),
        ),
        "Howard": CatalogEntry(
            name="Howard", troop="infantry", rarity="epic",
            arena_role="front_tank", arena_value=85, arena_tags=("tank", "team_def"),
        ),
        "Jabel": CatalogEntry(
            name="Jabel", troop="cavalry", rarity="legendary",
            arena_role="back_cc", arena_value=92, arena_tags=("cc", "aoe"),
        ),
        "Chenko": CatalogEntry(
            name="Chenko", troop="cavalry", rarity="epic",
            arena_role="back_dps", arena_value=88, arena_tags=("aoe", "dps"),
        ),
        "Saul": CatalogEntry(
            name="Saul", troop="archer", rarity="legendary",
            arena_role="back_cc", arena_value=80, arena_tags=("cc", "dps"),
        ),
        "Diana": CatalogEntry(
            name="Diana", troop="archer", rarity="epic",
            arena_role="back_dps", arena_value=70, arena_tags=("dps", "aoe", "stamina"),
            obtain="Desert Trial Event",
        ),
        "Gordon": CatalogEntry(
            name="Gordon", troop="cavalry", rarity="epic",
            arena_role="back_support", arena_value=75, arena_tags=("heal",),
        ),
    }


def _heroes() -> list[HeroRecord]:
    return [
        HeroRecord(name="Helga", stars=1, pellets=0, power=170000),
        HeroRecord(name="Howard", stars=3, pellets=0, power=390000),
        HeroRecord(name="Jabel", stars=3, pellets=1, power=560000),
        HeroRecord(name="Chenko", stars=3, pellets=1, power=330000),
        HeroRecord(name="Saul", stars=2, pellets=0, power=240000),
        HeroRecord(name="Diana", stars=3, pellets=3, power=450000),
        HeroRecord(name="Gordon", stars=2, pellets=5, power=230000),
    ]


def test_conquest_picks_five_with_two_front() -> None:
    roles = load_combat_roles("config/conquest_roles.yaml", catalog=_catalog())
    result = optimize_conquest(_heroes(), _catalog(), roles)
    assert result.status == "Optimal"
    assert result.mode == "conquest"
    assert len(result.heroes) == 5
    assert set(result.formation) == {"F1", "F2", "B1", "B2", "B3"}


def test_ultimate_multiplier_scales_with_slot0_level() -> None:
    bare = HeroRecord(name="X", skills=())
    mid = HeroRecord(
        name="Y",
        skills=(SkillRecord(slot=0, name="Ult", level=5),),
    )
    assert ultimate_level_multiplier(bare) == 1.0
    assert ultimate_level_multiplier(mid) == 1.0 + 0.04 * 5


def test_higher_ultimate_preferred_when_otherwise_equal() -> None:
    # Two infantry tanks with identical power/stars/catalog value;
    # only skill levels differ — higher ultimate should win a front slot.
    catalog = {
        "Howard": CatalogEntry(
            name="Howard", troop="infantry", rarity="epic",
            arena_role="front_tank", arena_value=85, arena_tags=("tank",),
        ),
        "Helga": CatalogEntry(
            name="Helga", troop="infantry", rarity="legendary",
            arena_role="front_fighter", arena_value=85, arena_tags=("tank",),
        ),
        "Jabel": CatalogEntry(
            name="Jabel", troop="cavalry", rarity="legendary",
            arena_role="back_cc", arena_value=85, arena_tags=("cc", "aoe"),
        ),
        "Chenko": CatalogEntry(
            name="Chenko", troop="cavalry", rarity="epic",
            arena_role="back_dps", arena_value=85, arena_tags=("aoe", "dps"),
        ),
        "Saul": CatalogEntry(
            name="Saul", troop="archer", rarity="legendary",
            arena_role="back_cc", arena_value=85, arena_tags=("cc", "dps"),
        ),
    }
    heroes = [
        HeroRecord(name="Howard", stars=3, pellets=0, power=400000, skills=(
            SkillRecord(slot=0, name="U", level=10),
        )),
        HeroRecord(name="Helga", stars=3, pellets=0, power=400000, skills=(
            SkillRecord(slot=0, name="U", level=1),
        )),
        HeroRecord(name="Jabel", stars=3, pellets=0, power=400000),
        HeroRecord(name="Chenko", stars=3, pellets=0, power=400000),
        HeroRecord(name="Saul", stars=3, pellets=0, power=400000),
    ]
    roles = load_combat_roles("config/conquest_roles.yaml", catalog=catalog)
    result = optimize_conquest(heroes, catalog, roles)
    front = {result.formation["F1"], result.formation["F2"]}
    assert "Howard" in front
