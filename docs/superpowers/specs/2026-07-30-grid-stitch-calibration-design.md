# 3×3 Grid Stitch Calibration Design

## Goal

Capture nine clean KingShot world-map frames at offsets `−120, 0, +120`
pixels on both axes and stitch them without duplicated structures or gaps.

## Capture

- Start from a clean world-map view.
- Capture a filled 3×3 grid using 120-pixel horizontal and vertical drags.
- Reject any frame containing a popup, modal, or deployment UI.
- Record the persistent viewport coordinate bar for every frame.

## Calibration

Use two independent observation types:

1. Shared city-name OCR provides pixel translation between overlapping frames.
2. Exact `X:Y` coordinates obtained by clicking static objects provide world
   positions and independent horizontal and vertical scale.

Fit a robust affine world-to-pixel transform from these observations. Reject
OCR or click observations whose residual exceeds the configured tolerance.
Require evidence for both axes before producing the final mosaic.

## Stitching

- Place frames using the fitted transform.
- Use shared city landmarks to refine local translation.
- Use lighting-normalized image correlation only when landmark evidence is
  unavailable.
- Paste structure-rich pixels ahead of grass to preserve buildings and
  monsters.
- Emit a wireframe diagnostic showing frame bounds and accepted anchors.

## Failure Handling

Stop with an explicit error rather than writing a misleading panorama when:

- the game leaves the world map;
- a clean frame cannot be obtained;
- either axis lacks enough calibration evidence;
- fitted observations disagree beyond tolerance.

## Verification

- Unit-test independent X/Y scale fitting, outlier rejection, and 3×3 layout.
- Run capture and stitching tests.
- Visually verify that repeated city names and exact-coordinate objects align
  once, with no duplicated cities at frame boundaries.
