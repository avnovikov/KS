# Conquest / Arena validation log

<p style="color:#c62828;font-weight:700;font-size:1.15rem;border:2px solid #c62828;padding:0.75rem 1rem;border-radius:6px;background:#ffebee;">
⚠ PLEASE VALIDATE AFTER ANOTHER UPDATE — this session has no independent clear to compare yet; wait for a new Conquest clear (or roster/gear/governor change) before marking OG-09 Pass/Fail.
</p>

**Date started:** 2026-08-09  
**Related:** [conquest-combat-and-optimiser-skills.md](conquest-combat-and-optimiser-skills.md), sim-lite design, OG-09  
**Mode focus:** Conquest stages (Arena deferred)
**OG-09 status:** Blocked — awaiting a later clear that can diverge from (or confirm) the optimiser pick below.

## How to read a Conquest row

Optimiser returns one 5-hero formation (2 front + 3 back). Compare that to the lineup you actually cleared a stage with. **Pass** if ≥3 of your clear heroes appear in the recommended 5 (or you would have cleared with the recommended set). Note α / AoE only if rankings look clearly wrong.

Default sim-lite knobs (unchanged this session): see `2026-08-09-conquest-combat-sim-lite-design.md` (α and `aoe_targets`).

## Sessions

| Date | Mode | Known result (your clear) | Top after (optimiser) | Pass? | Notes |
|------|------|---------------------------|------------------------|-------|-------|
| 2026-08-09 | Conquest | Deferred — same/no independent clear yet | F1 Chenko, F2 Howard · B1 Diana, B2 Jabel, B3 Saul · score≈712 | Blocked | Re-run after next roster/clear update. Before n/a. Individual rank: Jabel ≫ Diana > Helga > Saul > Yeonwoo. |

### Formation map (2026-08-09 optimiser)

```text
  Front:  Chenko (F1)     Howard (F2)
  Back:   Diana (B1)      Jabel (B2)      Saul (B3)
```

### Calibration backlog

When a row fails, note whether sim-lite α or AoE target factor should change, then amend `docs/superpowers/specs/2026-08-09-conquest-combat-sim-lite-design.md` in the same change set.
