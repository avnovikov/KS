# Object Digitization: Name OCR + Sprite Detection Design

**Date:** 2026-07-31  
**Status:** Approved for split implementation  
**Workspace:** `/Users/alexei/KS`  
**Foundation:** registered diamond mosaic + `cartograph.sqlite`  
**Related:** `2026-07-31-grid-foundation-sqlite-h3-design.md`, `2026-07-31-exact-object-registration-design.md`

## Goal

Fill the digital catalog with **named cities/alliance buildings** and **typed beasts/resources**, without per-object click-popup OCR. Two independent tracks share the same projection and SQLite store.

## Locked decisions

| Topic | Decision |
|-------|----------|
| Sequencing | Track A (names) and Track B (sprites) in parallel worktrees |
| Name OCR | Improve on existing frames first; targeted ADB zoom for misses — **no mass clicks** |
| Beasts/RSS | Hybrid: OpenCV templates now → YOLO when labeled set is large enough |
| Coords | Diamond tiles primary; project through existing affine + frame offsets |
| UI pins | Still cities + alliance only; sprites fill DB |
| Fail mode | Soft per-frame for OCR/sprites; do not abort mosaic |

## Track A — Name OCR v2

1. Stronger label OCR on masked bands (preprocess + EasyOCR and/or improved Tesseract; keep confidence).  
2. Merge into entity catalog with `ocr_projected` provenance.  
3. Optional later: ADB zoom screenshots for unresolved city-like candidates only.

**Owns:** `ks/cartograph/labels.py`, OCR portions of `entities.py` / pipeline digitize, `tests/test_cartograph_labels*.py` (new), OCR-related pipeline tests.

## Track B — Sprite templates → YOLO

1. Curate template pack under `assets/templates/cartograph/` (game crops + web refs; document licenses).  
2. Multi-scale template matcher → `rss` / `beast` / typed subclasses with `visual_projected`.  
3. Dataset export hooks for future YOLO; do not block Track A.

**Owns:** `ks/cartograph/sprites.py` (new), template assets, sprite tests, thin hook into `detect_frame_observations` via injectable detector (avoid rewriting OCR).

## Integration

Both tracks emit `EntityObservation`s; existing `merge_entity_observations` + SQLite write remain the sink. Prefer additive APIs so the two worktrees merge cleanly.

## Verification

- Track A: named city/alliance count on v9 rises materially vs baseline (~2 OCR entities).  
- Track B: synthetic band with planted beast/RSS templates recovers kind + approximate center.  
- Combined: `ui_pin` cities increase; RSS/beast rows appear with `ui_pin=0`.
