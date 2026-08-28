"""Run alliance member OCR bake-off across engines and preprocess profiles."""

from __future__ import annotations

import argparse
import json
import statistics
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from tools.alliance_ocr_bench.engines.base import OcrEngine, get_engines
from tools.alliance_ocr_bench.preprocess import apply_profile, list_profiles
from tools.alliance_ocr_bench.schema import GoldRow, load_gold
from tools.alliance_ocr_bench.score import ScoreSummary, hits_to_members, score_predictions

DEFAULT_BAND = (70, 250, 1030, 1600)  # x0, y0, x1, y1


def _crop_gold(image: np.ndarray, row: GoldRow) -> np.ndarray:
    if row.roi is not None:
        x0, y0, x1, y1 = row.roi
    else:
        x0, y0, x1, y1 = DEFAULT_BAND
    h, w = image.shape[:2]
    x0 = max(0, min(w, x0))
    x1 = max(0, min(w, x1))
    y0 = max(0, min(h, y0))
    y1 = max(0, min(h, y1))
    if x1 <= x0 or y1 <= y0:
        raise ValueError(f"invalid crop for gold id={row.id}: {(x0, y0, x1, y1)}")
    return image[y0:y1, x0:x1]


def _merge_summaries(parts: list[ScoreSummary]) -> ScoreSummary:
    merged = ScoreSummary()
    for part in parts:
        merged.name_exact += part.name_exact
        merged.name_near += part.name_near
        merged.power_exact += part.power_exact
        merged.power_within_0_1 += part.power_within_0_1
        merged.power_within_1_0 += part.power_within_1_0
        merged.row_tp += part.row_tp
        merged.row_fp += part.row_fp
        merged.row_fn += part.row_fn
    denom_p = merged.row_tp + merged.row_fp
    denom_r = merged.row_tp + merged.row_fn
    merged.precision = merged.row_tp / denom_p if denom_p else 0.0
    merged.recall = merged.row_tp / denom_r if denom_r else 0.0
    if merged.precision + merged.recall:
        merged.f1 = (
            2 * merged.precision * merged.recall / (merged.precision + merged.recall)
        )
    else:
        merged.f1 = 0.0
    return merged


def _write_summary(path: Path, rows: list[dict[str, Any]]) -> None:
    lines = [
        "# Alliance OCR bake-off summary",
        "",
        "| engine | profile | status | F1 | precision | recall | latency_ms |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        if row.get("status") != "ok":
            lines.append(
                f"| {row['engine']} | {row.get('profile', '')} | {row['status']} |  |  |  |  |"
            )
            continue
        m = row["metrics"]
        lines.append(
            "| {engine} | {profile} | ok | {f1:.3f} | {precision:.3f} | {recall:.3f} | {lat:.1f} |".format(
                engine=row["engine"],
                profile=row["profile"],
                f1=m["f1"],
                precision=m["precision"],
                recall=m["recall"],
                lat=row.get("latency_ms_median") or 0.0,
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_bench(
    gold_path: Path,
    shots_root: Path,
    out_dir: Path,
    engines: list[str] | None = None,
    profiles: list[str] | None = None,
    engine_overrides: list[OcrEngine] | None = None,
) -> Path:
    gold_rows = load_gold(gold_path)
    selected_profiles = profiles or list_profiles()
    engine_list = list(engine_overrides) if engine_overrides is not None else get_engines()
    if engines is not None:
        wanted = set(engines)
        engine_list = [e for e in engine_list if e.name in wanted]

    out_dir.mkdir(parents=True, exist_ok=True)
    report: list[dict[str, Any]] = []

    for engine in engine_list:
        if not engine.available():
            report.append(
                {
                    "engine": engine.name,
                    "profile": "",
                    "status": "skipped",
                    "reason": "not available",
                }
            )
            continue
        for profile in selected_profiles:
            parts: list[ScoreSummary] = []
            latencies: list[float] = []
            errors: list[str] = []
            for row in gold_rows:
                shot_path = shots_root / row.shot
                if not shot_path.exists():
                    errors.append(f"missing shot {shot_path}")
                    parts.append(ScoreSummary(row_fn=1))
                    continue
                image = cv2.imread(str(shot_path))
                if image is None:
                    errors.append(f"unreadable shot {shot_path}")
                    parts.append(ScoreSummary(row_fn=1))
                    continue
                try:
                    crop = _crop_gold(image, row)
                    processed = apply_profile(profile, crop)
                    started = time.perf_counter()
                    hits = engine.read(processed)
                    latencies.append((time.perf_counter() - started) * 1000.0)
                    members = hits_to_members(hits)
                    parts.append(score_predictions([row], members))
                except Exception as exc:  # noqa: BLE001 - bench must continue
                    errors.append(f"{row.id}: {exc}")
                    parts.append(ScoreSummary(row_fn=1))
            summary = _merge_summaries(parts)
            report.append(
                {
                    "engine": engine.name,
                    "profile": profile,
                    "status": "ok",
                    "metrics": asdict(summary),
                    "latency_ms_median": (
                        float(statistics.median(latencies)) if latencies else None
                    ),
                    "errors": errors,
                }
            )

    report.sort(
        key=lambda item: (
            0 if item.get("status") == "ok" else 1,
            -(item.get("metrics", {}) or {}).get("f1", 0.0),
            item.get("engine", ""),
            item.get("profile", ""),
        )
    )
    report_path = out_dir / "report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    _write_summary(out_dir / "summary.md", report)
    return report_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--shots-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--engines", nargs="*", default=None)
    parser.add_argument("--profiles", nargs="*", default=None)
    args = parser.parse_args(argv)
    path = run_bench(
        gold_path=args.gold,
        shots_root=args.shots_root,
        out_dir=args.out,
        engines=args.engines,
        profiles=args.profiles,
    )
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
