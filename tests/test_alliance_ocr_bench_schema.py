from pathlib import Path

import pytest

from tools.alliance_ocr_bench.schema import load_gold

FIXTURE = Path("tests/fixtures/alliance_ocr_bench/gold_sample.json")


def test_load_gold_ok():
    rows = load_gold(FIXTURE)
    assert len(rows) == 1
    assert rows[0].name == "DarkLord"
    assert rows[0].power == 12.5
    assert rows[0].roi == (10, 20, 200, 80)


def test_load_gold_rejects_missing_name(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('[{"id":"x","shot":"a.png","power":1.0}]', encoding="utf-8")
    with pytest.raises(ValueError, match="name"):
        load_gold(bad)


def test_load_gold_rejects_nonpositive_power(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(
        '[{"id":"x","shot":"a.png","name":"A","power":0}]',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="power"):
        load_gold(bad)
