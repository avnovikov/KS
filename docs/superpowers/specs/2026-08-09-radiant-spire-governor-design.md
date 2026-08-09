# Radiant Spire + Governor Gear — Design

**Date:** 2026-08-09  
**Branch / worktree:** `feature/radiant-spire-governor`  
**Status:** Draft for review  

## Goal

Ship a **thin vertical slice**:

1. **Manual governor gear inventory** — 6 slots, upgrade-with-buttons, dual persistence (JSON + SQLite).
2. **Radiant Spire optimiser** — two marches (schema ready for three), each with exclusive heroes and its own troop ratio, scoring with a **provisional strength proxy**.
3. Document **v1.1** (same product track): stage enemy stubs + Monte Carlo / round sim, once proxy is live.

## Decisions (locked)

| Topic | Choice |
|---|---|
| Scope shape | Vertical slice: inventory + optimiser together |
| Governor entry | Manual only (no ADB scrape in v1) |
| Optimiser objective | Best **troop ratio(s)** for clear/survive **proxy** |
| Heroes | Reuse existing heroes + hero-gear stores |
| Marches | **2 active** in v1 UI; model/API allow **3** slots |
| Combat engine v1 | Strength **proxy** (not Monte Carlo) |
| Combat engine v1.1 | Enemy floor stubs + MC / multi-round sim |

## Research summary (Radiant Spire)

Community sources (Kingshot Mastery / Kingshot Guide / kingshotdata) agree:

- Radiant Spire is the **all-systems** Sunday room (heroes, hero gear, pets, charms, research, **governor gear**, skins/VIP/island, …).
- Uses **your own troops** (Truegold matters); other rooms often stub T10.
- **No public closed-form score** like Bear’s 10-round formula. Practice is formation baselines + system diagnostics.
- Default starter ratio: **50% infantry / 15% cavalry / 35% archers** (±5% one axis after losses).
- AI troop mix (when known): most floors **~33/33/33**; floor 10 **~53/27/20** — useful later for enemy stubs, not required for proxy v1.

Governor gear (TC ≥ 22):

| Slots | Troop Atk% + Def% |
|---|---|
| Hood, Necklace | Cavalry |
| Cloak, Breeches (armor/pants) | Infantry |
| Ring, Staff | Archer |

