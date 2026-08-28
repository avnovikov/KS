# Discord-auth multi-user KS UI — Design

**Date:** 2026-08-14  
**Status:** Approved for implementation (idea-refine lock)  
**Idea / backlog:** `docs/ideas/discord-auth-multiuser-ui.md`, `docs/ideas/discord-auth-multiuser-backlog.md`

## Objective

Protect the FastAPI heroes/optimiser UI for AWS and give each Discord-authenticated user an isolated inventory tree.

## Architecture

```text
Browser
  │  Discord OAuth (identify)
  ▼
ks.auth (FastAPI routes + SessionMiddleware)
  │  bot token: guild member + ui_role
  ▼
session cookie { discord_user_id, username }
  │
  ▼
request.state.inventory  ← UserInventoryPaths + stores
  │
  ▼
existing GearStore / HeroStore / TroopStore / Governor / Research
```

### Auth-off (local)

Today’s `create_app(gear_dir=..., heroes_dir=...)` — single shared stores on `app.state`. No OAuth.

### Auth-on (AWS / multi-user)

- `users_root` required (default `data/users`)
- No startup-bound user stores
- After login, each request resolves `{users_root}/{discord_id}/...`

### Layout per user

```text
{users_root}/{discord_id}/
  gear/full-run/     # GearStore root (icons under icons/)
  heroes/full-run/   # HeroStore root
  troops.yaml
  governor/full-run/
  research/full-run/
```

### Role ≈ channel access

Configure Discord so only the private channel’s members have `ui_role` (e.g. `ks-ui`). App checks role name exactly (same contract as `member_has_write_role`).

## Config

Extend Discord-related settings (new section or `config/auth.yaml`):

| Key | Source | Purpose |
|-----|--------|---------|
| `DISCORD_OAUTH_CLIENT_ID` | env | OAuth app |
| `DISCORD_OAUTH_CLIENT_SECRET` | env | OAuth app |
| `KS_SESSION_SECRET` | env | Starlette session signing |
| `DISCORD_BOT_TOKEN` | env | Member/role lookup (existing) |
| `guild_id` | YAML | Required when auth on |
| `ui_role` | YAML | Default `ks-ui` |
| `public_base_url` | env/YAML | e.g. `https://ks.example.com` |

Redirect URI: `{public_base_url}/auth/callback`

## Components

| Unit | Responsibility |
|------|----------------|
| `ks.auth.config` | Load auth settings; fail fast when auth on and incomplete |
| `ks.auth.discord_oauth` | Authorize URL, code exchange, `@me` |
| `ks.auth.gate` | Bot-token guild member + role check |
| `ks.auth.session_user` | Typed session payload helpers |
| `ks.auth.deps` | `require_user`, optional user |
| `ks.auth.routes` | login / callback / logout router |
| `ks.auth.inventory` | `UserInventoryPaths` + `ensure_layout` |
| Heroes UI wiring | Middleware + request inventory + CLI |

## Error handling

- Missing auth env when auth on → fail at startup
- OAuth error / denied role → no session; redirect login with message
- Unauthenticated HTML → 302 `/auth/login`
- Unauthenticated `/api/*` → 401 JSON
- Unknown path under another user’s tree → never exposed (resolver only uses session id)

## Testing

- Mock Discord token + `@me` + guild member HTTP with httpx mock / respx-style manual mocks
- TestClient cookie sessions for two users writing distinct gear JSON
- Auth-off smoke: existing UI tests still pass

## Boundaries

**Always:** request-scoped stores when auth on; never put per-user stores on process-global `app.state` for concurrent use.

**Ask first:** changing OAuth to Cognito; shared alliance inventory mode; committing real Discord secrets.
