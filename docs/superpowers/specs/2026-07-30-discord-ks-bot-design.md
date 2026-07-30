# Discord KS Bot — Design

**Date:** 2026-07-30  
**Status:** Approved for implementation  
**Workspace:** `/Users/alexei/KS`

## Goal

Run an always-on Discord bot on this Mac that:

- Participates in server chat (read channels + send messages)
- Exposes slash commands and buttons that trigger KS actions
- Gates **write** actions behind a Discord role (default: `ks-ops`)
- Confirms writes in-channel with Approve / Reject buttons (replaces terminal `y`/`n` for Discord-started runs)

## Non-goals (v1)

- Discord OAuth / local user accounts
- Multi-guild fleet management
- Hosting off this Mac / public HTTPS interactions endpoint
- Auto-executing writes without button confirm
- Full chat LLM agent in Discord (commands + status messages only)

## Approach

**Approach 1:** `discord.py` bot process co-located with KS (same Python package). Bot token from environment; guild/role settings from YAML.

## Architecture

```
Discord (guild)
      ▲
      │ Gateway (bot token)
      ▼
 ks/discord/
   ├── auth        # role gate for write
   ├── proposals   # pending Propose → Approve/Reject state
   ├── bridge      # Discord intents → KS policy/pipeline/executor
   └── bot         # slash commands + button handlers
      ▼
 existing KS layers (config, policy, pipeline, executor, device)
```

### Auth model

| Concern | Mechanism |
|---------|-----------|
| Bot stays authorized | Discord application **bot token** (`DISCORD_BOT_TOKEN` env; never committed) |
| Human write access | Member must have configured Discord role (default name `ks-ops`) |
| Read / chat | Channel permissions in Discord; bot only speaks where invited |
| Button Approve | Re-check write role at click time (not only at slash time) |

### Write flow

1. Member with write role runs `/gather` (or similar)
2. Bot builds a KS proposal via bridge (fixture JSON path or live pipeline)
3. Bot posts embed + **Approve** / **Reject** buttons; stores pending proposal id
4. On **Approve**: role check again → `executor` → status reply
5. On **Reject** or expiry: cancel; no taps

### Read flow

- `/status` — bot online, dry_run flag, whether ADB serial is configured (no role required beyond channel access)

## Configuration

`config/discord.yaml`:

```yaml
guild_id: null          # optional; null = allow any guild the bot is in
write_role: ks-ops
proposal_ttl_seconds: 300
# Optional default fixture for offline / CI gather proposals from Discord
candidates_json: null
```

Secrets:

- `DISCORD_BOT_TOKEN` (required to start)

`.gitignore` must not track `.env` if used.

## Components

| Unit | Responsibility |
|------|----------------|
| `ks.discord.auth` | Pure helpers: does member have write role? |
| `ks.discord.proposals` | In-memory pending proposals with TTL |
| `ks.discord.config` | Load Discord YAML + require token from env |
| `ks.discord.bridge` | Propose/execute gather using existing KS APIs |
| `ks.discord.bot` | discord.py wiring only |
| CLI `ks-discord` | Start the always-on process |

## Error handling

- Missing token → fail fast with clear message (exit 1)
- No write role on slash/button → ephemeral denial
- Nothing to do / proposal failure → reply with reason; no buttons
- Approve after TTL / unknown id → ephemeral “expired”
- Executor errors → reply with error; do not crash the gateway loop

## Testing

- Unit tests for auth, proposal store, Discord config load (no live Discord)
- Bridge tests with FakeDevice + fixture candidates
- No network Discord tests in CI

## v1 command set

- `/status` — read
- `/gather` — write (role + button confirm); uses `candidates_json` from Discord config when set, otherwise live gather_once path when ADB available

## Mac always-on notes

Process is long-lived (`ks-discord`). Mac sleep disconnects the gateway; operator responsibility for sleep settings / launchd later (out of v1 code scope beyond a clear README note in the design).
