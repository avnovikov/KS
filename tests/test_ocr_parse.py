import numpy as np
import pytest

from ks.vision.ocr import ocr_region, parse_march_time, parse_rss_amount


def test_parse_rss_amount_suffixes():
    assert parse_rss_amount("70K") == 70_000
    assert parse_rss_amount("1.2M") == 1_200_000
    assert parse_rss_amount("14M") == 14_000_000
    assert parse_rss_amount("150000") == 150_000


def test_parse_rss_amount_rejects_bare_decimal():
    with pytest.raises(ValueError, match="cannot parse RSS amount"):
        parse_rss_amount("1.5")


@pytest.mark.parametrize(
    "text",
    ["", "abc", "1.5", "70X", "K70", "1.2.3M"],
)
def test_parse_rss_amount_rejects_garbage(text):
    with pytest.raises(ValueError, match="cannot parse RSS amount"):
        parse_rss_amount(text)


def test_ocr_region_rejects_invalid_box():
    image = np.zeros((10, 10), dtype=np.uint8)

    with pytest.raises(ValueError, match="x and y must be >= 0"):
        ocr_region(image, (-1, 0, 5, 5))
    with pytest.raises(ValueError, match="x and y must be >= 0"):
        ocr_region(image, (0, -1, 5, 5))
    with pytest.raises(ValueError, match="width and height must be > 0"):
        ocr_region(image, (0, 0, 0, 5))
    with pytest.raises(ValueError, match="width and height must be > 0"):
        ocr_region(image, (0, 0, 5, 0))
    with pytest.raises(ValueError, match="outside image bounds"):
        ocr_region(image, (8, 8, 5, 5))


def test_parse_march_time_formats():
    assert parse_march_time("1:30") == 90.0
    assert parse_march_time("1h 30m") == 5400.0
    assert parse_march_time("90s") == 90.0
