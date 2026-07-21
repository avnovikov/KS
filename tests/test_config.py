from pathlib import Path

from ks.config import load_config


def test_load_config_defaults_dry_run(tmp_path: Path):
    p = tmp_path / "params.yaml"
    p.write_text(
        """
dry_run: true
adb:
  serial: null
account:
  march_load: 1000000
  gather_rate_per_sec:
    bread: 200.0
    wood: 200.0
    stone: 40.0
    iron: 10.0
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
navigation: {}
""",
        encoding="utf-8",
    )
    cfg = load_config(p)
    assert cfg.dry_run is True
    assert cfg.account.march_load == 1_000_000
    assert cfg.account.gather_rate_per_sec["bread"] == 200.0
    assert cfg.scoring.candidate_limit == 5
