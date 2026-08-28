# In-app help & step onboarding — design

**Date:** 2026-08-28  
**Status:** Approved (step-based flow)  
**Related:** `2026-08-02-heroes-inventory-optimiser-ui-design.md`  
**Base UI branch:** `feature/governor-optimiser-wire` (Inventory subtabs incl. Governor)

## Goal

First-time and returning users get **in-app help** and a **linear setup wizard** that walks inventory in the order people actually use KS:

1. **Heroes**
2. **Gear**
3. **Troops**
4. **Governor charms**

After step 4, a short **Optimiser intro** (help only — not a checklist step) points users at Event lineups.

Machine/runtime setup (Python, ADB, `pip install`, first `collect`) stays in repo README — **not** in the step wizard.

## Locked decisions

| Topic | Decision |
|-------|----------|
| Delivery | In-app only (no standalone markdown doc as primary UX) |
| Flow shape | **Series of steps** — one screen per step, Next / Back / Skip |
| Step order | Heroes → Gear → Troops → Governor charms |
| “Infra” | **Troops** inventory lane (not ADB/machine setup) |
| Governor label | Subtab stays **Governor**; copy uses **Governor charms** where clearer |
| Optimiser | Step 5 on help hub only; not required for “setup complete” |
| Blocking | **Skippable** — user can leave wizard anytime; progress persists |
| Progress storage | `localStorage` key `ks.setup.v1` (no server auth in v1) |
| Theme | Apple-light shell — same chrome as Inventory / Optimiser |

## Information architecture

```text
Header:  KS · Inventory · Optimiser · [Setup] · [?]

/setup              → active step (redirects to current incomplete step)
/setup/1-heroes     → step 1
/setup/2-gear       → step 2
/setup/3-troops     → step 3
/setup/4-governor   → step 4
/setup/done         → completion screen → Optimiser CTA

/help               → reference hub (same four chapters + Optimiser)
/help/heroes … /help/governor
```

First visit to `/` or `/inventory/*` when setup incomplete: soft redirect to `/setup` (once per session; dismissible “Continue without setup”).

Inventory subtabs unchanged: **Gear · Heroes · Troops · Governor** (help copy references step numbers, not tab order).

## Step wizard UX

### Shared chrome (all steps)

- **Stepper** at top: `1 Heroes — 2 Gear — 3 Troops — 4 Governor charms`  
  - Completed steps: checkmark + link back  
  - Current: accent underline  
  - Future: muted, not clickable until prior step marked done (soft gate — “Skip to this step” link in footer for power users)
- **Body:** title, 2–4 short paragraphs, bullet “Do this”, optional tip callout
- **Primary action:** “Open [screen]” → deep link to inventory route
- **Secondary:** “Mark step complete” (manual) when auto-detect hasn’t fired
- **Footer:** Back · Skip setup · Next (enabled when step complete or user confirms “Done anyway”)

### Step 1 — Heroes

**Route:** `/setup/1-heroes` · **Deep link:** `/inventory/heroes`

**Do this:**
1. Run heroes collect (CLI) or use **Rescan from OCR** with Heroes roster visible
2. Spot-check stars, pellets, and power against the game
3. Fix highlighted rows; edits auto-save

**Auto-complete when:** `heroes.json` exists with ≥1 hero **and** (user saved an edit **or** clicked Mark complete).

**Tips:** Naked power matters for optimisers; assurance tints show low-trust fields.

### Step 2 — Gear

**Route:** `/setup/2-gear` · **Deep link:** `/inventory/gear`

**Do this:**
1. Leave **Backpack → Gear** open on device
2. **Rescan from OCR** (replaces inventory — confirm dialog)
3. Verify enhancement / mastery; use **Needs attention** filter

**Auto-complete when:** `gear.json` exists with ≥1 piece **and** (rescan finished **or** edit **or** Mark complete).

**Tips:** Pinned fields (•) survive rescan; clear a field to accept OCR again.

### Step 3 — Troops

**Route:** `/setup/3-troops` · **Deep link:** `/inventory/troops`

**Do this:**
1. Set **march capacity** and **Truegold**
2. Enter infantry / cavalry / archers tier counts
3. Confirm totals look right — all optimisers read this file

**Auto-complete when:** troops saved with `march_capacity > 0`.

**Tips:** No OCR yet — manual entry is source of truth.

### Step 4 — Governor charms

**Route:** `/setup/4-governor` · **Deep link:** `/inventory/governor-gear`

**Do this:**
1. Match all **6 in-game governor charm slots** to the cards shown
2. Use **Upgrade** as you level charms in-game (advances config ladder)
3. Check set bonus and per-troop Atk/Def% chips

**Auto-complete when:** all 6 governor slots present **and** (upgrade clicked **or** Mark complete).

**Tips:** Bonuses feed Bear / Swordland and other optimisers once wired.

### Done — `/setup/done`

- Message: inventory trustworthy enough to optimise
- CTA: **Open Event lineups** → `/optimiser/events`
- Link: **Help reference** → `/help`

## Help reference (`/help`)

Same four chapters as steps, plus **Optimiser overview** (Event lineups, Gear XP, Hero levels placeholder). Static Jinja pages — no JS required to read. Each chapter ends with “Repeat setup step →” linking back to `/setup/N-…`.

Header **`?`** always goes to `/help`. Header **Setup** shows `Step N of 4` or **Complete** when done.

## Progress model (`localStorage`)

```json
{
  "version": 1,
  "skipped": false,
  "current_step": 2,
  "completed": { "heroes": true, "gear": false, "troops": false, "governor": false },
  "dismissed_banners": { "heroes": false, "gear": true }
}
```

- **Skipped:** wizard hidden until user opens Setup from header  
- **current_step:** highest incomplete step (1–4), or 5 = done  
- Server may expose lightweight JSON (`GET /api/setup/status`) mirroring file checks for auto-complete — optional v1.1; v1 can use page-load hints only

## UI components (new)

| File | Role |
|------|------|
| `templates/setup/_stepper.html` | Shared step indicator |
| `templates/setup/step_heroes.html` … `step_governor.html` | Step bodies |
| `templates/setup/done.html` | Completion |
| `templates/help/index.html` + `help_*.html` | Reference chapters |
| `static/setup.js` | Progress read/write, auto-complete hooks |
| `static/setup.css` | Stepper + step layout (or extend `app.css`) |

Routes added in `ks/heroes/ui/app.py`: `/setup`, `/setup/{step}`, `/help`, `/help/{chapter}`.

## Contextual nudges (lightweight)

On each inventory page, if that step is incomplete and banner not dismissed: one-line strip linking to the matching setup step (“Step 2 of 4: finish gear review →”). Dismiss per section via `dismissed_banners`.

## Non-goals (v1)

- Machine / ADB / BlueStacks install in wizard  
- Blocking modal that prevents using Inventory without finishing setup  
- Research inventory as a step  
- i18n  
- Multi-user progress (auth tenancy)  
- Renaming Governor subtab to “Charms” (copy only)

## Acceptance

- New user can complete setup 1→4 without reading README  
- Each step deep-links to the correct inventory screen  
- Skip setup → full app usable; Setup pill returns to current step  
- Help hub readable on phone (~390px) with same Apple chrome  
- Completing step 4 shows Optimiser CTA  
- Existing inventory / optimiser routes unchanged when setup skipped  

## Testing

- Route smoke: all `/setup/*` and `/help/*` return 200  
- Stepper shows correct active step from query or default  
- `localStorage` progress survives reload (manual or Playwright)  
- Troops auto-complete fires on successful `POST /api/troops`  
- Skip clears forced redirect; header Setup still works  
