# Discord-auth multi-user KS UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add reusable Discord OAuth auth and per-user inventory tenancy so the heroes FastAPI UI can run safely on AWS.

**Architecture:** New `ks.auth` package handles OAuth, session cookies, and guild `ui_role` checks via the existing bot token. When auth is on, middleware binds `request.state.inventory` from `{users_root}/{discord_id}/`; auth-off keeps today’s single-dir `create_app` behavior.

**Tech Stack:** Python 3.12+, FastAPI/Starlette SessionMiddleware, httpx, existing GearStore/HeroStore/TroopStore, pytest + httpx TestClient.

## Global Constraints

- Work only in worktree `.worktrees/feature-discord-auth-multiuser-ui` on branch `feature/discord-auth-multiuser-ui`.
- Do not commit secrets; env vars only for tokens/secrets.
- Auth **off** by default; existing UI tests must keep passing without Discord.
- When auth **on**, never bind per-user stores on shared `app.state` for request handling (request-scoped only).
- Role gate uses exact role name match (same spirit as `ks.discord.auth.member_has_write_role`).
- Prefer small modules under `ks/auth/`; avoid bloating `app.py` beyond wiring.
- Install UI deps as needed: `pip install -e '.[ui,dev]'` from worktree (use repo `.venv` if present).
- Commit after each task with a focused message.

## File map

| Path | Role |
|------|------|
| `ks/auth/__init__.py` | Public exports |
| `ks/auth/config.py` | `AuthConfig` dataclass + loader |
| `ks/auth/discord_oauth.py` | Authorize URL, token exchange, fetch user |
| `ks/auth/gate.py` | Guild member + `ui_role` check via bot token |
| `ks/auth/session_user.py` | Session key helpers / `SessionUser` |
| `ks/auth/deps.py` | `require_user` |
| `ks/auth/routes.py` | `/auth/login`, `/callback`, `/logout` |
| `ks/auth/inventory.py` | `UserInventoryPaths` + `ensure_layout` |
| `ks/auth/middleware.py` | Protect routes + bind inventory |
| `config/auth.yaml` | Non-secret defaults (`ui_role`, optional guild_id placeholder) |
| `ks/heroes/ui/app.py` | Wire auth mode + request inventory |
| `ks/heroes/cli.py` | Flags/env for multi-user |
| `tests/test_auth_*.py` | Unit + isolation tests |
| `docs/superpowers/specs/2026-08-14-discord-auth-aws-notes.md` | Deploy notes (task 6) |

---

### Task 1: AUTH-01 — OAuth client + session user + `require_user`

**Files:**
- Create: `ks/auth/__init__.py`, `ks/auth/config.py`, `ks/auth/discord_oauth.py`, `ks/auth/session_user.py`, `ks/auth/deps.py`
- Create: `config/auth.yaml`
- Test: `tests/test_auth_oauth.py`, `tests/test_auth_deps.py`

**Interfaces:**
- Produces:
  - `AuthConfig(client_id, client_secret, session_secret, public_base_url, guild_id, ui_role, bot_token)`
  - `load_auth_config(path: Path | None = None) -> AuthConfig` (reads YAML + env; raises if required env missing when called)
  - `discord_authorize_url(cfg: AuthConfig, state: str) -> str`
  - `async exchange_code(cfg, code: str, http: httpx.AsyncClient) -> dict` → token payload
  - `async fetch_discord_user(access_token: str, http) -> SessionUser`
  - `SessionUser(id: str, username: str)`
  - `SESSION_USER_KEY = "ks_user"`
  - `require_user(request: Request) -> SessionUser` (sync FastAPI dep reading `request.session`)

- [ ] **Step 1: Write failing tests** for authorize URL shape, `SessionUser` round-trip helpers, and `require_user` 401 when session empty (use Starlette/FastAPI TestClient mini-app).

- [ ] **Step 2: Run tests — expect FAIL**

