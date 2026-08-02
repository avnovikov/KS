# Heroes Inventory + Optimiser UI — design

**Date:** 2026-08-02  
**Status:** Approved for planning (visual + IA locked in brainstorm)  
**Related:** gear UI, roster UI, event optimize UI, gear XP spend optimizer

## Goal

Local web UI to keep **inventory trustworthy** (spot-check vs game after OCR), then run **multiple optimisers** for event decisions. Look and feel is **Apple-light**, and the same UI must work well on a **phone browser** (thumb-friendly, not desktop-only tables).

Primary job: inventory-first → optimiser second.

## Locked decisions

| Topic | Decision |
|-------|----------|
| Approach | Spreadsheet+ polish (not review-queue wizard, not split workspace) |
| Theme | Apple light — `#f5f5f7` canvas, white panels, system/SF stack, accent `#0071e3` |
| Dark mode | Out of scope for this redesign |
| Nav | Two primary tabs: **Inventory** · **Optimiser** |
| Inventory subtabs | **Gear** · **Heroes** · **Troops** |
| Optimiser subtabs | Extensible: **Event lineups** · **Gear XP** · **Hero levels** · … |
| Nav chrome | Underline primary tabs + segmented subtabs (shell A) |
| OCR evidence crops | Deferred — see Parking lot (interesting, not v1) |
| Trust loop | Spot-check beside game after rescan; banner + row highlights |
| Forced verify gate | No — soft CTA into Optimiser only |
| Phone | First-class layout target (responsive), not a separate app |

## Information architecture

```text
KS
├── Inventory
│   ├── Gear          (pieces: enh / mastery / power)
│   ├── Heroes        (stars / pellets / power)
│   └── Troops        (I / C / A counts for solvers)
└── Optimiser
    ├── Event lineups (Swordland / Bear / Arena formations)
    ├── Gear XP       (fodder → enhancement spends for an event)
    ├── Hero levels   (which heroes to push next for an event) [planned]
    └── …             (future tools as subtabs)
```

Routes (proposed):

| Path | Screen |
|------|--------|
| `/` | Redirect → `/inventory/gear` (or last visited) |
| `/inventory/gear` | Gear table |
| `/inventory/heroes` | Heroes table |
| `/inventory/troops` | Troop counts editor |
| `/optimiser/events` | Event lineups (layout B) |
| `/optimiser/gear-xp` | Gear XP spend (layout A) |
| `/optimiser/hero-levels` | Placeholder or v1 when ready |
| Existing `/gear`, `/heroes`, `/optimize*` | Redirect to new paths for bookmarks |

## Visual system (Apple light + phone)

- **Canvas:** `#f5f5f7`; **panels:** `#ffffff`; **text:** `#1d1d1f`; **muted:** `#6e6e73` / `#86868b`; **border:** `#d2d2d7`
- **Accent:** `#0071e3`; **ok:** `#34c759`; **warn (needs attention):** `#ff9f0a`; **err:** `#ff3b30`
- **Type:** `-apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", sans-serif`
- **Controls:** segmented subtabs, pill primary buttons, soft 12–16px radii, light separators — no neon glow, no dark admin chrome
- **Safe areas:** respect `env(safe-area-inset-*)` on notched phones
- **Touch:** minimum ~44×44pt hit targets for tabs, Rescan, Run, editable fields
- **Narrow (&lt;640px):**
  - Primary tabs full-width; subtabs horizontally scrollable (no wrap crush)
  - Inventory tables: sticky first column (icon/name); horizontal scroll for other columns **or** stacked “key fields” row pattern for enh/mastery (prefer sticky column + scroll so bulk edit stays fast)
  - Event lineups: mode chips wrap/scroll; formation board scales portraits down but keeps Front/Back structure
  - Gear XP: single column already — full width inputs; sticky “Run” near bottom on small screens optional
- **Wide:** same components, more breathing room; no mandatory multi-column inventiveness beyond locked layouts

## UX flow

1. Open **Inventory** (Gear or Heroes).
2. **Rescan from OCR** (or edit manually). Device/game stays open beside (or under) the phone browser.
3. Banner: just rescanned · counts · changed/incomplete. Rows tinted (new / changed / incomplete).
4. Spot-check vs game; edit inline (**auto-save**); tint clears on edit. Optional **Mark all reviewed**.
5. Soft CTA → **Optimiser** (default last tool or Event lineups).
6. Pick optimiser subtab → run decision tool → (optional) return to Inventory to apply manual changes.

## Inventory screens

### Shared (Gear + Heroes)

