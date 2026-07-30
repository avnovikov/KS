from __future__ import annotations

from typing import TYPE_CHECKING

from adbutils import AdbClient
from adbutils.errors import AdbError

if TYPE_CHECKING:
    from adbutils import AdbDevice as AdbUtilsDevice


class AdbDevice:
    def __init__(self, device: AdbUtilsDevice) -> None:
        self._device = device

    @classmethod
    def connect(cls, serial: str | None = None) -> AdbDevice:
        try:
            client = AdbClient()
            device = client.device(serial=serial)
        except AdbError as exc:
            raise RuntimeError(
                f"No ADB device available{f' (serial={serial!r})' if serial else ''}: {exc}"
            ) from exc
        return cls(device)

    def screencap(self) -> bytes:
        png_bytes = self._device.shell(["screencap", "-p"], encoding=None)
        assert isinstance(png_bytes, bytes), "screencap must return raw PNG bytes"
        return png_bytes

    def tap(self, x: int, y: int) -> None:
        self._device.shell(["input", "tap", str(x), str(y)])

    def swipe(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration_ms: int = 300,
    ) -> None:
        self._device.shell(
            ["input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration_ms)]
        )
