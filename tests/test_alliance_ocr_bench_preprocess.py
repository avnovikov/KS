import numpy as np

from tools.alliance_ocr_bench.preprocess import apply_profile, list_profiles


def test_profile_list_includes_baseline_set():
    names = set(list_profiles())
    for required in {
        "raw",
        "gray",
        "gray_x2",
        "gray_x3",
        "clahe_x2",
        "otsu_x2",
        "otsu_x2_inv",
    }:
        assert required in names


def test_gray_x2_doubles_spatial_size():
    img = np.zeros((40, 60, 3), dtype=np.uint8)
    out = apply_profile("gray_x2", img)
    assert out.shape[0] == 80
    assert out.shape[1] == 120


def test_unknown_profile_raises():
    img = np.zeros((10, 10, 3), dtype=np.uint8)
    try:
        apply_profile("nope", img)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "nope" in str(exc)
