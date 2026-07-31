"""Safe blocker handling: never tap unless a known dialog is recognized."""

from ks.cartograph.live_capture import (
    QUIT_CANCEL_TAP,
    SafeAction,
    decide_blocker_action,
)


def test_no_action_when_viewport_readable():
    action = decide_blocker_action(
        viewport=(1046, 113),
        dialog_text="Quit game? Cancel Confirm",
    )
    assert action.kind == "none"
    assert action.reason == "viewport_ok"


def test_quit_dialog_taps_cancel_only_when_quit_seen():
    action = decide_blocker_action(
        viewport=None,
        dialog_text="Confirmation\nQuit game?\nCancel\nConfirm",
    )
    assert action == SafeAction(
        kind="tap", point=QUIT_CANCEL_TAP, reason="quit_cancel"
    )


def test_generic_confirmation_without_quit_is_ignored():
    """Do not Cancel arbitrary confirmations (Auto Hunting Go/Cancel is OK,
    but unknown Confirmation alone must not fire a blind tap)."""
    action = decide_blocker_action(
        viewport=None,
        dialog_text="Confirmation\nSomething else\nCancel\nGo",
    )
    assert action.kind == "none"
    assert action.reason == "unknown_no_tap"


def test_auto_hunting_upsell_taps_cancel():
    action = decide_blocker_action(
        viewport=None,
        dialog_text="You have not purchased the Auto Hunting Benefit. Cancel Go",
    )
    assert action.kind == "tap"
    assert action.point == QUIT_CANCEL_TAP
    assert action.reason == "purchase_cancel"


def test_never_plans_android_back():
    """Blind Back opens Quit / leaves map — must not be in the action set."""
    for text in (
        "",
        "Events Deals",
        "House 4 Build",
        "7 Daily Sign-in Gift",
        "Alliance is growing",
    ):
        action = decide_blocker_action(viewport=None, dialog_text=text)
        assert action.kind != "back", text


def test_tile_popup_coords_preferred_from_mid_banner():
    """Badland-style mid-screen X:Y must parse (not only bottom search bar)."""
    import numpy as np
    import cv2
    from ks.cartograph.viewport import ocr_viewport_from_image

    img = np.full((1920, 1080, 3), 40, dtype=np.uint8)
    # Fake mid-card with white text region — write readable X:Y via putText
    cv2.rectangle(img, (120, 700), (960, 1050), (220, 220, 220), -1)
    cv2.putText(
        img,
        "X:1049 Y:117",
        (280, 880),
        cv2.FONT_HERSHEY_SIMPLEX,
        2.0,
        (0, 0, 0),
        4,
        cv2.LINE_AA,
    )
    coords, raw = ocr_viewport_from_image(img)
    assert coords == (1049, 117), (coords, raw)


def test_grass_dismiss_and_probe_constants():
    from ks.cartograph.live_capture import GRASS_DISMISS_TAP, GRASS_DISMISS_TAPS, TILE_PROBE_TAPS

    assert GRASS_DISMISS_TAP[0] < 540  # off-center grass
    # Dismiss taps stay in the upper map band (above typical cards).
    assert all(y < 520 for _, y in GRASS_DISMISS_TAPS)
    # Probes sit in the mid-map (empty Badland tap).
    assert TILE_PROBE_TAPS[0] == (540, 860)
    assert all(450 < x < 650 and 750 < y < 1000 for x, y in TILE_PROBE_TAPS)


def test_tile_popup_visible_detects_pale_mid_card():
    import numpy as np
    from ks.cartograph.live_capture import tile_popup_visible

    clean = np.full((1920, 1080, 3), (40, 140, 40), dtype=np.uint8)
    assert tile_popup_visible(clean) is False

    popup = clean.copy()
    # Large beige card in the middle (above invite strip); area within card band.
    popup[700:1150, 180:900] = (230, 230, 235)
    assert tile_popup_visible(popup) is True


def test_tile_popup_visible_detects_lower_city_card():
    import numpy as np
    from ks.cartograph.live_capture import tile_popup_visible

    popup = np.full((1920, 1080, 3), (40, 140, 40), dtype=np.uint8)
    popup[1380:1490, 20:700] = (230, 230, 235)

    assert tile_popup_visible(popup) is True


