"""Per-request inventory bundle and ContextVar binding for auth mode.

In auth-off mode ``get_current_inventory()`` always returns ``None`` and every
caller falls back to the startup-bound stores captured in ``create_app``
closures.  In auth-on mode ``ProtectRoutesMiddleware`` calls
``build_inventory_bundle`` per authenticated request, sets the ContextVar, and
resets it after ``call_next``.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ks.auth.inventory import UserInventoryPaths
    from ks.heroes.gear_store import GearStore
    from ks.heroes.governor_store import GovernorGearStore
    from ks.heroes.research_store import ResearchStore
    from ks.heroes.store import HeroStore
    from ks.heroes.ui.troop_store import TroopStore


@dataclass
class InventoryBundle:
    """All per-user stores and paths for one authenticated request."""

    gear_dir: Path
    heroes_dir: Path
    troops_path: Path
    governor_dir: Path
    research_dir: Path
    store: "GearStore"
    hero_store: "HeroStore"
    troop_store: "TroopStore"
    governor_store: "GovernorGearStore"
    research_store: "ResearchStore"


# Set by ProtectRoutesMiddleware before dispatching each authenticated request;
# reset (via Token) after call_next returns.  Sync route handlers inherit the
# context from the asyncio task via run_in_executor so this propagates
# correctly for both async and sync FastAPI handlers.
_REQUEST_INVENTORY: ContextVar["InventoryBundle | None"] = ContextVar(
    "_REQUEST_INVENTORY", default=None
)


def get_current_inventory() -> "InventoryBundle | None":
    """Return the per-request inventory bundle, or ``None`` in auth-off mode."""
    return _REQUEST_INVENTORY.get()


def build_inventory_bundle(
    paths: "UserInventoryPaths", *, troops_seed: Path
) -> InventoryBundle:
    """Create all per-user stores after ensuring the directory layout exists.

    ``ensure_layout`` is idempotent: it creates missing dirs and seeds
    ``troops.yaml`` from ``troops_seed`` only on first use.
    """
    from ks.auth.inventory import ensure_layout
    from ks.heroes.gear_store import GearStore
    from ks.heroes.governor_store import GovernorGearStore
    from ks.heroes.research_store import ResearchStore
    from ks.heroes.store import HeroStore
    from ks.heroes.ui.troop_store import TroopStore

    ensure_layout(paths, troops_seed=troops_seed)

    troop_store = TroopStore(paths.troops_path, seed_from=troops_seed)
    troop_store.ensure_exists()

    return InventoryBundle(
        gear_dir=paths.gear_dir,
        heroes_dir=paths.heroes_dir,
        troops_path=paths.troops_path,
        governor_dir=paths.governor_dir,
        research_dir=paths.research_dir,
        store=GearStore(paths.gear_dir),
        hero_store=HeroStore(paths.heroes_dir),
        troop_store=troop_store,
        governor_store=GovernorGearStore(paths.governor_dir),
        research_store=ResearchStore(paths.research_dir),
    )
