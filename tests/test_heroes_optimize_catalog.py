from pathlib import Path

from ks.heroes.optimize.catalog import load_catalog


def test_catalog_joins_pro_and_yaml(tmp_path: Path) -> None:
    pro = tmp_path / "pro.json"
    pro.write_text(
        """
{
  "heroes": [
    {
      "name": "Amadeus",
      "gen": 1,
      "rarity": "legendary",
      "troop": "infantry",
      "rally": "S",
      "garrison": "B",
      "joiner": "A"
    }
  ]
}
""",
        encoding="utf-8",
    )
    yaml_path = tmp_path / "catalog.yaml"
    yaml_path.write_text(
        """
heroes:
  Amadeus:
    widget_type: attack
    effects:
      - kind: rally_attack
        max_value: 15.0
        applies_to: widget
      - kind: attack_up
        max_value: 25.0
        applies_to: expedition
""",
        encoding="utf-8",
    )
    catalog = load_catalog(pro, yaml_path)
    entry = catalog["Amadeus"]
    assert entry.gen == 1
    assert entry.troop == "infantry"
    assert entry.widget_type == "attack"
    assert entry.rally_tier == "S"
    assert any(e.kind == "rally_attack" for e in entry.effects)


def test_catalog_yaml_only_hero(tmp_path: Path) -> None:
    pro = tmp_path / "pro.json"
    pro.write_text('{"heroes": []}', encoding="utf-8")
    yaml_path = tmp_path / "catalog.yaml"
    yaml_path.write_text(
        """
heroes:
  Howard:
    widget_type: none
    troop: infantry
    gen: 0
    effects:
      - kind: damage_taken_down
        max_value: 20.0
""",
        encoding="utf-8",
    )
    catalog = load_catalog(pro, yaml_path)
    assert catalog["Howard"].widget_type == "none"
    assert catalog["Howard"].troop == "infantry"


def test_catalog_loads_diana_as_source_of_truth() -> None:
    from pathlib import Path

    from ks.heroes.optimize.catalog import arena_heroes_from_catalog

    root = Path(__file__).resolve().parents[1]
    catalog = load_catalog(None, root / "config" / "hero_catalog.yaml")
    diana = catalog["Diana"]
    assert diana.troop in {"archer", "archers"}
    assert diana.rarity == "epic"
    assert diana.gen == 1
    assert diana.obtain == "Desert Trial Event"
    assert diana.arena_role == "back_dps"
    assert diana.arena_value == 70
    assert "stamina" in diana.arena_tags
    assert any(e.kind == "stamina_cost_down" for e in diana.effects)
    assert any(e.kind == "wilderness_march_speed" for e in diana.effects)
    arena_heroes = arena_heroes_from_catalog(catalog)
    assert "Diana" in arena_heroes
    assert arena_heroes["Diana"]["arena_value"] == 70
