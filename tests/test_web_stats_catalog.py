"""Unit tests for kingshotdata HTML → catalog parse (fixture, no network)."""

from ks.heroes.web_stats_catalog import parse_hero_page

HELGA_SNIPPET = """
<html><body>
<h1>Helga</h1>
<p>Infantry hero · Generation 1</p>
<p>LegendaryInfantryGen 1Exclusive Weapon</p>
<p>Exclusive weapon Bands of Tyre</p>
<h3>Stats progression</h3>
<p>Star level stats31 stars · Infantry expedition</p>
<table>
<tr><th>Star</th><th>Exp. ATK%</th><th>Exp. DEF%</th><th>Shards</th></tr>
<tr><td>1</td><td>25.25%</td><td>25.25%</td><td>0</td></tr>
<tr><td>2</td><td>27.60%</td><td>27.60%</td><td>1</td></tr>
</table>
<h4>Conquest Skills</h4>
<p>Conquest stats</p>
<p>Hero Attack</p><p>1,873</p>
<p>Hero Defense</p><p>2,220</p>
<p>Hero Health</p><p>36,630</p>
<p>Conquest</p>
<p>Antler Assault</p>
<p>Performs an antler charge.</p>
<p>Area of Effect Damage Up:</p>
<p>160% / 176% / 192% / 208% / 224%</p>
<h4>Expedition Skills</h4>
<p>Expedition stats</p>
<p>Infantry Attack</p><p>+200.16%</p>
<p>Infantry Defense</p><p>+200.16%</p>
<p>Expedition</p>
<p>Echoes of Valhalla</p>
<p>Helga blows the horn.</p>
<p>Attack Up:</p>
<p>5% / 10% / 15% / 20% / 25%</p>
</body></html>
"""


def test_parse_helga_fixture_extracts_core_stats() -> None:
    hero = parse_hero_page(
        HELGA_SNIPPET, slug="helga", url="https://kingshotdata.com/heroes/helga/"
    )
    assert hero.name == "Helga"
    assert hero.troop == "infantry"
    assert hero.generation == 1
    assert hero.conquest["Hero Attack"] == 1873
    assert hero.conquest["Hero Defense"] == 2220
    assert hero.conquest["Hero Health"] == 36630
    assert hero.expedition["Infantry Attack"] == 200.16
    assert len(hero.star_table) >= 2
    assert hero.star_table[0].star == 1
    assert hero.star_table[0].expedition_attack_pct == 25.25
    skill_names = {s.name for s in hero.skills}
    assert "Antler Assault" in skill_names or "Echoes of Valhalla" in skill_names
