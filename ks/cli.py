"""CLI entry point for the KingShot gather optimiser.

Usage:
    ks --candidates-json <path>           # fixture / CI mode
    ks --candidates-json <path> --config <path>
    ks --live                             # live ADB mode (reads screen via OCR)
    ks --live --assume-free-march         # skip march-slot detection (bring-up)

Exit codes:
    0  – ok (executed or user declined)
    1  – error (bad args, bad JSON, config load failure, ADB failure)
    2  – nothing to do (no viable candidates)
"""
import argparse
import json
import sys
from pathlib import Path

from ks.config import load_config
from ks.device.fake import FakeDevice
from ks.executor import execute
from ks.models import GatherCandidate, NothingToDo
from ks.policy.gather import propose_gather


def confirm_yes_no(prompt: str, input_fn=input) -> bool:
    """Return True iff the user answers 'y' (case-insensitive).

    With an injected ``input_fn`` (e.g. in tests), any response other than
    'y'/'Y' is treated as False.  With real stdin the function accepts only
    y/n and re-prompts on garbage.
    """
    if input_fn is not input:
        return input_fn(f"{prompt} [y/n]: ").strip().lower() == "y"

    while True:
        response = input(f"{prompt} [y/n]: ").strip().lower()
        if response == "y":
            return True
        if response == "n":
            return False
        print("Please enter y or n.")


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ks",
        description="KingShot gather optimiser – propose and execute gather actions.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        metavar="PATH",
        help="Path to params.yaml (defaults to config/params.yaml).",
    )
    parser.add_argument(
        "--candidates-json",
        type=Path,
        dest="candidates_json",
        default=None,
        metavar="PATH",
        help="JSON file with a list of GatherCandidate dicts (fixture / CI mode).",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        default=False,
        help="Live ADB mode: screencap + OCR instead of a fixture JSON file.",
    )
    parser.add_argument(
        "--assume-free-march",
        action="store_true",
        dest="assume_free_march",
        default=False,
        help="Skip march-slot detection (useful during bring-up).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.  Returns an integer exit code."""
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    if not args.live and args.candidates_json is None:
        print(
            "Error: --candidates-json is required for fixture mode.  "
            "Run: ks --candidates-json tests/fixtures/candidates.json  "
            "or use --live for ADB mode.",
            file=sys.stderr,
        )
        return 1

    try:
        cfg = load_config(args.config)
    except Exception as exc:  # noqa: BLE001
        print(f"Error loading config: {exc}", file=sys.stderr)
        return 1

    if args.live:
        return _run_live(cfg, assume_free_march=args.assume_free_march)

    return _run_fixture(cfg, candidates_json=args.candidates_json)


def _run_live(cfg, *, assume_free_march: bool) -> int:
    """Connect to ADB device and run one gather cycle via gather_once."""
    from ks.device.adb import AdbDevice
    from ks.pipeline.gather_once import gather_once

    try:
        serial = cfg.adb.get("serial") if isinstance(cfg.adb, dict) else None
        device = AdbDevice.connect(serial=serial)
    except RuntimeError as exc:
        print(f"Error connecting to ADB device: {exc}", file=sys.stderr)
        return 1

    return gather_once(device, cfg, assume_free_march=assume_free_march)


def _run_fixture(cfg, *, candidates_json: Path) -> int:
    """Fixture / CI mode: load candidates from JSON, propose, confirm, execute."""
    try:
        raw = json.loads(candidates_json.read_text(encoding="utf-8"))
        candidates = [GatherCandidate(**item) for item in raw]
    except Exception as exc:  # noqa: BLE001
        print(f"Error loading candidates from {candidates_json}: {exc}", file=sys.stderr)
        return 1

    result = propose_gather(candidates, cfg, actions=())

    if isinstance(result, NothingToDo):
        print(f"Nothing to do: {result.reason}")
        return 2

    print(f"Proposal: {result.rationale}")
    confirmed = confirm_yes_no("Execute this gather?")

    if not confirmed:
        print("Cancelled.")
        return 0

    if not cfg.dry_run and not result.actions:
        print(
            "Error: proposal has no actions to execute. "
            "Fixture mode is propose-only; set dry_run: true or provide actions.",
            file=sys.stderr,
        )
        return 1

    device = FakeDevice()
    execute(
        device,
        result.actions,
        dry_run=cfg.dry_run,
        max_taps=cfg.executor.max_taps_per_proposal,
        tap_delay_ms=cfg.executor.tap_delay_ms,
        tap_jitter_ms=cfg.executor.tap_jitter_ms,
    )
    status = "dry-run skipped" if cfg.dry_run else "done"
    print(f"Execute result: {status}.")
    return 0
