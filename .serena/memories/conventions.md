# Conventions

- Package layout: `ks.<module>`; CLIs via `[project.scripts]` pointing at `*.cli:main` / `ks.cli:main`
- Prefer small cohesive modules; cartograph split by concern (viewport, registration, mosaic, store, render)
- Device abstraction: `ks.device.base` + ADB/BlueStacks/fake implementations — tests use fake device
- ADB-first automation (workspace rule): taps/swipes/screenshots via ADB; verify with screenshot or coordinate bar; prefer explicit popup X
- Config: YAML under `config/`; code loads via `ks.config`
- Specs/plans under `docs/superpowers/`; do not invent large refactors without confirmation
- Artifacts and `.worktrees/` are local/gitignored — do not commit capture outputs
- Tests mirror feature names: `tests/test_cartograph_*.py`, `tests/test_discord_*.py`