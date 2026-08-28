# Alliance member OCR bake-off

Offline harness to compare OCR engines and preprocess settings on alliance
member name+power crops. Does **not** change the live `scan_70` path.

Spec: `docs/superpowers/specs/2026-08-20-alliance-member-ocr-bakeoff-design.md`  
Plan: `docs/superpowers/plans/2026-08-20-alliance-member-ocr-bakeoff.md`

## Install

```bash
source .venv/bin/activate
pip install -e ".[dev,alliance-ocr-bench]"
# system tesseract still required for the tesseract engine
brew install tesseract
```

Optional engines that fail to import are skipped in the report (OK on Apple Silicon if Paddle is awkward).

## 1) Mine unstable candidates

Uses the same Levenshtein / power-gap rules as the alliance export sheet.

```bash
python -m tools.alliance_ocr_bench.mine_unstable \
  --old /Users/alexei/KS/artifacts/alliance-r4-r3-scan/names-2026-08-18T0042.json \
  --new /Users/alexei/KS/artifacts/alliance-r4-r3-scan/names-2026-08-18T2035.json \
  --out /Users/alexei/KS/artifacts/alliance-ocr-bench/candidates.csv
```

A single day-pair may yield only a few rows. Cross-comparing all `names*.json`
snapshots produced ~30 unique LEVENSHTEIN candidates at
`artifacts/alliance-ocr-bench/candidates-all-pairs.csv` (good gold seed).

## 2) Hand-confirm gold

Create `/Users/alexei/KS/artifacts/alliance-ocr-bench/gold.json` (≥30 rows) from
the CSV + screenshots. Schema:

```json
[
  {
    "id": "abc-r4-00-1",
    "shot": "ABC-r4-00.png",
    "roi": null,
    "name": "CorrectName",
    "power": 12.5,
    "tag": "ABC",
    "rank_hint": "r4"
  }
]
```

`roi` is `[x0,y0,x1,y1]` or `null` for the default member band `(70,250)–(1030,1600)`.
`shot` paths are relative to `--shots-root`.

## 3) Run the bench

```bash
python -m tools.alliance_ocr_bench.run_bench \
  --gold /Users/alexei/KS/artifacts/alliance-ocr-bench/gold.json \
  --shots-root /Users/alexei/KS/artifacts/alliance-r4-r3-scan \
  --out /Users/alexei/KS/artifacts/alliance-ocr-bench/out
```

Outputs: `report.json`, `summary.md` ranked by row F1 (name-near + power±1.0).

Optional filters: `--engines easyocr tesseract` `--profiles raw gray_x2`.

## Engines

| Name | Notes |
|------|--------|
| `easyocr` | Baseline (live scan) |
| `tesseract` | pytesseract |
| `paddle` | optional |
| `rapid` | optional RapidOCR ONNX |
| `modern` | docTR if installed; Surya detected but not fully wired |

## Phase 2

Wire the winning engine×profile into `scan_70` / `reocr_from_shots` only after
you pick a winner from `summary.md`.