```bash
cd /Users/alexei/KS/.worktrees/feature-discord-auth-multiuser-ui
pytest tests/test_auth_oauth.py tests/test_auth_deps.py -v
```

- [ ] **Step 3: Implement minimal `ks.auth` modules + `config/auth.yaml`** (`ui_role: ks-ui`, `guild_id: null`). Env: `DISCORD_OAUTH_CLIENT_ID`, `DISCORD_OAUTH_CLIENT_SECRET`, `KS_SESSION_SECRET`, `DISCORD_BOT_TOKEN`, optional `KS_PUBLIC_BASE_URL`.

- [ ] **Step 4: Run tests — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add ks/auth config/auth.yaml tests/test_auth_oauth.py tests/test_auth_deps.py
git commit -m "$(cat <<'EOF'
feat(auth): add Discord OAuth helpers and require_user dependency

EOF
)"
```

---

### Task 2: AUTH-02 — Guild + `ui_role` gate

**Files:**
- Create: `ks/auth/gate.py`
- Test: `tests/test_auth_gate.py`
- Modify: `ks/auth/discord_oauth.py` or callback helper only if needed later (keep gate pure)

**Interfaces:**
- Consumes: `AuthConfig`, Discord user id string
- Produces: `async def user_has_ui_access(cfg: AuthConfig, discord_user_id: str, http: httpx.AsyncClient) -> bool`
  - `GET https://discord.com/api/v10/guilds/{guild_id}/members/{user_id}` with `Authorization: Bot {bot_token}`
  - Load guild roles if needed OR compare role IDs after fetching guild roles; simplest path: fetch member `roles` (ids) + `GET /guilds/{id}/roles`, match role **name** to `cfg.ui_role`
- Reuse exact name equality like `member_has_write_role`

- [ ] **Step 1: Write failing tests** with httpx mock transport / monkeypatched client responses for allow, missing role, 404 member.

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement `gate.py`**

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit** `feat(auth): gate UI access with Discord guild ui_role`

---

### Task 3: AUTH-03 — `UserInventoryPaths` + `ensure_layout`

**Files:**
- Create: `ks/auth/inventory.py`
- Test: `tests/test_auth_inventory.py`

**Interfaces:**
- Produces:
  - `@dataclass UserInventoryPaths` with `root`, `gear_dir`, `heroes_dir`, `troops_path`, `governor_dir`, `research_dir`
  - `paths_for(users_root: Path, discord_user_id: str) -> UserInventoryPaths`
  - `ensure_layout(paths: UserInventoryPaths, *, troops_seed: Path) -> None` — mkdir parents; if troops missing, copy seed

Layout (must match design):

```text
{users_root}/{discord_user_id}/gear/full-run
{users_root}/{discord_user_id}/heroes/full-run
{users_root}/{discord_user_id}/troops.yaml
{users_root}/{discord_user_id}/governor/full-run
{users_root}/{discord_user_id}/research/full-run
```

- [ ] **Step 1: Failing path + ensure tests** (tmp_path)

- [ ] **Step 2: Run — FAIL**

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run — PASS**

- [ ] **Step 5: Commit** `feat(auth): per-user inventory path layout`

---

### Task 4: AUTH-04 — Auth routes + protect middleware + `create_app` wiring (auth shell)

**Files:**
- Create: `ks/auth/routes.py`, `ks/auth/middleware.py`
- Create: `ks/heroes/ui/templates/login.html` (minimal)
- Modify: `ks/heroes/ui/app.py` — SessionMiddleware when auth on; include router; protect
- Modify: `ks/heroes/cli.py` — `--users-root`, `--auth discord|off` (or env `KS_AUTH_MODE`)
- Test: `tests/test_auth_routes.py`

**Interfaces:**
- Produces: `build_auth_router(cfg: AuthConfig) -> APIRouter`
- Callback: exchange code → fetch user → `user_has_ui_access` → set session or reject
- `install_auth(app, cfg, users_root: Path)` attaches middleware:
  - Allow without auth: `/auth/*`, `/static/*`
  - HTML routes: redirect to `/auth/login`
  - `/api/*`: 401 JSON `{"detail":"unauthorized"}`
