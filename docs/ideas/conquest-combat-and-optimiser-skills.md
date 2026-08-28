# Conquest combat % and optimiser skills

**Date:** 2026-08-09  
**Status:** Locked direction (idea-refine)  
**Backlog:** [optimiser-governor-skills-backlog.md](optimiser-governor-skills-backlog.md)

## Problem Statement

How might we score Conquest/Arena (and wire governor + leveled skills across every combat optimiser) using real Conquest skill semantics — Attack×coeff, Attack%, attack speed, AoE, enemy damage taken, heal/toughness — instead of folding skill coefficients into Hero/Escort Attack flats, without boiling the ocean into a full tick combat sim?

## Recommended Direction

Ship a **shared Conquest sim-lite layer** consumed by Arena and Conquest formation scorers, plus a **docs-tracked wiring program** that pushes governor troop Atk%/Def% and correct skill families into Bear, Swordland, Arena/Conquest, Gear XP, and (later) Molten Fort.

Conquest skill labels are not Expedition `SkillMod`. Public Mastery text is `dealing Attack × X damage` with ladders like `Damage Up: 160 → 224`. Those coefficients must drive skill DPS, while `Attack Up` / `Defense Up` / `Attack Speed Up` / `Heal Up` / `Enemy Damage Taken Up` stay in separate buckets. Expedition modes keep the troop kill formula and `effect_op` stacking; they must not reuse Conquest coeff math.

Hybrid ladders: seed known ultimates (and other well-documented skills) from Kingshot Mastery into the catalog; fall back to `level/5 × max_value` where no ladder exists. Governor bonuses reuse the existing `governor_troop_bonuses()` helper already used by Radiant Spire.

Success is **correct model first**, then validate that ranked lineups better match known Conquest stage clears and Arena outcomes.

## Key Assumptions to Validate

- [ ] Damage Up / AoE Damage Up values are percent coefficients (`Attack × X/100`), not flat Attack%. Spot-check Amadeus Combo Slash and Vivian Gilded Barrage against in-game tooltips.
- [ ] A single AoE target factor (e.g. front-row share or fixed 1.5–2.5) is good enough for ranking; we do not need per-skill hitbox geometry in MVP.
- [ ] Attack Speed Up can be treated as linear on cast/auto rate for ranking (`× (1 + AS/100)`).
- [ ] Score `SkillDPS × Toughness^α` with a small fixed α ranks formations similarly to live clears once ultimates use real ladders.
- [ ] Manual skill levels (1–5 UI) plus hybrid ladders beat OCR `current_bonus` for Conquest scoring (already true for expedition after skill-levels work).

## MVP Scope

**In (docs this pass; code in later stories):**

- Idea one-pager + umbrella backlog (this folder).
- Design spec for Conquest sim-lite and hybrid ladder schema.
- Design for governor + skills across all optimisers.
- Phased implementation plan with local story IDs.

**In (first coding waves — see backlog):**

- `conquest_combat` module + catalog `ladder` field + seed examples.
- Wire sim-lite into Arena + Conquest scorers; stop mapping `damage_up`/`aoe_damage_up` into Attack flats.
- Governor into Bear, Swordland, Arena/Conquest, Gear XP.
- Expedition skill hardening where Bear/joiner still gaps.
- Validation checklist against personal clears.

## Not Doing (and Why)

- **Full tick / Monte Carlo Conquest sim** — reserved for a later fidelity jump (Radiant #38 is the analogous track); sim-lite is the locked MVP.
- **New GitHub issues** — backlog lives in `docs/ideas/` and `docs/superpowers/`; existing #41–#47 are cross-links only.
- **Molten Fort combat engine in the first impl wave** — design stub only until governor inventory + shared helpers are proven in existing solvers.
- **Seeding every Mastery ladder in the first PR** — schema + known ultimates; linear fallback elsewhere.
- **Replacing Expedition SkillMod with Conquest math** — different modes, different formulas.
- **ADB scrape of Conquest skill ladders** — catalog + manual levels remain source of truth for scoring.

## Open Questions

- Exact α for toughness in the product score (calibrate after first ranking vs clears).
- Whether Escort Attack/Defense/Health still belong in formation score once skill DPS is primary, or become secondary weights only.
- Ultimate levels 6–10: document Mastery breakpoints in catalog notes; UI today caps editable levels at 1–5 — extend later if needed.

## Related specs

- [2026-08-09-conquest-combat-sim-lite-design.md](../superpowers/specs/2026-08-09-conquest-combat-sim-lite-design.md)
- [2026-08-09-governor-skills-all-optimisers-design.md](../superpowers/specs/2026-08-09-governor-skills-all-optimisers-design.md)
- [2026-08-09-governor-skills-all-optimisers.md](../superpowers/plans/2026-08-09-governor-skills-all-optimisers.md) (implementation plan)
