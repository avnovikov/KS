"""Governor gear inventory UI smoke tests."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from ks.heroes.ui.app import create_app  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _client(tmp_path: Path) -> TestClient:
    gear = tmp_path / "gear"
    gear.mkdir()
    (gear / "gear.json").write_text("[]", encoding="utf-8")
    gov = tmp_path / "governor"
    return TestClient(
        create_app(
            gear_dir=gear,
            governor_dir=gov,
            gear_config=ROOT / "config" / "gear.yaml",
        )
    )


def test_governor_page_lists_six_slots(tmp_path: Path) -> None:
    client = _client(tmp_path)
    res = client.get("/inventory/governor-gear")
    assert res.status_code == 200
    body = res.text
    assert "Governor gear" in body
    for name in (
        "Hood",
        "Cloak",
        "Necklace",
        "Breeches",
        "Ring",
        "Staff",
    ):
        assert name in body
    assert 'data-upgrade="hood"' in body


def test_governor_api_upgrade_and_summary(tmp_path: Path) -> None:
    client = _client(tmp_path)
    before = client.get("/api/governor-gear")
    assert before.status_code == 200
    payload = before.json()
    assert len(payload["pieces"]) == 6
    hood = next(p for p in payload["pieces"] if p["slot_id"] == "hood")
    assert hood["tier"] == "green"
    assert hood["stars"] == 0

    upgraded = client.post("/api/governor-gear/hood/upgrade")
    assert upgraded.status_code == 200
    hood2 = next(p for p in upgraded.json()["pieces"] if p["slot_id"] == "hood")
    assert (hood2["tier"], hood2["stars"]) != (hood["tier"], hood["stars"])

    patched = client.patch(
        "/api/governor-gear/cloak",
        json={"tier": "blue", "stars": 2},
    )
    assert patched.status_code == 200
    cloak = next(p for p in patched.json()["pieces"] if p["slot_id"] == "cloak")
    assert cloak["tier"] == "blue"
    assert cloak["stars"] == 2
