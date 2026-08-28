from pathlib import Path

import cv2
import numpy as np

from tools.alliance_ocr_bench.run_bench import run_bench
from tools.alliance_ocr_bench.schema import OcrHit


class FakeEngine:
    name = "fake"

    def available(self) -> bool:
        return True

    def read(self, image_bgr: np.ndarray) -> list[OcrHit]:
        h, w = image_bgr.shape[:2]
        return [
            OcrHit("DarkLord", 0.99, (0, 0, w * 0.5, h * 0.4)),
            OcrHit("12.5M", 0.99, (0, h * 0.5, w * 0.5, h * 0.9)),
        ]


def test_run_bench_writes_report(tmp_path):
    shot = tmp_path / "synthetic.png"
    cv2.imwrite(str(shot), np.zeros((100, 200, 3), dtype=np.uint8))
    gold = tmp_path / "gold.json"
    gold.write_text(
        '[{"id":"1","shot":"synthetic.png","roi":null,"name":"DarkLord","power":12.5}]',
        encoding="utf-8",
    )
    out = tmp_path / "out"
    report_path = run_bench(
        gold_path=gold,
        shots_root=tmp_path,
        out_dir=out,
        engine_overrides=[FakeEngine()],
        profiles=["raw"],
    )
    assert report_path.exists()
    text = (out / "summary.md").read_text(encoding="utf-8")
    assert "fake" in text
    assert "f1" in text.lower() or "F1" in text
