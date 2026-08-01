from ks.heroes.name_ocr import (
    load_known_hero_names,
    load_name_catalog,
    match_known_hero_name,
    names_for_filters,
)


def test_catalog_includes_jabel_with_rarity_and_troop():
    catalog = load_name_catalog()
    assert "Jabel" in catalog
    assert (catalog["Jabel"].rarity or "").lower() == "legendary"
    assert (catalog["Jabel"].troop or "").lower() == "cavalry"


def test_filter_legendary_cavalry_includes_jabel():
    catalog = load_name_catalog()
    names = names_for_filters(catalog, rarity="SSR", troop="cavalry")
    assert "Jabel" in names
    assert "Amadeus" not in names  # infantry


def test_match_jabel_from_stylized_ocr_against_catalog():
    known = load_known_hero_names()
    assert "Jabel" in known
    assert match_known_hero_name("wvavel", known) == "Jabel"
    assert match_known_hero_name("jabel", known) == "Jabel"


def test_match_rejects_short_ocr_junk():
    known = load_known_hero_names()
    assert match_known_hero_name("Re", known) is None
    assert match_known_hero_name("irl", known) is None
