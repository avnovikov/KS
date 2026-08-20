"""Tesseract adapter via pytesseract."""

from __future__ import annotations

import shutil

import cv2
import numpy as np

from tools.alliance_ocr_bench.schema import OcrHit


def _tesseract_cmd() -> str | None:
    for candidate in (
        "/opt/homebrew/bin/tesseract",
        "/usr/local/bin/tesseract",
        shutil.which("tesseract"),
    ):
        if candidate:
            return candidate
    return None


class TesseractEngine:
    name = "tesseract"

    def __init__(self, psm: int = 6) -> None:
        self.psm = psm

    def available(self) -> bool:
        try:
            import pytesseract  # noqa: F401
        except ImportError:
            return False
        return _tesseract_cmd() is not None

    def read(self, image_bgr: np.ndarray) -> list[OcrHit]:
        if not self.available():
            raise RuntimeError("tesseract is not available")
        import pytesseract

        cmd = _tesseract_cmd()
        assert cmd is not None
        pytesseract.pytesseract.tesseract_cmd = cmd
        gray = (
            image_bgr
            if image_bgr.ndim == 2
            else cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
        )
        data = pytesseract.image_to_data(
            gray,
            output_type=pytesseract.Output.DICT,
            config=f"--psm {self.psm}",
        )
        hits: list[OcrHit] = []
        n = len(data["text"])
        for i in range(n):
            text = str(data["text"][i]).strip()
            if not text:
                continue
            conf_raw = float(data["conf"][i])
            if conf_raw < 0:
                continue
            x = float(data["left"][i])
            y = float(data["top"][i])
            w = float(data["width"][i])
            h = float(data["height"][i])
            hits.append(
                OcrHit(
                    text=text,
                    conf=conf_raw / 100.0,
                    box_xyxy=(x, y, x + w, y + h),
                )
            )
        return hits
