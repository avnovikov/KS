# Suggested commands

```bash
source .venv/bin/activate
pip install -e '.[dev]'
# optional stitch extras:
pip install -e '.[dev,stitch]'

pytest
pytest tests/test_cartograph_pipeline.py -v

ks --help
ks-cartograph --help
ks-discord --help

# ADB / emulator helpers
scripts/start_emulator.sh
scripts/bluestacks_connect.py
scripts/adb_smoke.py
```

Params live in `config/params.yaml`. Keep `dry_run: true` unless intentionally executing live taps.

Serena memory integrity (from project root):
```bash
/Users/alexei/Library/Python/3.13/bin/serena memories check
```