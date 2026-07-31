"""Live BlueStacks capture: open world map and sample surrounding screens."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import cv2
import numpy as np

from ks.cartograph.viewport import ocr_search_bar_from_image, ocr_viewport_from_image
from ks.device.adb import AdbDevice


@dataclass(frozen=True)
class CapturedFrame:
    name: str
    path: Path
    viewport: tuple[int, int] | None
    viewport_raw: str
    image: np.ndarray


@dataclass(frozen=True)
class SafeAction:
    """Only known blockers get a tap; unknown screens → none (never Back)."""

    kind: Literal["none", "tap"]
    point: tuple[int, int] | None = None
    reason: str = ""


# 1080×1920 BlueStacks portrait — Town bottom-nav "World" (map icon).
# Verified 2026-07-30: (1005, 1850) opens local map with search bar.
WORLD_FROM_TOWN_TAP = (1005, 1850)
# Quit-game / left-orange Cancel on two-button confirmations.
QUIT_CANCEL_TAP = (350, 1120)
# Open a map tile info banner: prefer empty grass in the *middle* of the map.
# True screen center is ~540×960; map content sits above bottom chrome.
TILE_PROBE_TAPS: tuple[tuple[int, int], ...] = (
    (540, 860),  # middle — empty Badland when nothing is there
    (480, 820),  # slight offsets if center is a city / beast
    (600, 900),
    (540, 780),
    (500, 940),
)
# Dismiss banner: tap empty map *above* typical cards (cards sit ~y 0.35–0.75).
# Side/upper grass avoids landing on Badland/lord panels or city centers.
GRASS_DISMISS_TAPS: tuple[tuple[int, int], ...] = (
    (160, 380),
    (920, 380),
    (540, 340),
    (200, 480),
    (880, 480),
    (540, 420),
)
# Escape march / hero-select screens opened by accidental Attack taps.
MARCH_BACK_TAP = (70, 95)
SELECT_HEROES_CLOSE_TAP = (1000, 280)
# Known Mail close (top-right X) on 1080×1920.
MAIL_CLOSE_TAP = (1020, 95)
# Legacy single-point alias used by capture loops.
GRASS_DISMISS_TAP = GRASS_DISMISS_TAPS[0]


def screencap_bgr(device: AdbDevice) -> np.ndarray:
    png = device.screencap()
    arr = np.frombuffer(png, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    assert img is not None, "failed to decode screencap"
    return img


def camera_moved(before: np.ndarray, after: np.ndarray, *, min_mean_delta: float = 1.5) -> bool:
    """Return whether the map content changed enough to accept a swipe."""
    if before.shape != after.shape or before.ndim != 3:
        raise ValueError(
            f"camera frames must have equal HxWx3 shapes; got {before.shape} and {after.shape}"
        )
    h, w = before.shape[:2]
    region = (
        slice(int(h * 0.15), int(h * 0.75)),
        slice(int(w * 0.12), int(w * 0.88)),
    )
    first = cv2.cvtColor(before[region], cv2.COLOR_BGR2GRAY)
    second = cv2.cvtColor(after[region], cv2.COLOR_BGR2GRAY)
    size = (max(64, first.shape[1] // 4), max(64, first.shape[0] // 4))
    first = cv2.resize(first, size, interpolation=cv2.INTER_AREA)
    second = cv2.resize(second, size, interpolation=cv2.INTER_AREA)
    shift, response = cv2.phaseCorrelate(
        first.astype(np.float32),
        second.astype(np.float32),
    )
    if response >= 0.05 and float(np.hypot(*shift)) >= 4.0:
        return True
    mean_delta = float(cv2.absdiff(first, second).mean())
    return mean_delta >= min_mean_delta


def _ocr_center_text(img: np.ndarray) -> str:
    """OCR the middle band where modal dialogs appear."""
    try:
        import pytesseract
    except ImportError:
        return ""
    from ks.cartograph.viewport import tesseract_cmd

    cmd = tesseract_cmd()
    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd
    h, w = img.shape[:2]
    mid = img[int(h * 0.28) : int(h * 0.72), int(w * 0.08) : int(w * 0.92)]
    return pytesseract.image_to_string(mid, config="--psm 6")


def decide_blocker_action(
    *,
    viewport: tuple[int, int] | None,
    dialog_text: str,
) -> SafeAction:
    """Choose at most one safe tap. Prefer doing nothing over wrong taps."""
    if viewport is not None:
        return SafeAction(kind="none", reason="viewport_ok")

    text = dialog_text or ""
    # Quit game is opened by accidental Android Back — Cancel only.
    if "Quit" in text and ("Cancel" in text or "Confirmation" in text):
        return SafeAction(kind="tap", point=QUIT_CANCEL_TAP, reason="quit_cancel")
    # Search → Auto Hunting upsell — Cancel (left), never Go.
    if "Auto Hunting" in text and "Cancel" in text:
        return SafeAction(kind="tap", point=QUIT_CANCEL_TAP, reason="purchase_cancel")

    # Unknown overlay / town / search / invite: do not tap or Back.
    return SafeAction(kind="none", reason="unknown_no_tap")


def apply_safe_blocker_action(device: AdbDevice, img: np.ndarray) -> bool:
    """Run one recognized dismiss tap. Returns True if a tap was made."""
    vp, _ = ocr_viewport_from_image(img)
    if vp is not None:
        return False
    text = _ocr_center_text(img)
    action = decide_blocker_action(viewport=vp, dialog_text=text)
    if action.kind != "tap" or action.point is None:
        return False
    device.tap(*action.point)
    time.sleep(0.8)
    return True


def _dismiss_quit_dialog(device: AdbDevice, img: np.ndarray) -> bool:
    """Compat helper: tap Cancel only for Quit / Auto Hunting confirmations."""
    return apply_safe_blocker_action(device, img)


def dismiss_map_blockers(device: AdbDevice, *, max_rounds: int = 3) -> np.ndarray:
    """Clear *known* blockers only. Never Android-Back or red-X hunting.

    If the screen is unrecognized and viewport OCR fails, leave it alone —
    blind taps open Events / Search / Town / Quit.
    """
    img = screencap_bgr(device)
    for _ in range(max_rounds):
        vp, _ = ocr_viewport_from_image(img)
        if vp is not None:
            return img
        if not apply_safe_blocker_action(device, img):
            return img
        img = screencap_bgr(device)
    return img


def ensure_world_map(device: AdbDevice, settle_s: float = 1.5) -> np.ndarray:
    """Return a frame already on the local world map (search-bar coords readable).

    Never tap World if OCR already succeeds — on the world map that same
    corner is Town and would leave the map.
    Never taps red UI blobs (Events/Deals look red).
    """
    img = dismiss_map_blockers(device)
    vp, _ = ocr_viewport_from_image(img)
    if vp is not None:
        return img

    device.tap(*WORLD_FROM_TOWN_TAP)
    time.sleep(settle_s + 0.5)
    img = dismiss_map_blockers(device)
    vp, raw = ocr_viewport_from_image(img)
    if vp is None:
        raise RuntimeError(
            "not on local world map after Town→World tap "
            f"{WORLD_FROM_TOWN_TAP}; OCR={raw!r}"
        )
    return img


def _pale_mask(img: np.ndarray, y0: float, y1: float, x0: float, x1: float) -> np.ndarray:
    h, w = img.shape[:2]
    roi = img[int(h * y0) : int(h * y1), int(w * x0) : int(w * x1)]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    return cv2.inRange(hsv, (0, 0, 180), (50, 70, 255))


def find_alliance_invite_close(img: np.ndarray) -> tuple[int, int] | None:
    """Return (x, y) of the red circular X on the lower alliance-invite banner.

    Must not match Mail icon badges or other red chrome — a wrong tap opens Mail.
    """
    if img.ndim != 3 or img.shape[0] < 100:
        return None
    h, w = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    red = cv2.bitwise_or(
        cv2.inRange(hsv, (0, 120, 120), (12, 255, 255)),
        cv2.inRange(hsv, (165, 120, 120), (180, 255, 255)),
    )
    # Invite X sits on the banner: ~x 0.90–0.96, ~y 0.72–0.78 (e.g. 1001,1432).
    y0, y1 = int(h * 0.70), int(h * 0.78)
    x0, x1 = int(w * 0.88), int(w * 0.97)
    roi = red[y0:y1, x0:x1]
    roi = cv2.morphologyEx(roi, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    cnts, _ = cv2.findContours(roi, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best: tuple[float, int, int] | None = None
    for c in cnts:
        area = cv2.contourArea(c)
        if area < 400 or area > 5000:
            continue
        x, y, bw, bh = cv2.boundingRect(c)
        # Circular ~40–70 px button.
        if not (35 <= bw <= 80 and 35 <= bh <= 80):
            continue
        aspect = bw / bh
        if not (0.75 <= aspect <= 1.35):
            continue
        cx, cy = x0 + x + bw // 2, y0 + y + bh // 2
        if best is None or area > best[0]:
            best = (area, cx, cy)
    return None if best is None else (best[1], best[2])


def alliance_invite_visible(img: np.ndarray) -> bool:
    """True when the bottom alliance-invite banner (red circular X) is open."""
    # Prefer geometric X — OCR markers like "View" false-positive too often.
    return find_alliance_invite_close(img) is not None


def find_popup_corner_close(img: np.ndarray) -> tuple[int, int] | None:
    """Find a low-saturation X button in either top corner of a pale popup."""
    if img.ndim != 3 or img.shape[0] < 100:
        return None
    height = img.shape[0]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    pale = cv2.inRange(hsv, (0, 0, 175), (50, 75, 255))
    contours, _ = cv2.findContours(pale, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for contour in sorted(contours, key=cv2.contourArea, reverse=True):
        if cv2.contourArea(contour) < 30_000:
            continue
        x, y, width, height = cv2.boundingRect(contour)
        if width < 250 or height < 100:
            continue
        for center_x in (x + 50, x + width - 50):
            center_y = y + 50
            if center_y >= int(height * 0.82):
                continue
            x0, x1 = max(0, center_x - 45), min(img.shape[1], center_x + 45)
            y0, y1 = max(0, center_y - 45), min(img.shape[0], center_y + 45)
            patch = img[y0:y1, x0:x1]
            patch_hsv = hsv[y0:y1, x0:x1]
            if patch.size == 0 or float((patch_hsv[:, :, 1] > 100).mean()) > 0.18:
                continue
            gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
            lines = cv2.HoughLinesP(
                cv2.Canny(gray, 60, 160),
                1,
                np.pi / 180,
                threshold=12,
                minLineLength=18,
                maxLineGap=8,
            )
            if lines is None:
                continue
            positive = False
            negative = False
            for x_start, y_start, x_end, y_end in lines[:, 0]:
                dx = int(x_end) - int(x_start)
                dy = int(y_end) - int(y_start)
                if abs(dx) < 10 or abs(dy) < 10:
                    continue
                if dx * dy > 0:
                    positive = True
                else:
                    negative = True
            if positive and negative:
                return center_x, center_y
    return None


def mail_modal_visible(img: np.ndarray) -> bool:
    """True when the full-screen Mail reader is open."""
    text = _ocr_center_text(img)
    return ("Dear Governor" in text) or (
        "Mail" in text and ("Kingshot Team" in text or "Rewards" in text or "Delete" in text)
    )


def march_ui_visible(img: np.ndarray) -> bool:
    """True when Attack opened the march / Select Heroes screen."""
    text = _ocr_center_text(img)
    markers = ("Select Heroes", "Target:", "Deploy", "Clear All", "Rookie Infantry")
    return any(m in text for m in markers)


def tile_popup_visible(img: np.ndarray) -> bool:
    """True when a Badland / lord / building info card is open (not invite/mail)."""
    if img.ndim != 3 or img.shape[0] < 100:
        return False
    if mail_modal_visible(img) or march_ui_visible(img):
        return False
    h, w = img.shape[:2]
    # Cards sit upper-mid→lower; include the top of lord panels (~y 0.22).
    y0, y1 = int(h * 0.18), int(h * 0.88)
    x0, x1 = int(w * 0.08), int(w * 0.92)
    mid = img[y0:y1, x0:x1]
    hsv = cv2.cvtColor(mid, cv2.COLOR_BGR2HSV)
    pale = cv2.inRange(hsv, (0, 0, 180), (50, 70, 255))
    cnts, _ = cv2.findContours(pale, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in cnts:
        area = cv2.contourArea(c)
        # Tile cards ~40k–350k; full-screen mail is ~800k+.
        if area < 35_000 or area > 400_000:
            continue
        M = cv2.moments(c)
        if M["m00"] <= 0:
            continue
        cy = y0 + int(M["m01"] / M["m00"])
        # Lower-left/right city cards can reach y≈0.77. Alliance invites also
        # sit low, but have a separately detectable red close button.
        if cy < int(h * 0.82) and not alliance_invite_visible(img):
            return True
    text = _ocr_center_text(img)
    markers = (
        "Badland",
        "Teleport",
        "Occupy",
        "Scout",
        "Attack",
        "Town Center",
        "Upgrade",
        "Occupied by",
        "Power",
    )
    return any(m in text for m in markers)


def map_overlay_visible(img: np.ndarray) -> bool:
    """True if any capture-blocking overlay is up."""
    return (
        mail_modal_visible(img)
        or march_ui_visible(img)
        or alliance_invite_visible(img)
        or tile_popup_visible(img)
    )


def _find_clear_grass_tap(img: np.ndarray) -> tuple[int, int] | None:
    """Find a uniform green map patch outside cards, buildings, and side UI."""
    if img.ndim != 3 or img.shape[0] < 600 or img.shape[1] < 400:
        return None
    h, w = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blocked = np.zeros((h, w), dtype=np.uint8)
    pale = cv2.inRange(hsv, (0, 0, 180), (50, 70, 255))
    contours, _ = cv2.findContours(pale, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for contour in contours:
        if cv2.contourArea(contour) < 20_000:
            continue
        bx, by, bw, bh = cv2.boundingRect(contour)
        # Pale body identifies a card; its teal header extends above that body.
        blocked[
            max(0, by - 260) : min(h, by + bh + 60),
            max(0, bx - 60) : min(w, bx + bw + 60),
        ] = 1
    best: tuple[float, int, int] | None = None
    radius = 18
    for y in range(280, min(1500, h - 300), 48):
        for x in range(120, w - 120, 48):
            if blocked[y, x]:
                continue
            patch = hsv[y - radius : y + radius + 1, x - radius : x + radius + 1]
            hue = float(np.median(patch[:, :, 0]))
            saturation = float(np.median(patch[:, :, 1]))
            value = float(np.median(patch[:, :, 2]))
            if not (25 <= hue <= 95 and 35 <= saturation <= 230 and 35 <= value <= 225):
                continue
            gray_patch = gray[y - radius : y + radius + 1, x - radius : x + radius + 1]
            edge_score = float(
                np.mean(np.abs(cv2.Laplacian(gray_patch, cv2.CV_32F)))
            )
            value_spread = float(np.std(patch[:, :, 2]))
            score = edge_score + 0.25 * value_spread
            if best is None or score < best[0]:
                best = (score, x, y)
    if best is None:
        return None
    return best[1], best[2]


def dismiss_tile_popup(
    device: AdbDevice,
    *,
    settle_s: float = 0.55,
    require_clear: bool = False,
) -> np.ndarray:
    """Close mail / march / invite / tile cards until the full map is visible."""
    img = screencap_bgr(device)
    for _ in range(10):
        if not map_overlay_visible(img):
            return img
        close = find_alliance_invite_close(img) or find_popup_corner_close(img)
        if close is not None:
            device.tap(*close)
            time.sleep(settle_s)
            img = screencap_bgr(device)
            continue
        if march_ui_visible(img):
            device.tap(*MARCH_BACK_TAP)
            time.sleep(settle_s + 0.3)
            img = screencap_bgr(device)
            if march_ui_visible(img):
                device.tap(*SELECT_HEROES_CLOSE_TAP)
                time.sleep(settle_s + 0.3)
                img = screencap_bgr(device)
            continue
        if mail_modal_visible(img):
            device.tap(*MAIL_CLOSE_TAP)
            time.sleep(settle_s + 0.3)
            img = screencap_bgr(device)
            continue
        if tile_popup_visible(img):
            cleared = False
            # Grass only — never tap Scout/Attack (opens Deploy).
            dynamic_tap = _find_clear_grass_tap(img)
            taps = (
                ((dynamic_tap,) if dynamic_tap is not None else ())
                + GRASS_DISMISS_TAPS
            )
            for x, y in taps:
                device.tap(x, y)
                time.sleep(settle_s)
                img = screencap_bgr(device)
                if mail_modal_visible(img) or march_ui_visible(img):
                    break
                if not tile_popup_visible(img):
                    cleared = True
                    break
            if cleared:
                continue
        break
    if require_clear and map_overlay_visible(img):
        raise RuntimeError(
            "map overlay still visible after dismiss taps; "
            "refusing to save a frame with an overlay"
        )
    return img


def capture_clean_frame_with_popup_coords(
    device: AdbDevice,
    *,
    settle_s: float = 0.9,
) -> tuple[np.ndarray, tuple[int, int] | None, str]:
    """Tap empty mid-map for the info banner, read X/Y, dismiss, return clean map.

    Workflow: tap middle (grass/Badland if nothing there) → OCR banner coords →
    tap grass to clear → save. Never returns a frame with a tile/invite/mail overlay.
    """
    clean = dismiss_tile_popup(device, settle_s=settle_s * 0.5, require_clear=True)
    vp, raw = ocr_search_bar_from_image(clean)
    if vp is not None:
        return clean, vp, raw

    # Fallback for layouts where the persistent coordinate bar is hidden.
    for probe in TILE_PROBE_TAPS:
        device.tap(*probe)
        time.sleep(settle_s)
        banner = screencap_bgr(device)
        if mail_modal_visible(banner) or march_ui_visible(banner):
            dismiss_tile_popup(device, settle_s=settle_s * 0.5)
            continue
        if not tile_popup_visible(banner):
            continue
        text = _ocr_center_text(banner)
        # City panels (Scout/Attack) — dismiss and try another mid-map point.
        if "Attack" in text or "Scout" in text:
            dismiss_tile_popup(device, settle_s=settle_s * 0.45, require_clear=False)
            continue
        vp, raw = ocr_viewport_from_image(banner)
        if vp is not None and 100 <= vp[0] <= 5000 and 10 <= vp[1] <= 5000:
            break
        vp = None

    clean = dismiss_tile_popup(device, settle_s=settle_s * 0.6, require_clear=True)
    return clean, vp, raw


def swipe_camera(device: AdbDevice, direction: str, distance_px: int = 200) -> None:
    """Drag anywhere on the map to pan the camera toward ``direction`` (E/N/W/S).

    Finger starts near mid-screen (open map) and moves opposite the look
    direction — same as a human click-and-drag.
    """
    d = max(80, int(distance_px))
    image = screencap_bgr(device)
    clear_grass = _find_clear_grass_tap(image)
    cx, cy = clear_grass or (540, 1200)
    half = d // 2
    cx = int(np.clip(cx, 120 + half, image.shape[1] - 120 - half))
    cy = int(np.clip(cy, 280 + half, min(1500, image.shape[0] - 300) - half))
    # Finger moves opposite to desired camera look direction (map follows finger).
    paths = {
        "E": (cx + d // 2, cy, cx - d // 2, cy),  # finger left → see east
        "W": (cx - d // 2, cy, cx + d // 2, cy),
        "N": (cx, cy - d // 2, cx, cy + d // 2),
        "S": (cx, cy + d // 2, cx, cy - d // 2),
    }
    if direction not in paths:
        raise ValueError(f"direction must be E/N/W/S; got {direction!r}")
    x1, y1, x2, y2 = paths[direction]
    device.swipe(x1, y1, x2, y2, duration_ms=280)


def capture_around(
    device: AdbDevice,
    out_dir: Path,
    *,
    count: int = 4,
    settle_s: float = 1.0,
    open_world: bool = True,
    swipe_px: int = 500,
) -> list[CapturedFrame]:
    """Capture center + ``count`` cardinal neighbours (E, N, W, S)."""
    if count not in (4,):
        raise ValueError("only count=4 supported in v1")
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

    device.tap(*GRASS_DISMISS_TAP)
    time.sleep(settle_s * 0.5)
    frames.append(_save("c0_center"))

    for i, direction in enumerate(["E", "N", "W", "S"], start=1):
        swipe_camera(device, direction, distance_px=swipe_px)
        time.sleep(settle_s)
        frames.append(_save(f"c{i}_{direction}"))
        opposite = {"E": "W", "W": "E", "N": "S", "S": "N"}[direction]
        swipe_camera(device, opposite, distance_px=swipe_px)
        time.sleep(settle_s * 0.6)

    return frames
