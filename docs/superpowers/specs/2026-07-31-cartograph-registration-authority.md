# Cartograph Registration Authority (2026-07-31)

> **Status:** locked. Canonical stitch uses click calibration; viewport OCR is fallback only.  
> **Reference artifact:** `artifacts/cartograph-grid300-5x5-badland-v9/`  
> **Code:** `ks/cartograph/pipeline.py` (`REGISTRATION_AUTHORITY_ORDER`, `resolve_capture_stitch_route`)

## Authority order (highest → lowest)

1. **Popup click + selected diamond** — tap a static map object, read popup `X,Y`, detect the selected-diamond pixel. Defines world scale and handedness (`exact-coordinate-calibration*.yaml`).
2. **Unique name landmarks** — same city / unique structure label across overlapping frames (translation constraints).
3. **Static SIFT** — buildings, rocks, trees; refine frame translations only (must not redefine world scale).
4. **Viewport / search-bar OCR** — bottom-of-screen camera coords. **Weak prior / offline fallback only.**

Animals, HUD, masked fill, and repeated ambiguous sprites (e.g. alliance mills) do not constrain registration.

## CLI / stitch routing

- `ks-cartograph --map --capture-dir DIR` calls `resolve_capture_stitch_route`:
  - seed YAML present → `register_and_digitize_capture` (canonical)
  - missing seed → viewport-OCR diamond stitch with an explicit WARNING
- `--require-registration` fails closed when no seed exists
- Live click + swipe calibration is deferred until device time is available; do not treat large offline viewport restitches as canonical scale

## Popup / overlay resolver

Before every map swipe, `resolve_blocking_screens` must clear blocking UI:

1. Prefer close controls (invite X, geometric panel X, pale-panel top-right).
2. Mail / march specific closes.
3. Grass taps outside the card.

Never Android Back (leaves World). A city profile card over mid-screen absorbs the fixed `swipe_camera` drag and must be dismissed first.

## Why this lock exists

The 17×17 offline repair path used search-bar OCR as placement authority and produced inconsistent px/world (~0.4× the v9 click diamond). The good 5×5 badland-v9 map used ~140 px/world from clicks. Agents must not skip click authority again for convenience.