- `create_app(..., auth_config: AuthConfig | None = None, users_root: Path | None = None)`
  - If `auth_config` is None: behavior unchanged (require gear_dir or heroes_dir)
  - If `auth_config` set: allow omitting gear/heroes dirs; set `app.state.auth_config`, `app.state.users_root`

**Note:** Full per-request store swap is Task 5. In Task 4, auth-on may still use a temporary empty shared root OR skip inventory pages until Task 5 — prefer: auth-on requires `users_root` and Task 4 only proves login session + 401/redirect; inventory pages can 503 until Task 5 if needed. Prefer completing enough that login works end-to-end with mocked Discord.

- [ ] **Step 1: Failing TestClient tests** — unauthenticated `/inventory/gear` redirects; `/api/troops` 401; callback with mocks sets cookie.

- [ ] **Step 2: Run — FAIL**

- [ ] **Step 3: Implement routes + middleware + wiring**

- [ ] **Step 4: Run auth route tests + a quick existing UI smoke if auth off**

```bash
pytest tests/test_auth_routes.py -v
pytest tests/test_heroes_ui_smoke.py -v 2>/dev/null || pytest tests/ -k "heroes_ui or create_app" -q --tb=no -x
```

- [ ] **Step 5: Commit** `feat(heroes-ui): Discord login routes and auth gate middleware`

---

### Task 5: AUTH-05 — Request-scoped multi-tenant stores

**Files:**
- Modify: `ks/auth/middleware.py` and/or new `ks/auth/request_inventory.py`
- Modify: `ks/heroes/ui/app.py` — `_require_gear` / `_require_heroes` take `Request`; resolve from `request.state.inventory` when auth on; fix icon serving for multi-user (route-based FileResponse under user dirs)
- Test: extend `tests/test_auth_routes.py` or `tests/test_auth_tenancy.py`

**Interfaces:**
- Produces: `build_inventory_bundle(paths: UserInventoryPaths) -> SimpleNamespace|dataclass` with stores
- Middleware (auth on + authenticated): `ensure_layout` → bind `request.state.inventory`
- `_require_gear(request)` / `_require_heroes(request)` use bundle
- Replace closed-over `gear_store` reads in handlers with request inventory (mechanical)
- Auth off: keep existing closures

- [ ] **Step 1: Failing test** — two sessions, user A PUT/PATCH something user B cannot see (minimal gear or troops write)

- [ ] **Step 2: Run — FAIL**

- [ ] **Step 3: Implement request-scoped binding + handler updates**

- [ ] **Step 4: Run tenancy + auth-off smoke**

- [ ] **Step 5: Commit** `feat(heroes-ui): request-scoped per-user inventory stores`

---

### Task 6: AUTH-06 — Isolation suite polish + AWS notes

**Files:**
- Create: `docs/superpowers/specs/2026-08-14-discord-auth-aws-notes.md`
- Modify: tests as needed; update idea backlog statuses to Done where accurate
- Ensure `docs/ideas/discord-auth-multiuser-backlog.md` checkboxes reflect reality

- [ ] **Step 1: Write AWS notes** (HTTPS, Discord Developer Portal redirect, env vars, create `ks-ui` role, assign to private channel members, ECS/EC2 sketch without over-engineering)

- [ ] **Step 2: Run full focused suite**

```bash
pytest tests/test_auth_oauth.py tests/test_auth_deps.py tests/test_auth_gate.py tests/test_auth_inventory.py tests/test_auth_routes.py tests/test_auth_tenancy.py -v
```

- [ ] **Step 3: Commit** `docs(auth): AWS Discord OAuth deploy notes and tenancy tests`

---

## Self-review checklist (controller)

Before dispatching Task 1: confirm no Cognito scope creep; role-not-channel is explicit; auth-off default preserved.
