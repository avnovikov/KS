"""Tests for CLI confirm loop (Task 7)."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ks.cli import confirm_yes_no, main
from ks.config import load_config


# ---------------------------------------------------------------------------
# confirm_yes_no unit tests
# ---------------------------------------------------------------------------


def test_confirm_yes():
    assert confirm_yes_no("Go?", input_fn=lambda _: "y") is True


def test_confirm_no():
    assert confirm_yes_no("Go?", input_fn=lambda _: "n") is False


def test_confirm_case_insensitive_Y():
    assert confirm_yes_no("Go?", input_fn=lambda _: "Y") is True


def test_confirm_garbage_treated_as_no():
    assert confirm_yes_no("Go?", input_fn=lambda _: "maybe") is False


def test_confirm_empty_treated_as_no():
    assert confirm_yes_no("Go?", input_fn=lambda _: "") is False


# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

_NEAR_CANDIDATE = {
    "resource": "bread",
    "tile_amount": 500_000.0,
    "march_time_one_way_s": 30.0,
    "vision_confidence": 0.95,
}
_FAR_CANDIDATE = {
    "resource": "bread",
    "tile_amount": 200_000.0,
    "march_time_one_way_s": 120.0,
    "vision_confidence": 0.90,
}

_TWO_CANDIDATES = [_NEAR_CANDIDATE, _FAR_CANDIDATE]


@pytest.fixture()
def candidates_json(tmp_path: Path) -> Path:
    path = tmp_path / "candidates.json"
    path.write_text(json.dumps(_TWO_CANDIDATES))
    return path


@pytest.fixture()
def empty_candidates_json(tmp_path: Path) -> Path:
    path = tmp_path / "empty.json"
    path.write_text(json.dumps([]))
    return path


# ---------------------------------------------------------------------------
# main() integration tests
# ---------------------------------------------------------------------------


def test_main_nothing_to_do_exits_2(empty_candidates_json: Path) -> None:
    code = main(["--candidates-json", str(empty_candidates_json)])
    assert code == 2


def test_main_proposal_declined_exits_0(candidates_json: Path) -> None:
    with patch("ks.cli.confirm_yes_no", return_value=False):
        code = main(["--candidates-json", str(candidates_json)])
    assert code == 0


def test_main_proposal_accepted_dry_run_exits_0(candidates_json: Path) -> None:
    """dry_run is True in default config; execute should succeed without real device."""
    with patch("ks.cli.confirm_yes_no", return_value=True):
        code = main(["--candidates-json", str(candidates_json)])
    assert code == 0


def test_main_proposal_accepted_live_empty_actions_exits_1(
    candidates_json: Path, capsys: pytest.CaptureFixture
) -> None:
    """Live run with empty actions must fail closed, not pretend success."""
    cfg = load_config()
    cfg.dry_run = False
    with patch("ks.cli.load_config", return_value=cfg):
        with patch("ks.cli.confirm_yes_no", return_value=True):
            code = main(["--candidates-json", str(candidates_json)])
    assert code == 1
    err = capsys.readouterr().err
    assert "no actions to execute" in err


def test_main_bad_json_exits_1(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("not json at all {{{")
    code = main(["--candidates-json", str(bad)])
    assert code == 1


def test_main_missing_candidates_json_flag_exits_1() -> None:
    code = main([])
    assert code == 1


def test_main_near_tile_wins(candidates_json: Path, capsys: pytest.CaptureFixture) -> None:
    """The near candidate (higher score) should appear in the printed rationale."""
    with patch("ks.cli.confirm_yes_no", return_value=False):
        main(["--candidates-json", str(candidates_json)])
    out = capsys.readouterr().out
    assert "bread" in out
