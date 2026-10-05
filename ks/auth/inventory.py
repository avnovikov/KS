"""Per-user inventory path helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil

from ks.auth.google_identity import email_path_segment
from ks.auth.session_user import PROVIDER_DISCORD, PROVIDER_GOOGLE, SessionUser


@dataclass(frozen=True, slots=True)
class UserInventoryPaths:
    """Resolved filesystem locations for one signed-in user."""

    root: Path
    gear_dir: Path
    heroes_dir: Path
    troops_path: Path
    governor_dir: Path
    research_dir: Path


def paths_for(users_root: Path, user: SessionUser | str) -> UserInventoryPaths:
    """Build the per-user layout rooted under ``users_root``.

    A Discord id string, or a Discord ``SessionUser``, stays at
    ``{users_root}/{discord_id}``. A Google user is ``{users_root}/google/{email}``.
    """

    root = _inventory_root(users_root, user)
    return UserInventoryPaths(
        root=root,
        gear_dir=root / "gear" / "full-run",
        heroes_dir=root / "heroes" / "full-run",
        troops_path=root / "troops.yaml",
        governor_dir=root / "governor" / "full-run",
        research_dir=root / "research" / "full-run",
    )


def _inventory_root(users_root: Path, user: SessionUser | str) -> Path:
    if isinstance(user, str):
        if not user:
            raise ValueError("discord_user_id must be a non-empty string")
        return users_root / user
    if user.provider == PROVIDER_GOOGLE:
        return users_root / "google" / email_path_segment(user.email)
    if user.provider == PROVIDER_DISCORD:
        if not user.id:
            raise ValueError("discord_user_id must be a non-empty string")
        return users_root / user.id
    raise ValueError(f"unknown auth provider: {user.provider}")


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

