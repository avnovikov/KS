from pathlib import Path

from ks.heroes.cli import build_parser, main


def test_recommend_parser_exists() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "recommend",
            "--heroes",
            "artifacts/heroes/x/heroes.json",
            "--force-role",
            "garrison",
        ]
    )
    assert args.command == "recommend"
    assert args.force_mode == "garrison"


def test_recommend_cli_smoke(tmp_path: Path) -> None:
    heroes = tmp_path / "heroes.json"
    heroes.write_text(
        """
[
  {"name": "Zoe", "power": 1000, "escorts": 10, "stars": 5},
  {"name": "Saul", "power": 900, "escorts": 10, "stars": 5},
  {"name": "Howard", "power": 800, "escorts": 10, "stars": 5},
  {"name": "Amadeus", "power": 1100, "escorts": 10, "stars": 5},
  {"name": "Jabel", "power": 950, "escorts": 10, "stars": 5}
]
""",
        encoding="utf-8",
    )
    troops = tmp_path / "troops.yaml"
    troops.write_text(
        "infantry: 80\ncavalry: 40\narchers: 40\nmarch_capacity: 150\n",
        encoding="utf-8",
    )
    out = tmp_path / "out.json"
    root = Path(__file__).resolve().parents[1]
    code = main(
        [
            "recommend",
            "--heroes",
            str(heroes),
            "--troops",
            str(troops),
            "--catalog",
            str(root / "config" / "hero_catalog.yaml"),
            "--scenarios",
            str(root / "config" / "point_scenarios.yaml"),
            "--pro-cache",
            str(tmp_path / "pro.json"),
            "--out",
            str(out),
        ]
    )
    assert code == 0
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "recommended_mode" in text
    assert "expected_personal_points" in text
