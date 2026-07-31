# Tech stack

- Language: Python ≥3.12
- Packaging: setuptools via `pyproject.toml`; local `.venv/`
- Core deps: PyYAML, adbutils, opencv-python-headless, numpy, pytesseract, discord.py, h3≥4
- Optional `stitch`: stitching + opencv-contrib-python-headless (<4.12)
- Dev: pytest≥8 (`[project.optional-dependencies] dev`)
- Device: ADB to BlueStacks (default serial `127.0.0.1:5555` in params)
- Cartograph persistence: SQLite + H3 indexing; HTML map render under `artifacts/` (gitignored)
- OCR: Tesseract via pytesseract
- Serena language server: `python`