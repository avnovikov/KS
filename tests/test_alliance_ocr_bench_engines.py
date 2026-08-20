from tools.alliance_ocr_bench.engines.base import get_engines
from tools.alliance_ocr_bench.engines.tesseract_engine import TesseractEngine
import numpy as np


def test_registry_includes_easyocr_and_tesseract():
    names = {e.name for e in get_engines()}
    assert "easyocr" in names
    assert "tesseract" in names


def test_registry_includes_optional_engine_names():
    names = {e.name for e in get_engines()}
    assert {"paddle", "rapid", "modern"} <= names


def test_tesseract_available_flag_is_bool():
    eng = TesseractEngine()
    assert isinstance(eng.available(), bool)


def test_unavailable_engine_read_returns_empty_or_raises_not_required():
    eng = TesseractEngine()
    if not eng.available():
        try:
            eng.read(np.zeros((32, 64, 3), dtype=np.uint8))
            assert False, "expected RuntimeError"
        except RuntimeError:
            pass
