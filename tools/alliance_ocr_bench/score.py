"""Score OCR member predictions against a gold set."""

from __future__ import annotations

from dataclasses import dataclass

from tools.alliance_ocr_bench.pairing import pair_members
from tools.alliance_ocr_bench.schema import GoldRow, OcrHit
from tools.alliance_ocr_bench.stability import normalize_name, ocr_edit_distance


@dataclass
class ScoreSummary:
    name_exact: int = 0
    name_near: int = 0
    power_exact: int = 0
    power_within_0_1: int = 0
    power_within_1_0: int = 0
    row_tp: int = 0
    row_fp: int = 0
    row_fn: int = 0
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0


def hits_to_members(hits: list[OcrHit]) -> list[dict]:
    paired_hits: list[tuple[float, float, str, float]] = []
    for hit in hits:
        x0, y0, x1, y1 = hit.box_xyxy
        cx = (x0 + x1) / 2.0
        cy = (y0 + y1) / 2.0
        paired_hits.append((cx, cy, hit.text, hit.conf))
    return pair_members(paired_hits)


def _name_match_rank(gold_name: str, pred_name: str) -> int | None:
    if normalize_name(gold_name) == normalize_name(pred_name):
        return 0
    distance = ocr_edit_distance(gold_name, pred_name)
    if distance is None:
        return None
    return distance


def score_predictions(gold: list[GoldRow], predicted_members: list[dict]) -> ScoreSummary:
    gold_left = list(gold)
    pred_left = list(predicted_members)
    summary = ScoreSummary()

    candidates: list[tuple[int, float, GoldRow, dict]] = []
    for g in gold_left:
        for p in pred_left:
            rank = _name_match_rank(g.name, str(p["name"]))
            if rank is None:
                continue
            gap = abs(float(p["power"]) - g.power)
            if gap > 1.0:
                continue
            candidates.append((rank, gap, g, p))
    candidates.sort(key=lambda item: (item[0], item[1]))

    used_gold: set[int] = set()
    used_pred: set[int] = set()
    for rank, gap, g, p in candidates:
        if id(g) in used_gold or id(p) in used_pred:
            continue
        if g not in gold_left or p not in pred_left:
            continue
        used_gold.add(id(g))
        used_pred.add(id(p))
        gold_left.remove(g)
        pred_left.remove(p)
        summary.row_tp += 1
        if rank == 0:
            summary.name_exact += 1
        else:
            summary.name_near += 1
        if gap == 0:
            summary.power_exact += 1
        if gap <= 0.1:
            summary.power_within_0_1 += 1
        if gap <= 1.0:
            summary.power_within_1_0 += 1

    summary.row_fn = len(gold_left)
    summary.row_fp = len(pred_left)
    denom_p = summary.row_tp + summary.row_fp
    denom_r = summary.row_tp + summary.row_fn
    summary.precision = summary.row_tp / denom_p if denom_p else 0.0
    summary.recall = summary.row_tp / denom_r if denom_r else 0.0
    if summary.precision + summary.recall:
        summary.f1 = (
            2 * summary.precision * summary.recall / (summary.precision + summary.recall)
        )
    else:
        summary.f1 = 0.0
    return summary
