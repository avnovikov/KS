# 3×3 Grid Stitch Calibration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Capture and accurately stitch a 3×3 KingShot grid using 120-pixel drags, shared city names, and exact object coordinates.

**Architecture:** Add a focused robust affine-calibration module that combines world-coordinate and shared-name observations. Feed its independent X/Y step estimates into the existing landmark-first grid stitcher, retaining normalized NCC only as fallback.

**Tech Stack:** Python, NumPy, OpenCV, pytest, EasyOCR/Tesseract, BlueStacks ADB.

## Global Constraints

- Capture offsets are exactly `−120, 0, +120` pixels on both axes.
- Saved frames must have no popup, modal, or deployment UI.
- Both axes require accepted calibration evidence.
- Fail explicitly instead of emitting an uncalibrated panorama.
- Do not create a git commit unless the user explicitly requests one.

---

### Task 1: Robust two-axis calibration

**Files:**
- Create: `ks/cartograph/calibration.py`
- Create: `tests/test_cartograph_calibration.py`

**Interfaces:**
- Produces: `CalibrationObservation(frame: str, world_x: float, world_y: float, pixel_x: float, pixel_y: float, weight: float)`
- Produces: `fit_world_to_pixel(observations, residual_limit_px=35.0) -> AffineCalibration`
- Produces: `AffineCalibration.matrix`, `AffineCalibration.accepted`, and `AffineCalibration.rejected`

- [ ] **Step 1: Write failing tests for independent X/Y scale and one rejected OCR outlier**

```python
def test_fit_world_to_pixel_recovers_both_axes_and_rejects_outlier():
    observations = synthetic_observations(scale_x=92.0, scale_y=68.0)
    observations.append(CalibrationObservation("bad", 9, 9, 4000, -3000, 0.2))
    fit = fit_world_to_pixel(observations, residual_limit_px=20.0)
    assert abs(fit.matrix[0, 0] - 92.0) < 1.0
    assert abs(fit.matrix[1, 1] - 68.0) < 1.0
    assert {item.frame for item in fit.rejected} == {"bad"}
```

- [ ] **Step 2: Run `pytest tests/test_cartograph_calibration.py -q`; expect failure because the module is missing**

- [ ] **Step 3: Implement weighted least-squares fitting, residual rejection, input validation, and explicit insufficient-axis errors**

```python
@dataclass(frozen=True)
class AffineCalibration:
    matrix: np.ndarray
    accepted: tuple[CalibrationObservation, ...]
    rejected: tuple[CalibrationObservation, ...]

def fit_world_to_pixel(
    observations: Sequence[CalibrationObservation],
    residual_limit_px: float = 35.0,
) -> AffineCalibration:
    ...
```

- [ ] **Step 4: Run `pytest tests/test_cartograph_calibration.py -q`; expect all tests to pass**

### Task 2: Integrate calibration with landmark placement

**Files:**
- Modify: `ks/cartograph/mosaic.py`
- Modify: `tests/test_cartograph_grid_stitch.py`

**Interfaces:**
- Consumes: `AffineCalibration`
- Produces: `stitch_grid_lattice(..., calibration: AffineCalibration | None = None)`

- [ ] **Step 1: Add a failing test where exact-coordinate scale sets the lattice and a shared city name refines translation**

```python
def test_grid_stitch_combines_coordinate_scale_and_city_translation(tmp_path):
    calibration = known_calibration(scale_x=90.0, scale_y=70.0)
    result = stitch_grid_lattice(
        nine_frames(),
        tmp_path / "panorama.png",
        calibration=calibration,
        landmarks_by_cell=shared_city_landmarks(),
    )
    assert result.image.size > 0
    assert (tmp_path / "panorama.png").is_file()
```

- [ ] **Step 2: Run the focused test; expect a signature failure**

- [ ] **Step 3: Derive `pe` and `ps` from accepted exact-coordinate observations, then apply shared-name offsets in `place_grid_by_landmarks`; reject a missing-axis calibration**

- [ ] **Step 4: Write accepted/rejected anchors and frame bounds into the existing debug directory**

- [ ] **Step 5: Run `pytest tests/test_cartograph_grid_stitch.py tests/test_cartograph_mosaic.py -q`; expect all tests to pass**

### Task 3: Capture, calibrate, stitch, and verify

**Files:**
- Create: `artifacts/cartograph-grid120-3x3/`
- Modify: `artifacts/cartograph-grid120-3x3/observations.yaml`

**Interfaces:**
- Consumes: clean `g_{x}_{y}.png` frames and exact clicked object coordinates
- Produces: `panorama.png`, `frames-wireframe.png`, and `observations.yaml`

- [ ] **Step 1: Clear the forced tutorial and verify the persistent coordinate bar is visible**
- [ ] **Step 2: Capture the filled 3×3 grid with `--around 1 --swipe-px 120`, stopping if any overlay remains**
- [ ] **Step 3: Record shared city-name landmarks and click enough static objects to constrain both axes**
- [ ] **Step 4: Fit calibration, stitch the nine frames, and render wireframe diagnostics**
- [ ] **Step 5: Run `pytest tests/test_cartograph_calibration.py tests/test_cartograph_grid_stitch.py tests/test_cartograph_mosaic.py tests/test_live_capture_safe_actions.py -q`; expect all tests to pass**
- [ ] **Step 6: Inspect `panorama.png`; repeated city names and exact-coordinate objects must align once without duplicated cities**
