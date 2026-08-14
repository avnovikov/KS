# Task 2 Report — AUTH-02 Guild + `ui_role` gate

## Summary

Implemented `ks/auth/gate.py` with `user_has_ui_access(cfg, discord_user_id, http)` so the UI can check Discord guild access through the bot token.

## Behavior

- Fetches the Discord guild member with `Authorization: Bot {bot_token}`.
- Fetches guild roles from Discord.
- Grants access only when the member has a role whose **name matches `cfg.ui_role` exactly** and the member actually holds that role id.
- Returns `False` for 404 member responses, malformed payloads, and other HTTP/API failures that should not grant access.

## Tests

- Added `tests/test_auth_gate.py`.
- Covered:
  - exact-name allow path
  - case-sensitive / exact-name mismatch denial
  - 404 member denial
  - roles lookup failure denial

## Verification

```bash
source /Users/alexei/KS/.venv/bin/activate && pytest tests/test_auth_oauth.py tests/test_auth_deps.py tests/test_auth_gate.py -v
```

Result: `13 passed`

