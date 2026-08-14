# Discord-auth multi-user KS UI — AWS notes

**Date:** 2026-08-14  
**Status:** Ready for deployment notes

## Goal

Run the heroes UI behind HTTPS with Discord OAuth and per-user inventories, without storing secrets in git.

## Public URL and redirect

- Use a public HTTPS base URL, for example `https://ks.example.com`
- Discord OAuth redirect URI must be:

```text
{public_base_url}/auth/callback
```

- Register that exact callback in the Discord Developer Portal

## Required environment variables

Set these in the runtime environment or secret store:

- `DISCORD_OAUTH_CLIENT_ID`
- `DISCORD_OAUTH_CLIENT_SECRET`
- `KS_SESSION_SECRET`
- `DISCORD_BOT_TOKEN`
- `KS_PUBLIC_BASE_URL`
- `KS_AUTH_MODE`
- Optional: `KS_USERS_ROOT`

Suggested values:

- `KS_AUTH_MODE=discord`
- `KS_USERS_ROOT=data/users`

## Discord role setup

- Create a Discord role named `ks-ui`
- If the deployment uses a different role name, set `ui_role` in auth config to match
- Assign that role to the private-channel members who should be allowed into the UI
- Set `guild_id` in config so the bot token can verify guild membership

## Runtime sketch

Start the UI in auth mode with the per-user root enabled:

```bash
ks-heroes ui --auth discord --users-root data/users
```

In auth mode:

- gear/heroes/governor/research data are resolved per Discord user id
- the app does not need pre-existing shared gear/heroes directories
- the bot token is used only for guild member and role checks

## Deployment shape

A simple AWS setup is enough:

- Run the app behind a reverse proxy or load balancer that terminates HTTPS
- Inject all secrets through AWS secret management or task environment variables
- Keep `data/users` on durable storage if the instance is meant to persist user inventories
- Do not commit secret values or session keys to the repository

## Secrets policy

- Discord client secret, session secret, and bot token stay out of git
- Use env vars or AWS secret storage only
- The repo should only contain non-secret defaults such as `ui_role`

