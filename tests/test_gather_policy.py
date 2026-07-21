from pathlib import Path

from ks.config import load_config
from ks.models import GatherCandidate, NothingToDo, Proposal, Tap
from ks.policy.gather import propose_gather

_MIN_YAML = """
dry_run: true
adb:
  serial: null
account:
  march_load: 500000
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
"""


def _cfg(tmp_path: Path):
    p = tmp_path / "params.yaml"
    p.write_text(_MIN_YAML, encoding="utf-8")
    return load_config(p)


def test_propose_gather_picks_highest_score(tmp_path: Path):
    cfg = _cfg(tmp_path)
    near = GatherCandidate("bread", 200_000, 30.0, 0.9)
    far = GatherCandidate("bread", 14_000_000, 3600.0, 0.9)
    result = propose_gather([far, near], cfg, actions=(Tap(100, 200),))
    assert isinstance(result, Proposal)
    assert result.scored.candidate is near
    assert "score=" in result.rationale


def test_propose_gather_empty_is_nothing(tmp_path: Path):
    cfg = _cfg(tmp_path)
    result = propose_gather([], cfg, actions=())
    assert isinstance(result, NothingToDo)
