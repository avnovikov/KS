from typing import Protocol


class Device(Protocol):
    def screencap(self) -> bytes: ...

    def tap(self, x: int, y: int) -> None: ...

    def swipe(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration_ms: int = 300,
    ) -> None: ...
