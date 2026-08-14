"""Per-user inventory path helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil


@dataclass(frozen=True, slots=True)
class UserInventoryPaths:
    """Resolved filesystem locations for one Discord user."""

    root: Path
    gear_dir: Path
    heroes_dir: Path
    troops_path: Path
    governor_dir: Path
    research_dir: Path


def paths_for(users_root: Path, discord_user_id: str) -> UserInventoryPaths:
    """Build the per-user layout rooted under ``users_root``."""

    if not discord_user_id:
        raise ValueError("discord_user_id must be a non-empty string")

    root = users_root / discord_user_id
    return UserInventoryPaths(
        root=root,
        gear_dir=root / "gear" / "full-run",
        heroes_dir=root / "heroes" / "full-run",
        troops_path=root / "troops.yaml",
        governor_dir=root / "governor" / "full-run",
        research_dir=root / "research" / "full-run",
    )


def ensure_layout(paths: UserInventoryPaths, *, troops_seed: Path) -> None:
    """Create the per-user directory layout and seed troops when needed."""

    if not troops_seed.is_file():
        raise FileNotFoundError(f"troops seed does not exist: {troops_seed}")

    for directory in (
        paths.root,
        paths.gear_dir,
        paths.heroes_dir,
        paths.governor_dir,
        paths.research_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    if not paths.troops_path.exists():
        shutil.copyfile(troops_seed, paths.troops_path)