- Same tier/star ladder per piece (Satin / Gilded Threads / Artisan's Vision).
- **3 pieces** same tier → Defense set bonus; **6 pieces** same tier → Attack set bonus.
- Charms are a **separate** system (Crystal Cave); out of scope for v1 except as zero stubs in the proxy.

## Why proxy first (not MC / enemy DB yet)

- We do **not** have a maintained per-floor enemy Atk/Def/HP/Lethality table in-repo.
- Monte Carlo against invented enemies looks precise and misleads.
- Proxy lets governor UI + dual-lineup ratio search ship, then we calibrate against real clears and add stubs + MC in v1.1 **in this same design track**.

---

## Part A — Governor gear inventory

### UX

- New inventory page (e.g. `/inventory/governor-gear`), hex / 2×3 layout mirroring the in-game profile:
  - Hood, Cloak, Ring, Necklace, Breeches, Staff (canonical slot ids below).
- Per slot card: rarity/tier badge, star count, current Atk%/Def% for its troop, **Upgrade** button.
- Upgrade advances one step on the YAML ladder (materials shown; v1 may track materials as optional counters or display-only costs).
- Header chips: Infantry / Cavalry / Archer Atk% & Def% totals; 3pc / 6pc set bonus status.

### Data model

```text
GovernorGearStore  →  governor_gear.json + governor_gear.db
piece: {
  slot_id,          # hood|cloak|ring|necklace|breeches|staff
  tier,             # green|blue|purple|gold|red (+ T-subtiers as needed)
  stars,            # int
  # derived from ladder, not OCR:
  attack_pct, defense_pct, power
}
```

- Canonical **display names** from `(slot_id)` (and optionally tier), not free text.
- Stat ladder + upgrade costs: `config/governor_gear.yaml` (seed from public tables; cite source in file header).

### Slot → troop mapping (config)

```yaml
slots:
  hood: { troop: cavalry, pair: necklace }
  necklace: { troop: cavalry, pair: hood }
  cloak: { troop: infantry, pair: breeches }
  breeches: { troop: infantry, pair: cloak }
  ring: { troop: archers, pair: staff }
  staff: { troop: archers, pair: ring }
```

### Set bonuses

- Compute min tier across pieces for “same tier” rules per public tables (document exact rule in YAML comments; implement the documented rule, not a guess).
- Expose `set_defense_pct` (3pc) and `set_attack_pct` (6pc) on the store summary API.

### API (sketch)

- `GET /api/governor-gear` — pieces + totals + set bonuses  
- `POST /api/governor-gear/{slot_id}/upgrade` — bump one ladder step  
- `PATCH /api/governor-gear/{slot_id}` — set tier/stars explicitly (manual correct)

---

## Part B — Radiant Spire optimiser (v1 proxy)

### Placement

- Optimise hub segment / page: **Radiant Spire** (alongside existing events).
- Inputs: governor store, hero store, gear store, troops.yaml / troop_stats.

### Marches

- Structure: `marches: [MarchSpec, MarchSpec, MarchSpec?]` — **length 3 in schema**, UI uses **2** in v1 (third `null` / inactive).
- Each march: `hero_names[3]`, `ratio: {infantry, cavalry, archers}` summing to 1.0, `capacity` fill from inventory (greedy / ratio fill, reuse bear helpers where possible).
- Heroes are **exclusive** across active marches.

### Hero selection (v1)

- Reuse catalog + expedition contributions (skills + assigned gear), same family as Swordland/Bear displays.
- Algorithm sketch:
  1. Rank heroes by expedition combat strength for Radiant weights (Attack+Lethality primary; Defense+Health secondary — configurable).
  2. Assign best feasible 3 to march 1 (one per troop type if `one_per_troop_type`).
  3. Assign next best exclusive 3 to march 2.
  4. For each march, search ratios; keep best proxy score.

### Ratio search

- Seed: `50/15/35`.
- Grid: ±5% steps on two axes (third residual), plus published alternates (55/10/35, 60/10/30, 50/10/40, 50/20/30).
- Independent search per march (ratios need not match).

### Foundational proxy (provisional)

Documented as **tunable**, not game-authoritative:

```text
For each troop type t ∈ {infantry, cavalry, archers}:
  atk%_t = governor_atk_t + hero_expedition_atk_t + set_attack (if 6pc)
  def%_t = governor_def_t + hero_expedition_def_t + set_defense (if 3pc)
  leth%_t = hero_expedition_leth_t   # charms/pets/research = 0 in v1
  hp%_t   = hero_expedition_hp_t

  offense_t = n_t × unit_atk(t) × (1 + atk%_t/100) × (leth_table/100) × (1 + leth%_t/100)
  tough_t   = n_t × unit_def(t) × (1 + def%_t/100) × (1 + hp%_t/100)

march_score = g(Σ offense_t, Σ tough_t)
            # v1 default: geometric mean  √(offense_sum × tough_sum)
lineup_score = march_score_1 + march_score_2   # equal weight; configurable
```

- `n_t` from ratio × march capacity (escorts included like other events).
- `unit_*` from `troop_stats.yaml` + inventory tier mix (Radiant uses **own troops**).

### Outputs

- Two marches: heroes, ratios, counts, proxy score.
- Breakdown chips: governor vs heroes/skills vs hero gear shares of atk/def.
- Explicit banner: “Proxy score — not in-game clear prediction.”

---

## Stories (backlog)

Tracked as GitHub issues so proxy-first v1 does not lose the deferred combat work:

| # | Story | Spec part |
|---|---|---|
| [#39](https://github.com/avnovikov/KS/issues/39) | Manual governor gear inventory (6 slots + upgrade) | A — **v1 slice** |
| [#40](https://github.com/avnovikov/KS/issues/40) | Radiant Spire dual-march proxy optimiser | B — **v1 slice** |
| [#37](https://github.com/avnovikov/KS/issues/37) | Radiant Spire enemy floor stub database | C — **v1.1** |
| [#38](https://github.com/avnovikov/KS/issues/38) | Radiant Spire Monte Carlo / multi-round combat engine | C — **v1.1** (depends on #37) |

## Part C — v1.1 (stories #37 / #38; not in first implementation PR)

1. **Enemy floor stubs** ([#37](https://github.com/avnovikov/KS/issues/37))  
   - `config/mystic_trial/radiant_spire_floors.yaml`  
   - Floor id, enemy ratio (default 33/33/33; floor 10 = 53/27/20), `enemy_power_scale` or full unit stats.  
   - Editable; seeded from community notes; grow via user reports / OCR later.

2. **Combat engine swap** ([#38](https://github.com/avnovikov/KS/issues/38))  
   - Multi-round or Monte Carlo using our stats vs floor stub.  
   - Optimiser objective → estimated win rate / remaining HP instead of proxy.  
   - Keep proxy as fallback when floor data missing.

3. Optional: paste battle-report enemy numbers to override stub for one run.

---

## Non-goals (v1)

- ADB scrape of governor profile  
- Charms / pets / research / skins inventory UIs  
- Stage ladder climb planner  
- Upgrade-next material optimiser for governor gear (may share ladder data later)

## Testing

- Unit: slot→troop mapping, set bonus thresholds, upgrade ladder step, canonical names.  
- Unit: proxy math with fixed governor + hero fixtures; ratio grid picks higher score when archer lethality rises.  
- Unit: hero exclusivity across two marches; third march slot unused.  
- UI smoke: upgrade button persists to JSON + SQLite; Radiant page returns two ratios.

## Implementation order

1. `governor_gear` config + models + store + API + inventory page  
2. Proxy scorer + dual-march ratio search (CLI then UI)  
3. Wire governor totals into scorer  
4. Spec note / issue for v1.1 floors + MC  

## Open calibration notes

- Exact set-bonus % table and “same tier” rule must match `config/governor_gear.yaml` sources (kingshotoptimizer / wiki).  
- Proxy `g(offense, tough)` may need a weight knob after first Sunday comparison.  
- Whether Radiant marches share one troop pool or each get full capacity — **v1 assumption: each march uses full march capacity** (game-like); if wrong, fix after one live check.
