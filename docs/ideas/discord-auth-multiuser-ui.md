# Discord-auth multi-user KS UI

**Date:** 2026-08-14  
**Status:** Locked direction (idea-refine)  
**Backlog:** [discord-auth-multiuser-backlog.md](discord-auth-multiuser-backlog.md)  
**Design:** [2026-08-14-discord-auth-multiuser-ui-design.md](../superpowers/specs/2026-08-14-discord-auth-multiuser-ui-design.md)  
**Plan:** [2026-08-14-discord-auth-multiuser-ui.md](../superpowers/plans/2026-08-14-discord-auth-multiuser-ui.md)

## Problem Statement

How might we let a few alliance members each manage **their own** gear/heroes/troops inventory on an AWS-hosted KS optimiser UI, gated by Discord (guild + role that encodes private-channel access), without building a full identity platform?

## Recommended Direction

Ship a shared **`ks.auth`** layer for FastAPI: Discord OAuth (`identify`) → verify guild membership and a configured UI role via the existing **bot token** (reuse `DISCORD_BOT_TOKEN` + guild settings) → signed session cookie with Discord user id + display name.

Inventories are **tenant-scoped** under `data/users/<discord_user_id>/` (gear, heroes, troops, governor, research as applicable). Local `ks-heroes ui` keeps today’s explicit `--gear` / `--heroes` paths with auth **off** by default. AWS / multi-user mode enables Discord auth and resolves stores from the session user (request-scoped — never mutate shared `app.state` stores per request).

**Channel gate (practical encoding):** Discord OAuth cannot cheaply prove “can view channel X.” Assign a dedicated Discord role (e.g. `ks-ui`) to members of the private channel; the app checks that role name (same pattern as `ks.discord.auth.member_has_write_role`).

## Key Assumptions to Validate

- [ ] Bot token can read guild members for role checks (`Guild Members` intent / REST member fetch)
- [ ] 2–10 users is the steady state
- [ ] Empty personal inventory on first login is OK
- [ ] One HTTPS origin on AWS for OAuth redirect is enough for v1

## MVP Scope

**In**

- `ks.auth`: OAuth routes, session, `require_user`, role gate
- Heroes UI: auth on/off; when on, per-user data roots for inventory + APIs
- Config: OAuth client id/secret, session secret, guild id, `ui_role`, public base URL
- Login / logout; unauthenticated HTML/API → login or 401
- Tests: gate allow/deny; two-user store isolation

**Out (v1)**

- Cognito / ALB OIDC
- Bot magic-link login
- Shared alliance inventory
- Edit audit log
- Multi-guild / public signup
- True channel-permission API checks (role stands in)

## Not Doing (and Why)

- Shared-secret-only site lock — no per-user inventory  
- Full Cognito IdP — duplicates Discord as source of truth  
- Bot magic-links as primary login — worse daily UX  
- Cloning one inventory to every user — privacy/confusion  

## Open Questions (resolved)

| Topic | Choice |
|-------|--------|
| Inventory | **A** — per Discord user tree |
| Gate | **Role** (encodes private-channel access) |
| Backlog home | **Docs only** |
| Implementation | Subagent-driven on feature branch |
