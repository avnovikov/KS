"""Tests for per-user inventory path layout."""

from __future__ import annotations

from pathlib import Path


def test_paths_for_builds_expected_layout():
    from ks.auth.inventory import paths_for

    paths = paths_for(Path("/inventory/users"), "discord-123")

    assert paths.root == Path("/inventory/users/discord-123")
    assert paths.gear_dir == Path("/inventory/users/discord-123/gear/full-run")
    assert paths.heroes_dir == Path("/inventory/users/discord-123/heroes/full-run")
    assert paths.troops_path == Path("/inventory/users/discord-123/troops.yaml")
    assert paths.governor_dir == Path("/inventory/users/discord-123/governor/full-run")
    assert paths.research_dir == Path("/inventory/users/discord-123/research/full-run")


def test_ensure_layout_creates_directories_and_copies_troops_seed(tmp_path: Path):
    from ks.auth.inventory import ensure_layout, paths_for

    users_root = tmp_path / "users"
    seed = tmp_path / "troops-seed.yaml"
    seed.write_text("troops: seed\n", encoding="utf-8")
    paths = paths_for(users_root, "discord-123")

    ensure_layout(paths, troops_seed=seed)

    assert paths.root.is_dir()
    assert paths.gear_dir.is_dir()
    assert paths.heroes_dir.is_dir()
    assert paths.governor_dir.is_dir()
    assert paths.research_dir.is_dir()
    assert paths.troops_path.read_text(encoding="utf-8") == "troops: seed\n"


def test_ensure_layout_preserves_existing_troops_file(tmp_path: Path):
    from ks.auth.inventory import ensure_layout, paths_for

    users_root = tmp_path / "users"
    seed = tmp_path / "troops-seed.yaml"
    seed.write_text("troops: seed\n", encoding="utf-8")
    paths = paths_for(users_root, "discord-123")
    paths.troops_path.parent.mkdir(parents=True, exist_ok=True)
    paths.troops_path.write_text("troops: existing\n", encoding="utf-8")

    ensure_layout(paths, troops_seed=seed)

    assert paths.troops_path.read_text(encoding="utf-8") == "troops: existing\n"
