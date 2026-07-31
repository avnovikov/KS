"""Discord bridge: propose/execute gather via existing KS APIs."""

from pathlib import Path

from ks.config import load_config
from ks.discord.bridge import BridgeResult, execute_proposal, propose_gather_from_json
from ks.device.fake import FakeDevice
from ks.models import NothingToDo, Proposal


def test_propose_gather_from_json_returns_proposal(tmp_path: Path):
    cfg_path = tmp_path / "params.yaml"
    cfg_path.write_text(
        Path("config/params.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    app_cfg = load_config(cfg_path)
    result = propose_gather_from_json(
        Path("tests/fixtures/candidates.json"),
        app_cfg,
    )
    assert isinstance(result, Proposal)
    assert result.kind == "gather"
    assert result.rationale


def test_propose_gather_from_json_nothing_to_do(tmp_path: Path):
    empty = tmp_path / "empty.json"
    empty.write_text("[]", encoding="utf-8")
    cfg_path = tmp_path / "params.yaml"
    cfg_path.write_text(
        Path("config/params.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    app_cfg = load_config(cfg_path)
    result = propose_gather_from_json(empty, app_cfg)
    assert isinstance(result, NothingToDo)


def test_execute_proposal_dry_run(tmp_path: Path):
    cfg_path = tmp_path / "params.yaml"
    cfg_path.write_text(
        Path("config/params.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    app_cfg = load_config(cfg_path)
    proposal = propose_gather_from_json(
        Path("tests/fixtures/candidates.json"),
        app_cfg,
    )
    assert isinstance(proposal, Proposal)
    device = FakeDevice()
    outcome = execute_proposal(device, proposal, app_cfg)
    assert isinstance(outcome, BridgeResult)
    assert outcome.ok is True
    assert outcome.skipped_dry_run is True
