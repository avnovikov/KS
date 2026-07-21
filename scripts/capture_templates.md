# Template Capture Checklist

Manual steps to capture the UI crop templates required by the vision layer.
Run once after the emulator and Kingshot are installed and working.

## Prerequisites

- ADB smoke passes: `python scripts/adb_smoke.py` exits 0 and writes `artifacts/smoke.png`.
- Kingshot is installed and launched inside the emulator.
- `.venv` is activated: `source .venv/bin/activate`

---

## 1. City view — free-march slot indicator

**Goal:** crop showing the march-slot button in the city view (used to detect idle slots).

1. Open Kingshot; navigate to the main city view.
2. Confirm at least one march slot shows as free (the slot icon is bright / unoccupied).
3. Take a screencap: `python scripts/adb_smoke.py` (re-runs and overwrites `artifacts/smoke.png`).
4. Crop the march-slot UI region and save as:
   `assets/templates/march_slot_free.png`
5. Record the bounding box (x, y, w, h) in `config/params.yaml` under
   `vision.templates.march_slot_free`.

---

## 2. Map search — resource-tile search panel

**Goal:** crop of the search/filter panel header when searching for resource tiles on the world map.

1. From city view, tap the world-map icon.
2. Tap the search/magnifier → select a resource type (e.g. **Bread**).
3. The resource-search panel opens.
4. Screencap → crop the panel header or search icon.
5. Save as: `assets/templates/map_search_panel.png`
6. Record bbox in `config/params.yaml` → `vision.templates.map_search_panel`.

---

## 3. Tile info — resource amount + march time

**Goal:** crop of the tile-info popup showing the resource amount and expected gather time.

1. On the world map, tap a resource tile to open its info popup.
2. Verify the popup shows: resource type, amount, normal march time.
3. Screencap → crop the popup content area (exclude close button).
4. Save as: `assets/templates/tile_info_popup.png`
5. Record bbox in `config/params.yaml` → `vision.templates.tile_info_popup`.

---

## 4. Gather confirm button

**Goal:** crop of the green "Gather" confirm button in the march confirmation screen.

1. From a tile info popup, tap "Gather" to open the march-confirm screen.
2. Screencap → crop just the confirm button (the green/prominent action button).
3. Save as: `assets/templates/gather_confirm_btn.png`
4. Record bbox in `config/params.yaml` → `vision.templates.gather_confirm_btn`.

---

## 5. Update params.yaml

Add / update the `vision.templates` block in `config/params.yaml`:

```yaml
vision:
  match_threshold: 0.85
  templates:
    march_slot_free: assets/templates/march_slot_free.png
    map_search_panel: assets/templates/map_search_panel.png
    tile_info_popup:  assets/templates/tile_info_popup.png
    gather_confirm_btn: assets/templates/gather_confirm_btn.png
```

---

## 6. Verify templates load

```bash
source .venv/bin/activate
python - <<'EOF'
from ks.vision.templates import TemplateLibrary
import yaml, pathlib
p = yaml.safe_load(pathlib.Path("config/params.yaml").read_text())
lib = TemplateLibrary(p["vision"]["templates"])
print("Loaded templates:", list(lib.templates))
EOF
```

All four template names should appear in the output.

---

## Notes

- Keep crops tight — avoid surrounding UI chrome that changes between game updates.
- Use PNG lossless; do not crop partial pixels (round to even dimensions).
- If a template fails matching (threshold < `match_threshold`), re-capture at the same
  emulator resolution used during normal operation.
- Do **not** commit screenshots that reveal your city name, alliance, or account
  identity unless you are comfortable with that.
