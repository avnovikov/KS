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
