"""In-app setup wizard and help hub routes."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from ks.heroes.gear_models import GearRecord  # noqa: E402
from ks.heroes.gear_store import GearStore  # noqa: E402
from ks.heroes.models import HeroRecord  # noqa: E402
from ks.heroes.store import HeroStore  # noqa: E402
from ks.heroes.ui.app import create_app  # noqa: E402
from ks.heroes.ui.setup_content import SETUP_STEPS  # noqa: E402


def _client(tmp_path: Path) -> TestClient:
    gear = tmp_path / "gear"
    heroes = tmp_path / "heroes"
    gear.mkdir()
    heroes.mkdir()
    GearStore(gear).upsert(
        GearRecord(piece_id="g1", name="Test Helm", scraped_at="t")
    )
    HeroStore(heroes).upsert(
        HeroRecord(name="Helga", stars=1, pellets=0, scraped_at="t")
    )
    return TestClient(create_app(gear_dir=gear, heroes_dir=heroes))


@pytest.mark.parametrize(
    "path,needle",
    [
        ("/setup/1-heroes", b"Verify your roster"),
        ("/setup/2-gear", b"Trust your backpack"),
        ("/setup/3-troops", b"march capacity"),
        ("/setup/4-governor", b"Governor charms"),
        ("/setup/done", b"Event lineups"),
        ("/help", b"Setup guide"),
        ("/help/heroes", b"Heroes"),
        ("/help/governor", b"Governor charms"),
    ],
)
def test_setup_and_help_pages_render(
    tmp_path: Path, path: str, needle: bytes
) -> None:
    res = _client(tmp_path).get(path)
    assert res.status_code == 200
    assert needle in res.content


def test_setup_root_redirects_to_first_step(tmp_path: Path) -> None:
    res = _client(tmp_path).get("/setup", follow_redirects=False)
    assert res.status_code == 302
    assert res.headers["location"] == f"/setup/{SETUP_STEPS[0].slug}"


def test_stepper_lists_all_four_steps(tmp_path: Path) -> None:
    res = _client(tmp_path).get("/setup/2-gear")
    assert res.status_code == 200
    for step in SETUP_STEPS:
        assert step.title.encode() in res.content


def test_layout_includes_setup_and_help_links(tmp_path: Path) -> None:
    res = _client(tmp_path).get("/inventory/heroes")
    assert b'href="/setup"' in res.content
    assert b'href="/help"' in res.content


def test_unknown_setup_step_404(tmp_path: Path) -> None:
    assert _client(tmp_path).get("/setup/9-nope").status_code == 404
