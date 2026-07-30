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

---

## 2. Map search — resource-tile search panel

**Goal:** crop of the search/filter panel header when searching for resource tiles on the world map.

1. From city view, tap the world-map icon.
2. Tap the search/magnifier → select a resource type (e.g. **Bread**).
3. The resource-search panel opens.
4. Screencap → crop the panel header or search icon.
5. Save as: `assets/templates/map_search_panel.png`

---

## 3. Tile info — resource amount + march time

**Goal:** crop of the tile-info popup showing the resource amount and expected gather time.

1. On the world map, tap a resource tile to open its info popup.
2. Verify the popup shows: resource type, amount, normal march time.
3. Screencap → crop the popup content area (exclude close button).
4. Save as: `assets/templates/tile_info_popup.png`

---

## 4. Gather confirm button

**Goal:** crop of the green "Gather" confirm button in the march confirmation screen.

1. From a tile info popup, tap "Gather" to open the march-confirm screen.
2. Screencap → crop just the confirm button (the green/prominent action button).
3. Save as: `assets/templates/gather_confirm_btn.png`

---

## 5. Confirm all four PNGs exist

Expected files under `assets/templates/`:

| File | Screen |
|------|--------|
| `march_slot_free.png` | City view, free march slot |
| `map_search_panel.png` | World map resource search panel |
| `tile_info_popup.png` | Tile info popup |
| `gather_confirm_btn.png` | Gather confirm button |

**Do not edit `config/params.yaml` yet.** `VisionConfig` currently only accepts
`match_threshold`; adding a `vision.templates` block will break `load_config`.
YAML wiring for template paths is added in **Task 9**.

---

## 6. Verify crops

Open each PNG and confirm the crop looks right — tight framing, no partial pixels,
recognisable UI element at your emulator resolution.

Optional: if you still have the screencap from the same step, check it matches
with `match_template`:

```bash
source .venv/bin/activate
python - <<'EOF'
import cv2
from pathlib import Path
from ks.vision.templates import match_template

hay = cv2.imread("artifacts/smoke.png")
assert hay is not None, "Run adb_smoke.py first"

needle_path = Path("assets/templates/march_slot_free.png")  # repeat per template
needle = cv2.imread(str(needle_path))
assert needle is not None, f"Missing {needle_path}"

m = match_template(hay, needle, threshold=0.85)
print(f"{needle_path.name}: score={m.score if m else 'no match'}")
EOF
```

Re-run `adb_smoke.py` on the matching screen before each optional check.

---

## Notes

- Keep crops tight — avoid surrounding UI chrome that changes between game updates.
- Use PNG lossless; do not crop partial pixels (round to even dimensions).
- If a template fails matching (threshold < `vision.match_threshold`), re-capture at the same
  emulator resolution used during normal operation.
- Do **not** commit screenshots that reveal your city name, alliance, or account
  identity unless you are comfortable with that.
