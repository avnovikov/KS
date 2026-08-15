# Bear Trap — show first-expedition SkillMod in UI

**Date:** 2026-08-15  
**Branch:** `feature/beartrap-skillmod-ui`  
**Status:** Approved (display)

## Goal

On Bear Trap (and Swordland where useful) lineup boards, show the **first-expedition Attack/Lethality DamageUp SkillMod** implied by the three chosen heroes — so Chenko-style lethality is visible, not only Attack/Defense columns.

## Payload

Each mode row gains:

```json
"skillmod_detail": {
  "joiner_only": true,
  "damage_up": 1.25,
  "by_op": {"101": 25.0, "102": 0.0},
  "by_hero": [
    {"name": "Chenko", "kind": "lethality_up", "effect_op": 101, "pct": 25.0}
  ]
}
```

Computed via `skillmod` helpers from catalog effects (`applies_to=expedition`, Attack/Lethality kinds; joiner filters `first_expedition`).

## UI

Below troops/points on Bear Trap boards: a short strip  
`SkillMod DamageUp ×1.25 · Chenko lethality_up +25% (op 101) · …`

## Out of scope (v1)

- Replacing `BeartrapBuffs.joiner_skillmod` in the damage extract with this value (follow-on)
- Editing skill levels in this strip
