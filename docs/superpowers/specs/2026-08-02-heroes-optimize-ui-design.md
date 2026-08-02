# Heroes Optimize UI — design

## Goal
Add `/optimize` to the existing FastAPI UI so a player can see recommended
formations and points for:

- **Swordland** — every mode (garrison, rally_lead, joiner, solo) with points
- **Bear Trap** — starter (`rally_lead`) + joiner with points (damage proxy)
- **Arena** — attack and defense (5 heroes, 2F+3B)

## Inputs
- Live `heroes.json` from `--heroes` (required for optimize)
- Optional `gear.json` from `--gear` (exclusive/class gear assignment)
- Repo `config/troops.yaml`, event YAMLs, point scenario YAMLs, `hero_catalog.yaml`,
  `arena_roles.yaml`

## API
- `GET /optimize` — HTML page (needs heroes dir)
- `GET /api/optimize` — JSON bundle:
  - `sword.modes[mode]` → recommend result dict + points
  - `bear.modes[mode]` → same
  - `arena.attack` / `arena.defense` → ArenaResult dict
  - `errors` for partial failures (per section)

## UI
- Third tab: Optimize (enabled when heroes configured)
- Three sections; each mode/side shows heroes, troops (events), score/points
- Run on page load via fetch; manual Refresh button
