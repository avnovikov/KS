"""Single-shot gather pipeline: navigate → detect march → collect → propose → execute.

Navigation tap coordinates and OCR crop boxes are read exclusively from
AppConfig (params.yaml), so no magic numbers appear in this module.
"""
from __future__ import annotations

from typing import Callable

import cv2
import numpy as np

from ks.config import AppConfig
from ks.device.base import Device
from ks.executor import execute
from ks.models import GatherCandidate, NothingToDo
from ks.policy.gather import propose_gather
from ks.vision.ocr import ocr_region, parse_march_time, parse_rss_amount


def detect_free_march(device: Device, cfg: AppConfig) -> bool:
    """Return True if a free march slot appears available.

    With no march-available template configured this returns True (bring-up
    shortcut).  A future task can add template matching here.
    """
    print("detect_free_march: no template configured; assuming free march")
    return True


def collect_candidates(device: Device, cfg: AppConfig) -> list[GatherCandidate]:
    """Screencap and OCR configured candidate regions.

    Returns an empty list when ``cfg.ocr_regions.candidates`` is empty, which
    lets offline tests work without any OCR configuration.  Each region that
    fails to parse is skipped with a warning rather than aborting the run
    (fail-closed OCR per spec).
    """
    regions = cfg.ocr_regions.candidates
    if not regions:
        return []

    png = device.screencap()
    img_array = np.frombuffer(png, np.uint8)
    frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
    if frame is None:
        print("collect_candidates: screencap decode failed; returning no candidates")
        return []

    candidates: list[GatherCandidate] = []
    for region in regions:
        try:
            amount_text = ocr_region(
                frame,
                (region.amount.x, region.amount.y, region.amount.w, region.amount.h),
            )
            march_text = ocr_region(
                frame,
                (
                    region.march_time.x,
                    region.march_time.y,
                    region.march_time.w,
                    region.march_time.h,
                ),
            )
            tile_amount = parse_rss_amount(amount_text)
            march_s = parse_march_time(march_text)
            candidates.append(
                GatherCandidate(
                    resource=region.resource,
                    tile_amount=tile_amount,
                    march_time_one_way_s=march_s,
                    vision_confidence=1.0,
                )
            )
        except ValueError as exc:
            print(f"collect_candidates: skipping '{region.resource}': {exc}")

    return candidates[: cfg.scoring.candidate_limit]


def gather_once(
    device: Device,
    cfg: AppConfig,
    *,
    input_fn: Callable[[str], str] = input,
    assume_free_march: bool = False,
) -> int:
    """Run one gather cycle.

    Steps:
    1. Detect free march slot (skipped when ``assume_free_march`` is True).
    2. Perform YAML-configured navigation taps.
    3. Collect candidates via OCR.
    4. Propose the best gather.
    5. Confirm with the user.
    6. Execute (respects ``cfg.dry_run``).

    Returns:
        0  – proposal presented and either executed or declined by user
        2  – nothing to do (no free march or no viable candidates)
    """
    if not assume_free_march and not detect_free_march(device, cfg):
        print("No free march slot detected; skipping gather.")
        return 2

    nav_taps = cfg.navigation.taps
    if nav_taps:
        if cfg.dry_run:
            print(f"dry-run: would navigate with {len(nav_taps)} tap(s)")
        else:
            for tap in nav_taps:
                device.tap(tap.x, tap.y)

    candidates = collect_candidates(device, cfg)

    result = propose_gather(candidates, cfg, actions=())
    if isinstance(result, NothingToDo):
        print(f"Nothing to do: {result.reason}")
        return 2

    print(f"Proposal: {result.rationale}")
    confirmed = _confirm_yes_no("Execute this gather?", input_fn=input_fn)

    if not confirmed:
        print("Cancelled.")
        return 0

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


def _confirm_yes_no(prompt: str, *, input_fn: Callable[[str], str]) -> bool:
    """Prompt the user for y/n; injected input_fn enables offline testing."""
    if input_fn is not input:
        return input_fn(f"{prompt} [y/n]: ").strip().lower() == "y"
    while True:
        response = input(f"{prompt} [y/n]: ").strip().lower()
        if response == "y":
            return True
        if response == "n":
            return False
        print("Please enter y or n.")
