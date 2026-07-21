import random
import time
from dataclasses import dataclass

from ks.device.base import Device
from ks.models import Action, Tap, Wait


@dataclass(frozen=True)
class ExecuteResult:
    taps_performed: int
    skipped_dry_run: bool


def execute(
    device: Device,
    actions: tuple[Action, ...],
    *,
    dry_run: bool,
    max_taps: int,
    tap_delay_ms: int,
    tap_jitter_ms: int,
) -> ExecuteResult:
    if dry_run:
        return ExecuteResult(taps_performed=0, skipped_dry_run=True)

    planned_taps = sum(1 for action in actions if isinstance(action, Tap))
    if planned_taps > max_taps:
        raise ValueError(
            f"planned tap count {planned_taps} exceeds max_taps {max_taps}"
        )

    taps_performed = 0
    for index, action in enumerate(actions):
        if isinstance(action, Tap):
            device.tap(action.x, action.y)
            taps_performed += 1
            has_more_taps = any(
                isinstance(following, Tap) for following in actions[index + 1 :]
            )
            if has_more_taps and (tap_delay_ms > 0 or tap_jitter_ms > 0):
                jitter = random.randint(0, tap_jitter_ms) if tap_jitter_ms > 0 else 0
                time.sleep((tap_delay_ms + jitter) / 1000)
        elif isinstance(action, Wait):
            time.sleep(action.ms / 1000)

    return ExecuteResult(taps_performed=taps_performed, skipped_dry_run=False)
