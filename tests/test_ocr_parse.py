from ks.vision.ocr import parse_march_time, parse_rss_amount


def test_parse_rss_amount_suffixes():
    assert parse_rss_amount("70K") == 70_000
    assert parse_rss_amount("1.2M") == 1_200_000
    assert parse_rss_amount("14M") == 14_000_000
    assert parse_rss_amount("150000") == 150_000


def test_parse_march_time_formats():
    assert parse_march_time("1:30") == 90.0
    assert parse_march_time("1h 30m") == 5400.0
    assert parse_march_time("90s") == 90.0
