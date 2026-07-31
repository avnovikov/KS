# Task completion checks

From repo root with venv active:

```bash
source .venv/bin/activate
pytest
```

Targeted:
```bash
pytest tests/test_<area>.py -v
```

No project-mandated formatter/linter/typechecker pins in `pyproject.toml` yet — run pytest before claiming done. For cartograph/device work, prefer relevant `test_cartograph_*` / `test_device_*` / `test_live_capture_*` suites over full suite only when scope is clearly narrow; still run full `pytest` before story close when practical.

Do not treat live BlueStacks runs as a substitute for unit tests.