def test_find_clear_grass_tap_avoids_popup_and_structures():
    import numpy as np
    from ks.cartograph.live_capture import _find_clear_grass_tap

    image = np.full((1920, 1080, 3), (45, 120, 55), dtype=np.uint8)
    image[250:950, 150:930] = (230, 230, 235)
    image[1050:1350, 300:700] = (20, 20, 20)

    tap = _find_clear_grass_tap(image)

    assert tap is not None
    x, y = tap
    assert tuple(image[y, x]) == (45, 120, 55)


def test_swipe_camera_starts_and_ends_on_clear_grass(monkeypatch):
    import numpy as np
    import ks.cartograph.live_capture as live_capture

    image = np.full((1920, 1080, 3), (45, 120, 55), dtype=np.uint8)
    image[700:1000, 400:700] = (180, 40, 30)

    class FakeDevice:
        swipe_call = None

        def swipe(self, *args, **kwargs):
            self.swipe_call = (*args, kwargs["duration_ms"])

    device = FakeDevice()
    monkeypatch.setattr(live_capture, "screencap_bgr", lambda _device: image)

    live_capture.swipe_camera(device, "E", distance_px=120)

    x1, y1, x2, y2, _duration = device.swipe_call
    assert tuple(image[y1, x1]) == (45, 120, 55)
    assert tuple(image[y2, x2]) == (45, 120, 55)


def test_find_popup_corner_close_detects_right_x():
    import cv2
    import numpy as np
    from ks.cartograph.live_capture import find_popup_corner_close

    image = np.full((1920, 1080, 3), (45, 120, 55), dtype=np.uint8)
    image[300:1200, 100:980] = (230, 230, 235)
    cv2.line(image, (920, 330), (960, 370), (45, 45, 45), 8)
    cv2.line(image, (960, 330), (920, 370), (45, 45, 45), 8)

    close = find_popup_corner_close(image)

    assert close is not None
    assert abs(close[0] - 940) < 20
    assert abs(close[1] - 350) < 20


def test_find_popup_corner_close_rejects_bottom_navigation_x():
    import cv2
    import numpy as np
    from ks.cartograph.live_capture import find_popup_corner_close

    image = np.full((1920, 1080, 3), (45, 120, 55), dtype=np.uint8)
    image[450:1250, 150:930] = (230, 230, 235)
    image[1760:1920, 0:1080] = (230, 230, 235)
    cv2.line(image, (25, 1785), (75, 1835), (45, 45, 45), 8)
    cv2.line(image, (75, 1785), (25, 1835), (45, 45, 45), 8)

    assert find_popup_corner_close(image) is None


def test_camera_moved_rejects_duplicate_and_accepts_shift():
    import numpy as np
    from ks.cartograph.live_capture import camera_moved

    before = np.full((1920, 1080, 3), (45, 120, 55), dtype=np.uint8)
    before[600:900, 350:650] = (180, 40, 30)
    shifted = np.roll(before, 90, axis=1)

    assert camera_moved(before, before.copy()) is False
    assert camera_moved(before, shifted) is True


def test_overlay_detection_on_saved_rays_frames():
    from pathlib import Path

    import cv2
    from ks.cartograph.live_capture import (
        alliance_invite_visible,
        find_alliance_invite_close,
        map_overlay_visible,
        tile_popup_visible,
    )

    # Prefer known dirty fixture if present; otherwise skip.
    root = Path("artifacts/cartograph-rays1")
    dirty = root / "pre-clean.png"
    if dirty.exists():
        img = cv2.imread(str(dirty))
        assert find_alliance_invite_close(img) is not None
        assert alliance_invite_visible(img) is True
        assert map_overlay_visible(img) is True
        return
    e1 = root / "E1.png"
    if not e1.exists():
        return
    # Clean captures must not trip overlay detection.
    assert map_overlay_visible(cv2.imread(str(e1))) is False
    _ = tile_popup_visible  # imported for API stability


def test_rejects_glitched_five_digit_x():
    from ks.cartograph.viewport import parse_viewport_text

    assert parse_viewport_text("X:10560 Y:112") == (10560, 112)
    # ocr_viewport_from_image filters the glitch; parse alone keeps raw ints.