- Dense sortable table, sticky header, filter chips, name search
- Auto-save on field blur/debounce (no per-row Save); toast on error only; brief cell “saved” flash
- Post-rescan trust: banner + row highlights; **Needs attention** filter
- Rescan button in header actions (confirm wipe/replace semantics unchanged per existing collectors)
- Soft link into Optimiser after rescan

### Gear

- Columns: name/icon, troop, slot, rarity, enhancement, mastery, power
- Incomplete = missing expected enh/mastery where rarity implies levels, etc. (keep heuristics simple and documented in implementation)

### Heroes

- Columns: name/icon, troop, rarity, stars, pellets, power (star-factor rescale on edit — existing behavior)

### Troops

- Simple Apple-form editors for infantry / cavalry / archers counts (and any other fields solvers already need)
- Persist in a small troops store (JSON alongside heroes/gear artifacts, or UI-owned override file); all optimiser tools must read the same source of truth
- Validation: non-negative integers; clear errors
- v1 may start as UI override of `config/troops.yaml` values without requiring a full troops OCR pipeline

## Optimiser screens

### Event lineups (layout B)

- Event segmented control: Swordland · Bear Trap · Arena
- Mode chips with points (or arena score) above
- Selected mode: **formation board** (Front/Back, portraits, troops line, points)
- Tap hero → sheet/drawer: why + leave-one-out + gear slots
- Refresh recomputes from current heroes + gear + troops
- Phone: board is the focus; chips scroll; detail opens as bottom sheet

### Gear XP (layout A)

- Single column: event target → fodder bag counts → **Find best spends** → baseline→best utility delta → ordered spends → leftovers
- Propose only in v1 (no auto-write to `gear.json`)
- Optional “Open in Event lineups” with resulting mode preselected
- Aligns with `2026-08-02-gear-xp-spend-optimizer-design.md` for algorithm/API

### Hero levels (planned subtab)

- **Job:** for a chosen event, recommend which owned heroes to push toward the next level / progression breakpoint so event utility rises most.
- UI shell: same Optimiser chrome; form (event + optional constraints) → ranked recommendations + expected Δ utility.
- Full algorithm/spec is a follow-on design; this doc only reserves the subtab and IA.

## Data / API notes (UI-facing)

- Reuse existing gear/heroes stores and optimize APIs where possible
- Troops must become a first-class UI-editable input for optimisers
- Redirect old URLs to new IA paths
- Partial failures surface per optimiser section (existing optimize error pattern)

## Non-goals (v1 of this redesign)

- Dark theme
- Review-queue wizard / forced verification gate
- Split inventory \| optimiser dual pane
- OCR evidence crops in the main table (see Parking lot)
- Auto-applying Gear XP spends into inventory
- Native iOS app (responsive web is enough)
- Full Hero levels solver (subtab may ship as placeholder)

## Parking lot — interesting, deferred

Keep these; do not implement in the first redesign pass unless explicitly pulled in:

| Idea | Why interesting | Why deferred |
|------|-----------------|--------------|
| **OCR evidence UI** | Show name/icon/level crops beside parsed values for faster trust without flipping to the game as much | User preferred lean spot-check with game open; still valuable later, especially on phone when game and browser can’t sit side-by-side |
| Review-queue “Looks good” pass | Strong trust ritual | Heavier than Spreadsheet+; rejected for v1 |
| Split workspace (inventory + live optimiser preview) | Instant feedback | Fast rescan edit + soft CTA preferred |
| Immersive lineup-only board (swipe modes) | Max game-screen feel | Mode chips + board (B) won |
| Gear XP split with live resulting lineup pane | Ties spend to formation | Single-column form (A) won for Gear XP |
| Persistent sidebar nav | All tools visible | Underline + segmented won for Apple feel |
| Apply Gear XP spends to inventory | One-tap commit | Propose-only safer for v1 |
| Multi-event joint optimise | Power-user planning | Out of scope |

When revisiting OCR evidence: prefer a detail sheet (“Show scan crop”) rather than cluttering every table row; on phone this may matter more than on desktop.

## Acceptance (design)

- User can move Inventory ↔ Optimiser without losing the light Apple chrome
- On a phone-width viewport, all primary flows usable with thumb (rescan, edit levels, run lineup, run gear XP)
- Post-rescan trust cues appear without OCR crops
- New optimiser tools can add a subtab without inventing a new shell
- Parking lot items remain documented for later

## Testing (when implemented)

- Layout smoke at ~390px and ~1280px widths
- Redirects from legacy paths
- Inventory auto-save + trust highlight clear-on-edit
- Optimiser events + gear-xp still return correct payloads under new routes
