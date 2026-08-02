# Optimize explainability (B + C)

## Goal
For each selected hero in Sword/Bear modes and Arena sides, show:

- **B — structured why:** role, catalog fits, slot/tag rationale (arena)
- **C — leave-one-out:** points/score lost if that hero is removed (and who replaces them)

## API shapes

**Events (Sword/Bear)** — on each `heroes[]` row:
```json
{
  "name": "Saul",
  "reason": "role=defense_widget, troop=archer, widget=defense",
  "explain": {
    "role": "defense_widget",
    "fits_because": ["Satisfies required defense widget for garrison", "Covers archers slot (one-per-troop formation)"],
    "leave_one_out": {
      "baseline_points": 26000,
      "points_without": 21000,
      "marginal_points": 5000,
      "critical": false,
      "alternate_lineup": ["Marlin", "Howard", "Gordon"],
      "status": "Optimal"
    }
  }
}
```

**Arena** — top-level `explanations[name]` (UI also accepts `heroes[].explain`):
`{slot, role, fits_because, leave_one_out, summary}` with LOO keys
`baseline_score` / `score_without` / `marginal_score` and optional `replacement_formation`.

`alternate_lineup` is the **full re-solved lineup**, not only substitutes.
`critical` is true only when re-solve status is `Infeasible`; other non-Optimal
statuses set `inconclusive: true`.

## UI
Gear popup: fits_because + “Removing costs … · alternate lineup: …” (or critical / inconclusive).
Section Regenerate always recomputes the full bundle and refreshes all panels.
