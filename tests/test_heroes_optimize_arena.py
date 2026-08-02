from ks.heroes.models import HeroRecord
from ks.heroes.optimize.arena import load_arena_roles, optimize_arena_attack
from ks.heroes.optimize.types import CatalogEntry


def test_arena_attack_picks_five_with_two_front() -> None:
    heroes = [
        HeroRecord(name="Helga", stars=1, pellets=0, power=170000),
        HeroRecord(name="Howard", stars=3, pellets=0, power=390000),
        HeroRecord(name="Jabel", stars=3, pellets=1, power=560000),
        HeroRecord(name="Chenko", stars=3, pellets=1, power=330000),
        HeroRecord(name="Saul", stars=2, pellets=0, power=240000),
        HeroRecord(name="Diana", stars=3, pellets=3, power=450000),
        HeroRecord(name="Gordon", stars=2, pellets=5, power=230000),
    ]
    catalog = {
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
    roles = load_arena_roles("config/arena_roles.yaml", catalog=catalog)
    result = optimize_arena_attack(heroes, catalog, roles)
    assert result.status == "Optimal"
    assert len(result.heroes) == 5
    assert "F1" in result.formation and "F2" in result.formation
    assert set(result.formation) == {"F1", "F2", "B1", "B2", "B3"}
    # Prefer infantry-ish tanks up front when available.
    front = {result.formation["F1"], result.formation["F2"]}
    assert "Howard" in front or "Helga" in front
