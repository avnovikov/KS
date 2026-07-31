# Exact Object Registration and Digitization Design

## Goal

Remove stitch-created duplicates and assign world coordinates to every
confidently detected map object. Exact clicked coordinates define the diamond
projection; shared static content refines frame placement; OCR and visual
detection produce a provenance-aware digital entity catalog.

## Registration authority

Inputs are ordered by authority:

1. Popup OCR world coordinates and selected-diamond centers identify exact
   world anchors.
2. Unique city/object names identify the same static object across frames.
3. Static SIFT correspondences (buildings, rocks, trees) refine translations.
4. Viewport OCR and swipe geometry are weak priors only.

Animals, effects, HUD, masked pixels, and unconstrained repeated sprites are
excluded from registration.

The solver represents one translation offset per frame, fixes
`c0_center = (0, 0)`, and solves pairwise translation constraints with robust
weighted least squares. Exact anchors establish world scale and handedness;
static-image edges remove frame-specific errors.

## Registration acceptance

- All 25 frames belong to one connected constraint graph.
- Every overlap with at least 20 static inliers has residual at most 3 px.
- Median edge residual is at most 1 px and p95 at most 2 px.
- Unique name/world anchors agree within 2 px.
- Any failed threshold aborts canonical mosaic generation.

Diagnostics persist matrix, offsets, graph connectivity, pair inlier counts,
residuals, and rejected constraints.

## Entity observations

Each observation records:

- source frame and pixel center;
- normalized identity, visible label, kind, and level;
- projected floating world coordinate and rounded tile coordinate;
- confidence and provenance (`popup_exact`, `ocr_projected`,
  `visual_projected`, or `operator`);
- optional popup path and contributing frames.

Named structures come from OCR label centers. Unlabelled static candidates come
from non-grass structure components. Red level badges provide candidate object
centers for monsters/resources, but uncertain kinds remain `unknown` rather
than being invented.

Projected coordinates use the corrected frame offset and affine projection.
Popup-confirmed observations override projected observations. Cross-frame
observations merge only when identity and coordinates agree.

## Digital outputs

`entities.yaml`, `entities.csv`, and `map.json` include confidence, provenance,
source frames, and coordinate residuals. The panorama and digital catalog use
the same corrected projection.

## Verification

- Synthetic graph tests recover known offsets and reject disconnected or
  high-residual graphs.
- Feature matching tests ignore moving sprites and repeated unconstrained
  assets.
- Entity tests project OCR centers, prioritize popup observations, and
  deduplicate cross-frame identities.
- The v9 artifact must satisfy registration thresholds and produce no
  stitch-created second peak farther than 3 px for cross-frame feature tracks.
