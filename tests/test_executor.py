from unittest.mock import patch

from ks.device.fake import FakeDevice
from ks.executor import execute
from ks.models import Tap, Wait


def test_dry_run_performs_zero_taps():
    d = FakeDevice(b"png")
    result = execute(
        d,
        (Tap(1, 2), Wait(10), Tap(3, 4)),
        dry_run=True,
        max_taps=20,
        tap_delay_ms=0,
        tap_jitter_ms=0,
    )
    assert result.skipped_dry_run is True
    assert result.taps_performed == 0
    assert d.taps == []


def test_live_respects_max_taps():
    d = FakeDevice(b"png")
    try:
        execute(
            d,
            (Tap(1, 1), Tap(2, 2), Tap(3, 3)),
            dry_run=False,
            max_taps=2,
            tap_delay_ms=0,
            tap_jitter_ms=0,
        )
        assert False, "expected ValueError"
    except ValueError as e:
        assert "max_taps" in str(e)
    assert len(d.taps) <= 2


@patch("ks.executor.time.sleep")
def test_tap_delay_applies_only_between_taps(mock_sleep):
    d = FakeDevice(b"png")
    execute(
        d,
        (Tap(1, 1), Tap(2, 2), Tap(3, 3)),
        dry_run=False,
        max_taps=20,
        tap_delay_ms=50,
        tap_jitter_ms=0,
    )
    assert mock_sleep.call_count == 2
    assert all(call.args == (0.05,) for call in mock_sleep.call_args_list)


@patch("ks.executor.time.sleep")
def test_single_tap_skips_inter_tap_delay(mock_sleep):
    d = FakeDevice(b"png")
    execute(
        d,
        (Tap(1, 1),),
        dry_run=False,
        max_taps=20,
        tap_delay_ms=50,
        tap_jitter_ms=0,
    )
    mock_sleep.assert_not_called()
