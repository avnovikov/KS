from ks.heroes.gear_parse import parse_gear_detail


def test_parse_gear_detail_from_live_ui_text():
    text = """
    Gear Details
    Judicator's Armet
    Mythic
    98,550
    Unequip
    Conquest Stats
    Hero Attack 288
    Hero Health 1,440
    Escort Attack 96
    Escort Health 480
    Expedition Stats
    Cavalry Lethality +30.60%
    Troop Mastery
    Mastery Forging
    Enhance
    +30
    Lv. 0
    """
    piece = parse_gear_detail(text, page=0, index=0)
    assert piece.name == "Judicator's Armet"
    assert piece.troop_type == "cavalry"
    assert piece.slot == "helmet"
    assert piece.rarity == "mythic"
    assert piece.enhancement_level == 30
    assert piece.mastery_level == 0
    assert piece.power == 98550
    assert piece.equipped is True
    assert piece.stats is not None
    assert piece.stats.conquest["Hero Attack"] == 288
    assert piece.stats.conquest["Hero Health"] == 1440
    assert piece.stats.expedition["Cavalry Lethality"] == 30.60
    assert piece.stats.attack is None
    assert piece.stats.defense is None
    assert piece.stats.health is None
    assert piece.stats.lethality == 30.60
    assert piece.inventory_page == 0
    assert piece.inventory_index == 0
    assert "Judicator" in (piece.raw_text or "")


def test_parse_gear_detail_infantry_chest_not_equipped():
    text = """
    Iron Cuirass
    Epic
    12,000
    Equip
    Conquest Stats
    Hero Defense 100
    Hero Health 500
    Expedition Stats
    Infantry Health +15.00%
    Infantry Defense +8.00%
    +41
    Lv. 0
    """
    piece = parse_gear_detail(text, page=1, index=2)
    assert piece.troop_type == "infantry"
    assert piece.slot == "chest"
    assert piece.rarity == "epic"
    assert piece.enhancement_level == 41
    assert piece.mastery_level == 0
    assert piece.equipped is False
    assert piece.stats.health == 15.0
    assert piece.stats.defense == 8.0
    assert piece.stats.lethality is None


def test_parse_gear_detail_gold_maps_to_mythic_gloves():
    text = "Archer Gauntlets\nGold\n+40\nMastery Lv. 4\nEquip\n"
    piece = parse_gear_detail(text, page=0, index=1)
    assert piece.troop_type == "archers"
    assert piece.slot == "gloves"
    assert piece.rarity == "mythic"
    assert piece.enhancement_level == 40
    assert piece.mastery_level == 4


def test_parse_gear_detail_partial_keeps_nulls():
    piece = parse_gear_detail("garbage ocr", page=0, index=0)
    assert piece.enhancement_level is None
    assert piece.name is None
    assert piece.raw_text == "garbage ocr"


def test_parse_power_strips_ocr_leading_digit():
    text = "Mythic\n798,550\nConquest Stats\nHero Attack 288\n"
    piece = parse_gear_detail(text, page=0, index=0)
    assert piece.power == 98550


def test_parse_power_keeps_leading_one_for_mid_six_digit():
    text = "Judicator's Armet\nMythic\n152,100\nConquest Stats\nHero Attack 363\n"
    piece = parse_gear_detail(text, page=0, index=0)
    assert piece.power == 152100


def test_parse_power_strips_leading_two_noise():
    text = "Stonewall Shroud\nRare\n218,360\nConquest Stats\nHero Defense 68\n"
    piece = parse_gear_detail(text, page=0, index=0)
    assert piece.power == 18360


def test_parse_enhancement_from_glued_title():
    text = "aer30 Judicator's Armet\nMythic\n98,550\n"
    piece = parse_gear_detail(text, page=0, index=0)
    assert piece.enhancement_level == 30
    assert piece.name == "Judicator's Armet"


def test_parse_enhancement_ignores_bare_digit_noise():
    text = "7\n7\nJudicator's Armet\nMythic\n+41\n"
    piece = parse_gear_detail(text, page=0, index=0)
    assert piece.enhancement_level == 41


def test_parse_enhancement_ignores_expedition_plus_percent():
    text = """
    Judicator's Armet
    Mythic
    152,100
    Conquest Stats
    Hero Attack 363
    Expedition Stats
    Cavalry Lethality +39.42%
    """
    piece = parse_gear_detail(text, page=0, index=0)
    # No +51 badge in OCR — recover from mythic power (+51 with mastery fit).
    assert piece.enhancement_level == 51


def test_parse_enhancement_falls_back_to_power_when_badge_missing():
    text = """
    Stonewall Gloves
    Rare
    18,362
    Conquest Stats
    Escort Defense 22
    Expedition Stats
    Infantry Health +6.90%
    """
    piece = parse_gear_detail(text, page=0, index=5)
    assert piece.enhancement_level == 7


def test_parse_enhancement_glued_lowercase_title():
    text = "pt20 praetorian's shroud\nEpic\n38,850\n"
    piece = parse_gear_detail(text, page=0, index=3)
    assert piece.enhancement_level == 20


