from ks.heroes.parse import (
    clean_name,
    parse_power,
    parse_skill_panel,
    parse_stats_panel,
)


def test_parse_power_strips_commas():
    assert parse_power("1,234,567") == 1_234_567


def test_parse_power_missing_returns_none():
    assert parse_power("no digits") is None


def test_clean_name_rejects_empty():
    assert clean_name("  ") is None
    assert clean_name("12") is None
    assert clean_name("Jabel") == "Jabel"


def test_parse_stats_panel_conquest_and_expedition():
    text = """
    Hero Stats
    Conquest
    Hero Attack 1,619
    Hero Defense 1,316
    Hero Health 14,679
    Escort Attack 539
    Escort Defense 438
    Escort Health 4,893
    Expedition
    Cavalry Attack +101.37%
    Cavalry Defense +101.37%
    Cavalry Lethality +49.43%
    Cavalry Health +16.95%
    """
    stats = parse_stats_panel(text)
    assert stats.conquest["Hero Attack"] == 1619
    assert stats.conquest["Escort Health"] == 4893
    assert stats.expedition["Cavalry Attack"] == 101.37
    assert stats.expedition["Cavalry Health"] == 16.95


def test_parse_skill_panel():
    text = (
        "Rally Flag Lv. 3\n"
        "Jabel, with her banner-like red armor, has a 24% chance of reducing damage.\n"
        "Damage Taken Chance Down: 8%/16%/24%/32%/40%"
    )
    skill = parse_skill_panel(text, slot=0)
    assert skill.name == "Rally Flag"
    assert skill.level == 3
    assert skill.description is not None
    assert "24%" in skill.description
    assert skill.upgrade_preview is not None
    assert "8%/16%" in skill.upgrade_preview
