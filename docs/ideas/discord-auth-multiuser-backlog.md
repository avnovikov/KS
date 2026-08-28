# Discord-auth multi-user UI — umbrella backlog

**Date:** 2026-08-14  
**Status:** Complete (AUTH-01..06 implemented and verified)  
**Idea:** [discord-auth-multiuser-ui.md](discord-auth-multiuser-ui.md)  
**Design:** [2026-08-14-discord-auth-multiuser-ui-design.md](../superpowers/specs/2026-08-14-discord-auth-multiuser-ui-design.md)  
**Plan:** [2026-08-14-discord-auth-multiuser-ui.md](../superpowers/plans/2026-08-14-discord-auth-multiuser-ui.md)

## Locked product choices

| Topic | Choice |
|-------|--------|
| Users | Few alliance members (≈2–10) |
| Inventory | Per Discord user id under `data/users/<id>/` |
| Identity | Discord OAuth `identify` |
| Authorization | Guild member + `ui_role` via bot token (role encodes private channel) |
| Local UI | Auth off; explicit `--gear` / `--heroes` paths |
| Backlog home | `docs/ideas/` + `docs/superpowers/` only |

## Dependency order

```text
AUTH-01 (OAuth + session + require_user)
  ├─► AUTH-02 (guild + ui_role gate)
  └─► AUTH-03 (per-user data root resolver)
        └─► AUTH-04 (wire FastAPI login/logout + protect routes)
              └─► AUTH-05 (request-scoped multi-tenant stores + icons)
                    └─► AUTH-06 (isolation tests + AWS deploy notes)
```

## Story board

| ID | Title | Status | Depends |
|----|-------|--------|---------|
| AUTH-01 | `ks.auth` Discord OAuth + session + `require_user` | Done | — |
| AUTH-02 | Guild + `ui_role` allow gate (bot token) | Done | AUTH-01 |
| AUTH-03 | Per-user data root resolver (`UserInventoryPaths`) | Done | AUTH-01 |
| AUTH-04 | Login/logout UX + protect HTML + `/api/*` | Done | AUTH-01, AUTH-02 |
| AUTH-05 | Request-scoped store binding in heroes UI | Done | AUTH-03, AUTH-04 |
| AUTH-06 | Isolation tests + AWS OAuth/HTTPS notes | Done | AUTH-05 |

---

## AUTH-01 — `ks.auth` OAuth + session + `require_user`

**Goal:** Reusable auth package independent of heroes UI.

**Acceptance:**

- [x] `AuthConfig` from env/YAML: client id/secret, session secret, public base URL, guild id, `ui_role`
- [x] Discord authorize URL + code exchange + fetch `/users/@me`
- [x] Signed session cookie stores `discord_user_id` + `username`
- [x] FastAPI `require_user` dependency raises 401 when missing
- [x] Unit tests with httpx mocked Discord endpoints

---

## AUTH-02 — Guild + `ui_role` gate

**Goal:** After OAuth identity, allow only guild members with `ui_role`.

**Acceptance:**

- [x] Fetch guild member via bot token (`DISCORD_BOT_TOKEN`)
- [x] Role name match reuses spirit of `ks.discord.auth.member_has_write_role` (exact name)
- [x] Denied users get clear 403 / login flash — no session cookie
- [x] Tests: allow with role, deny without, deny non-member

---

## AUTH-03 — Per-user data root

**Goal:** Deterministic paths per Discord user id; create empty inventory dirs on first use.

**Acceptance:**

- [x] `UserInventoryPaths` under `{users_root}/{discord_id}/` with gear/heroes/troops/governor/research
- [x] `ensure_layout()` creates dirs + seeds troops from `config/troops.yaml` if missing
- [x] Pure path tests; no FastAPI required

---

## AUTH-04 — Wire UI auth

**Goal:** Heroes UI can run with Discord auth enabled.

**Acceptance:**

- [x] Routes: `/auth/login`, `/auth/callback`, `/auth/logout`
- [x] Middleware or dependency: unauthenticated → redirect HTML to login, 401 JSON for `/api/*`
- [x] Public: `/auth/*`, `/static/*`, health if any
- [x] `create_app(..., auth_config=..., users_root=...)` and CLI flags / env for multi-user mode
- [x] Local default remains auth off

---

## AUTH-05 — Request-scoped multi-tenant stores

**Goal:** Concurrent users never share `GearStore` / `HeroStore` instances via `app.state`.

**Acceptance:**

- [x] Middleware binds `request.state.inventory` from session user
- [x] `_require_gear` / `_require_heroes` (and troops/governor/research) read request inventory
- [x] Icon bytes served from the current user’s dirs (no single global StaticFiles mount for multi-user)
- [x] Auth-off mode unchanged (startup-bound stores)

---

## AUTH-06 — Isolation tests + AWS notes

**Goal:** Prove tenancy and document deploy.

**Acceptance:**

- [x] Two fake sessions cannot read/write each other’s gear/heroes via TestClient
- [x] Short AWS notes: HTTPS URL, Discord OAuth redirect, secrets (client secret, session secret, bot token), role setup for private channel
