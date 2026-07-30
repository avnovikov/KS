import pytest
from pathlib import Path

from ks.config import load_config


def _valid_config_yaml(
    *,
    march_load: int = 1_000_000,
    gather_rates: dict[str, float] | None = None,
) -> str:
    rates = gather_rates or {
        "bread": 200.0,
        "wood": 200.0,
        "stone": 40.0,
        "iron": 10.0,
    }
    rates_yaml = "\n".join(f"    {k}: {v}" for k, v in rates.items())
    return f"""
dry_run: true
adb:
  serial: null
account:
  march_load: {march_load}
  gather_rate_per_sec:
{rates_yaml}
scoring:
  candidate_limit: 5
resources:
  preference_order: [bread, wood, stone, iron]
executor:
  max_taps_per_proposal: 20
  tap_delay_ms: 250
  tap_jitter_ms: 50
vision:
  match_threshold: 0.85
navigation: {{}}
"""


def test_load_config_defaults_dry_run(tmp_path: Path):
    p = tmp_path / "params.yaml"
    p.write_text(_valid_config_yaml(), encoding="utf-8")
    cfg = load_config(p)
    assert cfg.dry_run is True
    assert cfg.account.march_load == 1_000_000
    assert cfg.account.gather_rate_per_sec["bread"] == 200.0
    assert cfg.scoring.candidate_limit == 5


@pytest.mark.parametrize("march_load", [0, -1])
def test_load_config_rejects_non_positive_march_load(tmp_path: Path, march_load: int):
    p = tmp_path / "params.yaml"
    p.write_text(_valid_config_yaml(march_load=march_load), encoding="utf-8")

    with pytest.raises(ValueError, match="march_load must be positive"):
        load_config(p)


@pytest.mark.parametrize(
    ("resource", "rate"),
    [("bread", 0.0), ("wood", -5.0)],
)
def test_load_config_rejects_non_positive_gather_rate(
    tmp_path: Path, resource: str, rate: float
):
    p = tmp_path / "params.yaml"
    p.write_text(
        _valid_config_yaml(
            gather_rates={
                "bread": 200.0,
                "wood": 200.0,
                "stone": 40.0,
                "iron": 10.0,
                resource: rate,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"gather_rate_per_sec\[.+\] must be positive"):
        load_config(p)
