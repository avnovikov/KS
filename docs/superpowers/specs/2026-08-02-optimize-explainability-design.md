# Optimize explainability (B + C)

## Goal
For each selected hero in Sword/Bear modes and Arena sides, show:

- **B — structured why:** role, catalog fits, slot/tag rationale (arena)
- **C — leave-one-out:** points/score lost if that hero is removed (and who replaces them)

## API shape (per hero)
```json
{
  "name": "Saul",
  "reason": "short summary string",
  "explain": {
    "role": "defense_widget",
    "fits_because": ["Satisfies defense widget requirement", "troop=archer"],
    "leave_one_out": {
      "baseline_points": 26000,
      "points_without": 21000,
      "marginal_points": 5000,
      "critical": false,
      "replacement_heroes": ["Marlin", "Howard", "Gordon"],
      "status": "Optimal"
    }
  }
}
```

Arena uses `baseline_score` / `score_without` / `marginal_score` and includes `slot`.

## UI
In the existing gear popup, under each hero name: fits_because bullets + “Removing costs ~X pts” (or “critical — no feasible lineup”).
