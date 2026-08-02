"""Tests for Power-i parse helpers and lifetime history append."""

from __future__ import annotations

from pathlib import Path

from ks.heroes.models import HeroRecord, SkillRecord
from ks.heroes.power_breakdown import (
    breakdown_sum_ok,
    parse_power_breakdown,
    power_info_tap_from_power_box,
)
from ks.heroes.power_history import (
    append_if_changed,
    load_points,
    point_from_hero_and_breakdown,
    record_breakdown_for_hero,
)


def test_parse_jabel_probe_text() -> None:
    text = """
    Hero Power: 615,420
    From Level: 106,500
    From Stars: 226,200
    From Skills: 34,650
    Gear Strength: 248,070
    """
    b = parse_power_breakdown(text)
    assert b.hero_power == 615_420
    assert b.from_level == 106_500
    assert b.from_stars == 226_200
    assert b.from_skills == 34_650
    assert b.gear_strength == 248_070
    assert b.naked == 106_500 + 226_200 + 34_650
    assert breakdown_sum_ok(b)


def test_sum_ok_treats_missing_gear_as_zero() -> None:
    text = """
    Hero Power: 288,840
    From Level: 85,200
    From Stars: 180,960
    From Skills: 22,680
    """
    b = parse_power_breakdown(text)
    assert b.gear_strength is None
    assert breakdown_sum_ok(b)


def test_power_info_tap_near_power_box() -> None:
    x, y = power_info_tap_from_power_box(x=400, y=1140, w=320, h=70)
    assert x == 656
    assert y == 1175


def test_append_if_changed_skips_duplicate(tmp_path: Path) -> None:
    hero = HeroRecord(
        name="Jabel",
        level=57,
        stars=3,
        pellets=1,
        skills=(SkillRecord(slot=0, level=5),),
        scraped_at="2026-08-02T00:00:00Z",
    )
    bd = parse_power_breakdown(
        "Hero Power: 615,420\nFrom Level: 106,500\nFrom Stars: 226,200\n"
        "From Skills: 34,650\nGear Strength: 248,070\n"
    )
    hist = tmp_path / "power_history"
    assert record_breakdown_for_hero(hist, hero, bd) is True
    assert record_breakdown_for_hero(hist, hero, bd) is False
    points = load_points(hist, "Jabel")
    assert len(points) == 1
    assert points[0].from_level == 106_500
    assert points[0].level == 57


def test_append_when_level_bucket_changes(tmp_path: Path) -> None:
    hist = tmp_path / "power_history"
    h57 = HeroRecord(name="Saul", level=57, stars=2, pellets=0, scraped_at="t1")
    h58 = HeroRecord(name="Saul", level=58, stars=2, pellets=0, scraped_at="t2")
    bd57 = parse_power_breakdown(
        "Hero Power: 373820\nFrom Level: 106500\nFrom Stars: 99800\nFrom Skills: 25200\n"
        "Gear Strength: 142320\n"
    )
    bd58 = parse_power_breakdown(
        "Hero Power: 376620\nFrom Level: 109300\nFrom Stars: 99800\nFrom Skills: 25200\n"
        "Gear Strength: 142320\n"
    )
    assert record_breakdown_for_hero(hist, h57, bd57)
    assert record_breakdown_for_hero(hist, h58, bd58)
    points = load_points(hist, "Saul")
    assert len(points) == 2
    assert points[0].from_level == 106_500
    assert points[1].from_level == 109_300
    assert points[1].level == 58


def test_identity_ignores_scraped_at_only_change(tmp_path: Path) -> None:
    hist = tmp_path / "power_history"
    bd = parse_power_breakdown(
        "Hero Power: 188280\nFrom Level: 85200\nFrom Stars: 90480\nFrom Skills: 12600\n"
    )
    a = point_from_hero_and_breakdown(
        HeroRecord(name="Amane", level=57, stars=2, pellets=1, scraped_at="t1"),
        bd,
    )
    b = point_from_hero_and_breakdown(
        HeroRecord(name="Amane", level=57, stars=2, pellets=1, scraped_at="t2"),
        bd,
    )
    assert a.identity_key() == b.identity_key()
    assert append_if_changed(hist, "Amane", a)
    assert not append_if_changed(hist, "Amane", b)
