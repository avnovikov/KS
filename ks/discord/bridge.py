"""Map Discord gather intents onto existing KS propose/execute APIs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ks.config import AppConfig
from ks.device.base import Device
from ks.executor import execute
from ks.models import GatherCandidate, NothingToDo, Proposal, Tap
from ks.pipeline.gather_once import collect_candidates, detect_free_march
from ks.policy.gather import propose_gather


@dataclass(frozen=True)
class BridgeResult:
    ok: bool
    message: str
    skipped_dry_run: bool = False


def propose_gather_from_json(
    candidates_json: Path,
    app_cfg: AppConfig,
) -> Proposal | NothingToDo:
    """Load fixture candidates and return a gather proposal or NothingToDo."""
    if not candidates_json.is_file():
        raise FileNotFoundError(f"candidates JSON not found: {candidates_json}")
    raw = json.loads(candidates_json.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("candidates JSON must be a list of objects")
    candidates = [GatherCandidate(**item) for item in raw]
    return propose_gather(candidates, app_cfg, actions=())


def propose_gather_live(
    device: Device,
    app_cfg: AppConfig,
    *,
    assume_free_march: bool = False,
) -> Proposal | NothingToDo:
    """Navigate + OCR + propose without confirming or executing."""
    if not assume_free_march and not detect_free_march(device, app_cfg):
        return NothingToDo(reason="no free march slot detected")

    nav_taps = app_cfg.navigation.taps
    if nav_taps and not app_cfg.dry_run:
        execute(
            device,
            tuple(Tap(t.x, t.y) for t in nav_taps),
            dry_run=False,
            max_taps=app_cfg.executor.max_taps_per_proposal,
            tap_delay_ms=app_cfg.executor.tap_delay_ms,
            tap_jitter_ms=app_cfg.executor.tap_jitter_ms,
        )

    gather_actions = tuple(Tap(t.x, t.y) for t in app_cfg.navigation.gather_actions)
    candidates = collect_candidates(device, app_cfg)
    return propose_gather(candidates, app_cfg, actions=gather_actions)


def execute_proposal(
    device: Device,
    proposal: Proposal,
    app_cfg: AppConfig,
) -> BridgeResult:
    """Execute an approved proposal; respects ``app_cfg.dry_run``."""
    if not app_cfg.dry_run and not proposal.actions:
        return BridgeResult(
            ok=False,
            message=(
                "proposal has no actions to execute; "
                "set dry_run: true or provide gather_actions"
            ),
        )
    result = execute(
        device,
        proposal.actions,
        dry_run=app_cfg.dry_run,
        max_taps=app_cfg.executor.max_taps_per_proposal,
        tap_delay_ms=app_cfg.executor.tap_delay_ms,
        tap_jitter_ms=app_cfg.executor.tap_jitter_ms,
    )
    if result.skipped_dry_run:
        return BridgeResult(ok=True, message="dry-run skipped", skipped_dry_run=True)
    return BridgeResult(
        ok=True,
        message=f"executed ({result.taps_performed} taps)",
        skipped_dry_run=False,
    )
