"""Capture multi-screen rays and stitch a viewport-aligned mosaic."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from ks.cartograph.calibration import AffineCalibration
from ks.cartograph.landmarks import (
    extract_name_landmarks,
    landmark_pair_offsets,
)
from ks.cartograph.lighting import (
    band_match_gray,
    normalize_background_lighting,
)
from ks.cartograph.live_capture import (
    CapturedFrame,
    GRASS_DISMISS_TAP,
    capture_clean_frame_with_popup_coords,
    dismiss_map_blockers,
    ensure_world_map,
    screencap_bgr,
    swipe_camera,
)
from ks.cartograph.mask import MaskConfig, bluestacks_mask_config, mask_and_crop
from ks.cartograph.project import AffineProjection, Matrix2x2
from ks.device.adb import AdbDevice

OPPOSITE = {"E": "W", "W": "E", "N": "S", "S": "N"}
DIRECTIONS = ("E", "N", "W", "S")


def _ocr_tile_delta_ok(
    before: tuple[int, int],
    after: tuple[int, int],
    min_tile_delta: int,
) -> bool:
    """True when manhattan or hypot tile distance meets ``min_tile_delta``."""
    if min_tile_delta < 1:
        raise ValueError(f"min_tile_delta must be >= 1; got {min_tile_delta}")
    dx = abs(before[0] - after[0])
    dy = abs(before[1] - after[1])
    return (dx + dy) >= min_tile_delta or math.hypot(dx, dy) >= min_tile_delta


def swipe_camera_verified(
    device: AdbDevice,
    direction: str,
    *,
    distance_px: int,
    settle_s: float,
    attempts: int = 3,
    min_tile_delta: int = 2,
) -> tuple[int, int]:
    """ADB-swipe until search-bar world coords change; pixel-only motion is not enough.

    Returns the post-swipe viewport ``(x, y)``. Fails closed if OCR cannot confirm
    a real coordinate change after retries.
    """
    from ks.cartograph.viewport import ocr_viewport_from_image

    distances = [
        max(80, int(distance_px)),
        max(80, int(distance_px * 1.25)),
        max(80, int(distance_px * 1.6)),
    ]
    before = screencap_bgr(device)
    vp_before, raw_before = ocr_viewport_from_image(before)
    if vp_before is None:
        raise RuntimeError(
            f"cannot verify {direction} swipe: pre-swipe viewport OCR failed "
            f"({raw_before!r})"
        )

    last_raw = raw_before
    retry_count = max(attempts, len(distances))
    for attempt in range(retry_count):
        if attempt > 0:
            dismiss_map_blockers(device)
            time.sleep(0.35)
            before = screencap_bgr(device)
            vp_before, raw_before = ocr_viewport_from_image(before)
            if vp_before is None:
                raise RuntimeError(
                    f"cannot verify {direction} swipe: viewport OCR failed on retry "
                    f"({raw_before!r})"
                )
            last_raw = raw_before
        dist = distances[min(attempt, len(distances) - 1)]
        swipe_camera(device, direction, distance_px=dist)
        time.sleep(settle_s)
        after = screencap_bgr(device)
        vp_after, raw_after = ocr_viewport_from_image(after)
        last_raw = raw_after
        if vp_after is None:
            continue
        if _ocr_tile_delta_ok(vp_before, vp_after, min_tile_delta):
            return vp_after
        # Pixel flicker without coord change is a stuck camera — keep retrying.
        before = after
        vp_before = vp_after

    raise RuntimeError(
        f"camera coords did not change after {retry_count} ADB "
        f"{direction} swipes (base {distance_px}px); last OCR={last_raw!r}"
    )


def grid_cell_order(depth: int) -> list[tuple[int, int]]:
    """Screen offsets ``(ex, ey)`` for a filled ``(2*depth+1)²`` grid.

    ``ex`` = screens east of center, ``ey`` = screens south of center.
    Order is serpentine by row (north→south), alternating E/W each row.
    """
    if depth < 1 or depth > 8:
        raise ValueError(f"depth must be 1..8; got {depth}")
    cells: list[tuple[int, int]] = []
    for row_i, ey in enumerate(range(-depth, depth + 1)):
        xs = list(range(-depth, depth + 1))
        if row_i % 2 == 1:
            xs.reverse()
        for ex in xs:
            cells.append((ex, ey))
    return cells


def grid_swipe_path(
    from_cell: tuple[int, int], to_cell: tuple[int, int]
) -> list[str]:
    """Cardinal swipes to move camera from one grid cell to another."""
    fx, fy = from_cell
    tx, ty = to_cell
    path: list[str] = []
    dx, dy = tx - fx, ty - fy
    path.extend(["E"] * dx if dx > 0 else ["W"] * (-dx))
    path.extend(["S"] * dy if dy > 0 else ["N"] * (-dy))
    return path


@dataclass(frozen=True)
class MosaicResult:
    image: np.ndarray
    path: Path
    center: tuple[int, int]
    # world tile → panorama pixel: pan = origin + (w - center) * scale
    scale_x: float
    scale_y: float
    origin_x: float
    origin_y: float
    band_w: int
    band_h: int
    world_to_pixel_matrix: Matrix2x2 | None = None

    def __post_init__(self) -> None:
        if self.world_to_pixel_matrix is None:
            return
        validated = AffineProjection(
            center=(0.0, 0.0),
            pixel_origin=(0.0, 0.0),
            matrix=self.world_to_pixel_matrix,
        )
        object.__setattr__(self, "world_to_pixel_matrix", validated.matrix)


def capture_rays(
    device: AdbDevice,
    out_dir: Path,
    *,
    depth: int = 4,
    settle_s: float = 1.0,
    open_world: bool = True,
    swipe_px: int = 520,
) -> list[CapturedFrame]:
    """Capture center, then ``depth`` screens along each of E/N/W/S (return after each ray).

    Each saved frame is a *clean* full map: tap tile → read X/Y from the info
    banner → tap grass to dismiss → save. Never persist the banner screenshot.
    """
    if depth < 1 or depth > 8:
        raise ValueError(f"depth must be 1..8; got {depth}")
    out_dir.mkdir(parents=True, exist_ok=True)

    if open_world:
        ensure_world_map(device, settle_s=settle_s + 0.5)
    else:
        dismiss_map_blockers(device)

    frames: list[CapturedFrame] = []

    def _save(name: str) -> CapturedFrame:
        image, vp, raw = capture_clean_frame_with_popup_coords(
            device, settle_s=settle_s * 0.85
        )
        if vp is None:
            raise RuntimeError(
                f"{name}: World-map coordinate bar is unreadable; "
                "aborting capture before saving a non-map frame"
            )
        path = out_dir / f"{name}.png"
        cv2.imwrite(str(path), image)
        return CapturedFrame(
            name=name, path=path, viewport=vp, viewport_raw=raw, image=image
        )

    # Ensure no leftover banner before the first probe.
    device.tap(*GRASS_DISMISS_TAP)
    time.sleep(settle_s * 0.5)
    frames.append(_save("c0_center"))

    for direction in DIRECTIONS:
        for step in range(1, depth + 1):
            swipe_camera(device, direction, distance_px=swipe_px)
            time.sleep(settle_s)
            frames.append(_save(f"{direction}{step}"))
        for _ in range(depth):
            swipe_camera(device, OPPOSITE[direction], distance_px=swipe_px)
            time.sleep(settle_s * 0.55)

    return frames


def capture_grid(
    device: AdbDevice,
    out_dir: Path,
    *,
    depth: int = 3,
    settle_s: float = 1.0,
    open_world: bool = True,
    swipe_px: int = 520,
) -> list[CapturedFrame]:
    """Capture a filled ``(2*depth+1)²`` screen grid (serpentine walk).

    Saves clean full-map frames only; coordinates come from the tile info banner.
    Existing ``g_*.png`` / ``c0_center.png`` frames are reused (resume-safe).
    """
    cells = grid_cell_order(depth)
    out_dir.mkdir(parents=True, exist_ok=True)

    if open_world:
        ensure_world_map(device, settle_s=settle_s + 0.5)
    else:
        dismiss_map_blockers(device)

    frames: list[CapturedFrame] = []

    def _frame_path(name: str) -> Path:
        return out_dir / f"{name}.png"

    def _load_existing(name: str) -> CapturedFrame | None:
        path = _frame_path(name)
        if not path.is_file():
            return None
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None:
            return None
        from ks.cartograph.viewport import ocr_viewport_from_image

        vp, raw = ocr_viewport_from_image(image)
        if vp is None:
            return None
        return CapturedFrame(
            name=name, path=path, viewport=vp, viewport_raw=raw, image=image
        )

    def _save(name: str, *, prev_vp: tuple[int, int] | None) -> CapturedFrame:
        existing = _load_existing(name)
        if existing is not None:
            return existing
        image, vp, raw = capture_clean_frame_with_popup_coords(
            device, settle_s=settle_s * 0.85
        )
        if vp is None:
            raise RuntimeError(
                f"{name}: World-map coordinate bar is unreadable; "
                "aborting capture before saving a non-map frame"
            )
        if prev_vp is not None and vp == prev_vp:
            raise RuntimeError(
                f"{name}: viewport stuck at {vp} (same as previous frame); "
                "refusing to save duplicate coordinates"
            )
        path = _frame_path(name)
        cv2.imwrite(str(path), image)
        return CapturedFrame(
            name=name, path=path, viewport=vp, viewport_raw=raw, image=image
        )

    # Prefer starting from the last saved cell so resume does not re-walk completed cells.
    cur = (0, 0)
    last_done: int | None = None
    for i, cell in enumerate(cells):
        name = "c0_center" if cell == (0, 0) else f"g_{cell[0]}_{cell[1]}"
        if _frame_path(name).is_file():
            last_done = i
            cur = cell

    if last_done is not None:
        for cell in cells[: last_done + 1]:
            name = "c0_center" if cell == (0, 0) else f"g_{cell[0]}_{cell[1]}"
            frame = _load_existing(name)
            if frame is None:
                raise RuntimeError(f"resume expected existing frame {name}")
            frames.append(frame)
            if cell == (0, 0):
                center_copy = out_dir / "g_0_0.png"
                if not center_copy.is_file():
                    cv2.imwrite(str(center_copy), frame.image)
        cells = cells[last_done + 1 :]

    prev_vp = frames[-1].viewport if frames else None
    for cell in cells:
        swipes = grid_swipe_path(cur, cell)
        for direction in swipes:
            swipe_camera_verified(
                device,
                direction,
                distance_px=swipe_px,
                settle_s=settle_s,
            )
        name = "c0_center" if cell == (0, 0) else f"g_{cell[0]}_{cell[1]}"
        frame = _save(name, prev_vp=prev_vp)
        frames.append(frame)
        prev_vp = frame.viewport
        if cell == (0, 0):
            cv2.imwrite(str(out_dir / "g_0_0.png"), frame.image)
        cur = cell

    return frames


def _estimate_scale(
    frames: list[CapturedFrame],
    band_w: int,
    band_h: int,
) -> tuple[float, float]:
    """px per world-tile from consecutive viewports (fallback ~55)."""
    xs: list[float] = []
    ys: list[float] = []
    by_name = {f.name: f for f in frames if f.viewport}
    center_f = by_name.get("c0_center") or by_name.get("g_0_0")
    if center_f and center_f.viewport:
        for direction in DIRECTIONS:
            prev = center_f.viewport
            for step in range(1, 9):
                fr = by_name.get(f"{direction}{step}")
                if not fr or not fr.viewport:
                    break
                dx = fr.viewport[0] - prev[0]
                dy = fr.viewport[1] - prev[1]
                if direction in ("E", "W") and abs(dx) >= 2:
                    xs.append(band_w * 0.72 / abs(dx))
                if direction in ("N", "S") and abs(dy) >= 2:
                    ys.append(band_h * 0.55 / abs(dy))
                prev = fr.viewport

    # Grid / near-neighbour pairs — swipes are usually diagonal in world X/Y.
    usable = [f for f in frames if f.viewport is not None]
    for i, a in enumerate(usable):
        assert a.viewport is not None
        for b in usable[i + 1 :]:
            assert b.viewport is not None
            dx = b.viewport[0] - a.viewport[0]
            dy = b.viewport[1] - a.viewport[1]
            adx, ady = abs(dx), abs(dy)
            dist = float(np.hypot(adx, ady))
            # One screen step is typically ~8–18 tiles (often diagonal).
            if 6 <= adx <= 20 and ady <= max(3, adx * 1.15):
                xs.append(band_w * 0.70 / adx)
            if 6 <= ady <= 20 and adx <= max(3, ady * 1.15):
                ys.append(band_h * 0.55 / ady)
            if 8 <= dist <= 22 and adx >= 4 and ady >= 4:
                xs.append(band_w * 0.55 / adx)
                ys.append(band_h * 0.45 / ady)

    sx = float(np.median(xs)) if xs else 55.0
    sy = float(np.median(ys)) if ys else 55.0
    assert sx > 5 and sy > 5, (sx, sy)
    return sx, sy


def parse_grid_cell(name: str) -> tuple[int, int] | None:
    """Parse screen-grid cell from frame name.

    Supports ``c0_center`` / ``g_{ex}_{ey}`` and ray names ``E1``…``S3``
    (and legacy ``c1_E``).
    """
    if name in ("c0_center", "g_0_0", "c0"):
        return (0, 0)
    import re

    m = re.fullmatch(r"g_(-?\d+)_(-?\d+)", name)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.fullmatch(r"([ENWS])(\d+)", name)
    if m:
        step = int(m.group(2))
        if step < 1:
            return None
        return {
            "E": (step, 0),
            "W": (-step, 0),
            "N": (0, -step),
            "S": (0, step),
        }[m.group(1)]
    m = re.fullmatch(r"c\d+_([ENWS])", name)
    if m:
        return {"E": (1, 0), "W": (-1, 0), "N": (0, -1), "S": (0, 1)}[m.group(1)]
    return None


def calibrate_grid_pixel_steps(
    frames: list[CapturedFrame],
    band_w: int,
    band_h: int,
    *,
    overlap: float = 0.55,
    refine: bool = True,
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Pixel step for +1 screen East and +1 screen South from controlled neighbors.

    Seed from OCR tile deltas (overlap-scaled), then optionally refine with
    local NCC around that seed so terrain lines up for nearby merges.

    Small swipes (tile Δ ≈ 1) make OCR scale unstable — fall back to a pure
    overlap fraction of the band size on that axis.
    """
    if not (0.3 <= overlap <= 0.8):
        raise ValueError(f"overlap must be 0.3..0.8; got {overlap}")
    by_cell: dict[tuple[int, int], CapturedFrame] = {}
    for f in frames:
        cell = parse_grid_cell(f.name)
        if cell is None or f.viewport is None:
            continue
        by_cell[cell] = f
    if len(by_cell) < 2:
        raise ValueError("need ≥2 grid frames with viewport OCR to calibrate steps")

    e_wx: list[float] = []
    e_wy: list[float] = []
    s_wx: list[float] = []
    s_wy: list[float] = []
    for (ex, ey), fr in by_cell.items():
        assert fr.viewport is not None
        east = by_cell.get((ex + 1, ey))
        if east and east.viewport:
            e_wx.append(float(east.viewport[0] - fr.viewport[0]))
            e_wy.append(float(east.viewport[1] - fr.viewport[1]))
        south = by_cell.get((ex, ey + 1))
        if south and south.viewport:
            s_wx.append(float(south.viewport[0] - fr.viewport[0]))
            s_wy.append(float(south.viewport[1] - fr.viewport[1]))

    pe = (overlap * band_w, 0.0)
    ps = (0.0, overlap * band_h)
    if not e_wx and not s_wx:
        raise ValueError("need at least one E or S neighbor edge to calibrate")

    if e_wx:
        ew, eh = float(np.median(e_wx)), float(np.median(e_wy))
        e_len = float(np.hypot(ew, eh))
        # Tiny tile steps (small swipe) → keep overlap default; only use OCR
        # scale when the camera clearly moved several tiles.
        if e_len >= 6.0:
            scale = (overlap * band_w) / e_len
            pe = (ew * scale, eh * scale)
    if s_wx:
        sw, sh = float(np.median(s_wx)), float(np.median(s_wy))
        s_len = float(np.hypot(sw, sh))
        if s_len >= 6.0:
            scale = (overlap * band_h) / s_len
            # Image +Y is down; south screen content is below center.
            step = (sw * scale, sh * scale)
            if step[1] < 0:
                step = (step[0], -step[1])
            ps = step

    if refine:
        pe_r, ps_r = _refine_steps_ncc(by_cell, pe, ps, band_w, band_h)
        if pe_r is not None:
            pe = pe_r
        if ps_r is not None:
            ps = ps_r
    return pe, ps


