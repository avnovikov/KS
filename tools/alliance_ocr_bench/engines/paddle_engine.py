"""Optional PaddleOCR adapter."""

from __future__ import annotations

import numpy as np

from tools.alliance_ocr_bench.schema import OcrHit


class PaddleEngine:
    name = "paddle"

    def __init__(self) -> None:
        self._ocr = None
        self._failed = False

    def available(self) -> bool:
        if self._failed:
            return False
        try:
            from paddleocr import PaddleOCR  # noqa: F401
        except ImportError:
            self._failed = True
            return False
        return True

    def _get_ocr(self):
        if self._ocr is not None:
            return self._ocr
        if not self.available():
            raise RuntimeError("paddleocr is not available")
        from paddleocr import PaddleOCR

        self._ocr = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
        return self._ocr

    def read(self, image_bgr: np.ndarray) -> list[OcrHit]:
        ocr = self._get_ocr()
        result = ocr.ocr(image_bgr, cls=True)
        hits: list[OcrHit] = []
        if not result:
            return hits
        for page in result:
            if not page:
                continue
            for item in page:
                box, (text, conf) = item
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
