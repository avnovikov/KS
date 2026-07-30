"""Tests for BlueStacks connect helper (mocked adb)."""

from unittest.mock import patch

import pytest

from ks.device import bluestacks


def test_list_device_serials_parses_adb_devices() -> None:
    fake = "List of devices attached\n127.0.0.1:5555\tdevice\nemulator-5554\toffline\n"

    class Proc:
        stdout = fake
        stderr = ""
        returncode = 0

    with patch.object(bluestacks, "_run_adb", return_value=Proc()):
        assert bluestacks.list_device_serials() == ["127.0.0.1:5555"]


def test_try_connect_prefers_existing() -> None:
    with patch.object(
        bluestacks, "list_device_serials", return_value=["127.0.0.1:5565"]
    ):
        assert bluestacks.try_connect_bluestacks() == "127.0.0.1:5565"


def test_connect_port_requires_online_device() -> None:
    class Proc:
        stdout = "connected to 127.0.0.1:5555\n"
        stderr = ""
        returncode = 0

    with patch.object(bluestacks, "_run_adb", return_value=Proc()):
        with patch.object(bluestacks, "list_device_serials", return_value=[]):
            with pytest.raises(RuntimeError, match="not online"):
                bluestacks.connect_port(5555)


def test_connect_port_ok_when_listed() -> None:
    class Proc:
        stdout = "connected to 127.0.0.1:5555\n"
        stderr = ""
        returncode = 0

    with patch.object(bluestacks, "_run_adb", return_value=Proc()):
        with patch.object(
            bluestacks, "list_device_serials", return_value=["127.0.0.1:5555"]
        ):
            assert bluestacks.connect_port(5555) == "127.0.0.1:5555"
