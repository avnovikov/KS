import json
from pathlib import Path

import pytest

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
            name="Helga", troop="infantry", rarity="epic",
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


def test_cli_conquest_argparse_smoke(tmp_path: Path) -> None:
    """CLI parser accepts conquest subcommand with required --heroes flag."""
    from ks.heroes.cli import build_parser

    heroes_file = tmp_path / "heroes.json"
    heroes_file.write_text(
        json.dumps({"heroes": [h.to_dict() for h in _heroes()]}),
        encoding="utf-8",
    )
    parser = build_parser()
    args = parser.parse_args([
        "conquest",
        "--heroes", str(heroes_file),
        "--out", str(tmp_path / "conquest_result.json"),
    ])
    assert args.command == "conquest"
    assert args.heroes == heroes_file
    assert args.roles.name == "conquest_roles.yaml"
    assert args.gear is None


def test_conquest_result_dict_carries_contributions() -> None:
    roles = load_combat_roles("config/conquest_roles.yaml", catalog=_catalog())
    # with_survival=False keeps this test on the path Task 4 owns; the
    # survival pipeline is rewired in Task 5, and the end-to-end
    # with-survival path is covered by the Task 9 wiring suite.
    payload = optimize_conquest(
        _heroes(), _catalog(), roles, with_survival=False
    ).to_dict()
    assert payload["stat_family"] == "conquest"
    assert set(payload["contributions"]) == set(payload["heroes"])
    for contrib in payload["contributions"].values():
        assert contrib["family"] == "conquest"
        for share in contrib["stats"].values():
            assert share["hero"] >= 0
            assert share["total"] == pytest.approx(
                share["hero"] + share["skills"] + share["gear"]
            )


def test_conquest_result_keeps_contributions_with_survival_attached() -> None:
    # attach_survival rebuilds CombatFormationResult from the pre-survival
    # result; it must forward stat_family/contributions/formation_totals
    # rather than letting them reset to the dataclass defaults. with_survival
    # defaults to True everywhere in the app, so this is the path real
    # callers actually take.
    roles = load_combat_roles("config/conquest_roles.yaml", catalog=_catalog())
    payload = optimize_conquest(_heroes(), _catalog(), roles).to_dict()
    assert payload["status"] == "Optimal"
    assert "survival" in payload
    assert payload["stat_family"] == "conquest"
    assert payload["formation_totals"] is not None
    assert set(payload["contributions"]) == set(payload["heroes"])