def calibrated_grid_steps(
    by_cell: dict[tuple[int, int], CapturedFrame],
    calibration: AffineCalibration,
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Derive one-screen X/Y pixel steps from an exact world-to-pixel fit."""
    center = by_cell.get((0, 0))
    if center is None or center.viewport is None:
        raise ValueError("calibrated grid steps require a center viewport")
    linear = np.asarray(calibration.matrix, dtype=float)[:, :2]
    if linear.shape != (2, 2):
        raise ValueError(
            f"calibration matrix must be 2x3; got {calibration.matrix.shape}"
        )

    grid_deltas: list[tuple[float, float]] = []
    pixel_deltas: list[np.ndarray] = []
    center_world = np.asarray(center.viewport, dtype=float)
    for cell, frame in by_cell.items():
        if cell == (0, 0) or frame.viewport is None:
            continue
        grid_deltas.append((float(cell[0]), float(cell[1])))
        world_delta = np.asarray(frame.viewport, dtype=float) - center_world
        pixel_deltas.append(linear @ world_delta)
    if len(grid_deltas) < 2:
        raise ValueError("calibrated grid steps require both grid axes")

    coefficients, _, rank, _ = np.linalg.lstsq(
        np.asarray(grid_deltas, dtype=float),
        np.asarray(pixel_deltas, dtype=float),
        rcond=None,
    )
    if rank < 2:
        raise ValueError("calibrated grid steps require both grid axes")
    pe = (float(coefficients[0, 0]), float(coefficients[0, 1]))
    ps = (float(coefficients[1, 0]), float(coefficients[1, 1]))
    return pe, ps


def _refine_steps_ncc(
    by_cell: dict[tuple[int, int], CapturedFrame],
    pe: tuple[float, float],
    ps: tuple[float, float],
    band_w: int,
    band_h: int,
    *,
    radius: int = 220,
    step: int = 15,
    min_score: float = 0.18,
) -> tuple[tuple[float, float] | None, tuple[float, float] | None]:
    """Refine lattice steps by NCC on masked bands around the OCR seed."""
    mask_cfg = bluestacks_mask_config()
    fill = np.array(mask_cfg.fill, dtype=np.uint8)

    def _band(fr: CapturedFrame) -> np.ndarray:
        b = mask_and_crop(fr.image, mask_cfg)
        if b.shape[0] != band_h or b.shape[1] != band_w:
            b = cv2.resize(b, (band_w, band_h))
        return b

    def _ncc(a: np.ndarray, b: np.ndarray, seed: tuple[float, float]) -> tuple[float, float] | None:
        # Match on lighting-normalized structure edges (day/night grass differs).
        ga = band_match_gray(a)
        gb = band_match_gray(b)
        ma = ~np.all(a == fill, axis=2)
        mb = ~np.all(b == fill, axis=2)
        ph, pw = max(48, band_h // 5), max(48, band_w // 5)
        y0, x0 = (band_h - ph) // 2, (band_w - pw) // 2
        if float(ma[y0 : y0 + ph, x0 : x0 + pw].mean()) < 0.8:
            return None
        patch = ga[y0 : y0 + ph, x0 : x0 + pw]
        patch = patch - patch.mean()
        best = (-1.0, seed[0], seed[1])
        sx0, sy0 = int(seed[0]), int(seed[1])
        for dx in range(sx0 - radius, sx0 + radius + 1, step):
            for dy in range(sy0 - radius, sy0 + radius + 1, step):
                xb, yb = x0 - dx, y0 - dy
                if xb < 0 or yb < 0 or xb + pw > band_w or yb + ph > band_h:
                    continue
                if float(mb[yb : yb + ph, xb : xb + pw].mean()) < 0.8:
                    continue
                roi = gb[yb : yb + ph, xb : xb + pw]
                roi = roi - roi.mean()
                den = float(np.sqrt((patch * patch).sum() * (roi * roi).sum())) + 1e-6
                score = float((patch * roi).sum() / den)
                if score > best[0]:
                    best = (score, float(dx), float(dy))
        if best[0] < min_score:
            return None
        return (best[1], best[2])

    e_meas: list[tuple[float, float]] = []
    s_meas: list[tuple[float, float]] = []
    for (ex, ey), fr in by_cell.items():
        a = _band(fr)
        east = by_cell.get((ex + 1, ey))
        if east is not None:
            off = _ncc(a, _band(east), pe)
            if off is not None:
                e_meas.append(off)
        south = by_cell.get((ex, ey + 1))
        if south is not None:
            off = _ncc(a, _band(south), ps)
            if off is not None:
                s_meas.append(off)

    pe_out = (
        (float(np.median([p[0] for p in e_meas])), float(np.median([p[1] for p in e_meas])))
        if len(e_meas) >= 3
        else None
    )
    ps_out = (
        (float(np.median([p[0] for p in s_meas])), float(np.median([p[1] for p in s_meas])))
        if len(s_meas) >= 3
        else None
    )
    return pe_out, ps_out


def _ncc_band_offset(
    band_a: np.ndarray,
    band_b: np.ndarray,
    seed: tuple[float, float],
    fill: np.ndarray,
    *,
    radius: int = 160,
    step: int = 10,
    min_score: float = 0.22,
) -> tuple[float, float] | None:
    """Pixel offset of band_b origin relative to band_a via local NCC.

    Uses lighting-normalized structure edges so day/night grass does not
    dominate the match.
    """
    if band_a.shape != band_b.shape:
        raise ValueError(f"band shapes must match; got {band_a.shape} vs {band_b.shape}")
    bh, bw = band_a.shape[:2]
    ga = band_match_gray(band_a)
    gb = band_match_gray(band_b)
    mb = ~np.all(band_b == fill, axis=2)
    ph, pw = max(48, bh // 5), max(48, bw // 5)
    y0, x0 = (bh - ph) // 2, (bw - pw) // 2
    patch = ga[y0 : y0 + ph, x0 : x0 + pw]
    patch = patch - patch.mean()
    best = (-1.0, seed[0], seed[1])
    sx0, sy0 = int(round(seed[0])), int(round(seed[1]))
    for dx in range(sx0 - radius, sx0 + radius + 1, step):
        for dy in range(sy0 - radius, sy0 + radius + 1, step):
            xb, yb = x0 - dx, y0 - dy
            if xb < 0 or yb < 0 or xb + pw > bw or yb + ph > bh:
                continue
            if float(mb[yb : yb + ph, xb : xb + pw].mean()) < 0.75:
                continue
            roi = gb[yb : yb + ph, xb : xb + pw]
            roi = roi - roi.mean()
            den = float(np.sqrt((patch * patch).sum() * (roi * roi).sum())) + 1e-6
            score = float((patch * roi).sum() / den)
            if score > best[0]:
                best = (score, float(dx), float(dy))
    if best[0] < min_score:
        return None
    return (best[1], best[2])


def place_grid_by_landmarks(
    by_cell: dict[tuple[int, int], CapturedFrame],
    pe: tuple[float, float],
    ps: tuple[float, float],
    band_w: int,
    band_h: int,
    *,
    mask_cfg: MaskConfig | None = None,
    landmarks_by_cell: dict[tuple[int, int], list] | None = None,
    use_ncc: bool = True,
) -> dict[tuple[int, int], tuple[float, float]]:
    """Place cells from shared ``lord…`` names first; NCC only fills gaps.

    Day/night lighting makes grass NCC unreliable, so name offsets win when
    present. Remaining cells use edge-anchored lattice + lighting-robust NCC.
    """
    if not by_cell:
        raise ValueError("by_cell must not be empty")
    if (0, 0) not in by_cell:
        raise ValueError("place_grid_by_landmarks needs center cell (0,0)")

    mask_cfg = mask_cfg or bluestacks_mask_config()
    fill = np.array(mask_cfg.fill, dtype=np.uint8)

    bands: dict[tuple[int, int], np.ndarray] = {}
    for cell, fr in by_cell.items():
        band = mask_and_crop(fr.image, mask_cfg)
        if band.shape[0] != band_h or band.shape[1] != band_w:
            band = cv2.resize(band, (band_w, band_h))
        bands[cell] = band

    if landmarks_by_cell is None:
        landmarks_by_cell = {
            cell: extract_name_landmarks(band) for cell, band in bands.items()
        }

    name_cons_all = landmark_pair_offsets(landmarks_by_cell)
    # Prefer pe/ps measured from shared names when the swipe is small
    # (viewport tile Δ is tiny and overlap*band overestimates the step).
    pe_lm, ps_lm = _steps_from_landmarks(name_cons_all)
    if pe_lm is not None:
        pe = pe_lm
    if ps_lm is not None:
        ps = ps_lm

    name_cons = [
        cons
        for cons in name_cons_all
        if _landmark_offset_plausible(cons, pe, ps, band_w, band_h)
    ]
    pos = _place_from_landmark_bfs(name_cons, seed=(0, 0))
    missing = [c for c in by_cell if c not in pos]
    if missing:
        # Cross / star (few cells): lattice from center — do not pin the
        # leftmost column at origin (that collides with center-at-origin).
        if len(by_cell) <= 5:
            for cell in missing:
                seed = (
                    cell[0] * pe[0] + cell[1] * ps[0],
                    cell[0] * pe[1] + cell[1] * ps[1],
                )
                if use_ncc and (0, 0) in bands and cell in bands:
                    ncc = _ncc_band_offset(
                        bands[(0, 0)], bands[cell], seed, fill,
                        radius=100, step=8, min_score=0.25,
                    )
                    if ncc is not None:
                        seed = ncc
                pos[cell] = seed
        else:
            edge = _place_edge_anchored_grid(
                sorted(by_cell.keys()),
                bands,
                pe,
                ps,
                fill,
                use_ncc=use_ncc,
            )
            shared = [c for c in pos if c in edge]
            if shared:
                sx = float(np.median([pos[c][0] - edge[c][0] for c in shared]))
                sy = float(np.median([pos[c][1] - edge[c][1] for c in shared]))
            else:
                sx = sy = 0.0
            for cell in missing:
                pos[cell] = (edge[cell][0] + sx, edge[cell][1] + sy)
        if name_cons:
            pos = _refine_positions_landmarks(pos, name_cons)
    elif name_cons:
        pos = _refine_positions_landmarks(pos, name_cons)
    for cell in by_cell:
        if cell not in pos:
            pos[cell] = (
                cell[0] * pe[0] + cell[1] * ps[0],
                cell[0] * pe[1] + cell[1] * ps[1],
            )
    return pos


def _steps_from_landmarks(
    constraints: list[
        tuple[tuple[int, int], tuple[int, int], float, float, float]
    ],
) -> tuple[tuple[float, float] | None, tuple[float, float] | None]:
    """Estimate (+1E, +1S) pixel steps from adjacent shared-name offsets."""
    e_offs: list[tuple[float, float]] = []
    s_offs: list[tuple[float, float]] = []
    for ca, cb, dx, dy, _w in constraints:
        dex, dey = cb[0] - ca[0], cb[1] - ca[1]
        if dex == 1 and dey == 0 and dx > 40 and abs(dy) < 0.35 * abs(dx):
            e_offs.append((dx, dy))
        elif dex == -1 and dey == 0 and dx < -40 and abs(dy) < 0.35 * abs(dx):
            e_offs.append((-dx, -dy))
        elif dey == 1 and dex == 0 and abs(dy) > 40 and abs(dx) < 0.35 * abs(dy):
            s_offs.append((dx, abs(dy)))
        elif dey == -1 and dex == 0 and abs(dy) > 40 and abs(dx) < 0.35 * abs(dy):
            s_offs.append((-dx, abs(dy)))
    pe = (
        (float(np.median([o[0] for o in e_offs])), float(np.median([o[1] for o in e_offs])))
        if e_offs
        else None
    )
    ps = (
        (float(np.median([o[0] for o in s_offs])), float(np.median([o[1] for o in s_offs])))
        if s_offs
        else None
    )
    return pe, ps


def _adjacent_cells(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return abs(a[0] - b[0]) + abs(a[1] - b[1]) == 1


def _landmark_offset_plausible(
    cons: tuple[tuple[int, int], tuple[int, int], float, float, float],
    pe: tuple[float, float],
    ps: tuple[float, float],
    band_w: int,
    band_h: int,
) -> bool:
    ca, cb, dx, dy, _w = cons
    dex, dey = cb[0] - ca[0], cb[1] - ca[1]
    exp_dx = dex * pe[0] + dey * ps[0]
    exp_dy = dex * pe[1] + dey * ps[1]
    if abs(dx - exp_dx) > 0.35 * band_w or abs(dy - exp_dy) > 0.35 * band_h:
        return False
    # Primary axis must move the right way (reject OCR that flips W↔E etc.).
    if dex != 0 and dx * exp_dx < 0:
        return False
    if dey != 0 and dy * exp_dy < 0:
        return False
    # Orthogonal drift must stay small (rejects misread labels on W/E).
    if dex != 0 and abs(dy) > 0.12 * band_h:
        return False
    if dey != 0 and abs(dx) > 0.12 * band_w:
        return False
    return True


def _place_from_landmark_bfs(
    constraints: list[
        tuple[tuple[int, int], tuple[int, int], float, float, float]
    ],
    *,
    seed: tuple[int, int] = (0, 0),
) -> dict[tuple[int, int], tuple[float, float]]:
    """BFS place cells from ``seed`` using name-offset constraints only."""
    pos: dict[tuple[int, int], tuple[float, float]] = {seed: (0.0, 0.0)}
    if not constraints:
        return pos
    graph: dict[
        tuple[int, int],
        list[tuple[tuple[int, int], float, float, float]],
    ] = {}
    for ca, cb, dx, dy, w in constraints:
        graph.setdefault(ca, []).append((cb, dx, dy, w))
        graph.setdefault(cb, []).append((ca, -dx, -dy, w))
    queue = [seed]
    while queue:
        cur = queue.pop(0)
        for nb, dx, dy, _w in graph.get(cur, []):
            if nb in pos:
                continue
            cx, cy = pos[cur]
            pos[nb] = (cx + dx, cy + dy)
            queue.append(nb)
    return pos


def _neighbor_offset(
    bands: dict[tuple[int, int], np.ndarray],
    frm: tuple[int, int],
    to: tuple[int, int],
    seed: tuple[float, float],
    fill: np.ndarray,
    *,
    use_ncc: bool,
) -> tuple[float, float]:
    if use_ncc and frm in bands and to in bands:
        off = _ncc_band_offset(bands[frm], bands[to], seed, fill)
        if off is not None:
            return off
    return seed


def _place_edge_anchored_grid(
    cells: list[tuple[int, int]],
    bands: dict[tuple[int, int], np.ndarray],
    pe: tuple[float, float],
    ps: tuple[float, float],
    fill: np.ndarray,
    *,
    use_ncc: bool,
) -> dict[tuple[int, int], tuple[float, float]]:
    """Pin left column, chain right column, fill middle from both edges."""
    cell_set = set(cells)
    ex_min = min(c[0] for c in cells)
    ex_max = max(c[0] for c in cells)
    ey_vals = sorted({c[1] for c in cells})

    pos: dict[tuple[int, int], tuple[float, float]] = {}

    def _chain_column(ex: int, origin: tuple[float, float]) -> None:
        col = sorted([c for c in cells if c[0] == ex], key=lambda c: c[1])
        if not col:
            return
        pos[col[0]] = origin
        for prev, cur in zip(col, col[1:]):
            dey = cur[1] - prev[1]
            seed = (ps[0] * dey, ps[1] * dey)
            off = _neighbor_offset(bands, prev, cur, seed, fill, use_ncc=use_ncc)
            pos[cur] = (pos[prev][0] + off[0], pos[prev][1] + off[1])

    _chain_column(ex_min, (0.0, 0.0))

    # Provisional right column from lattice span, then re-chain vertically.
    span = ex_max - ex_min
    assert span >= 1, span
    right_origin = (span * pe[0], span * pe[1])
    # Align right origin to left's ey_min row via pe*span.
    ey0 = min(ey_vals)
    if (ex_min, ey0) in pos:
        right_origin = (
            pos[(ex_min, ey0)][0] + span * pe[0],
            pos[(ex_min, ey0)][1] + span * pe[1],
        )
    if (ex_max, ey0) in cell_set:
        _chain_column(ex_max, right_origin)
    elif any(c[0] == ex_max for c in cells):
        # Start chain at whatever topmost right cell exists.
        top = min([c for c in cells if c[0] == ex_max], key=lambda c: c[1])
        _chain_column(
            ex_max,
            (
                pos.get((ex_min, top[1]), (0.0, 0.0))[0] + span * pe[0],
                pos.get((ex_min, top[1]), (0.0, 0.0))[1] + span * pe[1],
            ),
        )

    # Per-row fill: interpolate between fixed L/R edges (covers the gap).
    # Optional NCC is only a small refine around that seed — middle NCC alone
    # tends to shrink steps and leave holes next to the edges.
    for ey in ey_vals:
        row = sorted([c for c in cells if c[1] == ey], key=lambda c: c[0])
        left_cell = (ex_min, ey)
        right_cell = (ex_max, ey)
        if left_cell not in pos or right_cell not in pos:
            for cell in row:
                if cell not in pos:
                    pos[cell] = _lattice_fallback(cell, pos, cells)
            continue
        lx, ly = pos[left_cell]
        rx, ry = pos[right_cell]
        for cell in row:
            if cell[0] in (ex_min, ex_max):
                continue
            t = (cell[0] - ex_min) / span
            seed = ((1.0 - t) * lx + t * rx, (1.0 - t) * ly + t * ry)
            if use_ncc and (cell[0] - 1, ey) in pos and cell in bands:
                west = (cell[0] - 1, ey)
                ncc = _ncc_band_offset(
                    bands[west],
                    bands[cell],
                    (seed[0] - pos[west][0], seed[1] - pos[west][1]),
                    fill,
                    radius=80,
                    step=8,
                    min_score=0.28,
                )
                if ncc is not None:
                    cand = (pos[west][0] + ncc[0], pos[west][1] + ncc[1])
                    # Keep mostly edge-lerp; allow mild NCC nudge.
                    seed = (0.75 * seed[0] + 0.25 * cand[0], 0.75 * seed[1] + 0.25 * cand[1])
            pos[cell] = seed

    for cell in cells:
        if cell not in pos:
            pos[cell] = _lattice_fallback(cell, pos, cells)
    assert set(pos) == cell_set
    return pos


def _refine_positions_landmarks(
    pos: dict[tuple[int, int], tuple[float, float]],
    constraints: list[
        tuple[tuple[int, int], tuple[int, int], float, float, float]
    ],
    *,
    min_weight: float = 10.0,
    iters: int = 8,
) -> dict[tuple[int, int], tuple[float, float]]:
    """Pull placements toward high-weight (name) constraints after BFS seed."""
    strong = [c for c in constraints if c[4] >= min_weight]
    if not strong:
        return pos
    out = dict(pos)
    pin = min(out.keys(), key=lambda c: (c[0], c[1]))
    pin_xy = out[pin]
    for _ in range(iters):
        acc: dict[tuple[int, int], list[tuple[float, float, float]]] = {
            c: [] for c in out
        }
        for ca, cb, dx, dy, w in strong:
            if ca not in out or cb not in out:
                continue
            # Target: O_b = O_a + (dx,dy). Split correction across both ends.
            ax, ay = out[ca]
            bx, by = out[cb]
            err_x = (ax + dx) - bx
            err_y = (ay + dy) - by
            # Reduce residual: move A down the error, B up the error.
            acc[ca].append((ax - 0.5 * err_x, ay - 0.5 * err_y, w))
            acc[cb].append((bx + 0.5 * err_x, by + 0.5 * err_y, w))
        for cell, votes in acc.items():
            if cell == pin or not votes:
                continue
            # Blend toward landmark targets but keep some of current pose.
            wsum = sum(v[2] for v in votes)
            tx = sum(v[0] * v[2] for v in votes) / wsum
            ty = sum(v[1] * v[2] for v in votes) / wsum
            cx, cy = out[cell]
            out[cell] = (0.35 * cx + 0.65 * tx, 0.35 * cy + 0.65 * ty)
        # Keep pin fixed; translate all so pin stays put.
        shift = (pin_xy[0] - out[pin][0], pin_xy[1] - out[pin][1])
        if abs(shift[0]) + abs(shift[1]) > 1e-6:
            out = {c: (xy[0] + shift[0], xy[1] + shift[1]) for c, xy in out.items()}
    return out


def _estimate_from_placed(
    cell: tuple[int, int],
    pos: dict[tuple[int, int], tuple[float, float]],
    cons_list: list[
        tuple[tuple[int, int], tuple[int, int], float, float, float]
    ],
) -> tuple[float, float] | None:
    xs: list[float] = []
    ys: list[float] = []
    ws: list[float] = []
    for ca, cb, dx, dy, w in cons_list:
        if ca in pos and cb == cell:
            xs.append(pos[ca][0] + dx)
            ys.append(pos[ca][1] + dy)
            ws.append(w)
        elif cb in pos and ca == cell:
            xs.append(pos[cb][0] - dx)
            ys.append(pos[cb][1] - dy)
            ws.append(w)
    if not ws:
        return None
    wsum = float(sum(ws))
    assert wsum > 0, wsum
    return (
        float(sum(x * w for x, w in zip(xs, ws)) / wsum),
        float(sum(y * w for y, w in zip(ys, ws)) / wsum),
    )


def _lattice_fallback(
    cell: tuple[int, int],
    pos: dict[tuple[int, int], tuple[float, float]],
    _cells: list[tuple[int, int]],
) -> tuple[float, float]:
    """Place via integer cell delta from nearest already-placed cell."""
    if not pos:
        return (0.0, 0.0)
    # Infer pe/ps from any placed east/south pair if possible; else unit guess.
    pe = (200.0, -200.0)
    ps = (-250.0, -220.0)
    placed = list(pos.keys())
    for (ex, ey) in placed:
        if (ex + 1, ey) in pos:
            pe = (
                pos[(ex + 1, ey)][0] - pos[(ex, ey)][0],
                pos[(ex + 1, ey)][1] - pos[(ex, ey)][1],
            )
            break
    for (ex, ey) in placed:
        if (ex, ey + 1) in pos:
            ps = (
                pos[(ex, ey + 1)][0] - pos[(ex, ey)][0],
                pos[(ex, ey + 1)][1] - pos[(ex, ey)][1],
            )
            break
    anchor = min(
        placed,
        key=lambda c: abs(c[0] - cell[0]) + abs(c[1] - cell[1]),
    )
    dex, dey = cell[0] - anchor[0], cell[1] - anchor[1]
    return (
        pos[anchor][0] + dex * pe[0] + dey * ps[0],
        pos[anchor][1] + dex * pe[1] + dey * ps[1],
    )


def merge_pair_debug(
    frame_a: CapturedFrame,
    frame_b: CapturedFrame,
    out_path: Path,
    *,
    offset: tuple[float, float],
    mask_cfg: MaskConfig | None = None,
) -> np.ndarray:
    """Paste two nearby bands at a known offset (for stepwise QA)."""
    mask_cfg = mask_cfg or bluestacks_mask_config()
    a = mask_and_crop(frame_a.image, mask_cfg)
    b = mask_and_crop(frame_b.image, mask_cfg)
    if b.shape != a.shape:
        b = cv2.resize(b, (a.shape[1], a.shape[0]))
    bh, bw = a.shape[:2]
    dx, dy = offset
    x0 = int(round(min(0, dx)))
    y0 = int(round(min(0, dy)))
    x1 = int(round(max(bw, dx + bw)))
    y1 = int(round(max(bh, dy + bh)))
    canvas = np.zeros((y1 - y0, x1 - x0, 3), dtype=np.uint8)
    fill = np.array(mask_cfg.fill, dtype=np.uint8)
    canvas[:] = fill
    weight = np.zeros(canvas.shape[:2], dtype=np.float32)

    def _paste(band: np.ndarray, ox: float, oy: float) -> None:
        px = int(round(ox - x0))
        py = int(round(oy - y0))
        xa0, ya0 = max(0, px), max(0, py)
        xa1, ya1 = min(canvas.shape[1], px + bw), min(canvas.shape[0], py + bh)
        if xa0 >= xa1 or ya0 >= ya1:
            return
        bx0, by0 = xa0 - px, ya0 - py
        patch = band[by0 : by0 + (ya1 - ya0), bx0 : bx0 + (xa1 - xa0)]
        is_fill = np.all(patch == fill, axis=2)
        wpatch = (~is_fill).astype(np.float32)
        wroi = weight[ya0:ya1, xa0:xa1]
        better = wpatch > wroi
        roi = canvas[ya0:ya1, xa0:xa1]
        roi[better] = patch[better]
        weight[ya0:ya1, xa0:xa1] = np.maximum(wroi, wpatch)

    _paste(a, 0.0, 0.0)
    _paste(b, dx, dy)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), canvas)
    return canvas


def _grass_mask(band: np.ndarray) -> np.ndarray:
    """Boolean mask of plains-grass pixels (True = grass)."""
    hsv = cv2.cvtColor(band, cv2.COLOR_BGR2HSV)
    hue, sat, val = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    return (hue >= 28) & (hue <= 90) & (sat >= 35) & (val >= 45)


def _structure_score(band: np.ndarray) -> np.ndarray:
    """Per-pixel score favoring buildings / labels over flat grass.

    Misaligned overlaps otherwise let a neighbor's grass stamp out a city.
    Dilate edges so solid building interiors keep the high score of their rim.
    """
    if band.ndim != 3:
        raise ValueError(f"band must be HxWx3; got {band.shape}")
    gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY).astype(np.float32)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    edges = cv2.magnitude(gx, gy)
    edges = cv2.dilate(edges, np.ones((17, 17), np.uint8))
    hsv = cv2.cvtColor(band, cv2.COLOR_BGR2HSV).astype(np.float32)
    sat = hsv[:, :, 1]
    grass = _grass_mask(band).astype(np.float32)
    non_grass = 1.0 - grass
    score = edges * 0.05 + sat * 0.2 + non_grass * 55.0
    return score.astype(np.float32)


def _paste_band_structure_aware(
    canvas: np.ndarray,
    weight: np.ndarray,
    structure: np.ndarray,
    band: np.ndarray,
    soft: np.ndarray,
    *,
    x0: int,
    y0: int,
    fill: np.ndarray,
    struct_margin: float = 12.0,
) -> None:
    """Paste ``band`` onto canvas; never overwrite buildings with grass."""
    bh, bw = band.shape[:2]
    canvas_h, canvas_w = canvas.shape[:2]
    x1, y1 = x0 + bw, y0 + bh
    xa0, ya0 = max(0, x0), max(0, y0)
    xa1, ya1 = min(canvas_w, x1), min(canvas_h, y1)
    if xa0 >= xa1 or ya0 >= ya1:
        return
    bx0, by0 = xa0 - x0, ya0 - y0
    patch = band[by0 : by0 + (ya1 - ya0), bx0 : bx0 + (xa1 - xa0)]
    wpatch = soft[by0 : by0 + (ya1 - ya0), bx0 : bx0 + (xa1 - xa0)].copy()
    spatch = _structure_score(patch)
    grass_new = _grass_mask(patch)
    is_fill = np.all(patch == fill, axis=2)
    wpatch[is_fill] = 0.0
    spatch[is_fill] = 0.0

    wroi = weight[ya0:ya1, xa0:xa1]
    sroi = structure[ya0:ya1, xa0:xa1]
    roi = canvas[ya0:ya1, xa0:xa1]
    # Existing non-fill, non-grass ≈ building / label / rock already placed.
    existing_content = ~np.all(roi == fill, axis=2) & (wroi > 0)
    grass_old = _grass_mask(roi)
    building_old = existing_content & ~grass_old

    destroys = ((sroi > spatch + struct_margin) & (sroi > 25.0)) | (
        building_old & grass_new
    )
    take = (wpatch > wroi) & ~destroys
    roi[take] = patch[take]
    weight[ya0:ya1, xa0:xa1] = np.where(take, np.maximum(wroi, wpatch), wroi)
    structure[ya0:ya1, xa0:xa1] = np.where(take, np.maximum(sroi, spatch), sroi)


def stitch_grid_lattice(
    frames: list[CapturedFrame],
    out_path: Path,
    *,
    mask_cfg: MaskConfig | None = None,
    overlap: float = 0.55,
    debug_dir: Path | None = None,
    use_landmarks: bool = True,
    calibration: AffineCalibration | None = None,
    frame_offsets: dict[str, tuple[float, float]] | None = None,
    world_to_pixel_matrix: Matrix2x2 | None = None,
) -> MosaicResult:
    """Stitch by screen-grid placement (landmark graph when available).

    Prefer shared player/alliance name offsets + neighbor NCC over a single
    global lattice so middle gaps align while leftmost/rightmost columns stay
    coherent. Falls back to ``ex*pe + ey*ps`` when landmarks are disabled.

    ``frame_offsets`` is the sole placement authority when provided. Pass the
    seed ``world_to_pixel_matrix`` alongside it so panorama projection stays
    diamond-correct; do not also pass ``calibration``.
    """
    if calibration is not None and frame_offsets is not None:
        raise ValueError(
            "calibration and frame_offsets are competing placement authorities"
        )
    if world_to_pixel_matrix is not None and calibration is not None:
        raise ValueError(
            "world_to_pixel_matrix and calibration are competing projection authorities"
        )
    if world_to_pixel_matrix is not None and frame_offsets is None:
        raise ValueError(
            "world_to_pixel_matrix requires frame_offsets as placement authority"
        )
    mask_cfg = mask_cfg or bluestacks_mask_config()
    by_cell: dict[tuple[int, int], CapturedFrame] = {}
    for f in frames:
        cell = parse_grid_cell(f.name)
        if cell is None:
            continue
        # Prefer frames that have OCR for calibration; still place all grid cells.
        by_cell[cell] = f
    if (0, 0) not in by_cell:
        raise ValueError("stitch_grid_lattice needs c0_center / g_0_0")
    center_f = by_cell[(0, 0)]
    band0 = mask_and_crop(center_f.image, mask_cfg)
    bh, bw = band0.shape[:2]
    if frame_offsets is not None:
        missing_offsets = [
            frame.name for frame in by_cell.values() if frame.name not in frame_offsets
        ]
        if missing_offsets:
            raise ValueError(
                f"exact-object frame offsets missing for {sorted(missing_offsets)}"
            )
        cell_pos = {
            cell: frame_offsets[frame.name] for cell, frame in by_cell.items()
        }
    elif calibration is not None:
        linear = np.asarray(calibration.matrix, dtype=float)[:, :2]
        AffineProjection(
            center=(0.0, 0.0),
            pixel_origin=(0.0, 0.0),
            matrix=linear,
        )
        if any(frame.viewport is None for frame in by_cell.values()):
            raise ValueError(
                "calibrated grid placement requires every frame viewport"
            )
        center_world = np.asarray(center_f.viewport, dtype=float)
        cell_pos = {
            cell: tuple(
                linear @ (np.asarray(frame.viewport, dtype=float) - center_world)
            )
            for cell, frame in by_cell.items()
        }
    else:
        pe, ps = calibrate_grid_pixel_steps(
            list(by_cell.values()), bw, bh, overlap=overlap
        )
        if use_landmarks:
            cell_pos = place_grid_by_landmarks(
                by_cell, pe, ps, bw, bh, mask_cfg=mask_cfg
            )
        else:
            cell_pos = {
                (ex, ey): (ex * pe[0] + ey * ps[0], ex * pe[1] + ey * ps[1])
                for (ex, ey) in by_cell
            }

    if debug_dir is not None:
        debug_dir.mkdir(parents=True, exist_ok=True)
        # Merge center with each cardinal neighbor first (user-requested iterate).
        for label, cell in (("E", (1, 0)), ("W", (-1, 0)), ("S", (0, 1)), ("N", (0, -1))):
            nb = by_cell.get(cell)
            if nb is None or cell not in cell_pos:
                continue
            ox0, oy0 = cell_pos[(0, 0)]
            ox1, oy1 = cell_pos[cell]
            merge_pair_debug(
                center_f,
                nb,
                debug_dir / f"pair-center-{label}.png",
                offset=(ox1 - ox0, oy1 - oy0),
                mask_cfg=mask_cfg,
            )

    pads = list(cell_pos.values())
    min_ox = min(p[0] for p in pads) - bw // 2
    max_ox = max(p[0] for p in pads) + bw // 2
    min_oy = min(p[1] for p in pads) - bh // 2
    max_oy = max(p[1] for p in pads) + bh // 2
    origin_x = -min_ox
    origin_y = -min_oy
    canvas_w = int(np.ceil(max_ox - min_ox)) + 2
    canvas_h = int(np.ceil(max_oy - min_oy)) + 2
    fill = np.array(mask_cfg.fill, dtype=np.uint8)
    canvas = np.zeros((canvas_h, canvas_w, 3), dtype=np.uint8)
    canvas[:] = fill
    weight = np.zeros((canvas_h, canvas_w), dtype=np.float32)
    structure = np.zeros((canvas_h, canvas_w), dtype=np.float32)

    yy, xx = np.mgrid[0:bh, 0:bw]
    soft = np.clip(
        (1.0 - np.abs((xx - bw / 2) / (bw / 2)))
        * (1.0 - np.abs((yy - bh / 2) / (bh / 2))),
        0.05,
        1.0,
    ).astype(np.float32)

    # Structure-rich frames first so cities land before grass neighbors can stamp.
    richness: dict[tuple[int, int], float] = {}
    for cell, fr in by_cell.items():
        band = mask_and_crop(fr.image, mask_cfg)
        if band.shape[0] != bh or band.shape[1] != bw:
            band = cv2.resize(band, (bw, bh))
        richness[cell] = float(_structure_score(band).mean())
    order = sorted(
        by_cell.keys(),
        key=lambda c: (-richness[c], abs(c[0]) + abs(c[1])),
    )
    for cell in order:
        fr = by_cell[cell]
        band = mask_and_crop(fr.image, mask_cfg)
        if band.shape[0] != bh or band.shape[1] != bw:
            band = cv2.resize(band, (bw, bh))
        # Normalize terrain seams while retaining original city/unit colors.
        band = normalize_background_lighting(band)
        ox, oy = cell_pos[cell]
        x0 = int(round(origin_x + ox - bw / 2))
        y0 = int(round(origin_y + oy - bh / 2))
        _paste_band_structure_aware(
            canvas,
            weight,
            structure,
            band,
            soft,
            x0=x0,
            y0=y0,
            fill=fill,
        )

    ys_c, xs_c = np.where(weight > 0)
    if len(xs_c) > 0:
        pad = 8
        x0c = max(0, int(xs_c.min()) - pad)
        x1c = min(canvas_w, int(xs_c.max()) + 1 + pad)
        y0c = max(0, int(ys_c.min()) - pad)
        y1c = min(canvas_h, int(ys_c.max()) + 1 + pad)
        canvas = canvas[y0c:y1c, x0c:x1c]
        origin_x -= x0c
        origin_y -= y0c

    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), canvas)
    center_vp = center_f.viewport or (0, 0)
    published_matrix: Matrix2x2 | None = None
    if calibration is not None:
        linear = np.asarray(calibration.matrix, dtype=float)[:, :2]
        scale_x = float(np.linalg.norm(linear[:, 0]))
        scale_y = float(np.linalg.norm(linear[:, 1]))
        published_matrix = (
            (float(linear[0, 0]), float(linear[0, 1])),
            (float(linear[1, 0]), float(linear[1, 1])),
        )
    elif world_to_pixel_matrix is not None:
        published_matrix = AffineProjection(
            center=(0.0, 0.0),
            pixel_origin=(0.0, 0.0),
            matrix=world_to_pixel_matrix,
        ).matrix
        linear = np.asarray(published_matrix, dtype=float)
        scale_x = float(np.linalg.norm(linear[:, 0]))
        scale_y = float(np.linalg.norm(linear[:, 1]))
    elif frame_offsets is not None:
        # Placement is exact; scale metadata is unavailable without world matrix.
        scale_x = scale_y = 55.0
    else:
        # World px/tile ≈ lattice step / median tile step (~11 E, ~14 S).
        scale_x = float(np.hypot(*pe) / 11.0)
        scale_y = float(np.hypot(*ps) / 14.0)
    return MosaicResult(
        image=canvas,
        path=out_path,
        center=center_vp,
        scale_x=max(scale_x, 5.0),
        scale_y=max(scale_y, 5.0),
        origin_x=origin_x,
        origin_y=origin_y,
        band_w=bw,
        band_h=bh,
        world_to_pixel_matrix=published_matrix,
    )


def filter_viewport_frames(
    frames: list[CapturedFrame],
    *,
    max_dev: float = 80.0,
) -> list[CapturedFrame]:
    """Drop OCR outliers that would explode mosaic extent (e.g. Y:1499, X:16)."""
    usable = [f for f in frames if f.viewport is not None]
    if len(usable) < 3:
        return usable
    xs = [f.viewport[0] for f in usable]  # type: ignore[index]
    ys = [f.viewport[1] for f in usable]  # type: ignore[index]
    mx = float(np.median(xs))
    my = float(np.median(ys))
    kept: list[CapturedFrame] = []
    for f in usable:
        assert f.viewport is not None
        if abs(f.viewport[0] - mx) <= max_dev and abs(f.viewport[1] - my) <= max_dev:
            kept.append(f)
    if len(kept) < 2:
        raise ValueError(
            f"too few frames after viewport outlier filter "
            f"({len(kept)} kept from {len(usable)}; median=({mx:.0f},{my:.0f}))"
        )
    return kept


def stitch_viewport_mosaic(
    frames: list[CapturedFrame],
    out_path: Path,
    *,
    mask_cfg: MaskConfig | None = None,
    max_viewport_dev: float = 80.0,
    debug_dir: Path | None = None,
) -> MosaicResult:
    """Stitch masked bands. Prefer controlled grid lattice when ``g_*`` frames exist."""
    gridish = [f for f in frames if parse_grid_cell(f.name) is not None]
    if len(gridish) >= 3:
        return stitch_grid_lattice(
            frames, out_path, mask_cfg=mask_cfg, debug_dir=debug_dir
        )

    mask_cfg = mask_cfg or bluestacks_mask_config()
    usable = filter_viewport_frames(frames, max_dev=max_viewport_dev)
    if not usable:
        raise ValueError("no frames with viewport OCR for mosaic")
    center_f = next(
        (f for f in usable if f.name in ("c0_center", "g_0_0")), usable[0]
    )
    assert center_f.viewport is not None
    center = center_f.viewport
    band0 = mask_and_crop(center_f.image, mask_cfg)
    bh, bw = band0.shape[:2]
    sx, sy = _estimate_scale(usable, bw, bh)

    pads = []
    for f in usable:
        assert f.viewport is not None
        pads.append(
            (
                (f.viewport[0] - center[0]) * sx,
                (f.viewport[1] - center[1]) * sy,
            )
        )
    min_ox = min(p[0] for p in pads) - bw // 2
    max_ox = max(p[0] for p in pads) + bw // 2
    min_oy = min(p[1] for p in pads) - bh // 2
    max_oy = max(p[1] for p in pads) + bh // 2
    origin_x = -min_ox
    origin_y = -min_oy
    canvas_w = int(np.ceil(max_ox - min_ox)) + 2
    canvas_h = int(np.ceil(max_oy - min_oy)) + 2
    fill = np.array(mask_cfg.fill, dtype=np.uint8)
    canvas = np.zeros((canvas_h, canvas_w, 3), dtype=np.uint8)
    canvas[:] = fill
    weight = np.zeros((canvas_h, canvas_w), dtype=np.float32)

    yy, xx = np.mgrid[0:bh, 0:bw]
    wx = 1.0 - np.abs((xx - bw / 2) / (bw / 2))
    wy = 1.0 - np.abs((yy - bh / 2) / (bh / 2))
    soft = np.clip(wx * wy, 0.05, 1.0).astype(np.float32)

    for f in usable:
        assert f.viewport is not None
        band = mask_and_crop(f.image, mask_cfg)
        if band.shape[0] != bh or band.shape[1] != bw:
            band = cv2.resize(band, (bw, bh))
        band = normalize_background_lighting(band)
        ox = (f.viewport[0] - center[0]) * sx
        oy = (f.viewport[1] - center[1]) * sy
        x0 = int(round(origin_x + ox - bw / 2))
        y0 = int(round(origin_y + oy - bh / 2))
        x1, y1 = x0 + bw, y0 + bh
        xa0, ya0 = max(0, x0), max(0, y0)
        xa1, ya1 = min(canvas_w, x1), min(canvas_h, y1)
        if xa0 >= xa1 or ya0 >= ya1:
            continue
        bx0, by0 = xa0 - x0, ya0 - y0
        bx1, by1 = bx0 + (xa1 - xa0), by0 + (ya1 - ya0)
        patch = band[by0:by1, bx0:bx1]
        wpatch = soft[by0:by1, bx0:bx1].copy()
        # Masked UI is fill-colored — never paste it (leaves true gaps, not fake terrain).
        is_fill = np.all(patch == fill, axis=2)
        wpatch[is_fill] = 0.0
        wroi = weight[ya0:ya1, xa0:xa1]
        better = wpatch > wroi
        roi = canvas[ya0:ya1, xa0:xa1]
        roi[better] = patch[better]
        weight[ya0:ya1, xa0:xa1] = np.maximum(wroi, wpatch)

    # Crop to content bbox so HTML isn't mostly empty canvas.
    ys_c, xs_c = np.where(weight > 0)
    if len(xs_c) > 0:
        pad = 8
        x0c = max(0, int(xs_c.min()) - pad)
        x1c = min(canvas_w, int(xs_c.max()) + 1 + pad)
        y0c = max(0, int(ys_c.min()) - pad)
        y1c = min(canvas_h, int(ys_c.max()) + 1 + pad)
        canvas = canvas[y0c:y1c, x0c:x1c]
        origin_x -= x0c
        origin_y -= y0c

    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), canvas)
    return MosaicResult(
        image=canvas,
        path=out_path,
        center=center,
        scale_x=sx,
        scale_y=sy,
        origin_x=origin_x,
        origin_y=origin_y,
        band_w=bw,
        band_h=bh,
    )


def mosaic_projection(mosaic: MosaicResult) -> AffineProjection:
    """Return the mosaic's affine world-to-panorama projection."""
    matrix = mosaic.world_to_pixel_matrix
    if matrix is None:
        matrix = ((mosaic.scale_x, 0.0), (0.0, mosaic.scale_y))
    return AffineProjection(
        center=mosaic.center,
        pixel_origin=(mosaic.origin_x, mosaic.origin_y),
        matrix=matrix,
    )


def panorama_world_bounds(
    mosaic: MosaicResult,
) -> tuple[float, float, float, float]:
    """Return world bounds covering all four panorama image corners."""
    height, width = mosaic.image.shape[:2]
    return mosaic_projection(mosaic).world_bounds_for_image(width, height)


def world_to_panorama(
    wx: float,
    wy: float,
    mosaic: MosaicResult,
) -> tuple[float, float]:
    """Map world tile to panorama pixel (band-center convention)."""
    return mosaic_projection(mosaic).pixel_from_world(wx, wy)


def warp_mosaic_to_isometric(
    mosaic: MosaicResult,
    *,
    min_x: int,
    max_x: int,
    min_y: int,
    max_y: int,
    tile_w: float = 36,
    tile_h: float = 20,
    margin: float = 48.0,
    out_path: Path | None = None,
) -> tuple[np.ndarray, float, float, float, float]:
    """Resample masked mosaic into isometric diamond space.

    Returns ``(iso_bgr, width, height, origin_x, origin_y)`` matching
    ``render_isometric_svg`` coordinates so icons/grid align on top.
    """
    def iso(x: float, y: float) -> tuple[float, float]:
        return (x - y) * (tile_w / 2.0), (x + y) * (tile_h / 2.0)

    corner_pts = [
        iso(min_x, min_y),
        iso(max_x + 1, min_y),
        iso(min_x, max_y + 1),
        iso(max_x + 1, max_y + 1),
    ]
    xs = [c[0] for c in corner_pts]
    ys = [c[1] for c in corner_pts]
    ox = -min(xs) + margin
    oy = -min(ys) + margin
    width = int(np.ceil(max(xs) - min(xs) + 2 * margin))
    height = int(np.ceil(max(ys) - min(ys) + 2 * margin + 28))

    # Inverse iso for each output pixel → world → panorama sample
    # sx = (x - y) * tw/2 + ox  =>  u = (sx - ox) / (tw/2) = x - y
    # sy = (x + y) * th/2 + oy  =>  v = (sy - oy) / (th/2) = x + y
    # x = (v + u) / 2,  y = (v - u) / 2
    tw2 = tile_w / 2.0
    th2 = tile_h / 2.0
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    u = (xx - ox) / tw2
    v = (yy - oy) / th2
    world_x = (v + u) / 2.0
    world_y = (v - u) / 2.0
    pan_x, pan_y = mosaic_projection(mosaic).pixel_from_world(world_x, world_y)
    pan_x = np.asarray(pan_x, dtype=np.float32)
    pan_y = np.asarray(pan_y, dtype=np.float32)

    iso_img = cv2.remap(
        mosaic.image,
        pan_x,
        pan_y,
        interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=list(bluestacks_mask_config().fill),
    )
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(out_path), iso_img)
    return iso_img, float(width), float(height), ox, oy
