"""Every optimiser surface derives strength from stat contributions.

Wiring + invariant assertions, deliberately not frozen score values — the
whole point of the rewrite is that the numbers changed. See the plan's
"Measured calibration note" for the size of that change.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ks.heroes.gear_models import GearRecord, GearStats
from ks.heroes.models import HeroRecord, HeroStats
from ks.heroes.ui.optimize_run import run_optimize_bundle

_ROOT = Path(__file__).resolve().parents[1]
_SHARE_KEYS = {"hero", "skills", "gear", "total"}


def _heroes() -> list[HeroRecord]:
    rows = [
        ("Helga", "infantry", "legendary", 3, 500_000),
        ("Howard", "infantry", "epic", 3, 390_000),
        ("Jabel", "cavalry", "legendary", 4, 650_000),
        ("Chenko", "cavalry", "epic", 3, 400_000),
        ("Saul", "archer", "legendary", 2, 250_000),
        ("Diana", "archer", "epic", 3, 450_000),
        ("Gordon", "cavalry", "epic", 2, 230_000),
    ]
    return [
        HeroRecord(
            name=name, troop_type=troop, rarity=rarity, stars=stars, pellets=0,
            power=power, escorts=5, roster_page=0, roster_index=i, scraped_at="t",
            stats=HeroStats(
                conquest={
                    "Hero Attack": power // 300,
                    "Hero Defense": power // 350,
                    "Hero Health": power // 40,
                    "Escort Attack": power // 900,
                    "Escort Defense": power // 1050,
                    "Escort Health": power // 120,
                }
            ),
        )
        for i, (name, troop, rarity, stars, power) in enumerate(rows)
    ]


def _gear() -> list[GearRecord]:
    prefix = {"infantry": "Infantry", "cavalry": "Cavalry", "archers": "Archer"}
    out: list[GearRecord] = []
    for troop in ("infantry", "cavalry", "archers"):
        for slot in ("helmet", "chest", "gloves", "boots"):
            stat = "Lethality" if slot in ("helmet", "boots") else "Health"
            out.append(
                GearRecord(
                    piece_id=f"{troop}-{slot}", name=f"{troop} {slot}",
                    troop_type=troop, slot=slot, rarity="mythic",
                    enhancement_level=40, power=60_000,
                    stats=GearStats(
                        conquest={"Hero Attack": 300, "Hero Health": 1500},
                        expedition={f"{prefix[troop]} {stat}": 32.0},
                    ),
                )
            )
    return out


@pytest.fixture(scope="module")
def bundle() -> dict:
    return run_optimize_bundle(_heroes(), gear=_gear(), config_root=_ROOT)


def _check(contribution: dict) -> None:
    assert contribution["estimated"] is True
    assert set(contribution["power"]) == _SHARE_KEYS
    for block in [contribution["power"]] + list(contribution["stats"].values()):
        assert block["hero"] >= 0
        assert block["skills"] >= 0
        assert block["gear"] >= 0
        assert block["total"] == pytest.approx(
            block["hero"] + block["skills"] + block["gear"]
        )


def test_every_optimal_section_reports_contributions(bundle: dict) -> None:
    seen = 0
    for section in ("sword", "bear"):
        for row in (bundle[section].get("modes") or {}).values():
            assert row["stat_family"] == "expedition"
            _check(row["formation_totals"])
            for contrib in (row["contributions"] or {}).values():
                assert contrib["family"] == "expedition"
                _check(contrib)
            seen += 1
    assert seen >= 1, "expected at least one Optimal sword/bear mode to check"

    # The three combat rows are asserted Optimal outright, not skipped on
    # infeasibility — a `seen` counter shared with the sword/bear loop above
    # let all three go infeasible here without failing the test at all.
    combat_rows = (
        ("arena.attack", bundle["arena"]["attack"]),
        ("arena.defense", bundle["arena"]["defense"]),
        ("conquest", bundle["conquest"]),
    )
    for label, row in combat_rows:
        assert row["status"] == "Optimal", f"{label}: {row.get('error') or row['status']}"
        assert row["stat_family"] == "conquest"
        _check(row["formation_totals"])
        for contrib in (row["contributions"] or {}).values():
            assert contrib["family"] == "conquest"
            _check(contrib)


def test_formation_totals_equal_sum_of_hero_contributions(bundle: dict) -> None:
    for row in (bundle["arena"]["attack"], bundle["conquest"]):
        assert row["status"] == "Optimal", row.get("error") or row["status"]
        totals = row["formation_totals"]
        contribs = list((row["contributions"] or {}).values())
        assert totals["power"]["total"] == pytest.approx(
            sum(c["power"]["total"] for c in contribs)
        )
        for label, share in totals["stats"].items():
            assert share["total"] == pytest.approx(
                sum((c["stats"].get(label) or {}).get("total", 0.0) for c in contribs)
            )


def test_no_scorer_still_uses_the_gear_bonus_heuristic() -> None:
    """Success criterion 4: naked power + heuristic gear bonus is gone."""
    optimize_dir = _ROOT / "ks" / "heroes" / "optimize"
    offenders = [
        path.name
        for path in sorted(optimize_dir.glob("*.py"))
        if "gear_bonus" in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"heuristic gear bonus still referenced in {offenders}"
