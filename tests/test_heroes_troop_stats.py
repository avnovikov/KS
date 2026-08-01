from pathlib import Path

from ks.heroes.optimize.troop_stats import load_troop_stats


def test_troop_stats_t6_matches_bear_guide() -> None:
    root = Path(__file__).resolve().parents[1]
    table = load_troop_stats(root / "config" / "troop_stats.yaml")
    inf = table.get("infantry", 6, truegold=0)
    cav = table.get("cavalry", 6, truegold=0)
    arc = table.get("archers", 6, truegold=0)
    assert (inf.attack, inf.health) == (243, 730)
    assert (cav.attack, cav.health) == (730, 243)
    assert (arc.attack, arc.health) == (974, 183)
    assert inf.defense == 10 and inf.lethality == 10


def test_troop_stats_t7_present() -> None:
    root = Path(__file__).resolve().parents[1]
    table = load_troop_stats(root / "config" / "troop_stats.yaml")
    assert table.get("infantry", 7).attack == 287
    assert table.get("cavalry", 7).attack == 862
    assert table.get("archers", 7).attack == 1149
