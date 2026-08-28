"""Copy and routing metadata for the in-app setup wizard and help hub."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SetupStep:
    id: str
    number: int
    slug: str
    title: str
    headline: str
    inventory_path: str
    inventory_label: str
    do_this: tuple[str, ...]
    tips: tuple[str, ...]


SETUP_STEPS: tuple[SetupStep, ...] = (
    SetupStep(
        id="heroes",
        number=1,
        slug="1-heroes",
        title="Heroes",
        headline="Verify your roster",
        inventory_path="/inventory/heroes",
        inventory_label="Open Heroes",
        do_this=(
            "Collect or rescan heroes with the roster visible on your device.",
            "Spot-check stars, pellets, and power against the game.",
            "Fix highlighted rows — edits save automatically.",
        ),
        tips=(
            "Naked power matters for optimisers.",
            "Assurance tints show fields that still need a look.",
        ),
    ),
    SetupStep(
        id="gear",
        number=2,
        slug="2-gear",
        title="Gear",
        headline="Trust your backpack inventory",
        inventory_path="/inventory/gear",
        inventory_label="Open Gear",
        do_this=(
            "Leave Backpack → Gear open on the device.",
            "Run Rescan from OCR (replaces the whole inventory).",
            "Use Needs attention to find incomplete enhancement or mastery.",
        ),
        tips=(
            "Pinned fields (•) survive rescan; clear a value to accept OCR again.",
        ),
    ),
    SetupStep(
        id="troops",
        number=3,
        slug="3-troops",
        title="Troops",
        headline="Set march size and troop counts",
        inventory_path="/inventory/troops",
        inventory_label="Open Troops",
        do_this=(
            "Enter march capacity and Truegold.",
            "Fill infantry, cavalry, and archers tier counts.",
            "Confirm totals — every optimiser reads this file.",
        ),
        tips=("No OCR yet — manual entry is the source of truth.",),
    ),
    SetupStep(
        id="governor",
        number=4,
        slug="4-governor",
        title="Governor charms",
        headline="Mirror your six in-game charm slots",
        inventory_path="/inventory/governor-gear",
        inventory_label="Open Governor charms",
        do_this=(
            "Match all six governor charm slots to what you see in-game.",
            "Use Upgrade as you level charms (advances the config ladder).",
            "Check set bonus and per-troop Atk/Def% chips.",
        ),
        tips=("Bonuses feed Bear, Swordland, and other optimisers.",),
    ),
)

STEP_BY_SLUG = {step.slug: step for step in SETUP_STEPS}
STEP_BY_ID = {step.id: step for step in SETUP_STEPS}
STEP_BY_NUMBER = {step.number: step for step in SETUP_STEPS}
FIRST_STEP_SLUG = SETUP_STEPS[0].slug


def resume_slug(*, current_step: int) -> str:
    """Setup URL slug for a stored current_step (1–4), or done when past step 4."""
    if current_step >= 5:
        return "done"
    step = STEP_BY_NUMBER.get(current_step)
    return step.slug if step is not None else FIRST_STEP_SLUG

HELP_CHAPTERS: tuple[dict[str, str], ...] = (
    {
        "id": "heroes",
        "title": "Heroes",
        "setup_slug": "1-heroes",
        "summary": "Roster OCR, trust highlights, and naked power.",
    },
    {
        "id": "gear",
        "title": "Gear",
        "setup_slug": "2-gear",
        "summary": "Backpack rescan, pinning, and incomplete rows.",
    },
    {
        "id": "troops",
        "title": "Troops",
        "setup_slug": "3-troops",
        "summary": "March capacity, Truegold, and tier counts.",
    },
    {
        "id": "governor",
        "title": "Governor charms",
        "setup_slug": "4-governor",
        "summary": "Six-slot mirror, upgrades, and set bonuses.",
    },
)

OPTIMISER_HELP: dict[str, Any] = {
    "title": "Optimiser",
    "summary": "Run after inventory is trustworthy.",
    "entries": (
        ("Event lineups", "/optimiser/events", "Swordland, Bear, Arena, Conquest formations."),
        ("Gear XP", "/optimiser/gear-xp", "Where to spend fodder for the biggest utility gain."),
        ("Hero levels", "/optimiser/hero-levels", "Placeholder — coming later."),
    ),
}


def step_context(step: SetupStep) -> dict[str, Any]:
    return {
        "step": step,
        "steps": SETUP_STEPS,
        "prev_slug": (
            SETUP_STEPS[step.number - 2].slug if step.number > 1 else None
        ),
        "next_slug": (
            SETUP_STEPS[step.number].slug if step.number < len(SETUP_STEPS) else None
        ),
    }
