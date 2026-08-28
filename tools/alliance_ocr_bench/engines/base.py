"""OCR engine protocol and registry."""

from __future__ import annotations

from typing import Protocol

import numpy as np

from tools.alliance_ocr_bench.schema import OcrHit


class OcrEngine(Protocol):
    name: str

    def available(self) -> bool: ...

    def read(self, image_bgr: np.ndarray) -> list[OcrHit]: ...


def get_engines() -> list[OcrEngine]:
    from tools.alliance_ocr_bench.engines.easyocr_engine import EasyOcrEngine
    from tools.alliance_ocr_bench.engines.modern_engine import ModernEngine
    from tools.alliance_ocr_bench.engines.paddle_engine import PaddleEngine
    from tools.alliance_ocr_bench.engines.rapid_engine import RapidEngine
    from tools.alliance_ocr_bench.engines.tesseract_engine import TesseractEngine

    return [
        EasyOcrEngine(),
        TesseractEngine(),
        PaddleEngine(),
        RapidEngine(),
        ModernEngine(),
    ]
