"""Offline tests for gather_once pipeline (Task 9).

Uses FakeDevice + monkeypatched collect_candidates / detect_free_march so no
emulator is required.
"""
import pytest

from ks.config import load_config
from ks.device.fake import FakeDevice
from ks.models import GatherCandidate
from ks.pipeline.gather_once import gather_once
from tests.test_gather_policy import _MIN_YAML


def test_gather_once_dry_run_yes_performs_zero_taps(tmp_path, monkeypatch, capsys):
    from tests.test_gather_policy import _cfg

    cfg = _cfg(tmp_path)
    assert cfg.dry_run is True
    device = FakeDevice(b"\x89PNG\r\n\x1a\nfake")

    def fake_collect(device, cfg):
        return [
            GatherCandidate("bread", 14_000_000, 3600.0, 0.9),
            GatherCandidate("bread", 200_000, 30.0, 0.9),
        ]

    monkeypatch.setattr("ks.pipeline.gather_once.collect_candidates", fake_collect)
    monkeypatch.setattr("ks.pipeline.gather_once.detect_free_march", lambda device, cfg: True)

    code = gather_once(device, cfg, input_fn=lambda _: "y")
    captured = capsys.readouterr().out
    assert code == 0
    assert "score=" in captured
    assert device.taps == []


def test_gather_once_dry_run_does_not_navigate(tmp_path, monkeypatch, capsys):
    yaml_with_nav = _MIN_YAML.replace(
        "navigation: {}",
        """navigation:
  taps:
    - {x: 54, y: 1820}
    - {x: 900, y: 100}""",
    )
    p = tmp_path / "params.yaml"
    p.write_text(yaml_with_nav, encoding="utf-8")
    cfg = load_config(p)
    assert cfg.dry_run is True
    assert len(cfg.navigation.taps) == 2

    device = FakeDevice()
    monkeypatch.setattr("ks.pipeline.gather_once.detect_free_march", lambda d, c: True)
    monkeypatch.setattr(
        "ks.pipeline.gather_once.collect_candidates",
        lambda d, c: [GatherCandidate("bread", 500_000, 60.0, 0.9)],
    )

    code = gather_once(device, cfg, input_fn=lambda _: "n")
    assert code == 0
    assert device.taps == []
    out = capsys.readouterr().out
    assert "dry-run: would navigate with 2 tap(s)" in out


def test_gather_once_no_free_march_returns_2(tmp_path, monkeypatch):
    from tests.test_gather_policy import _cfg

    cfg = _cfg(tmp_path)
    device = FakeDevice()
    monkeypatch.setattr("ks.pipeline.gather_once.detect_free_march", lambda d, c: False)

    code = gather_once(device, cfg)
    assert code == 2
    assert device.taps == []


def test_gather_once_no_candidates_returns_2(tmp_path, monkeypatch, capsys):
    from tests.test_gather_policy import _cfg

    cfg = _cfg(tmp_path)
    device = FakeDevice()
    monkeypatch.setattr("ks.pipeline.gather_once.detect_free_march", lambda d, c: True)
    monkeypatch.setattr("ks.pipeline.gather_once.collect_candidates", lambda d, c: [])

    code = gather_once(device, cfg)
    assert code == 2
    out = capsys.readouterr().out
    assert "Nothing to do" in out


def test_gather_once_user_declines_returns_0(tmp_path, monkeypatch, capsys):
    from tests.test_gather_policy import _cfg

    cfg = _cfg(tmp_path)
    device = FakeDevice()
    monkeypatch.setattr("ks.pipeline.gather_once.detect_free_march", lambda d, c: True)
    monkeypatch.setattr(
        "ks.pipeline.gather_once.collect_candidates",
        lambda d, c: [GatherCandidate("bread", 500_000, 60.0, 0.9)],
    )

    code = gather_once(device, cfg, input_fn=lambda _: "n")
    assert code == 0
    out = capsys.readouterr().out
    assert "Cancelled" in out
    assert device.taps == []


def test_gather_once_assume_free_march_skips_detection(tmp_path, monkeypatch, capsys):
    """--assume-free-march must bypass detect_free_march entirely."""
    from tests.test_gather_policy import _cfg

    cfg = _cfg(tmp_path)
    device = FakeDevice()

    detection_called = []

    def spy_detect(d, c):
        detection_called.append(True)
        return False  # would block gather if called

    monkeypatch.setattr("ks.pipeline.gather_once.detect_free_march", spy_detect)
    monkeypatch.setattr(
        "ks.pipeline.gather_once.collect_candidates",
        lambda d, c: [GatherCandidate("bread", 500_000, 60.0, 0.9)],
    )

    code = gather_once(device, cfg, input_fn=lambda _: "y", assume_free_march=True)
    assert not detection_called, "detect_free_march should not be called when assume_free_march=True"
    assert code == 0
