# Arena / Conquest front-survival opponent models

**Date:** 2026-08-03  
**Branch / worktree:** `feature/conquest-formation-optimizer`  
**Status:** Spec approved for v1; first Conquest run in scope

## Goal

Improve Arena and Conquest recommendations by modelling **front-row collapse as defense degradation**: if the front cannot hold, backline contribution is scaled down. Opponent pressure comes from **concrete self-play foes** built from **our scraped heroes, gear, and power** — not catalog ghosts and not a bare `×1.2` on our ATK flats.

## Problem

Current ILP maximizes `base_score × placement_mult` and (for Arena attack) claims gear **B2-first**. That can crown a strong backliner (e.g. Jabel + mythic) while the infantry front is undergeared. In Conquest/Arena, when the front dies, the backline is focused next and the fight collapses — community and official targeting both describe this cascade. Our solver did not encode it.

## Confirmed decisions

| Topic | Decision |
|-------|----------|
| Roster for foes | **Our** `heroes.json` only |
| Gear for foes | **Our** `gear.json`; each side assigns from a **cloned** pool (attack/defense presets may share heroes in-game) |
| Points | Scraped power / stars / Conquest stats — sanitize absurd OCR power |
| Primary foe | **Naive max-power**: top 5 by power; **infantry fill F1/F2 first**; rest by power; gear front-first |
| Extra foes (sensitivity) | **Troop-balanced naive**; **current heuristic** (today’s Conquest/Arena defense solver) |
| Pressure \(O_E\) | Foe’s **heuristic offense score** (same units as current formation score terms), not raw Hero Attack sum |
| Toughness \(\tau\) | \(\mathrm{HeroHP} \times \mathrm{HeroDEF} \times (1+g)\) from Conquest scrapes + health-slot gear fractions |
| Degradation | \(s=\tau_F/(\tau_F+O_E)\), \(\tau_{\mathrm{eff}}=s\tau_F+(1-s)\tau_B\); scale backline utility by a factor derived from \(s\) / \(\tau_{\mathrm{eff}}\) |
| Gear claim (our attack / Conquest) | Prefer **F1, F2** before B2 (already true for Conquest order; Arena attack must change) |
| Full tick sim | **Out of scope** for v1 |

## Math (v1)

Per hero:

\[
\tau_h = \max(1,\mathrm{HP}_h) \cdot \max(1,\mathrm{DEF}_h) \cdot (1 + g_h)
\]

\(g_h\) = sum of expedition health-stat fractions for chest/gloves assigned to that hero (0 if none / unknown rarity). Escort HP OCR is **not** trusted when clearly truncated (values \(\lt 100\) while raw text suggests thousands); use Hero HP/DEF only in v1.

Formation:

\[
\tau_F = \tau_{F1}+\tau_{F2},\quad \tau_B = \tau_{B1}+\tau_{B2}+\tau_{B3}
\]

Foe offense \(O_E\): sum of that foe’s per-slot heuristic contributions (existing `hero_base_score × placement_mult`), i.e. the current setup’s attack-shaped score for their lineup.

**Unit bridge:** \(\tau\) is HP×DEF (~1e6–1e8) while \(O_E\) is heuristic score (~1e2–1e3). Convert with a roster scale \(c = \mathrm{median}(\tau_h)/\mathrm{median}(U_h)\):

\[
O_\tau = c \cdot O_E
\]

Survival:

\[
s = \frac{\tau_F}{\tau_F + O_\tau} \in (0,1)
\qquad
\tau_{\mathrm{eff}} = s\,\tau_F + (1-s)\,\tau_B
\qquad
\delta = s
\]

Effective utility for **our** lineup against foe \(E\):

\[
U_{\mathrm{eff}}(E) = U_{\mathrm{front}} + \delta \cdot U_{\mathrm{back}} + \lambda \ln(1+\tau_{\mathrm{eff}})
\]

