"""Optional modern OCR adapter: prefer docTR, fall back to Surya."""

from __future__ import annotations

import numpy as np

from tools.alliance_ocr_bench.schema import OcrHit


class ModernEngine:
    name = "modern"

    def __init__(self) -> None:
        self._backend: str | None = None
        self._predictor = None
        self._failed = False

    def available(self) -> bool:
        if self._failed:
            return False
        if self._backend is not None:
            return True
        try:
            import doctr  # noqa: F401

            self._backend = "doctr"
            return True
        except ImportError:
            pass
        try:
            import surya  # noqa: F401

            self._backend = "surya"
            return True
        except ImportError:
            self._failed = True
            return False

    def _ensure(self) -> None:
        if not self.available():
            raise RuntimeError("modern OCR (docTR/Surya) is not available")
        if self._predictor is not None:
            return
        if self._backend == "doctr":
            from doctr.io import DocumentFile
            from doctr.models import ocr_predictor

            self._predictor = (DocumentFile, ocr_predictor(pretrained=True))
            return
        raise RuntimeError(
            "Surya backend selected but full wiring is deferred; install python-doctr"
        )

    def read(self, image_bgr: np.ndarray) -> list[OcrHit]:
        self._ensure()
        assert self._backend == "doctr"
        import cv2
        from doctr.io import DocumentFile

        _DocumentFile, predictor = self._predictor
        rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
        # doctr DocumentFile.from_images expects path or PIL; use numpy via pages API
        from PIL import Image

        pil = Image.fromarray(rgb)
        doc = DocumentFile.from_images([np.array(pil)])
        result = predictor(doc)
        hits: list[OcrHit] = []
        h, w = image_bgr.shape[:2]
        for page in result.pages:
            for block in page.blocks:
                for line in block.lines:
                    for word in line.words:
                        (x0, y0), (x1, y1) = word.geometry
                        hits.append(
                            OcrHit(
                                text=str(word.value).strip(),
                                conf=float(getattr(word, "confidence", 0.5) or 0.5),
                                box_xyxy=(x0 * w, y0 * h, x1 * w, y1 * h),
                            )
                        )
        return hits
