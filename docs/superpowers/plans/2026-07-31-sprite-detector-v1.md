# Track B: Sprite Templates → YOLO Path Implementation Plan

> **Worktree:** `.worktrees/feature-cartograph-sprite-detector-v1`  
> **Branch:** `feature/cartograph-sprite-detector-v1`

**Goal:** Detect beasts and resources via multi-scale template matching; structure assets and APIs so a YOLO trainer can replace templates later.

**Tech:** OpenCV template matching, pytest, optional future Ultralytics (not required this track).

## Files

| File | Change |
|------|--------|
| `ks/cartograph/sprites.py` | `match_sprites(band) -> list[EntityObservation]` |
| `assets/templates/cartograph/README.md` | How to add crops; license note |
| `assets/templates/cartograph/{beast,rss,wood,bread,stone,iron}/` | Seed templates (from local captures preferred; web only if license-ok) |
| `ks/cartograph/entities.py` | Call sprite matcher after OCR (injectable) |
| `tests/test_cartograph_sprites.py` | Planted template recovers kind |

## Tasks

1. Failing tests with synthetic band + known template paste.  
2. Implement multi-scale NCC/TM_CCOEFF_NORMED with score threshold + NMS.  
3. Seed ≥1 real crop per class from v9 frames if possible (prefer game captures over random web).  
4. Hook into `detect_frame_observations` without breaking OCR path.  
5. Stub `export_yolo_labels()` or dataset notes for graduation — no full train yet.

Do **not** rewrite `labels.py` OCR engine. Do not commit unless asked.