- \(U_{\mathrm{front}}\), \(U_{\mathrm{back}}\): existing heuristic slot scores split by F* vs B*  
- \(\lambda\): YAML knob (default `5.0`)  
- **Primary decision score** = \(U_{\mathrm{eff}}\) vs naive max-power foe  
- Sensitivity table: also report vs troop-balanced and heuristic foes  

Power sanitize: if `power > 2_000_000` or `power > 20 × median(roster power)`, replace with median of same-rarity peers (or stars-scaled fallback) before naive top-5 selection.

## Architecture

```
opponent_models.py     # build NaiveMaxPower / TroopBalanced / HeuristicFoe lineups + gear
front_survival.py      # tau, s, tau_eff, delta, U_eff
combat_formation.py    # unchanged ILP core (placement)
conquest.py / arena.py # after ILP: gear F-first; attach survival vs foes; optional local F/B swap if U_eff rises
```

### Opponent builders

1. **`naive_max_power`**  
   Sort heroes by sanitized power desc → take 5. Place up to 2 infantry in F1/F2 (highest power infantry first); fill remaining fronts then backs by power. Gear: `assign_exclusive_sets` with priority `F1,F2,B2,B1,B3`.

2. **`troop_balanced_naive`**  
   Ensure F1/F2 are the two best infantry if ≥2 infantry exist; otherwise best toughness proxies. Back: highest power among remaining. Same gear order.

3. **`heuristic_foe`**  
   Run existing `optimize_conquest` / `optimize_arena_defense` on the same roster (no survival loop) to get formation + gear; use as foe.

### Integration (Conquest first)

1. Run existing `optimize_conquest` ILP (placement).  
2. Assign our gear with Conquest order `F1,F2,B2,B1,B3`.  
3. Build foes (1–3) from same heroes/gear clones.  
4. Compute \(U_{\mathrm{eff}}\) vs each; set `result.score` to primary \(U_{\mathrm{eff}}\) (or keep ILP score and add `survival` block — **prefer add `survival` block and `score_eff`** so CLI can show both).  
5. Optional v1.1: one local-improvement pass swapping each back hero into a front slot if primary \(U_{\mathrm{eff}}\) increases.

Arena attack follows the same pattern in a follow-up; Arena attack gear order becomes `F1,F2,B2,B1,B3`.

## Config

Extend `config/conquest_roles.yaml` (and later `arena_roles.yaml`):

```yaml
survival:
  enabled: true
  primary_foe: naive_max_power
  foes: [naive_max_power, troop_balanced_naive, heuristic_foe]
  lambda_tau: 5.0
  power_sanitize_max: 2000000
  power_sanitize_median_factor: 20
```

## CLI / output

`ks-heroes conquest` writes JSON including:

```json
"survival": {
  "our": {"formation": {}, "tau_F": 0, "tau_B": 0, "U_front": 0, "U_back": 0},
  "foes": {
    "naive_max_power": {
      "formation": {}, "O": 0, "s": 0, "tau_eff": 0, "delta": 0, "score_eff": 0
    }
  },
  "primary_foe": "naive_max_power",
  "score_eff": 0
}
```

Print a short foe comparison table on stdout.

## Testing

- Unit: \(\tau\), \(s\), \(\delta\) with fixed HP/DEF; infantry-first naive placement  
- Unit: power sanitize drops Helga-like 9e6 outliers from top-5  
- Integration: fixture roster where naked back carry + weak front loses `score_eff` to geared Howard front vs same foe  
- Existing Arena/Conquest ILP tests stay green  

## Out of scope

- Full skill cooldown / energy sim  
- Catalog-generated whale opponents  
- Expedition troop-row cascade (separate layer; same math family later)  
- Changing Bear / Swordland recommend  

## Success criteria

1. Spec committed on this branch.  
2. First Conquest run on live `full-run` heroes+gear emits formation, gear, and survival table vs ≥2 foe models.  
3. Primary foe uses **our** heroes/gear/power with infantry-first naive placement.  
4. Geared infantry front improves `score_eff` vs feeding mythic to backline alone (demonstrated on the live run or a fixture).
