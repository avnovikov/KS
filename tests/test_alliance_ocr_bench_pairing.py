from tools.alliance_ocr_bench.pairing import is_name, pair_members, parse_power


def test_parse_power_millions():
    assert parse_power("12.5M") == 12.5
    assert parse_power("12.5 M") == 12.5


def test_parse_power_rejects_garbage():
    assert parse_power("hello") is None


def test_is_name_rejects_ranks_and_power():
    assert is_name("DarkLord") is True
    assert is_name("R4") is False
    assert is_name("12.5M") is False


def test_pair_members_links_name_above_power():
    hits = [
        (100.0, 50.0, "DarkLord", 0.9),
        (100.0, 90.0, "12.5M", 0.95),
    ]
    assert pair_members(hits) == [{"name": "DarkLord", "power": 12.5}]
