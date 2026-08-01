from pathlib import Path

from ks.heroes.optimize.troops import allocate_highest_first, load_troops_config


def test_load_troops_flat_still_works(tmp_path: Path) -> None:
    p = tmp_path / "troops.yaml"
    p.write_text(
        "infantry: 100\ncavalry: 20\narchers: 30\nmarch_capacity: 150\n",
        encoding="utf-8",
    )
    cfg = load_troops_config(p)
    assert cfg.infantry == 100
    assert cfg.cavalry == 20
    assert cfg.archers == 30
    assert cfg.march_capacity == 150


def test_load_troops_by_level(tmp_path: Path) -> None:
    p = tmp_path / "troops.yaml"
    p.write_text(
        """
march_capacity: 200000
infantry:
  1: 100
  2: 200
  7: 50000
cavalry:
  5: 1000
  7: 20000
archers:
  6: 5000
  7: 30000
""",
        encoding="utf-8",
    )
    cfg = load_troops_config(p)
    assert cfg.infantry == 50300
    assert cfg.cavalry == 21000
    assert cfg.archers == 35000
    assert cfg.levels("infantry")[7] == 50000
    assert cfg.max_level == 7


def test_allocate_highest_first() -> None:
    owned = {1: 100, 5: 50, 7: 200}
    got = allocate_highest_first(owned, 220)
    assert got == {7: 200, 5: 20}


def test_load_troops_rejects_negative(tmp_path: Path) -> None:
    p = tmp_path / "troops.yaml"
    p.write_text(
        "infantry: -1\ncavalry: 0\narchers: 0\nmarch_capacity: 10\n",
        encoding="utf-8",
    )
    try:
        load_troops_config(p)
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "non-negative" in str(exc).lower() or "negative" in str(exc).lower()
