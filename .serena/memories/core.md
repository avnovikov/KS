# KS — KingShot automation / cartography

Python package under `ks/` for BlueStacks/ADB KingShot automation, gather optimisation, Discord bot, and World-map cartography.

## Source map

- `ks/cli.py` — main `ks` CLI entry
- `ks/config.py` + `config/params.yaml` — runtime config (ADB serial, cartograph, scoring, vision)
- `ks/device/` — ADB / BlueStacks / fake device backends (`adb.py`, `bluestacks.py`, `fake.py`)
- `ks/cartograph/` — map capture, registration, mosaic, H3, SQLite store, HTML render (`ks-cartograph`)
- `ks/discord/` — Discord bot (`ks-discord`)
- `ks/pipeline/`, `ks/policy/`, `ks/placement/`, `ks/vision/` — gather/proposal/OCR pipeline
- `ks/executor.py` — tap execution with limits/jitter
- `scripts/` — one-off stitch/capture/emulator helpers
- `tests/` — pytest suite (cartograph + device + discord + pipeline)
- `docs/superpowers/specs/` — design specs; `artifacts/` gitignored runtime outputs

## Invariants

- ADB-first for device/game actions; verify transitions from screenshots or map coordinate OCR — see Cursor rule `.cursor/rules/adb-first.mdc`
- Never continue map capture after leaving World map
- Config-driven: prefer `config/params.yaml` over hardcoding
- Editable install: package name `ks`, scripts `ks`, `ks-discord`, `ks-cartograph`

## Further memories

- Stack/pins: `mem:tech_stack`
- Day-to-day commands: `mem:suggested_commands`
- Style/patterns: `mem:conventions`
- Done checklist: `mem:task_completion`