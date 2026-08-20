import json
from pathlib import Path

from tools.alliance_ocr_bench.mine_unstable import mine_unstable, write_candidates_csv

FIX = Path("tests/fixtures/alliance_ocr_bench")


def test_mine_finds_levenshtein_pair():
    old = json.loads((FIX / "names_a.json").read_text(encoding="utf-8"))
    new = json.loads((FIX / "names_b.json").read_text(encoding="utf-8"))
    rows = mine_unstable(old, new)
    assert len(rows) == 1
    assert rows[0]["match_kind"] == "LEVENSHTEIN"
    assert rows[0]["tag"] == "ABC"
    assert rows[0]["edit_distance"] == 1


def test_write_candidates_csv(tmp_path):
    path = tmp_path / "c.csv"
    write_candidates_csv(
        [
            {
                "tag": "ABC",
                "old_name": "DarkLord99",
                "new_name": "DarkLord9",
                "old_power": 12.5,
                "new_power": 12.5,
                "edit_distance": 1,
                "match_kind": "LEVENSHTEIN",
                "suggested_shots": "ABC-r4-00.png",
            }
        ],
        path,
    )
    text = path.read_text(encoding="utf-8")
    assert "DarkLord99" in text
    assert "suggested_shots" in text
