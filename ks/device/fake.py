class FakeDevice:
    def __init__(self, png_bytes: bytes = b"\x89PNG\r\n\x1a\n") -> None:
        self.png_bytes = png_bytes
        self.taps: list[tuple[int, int]] = []

    def screencap(self) -> bytes:
        return self.png_bytes

    def tap(self, x: int, y: int) -> None:
        self.taps.append((x, y))

    def swipe(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration_ms: int = 300,
    ) -> None:
        pass
