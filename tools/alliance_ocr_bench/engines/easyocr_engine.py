"""EasyOCR adapter (live-scan baseline)."""

from __future__ import annotations

import cv2
import numpy as np

from tools.alliance_ocr_bench.schema import OcrHit


class EasyOcrEngine:
    name = "easyocr"

    def __init__(self) -> None:
        self._reader = None
        self._failed = False

    def available(self) -> bool:
        if self._failed:
            return False
        try:
            import easyocr  # noqa: F401
        except ImportError:
            self._failed = True
            return False
        return True

    def _get_reader(self):
        if self._reader is not None:
            return self._reader
        if not self.available():
            raise RuntimeError("easyocr is not available")
        import easyocr

        self._reader = easyocr.Reader(["en"], gpu=False, verbose=False)
        return self._reader

    def read(self, image_bgr: np.ndarray) -> list[OcrHit]:
        reader = self._get_reader()
        rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
        hits: list[OcrHit] = []
        for box, text, conf in reader.readtext(rgb, detail=1, paragraph=False):
            xs = [float(p[0]) for p in box]
            ys = [float(p[1]) for p in box]
            hits.append(
                OcrHit(
                    text=str(text).strip(),
                    conf=float(conf),
                    box_xyxy=(min(xs), min(ys), max(xs), max(ys)),
                )
            )
        return hits
