# Exact Object Registration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Produce a globally registered, duplicate-free 25-frame mosaic and a provenance-aware object catalog with world coordinates.

**Architecture:** Exact popup anchors establish diamond geometry. A robust graph solver refines per-frame translations from static SIFT and unique-name constraints. Entity extraction then projects OCR/visual centers through the corrected geometry and merges observations by identity and coordinate.

**Tech Stack:** Python 3.13, NumPy, OpenCV SIFT, EasyOCR/Tesseract, pytest, YAML/JSON.

## Global Constraints

- Exact clicked coordinates remain the primary world-coordinate authority.
- Image matching may refine translations but must not define world scale.
- Dynamic animals/effects, HUD, fill masks, and unsupported repeated sprites do not constrain registration.
- Canonical output fails closed when graph or residual thresholds fail.
- Every entity coordinate includes confidence and provenance.

---

### Task 1: Robust global translation graph

**Files:**
- Create: `ks/cartograph/registration.py`
- Modify: `ks/cartograph/calibration.py`
- Test: `tests/test_cartograph_registration.py`

**Interfaces:**
- `PairTranslation(frame_a, frame_b, delta_x, delta_y, weight, source, inliers)`
- `RegistrationMetrics(median_px, p95_px, max_px, connected_frames)`
- `GlobalRegistration(frame_offsets, metrics, accepted, rejected)`
- `solve_frame_translations(constraints, reference_frame, expected_frames)`

- [ ] Write failing synthetic tests for exact recovery, weighted outlier rejection,
  disconnected graphs, and threshold failure.
- [ ] Implement robust weighted least squares with a fixed reference frame,
  Huber/MAD reweighting, graph-connectivity checks, and explicit diagnostics.
- [ ] Run focused registration/calibration tests.

### Task 2: Static overlap constraints

**Files:**
- Modify: `ks/cartograph/registration.py`
- Modify: `ks/cartograph/landmarks.py`
- Test: `tests/test_cartograph_registration.py`

**Interfaces:**
- `match_static_translation(frame_a, frame_b, seed_delta, mask_cfg)`
- `build_registration_constraints(frames, seed_offsets, landmarks_by_frame)`

- [ ] Write failing image tests with a known translation, a moving sprite, and
  repeated distractors.
- [ ] Implement masked SIFT matching with ratio filtering, seed-distance gating,
  robust translation inliers, and score/inlier thresholds.
- [ ] Convert unique-name matches into high-weight pair constraints.
- [ ] Keep exact/viewport offsets as priors with lower translation weight.
- [ ] Run focused tests and verify a connected 25-frame graph.

### Task 3: Provenance-aware entity catalog

**Files:**
- Modify: `ks/cartograph/models.py`
- Create: `ks/cartograph/entities.py`
- Modify: `ks/cartograph/labels.py`
- Modify: `ks/cartograph/dedupe.py`
- Test: `tests/test_cartograph_entities.py`

**Interfaces:**
- `EntityObservation`
- `EntityCatalogEntry`
- `detect_frame_observations()`
- `project_observation()`
- `merge_entity_observations()`

- [ ] Write failing tests for OCR center projection, badge/static candidates,
  popup-priority merging, provenance, confidence, and coordinate disagreement.
- [ ] Add typed immutable observation/catalog records.
- [ ] Extract OCR confidence and parsed level/type without changing existing
  label APIs.
- [ ] Detect conservative non-grass static components and badge-associated
  candidates; emit uncertain kinds as `unknown`.
- [ ] Project through corrected frame geometry and robustly merge cross-frame
  observations.
- [ ] Run focused entity, label, and dedupe tests.

### Task 4: Export and end-to-end rebuild

**Files:**
- Modify: `ks/cartograph/pipeline.py`
- Modify: `ks/cartograph/render_map.py`
- Modify: `ks/cartograph/mosaic.py`
- Test: `tests/test_cartograph_render_map.py`
- Generated: `artifacts/cartograph-grid300-5x5-badland-v9/`

- [ ] Add failing tests for registration diagnostics and entity provenance in
  `map.json`/CSV/YAML.
- [ ] Wire corrected offsets into `stitch_grid_lattice` as the sole placement
  authority.
- [ ] Export registration diagnostics and the canonical entity catalog.
- [ ] Rebuild the v9 panorama, map, JSON, and CSV.
- [ ] Verify all registration thresholds and cross-frame feature-track
  uniqueness before replacing canonical artifacts.

### Task 5: Final verification

- [ ] Run focused cartograph suites.
- [ ] Run lints for all edited Python files.
- [ ] Visually inspect the user-marked regions and overlay.
- [ ] Run a final independent agent review.
