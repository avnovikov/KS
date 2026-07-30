# Bear Trap placement proposal — State #2339 [UTD]

**Generated:** 2026-07-30  
**Blockers:** `blockers.yaml` (popup-confirmed only — OCR still pending)  
**Maps:** `placement-map.html` (primary) · `placement-map-score-best.html` (optimizer #1)  
**Seats:** `seats.csv`

> Caveat: blocker layer is incomplete (no full OCR yet). Treat seats that land on
> undigitized rocks/RSS as provisional; re-run after OCR.

## Primary recommendation (V3-style D≈7, E/W)

| | |
|--|--|
| **Trap 2 (fixed)** | `698, 816` |
| **New trap (Trap 1)** | **`691, 815`** |
| Pose | D=7 **W** lateral=+1 |
| Score | 265.6 (rank among D=7 E/W) |
| Leaders T2 / T1 / BOTH | 8 / 8 / 4 |
| Joiners (cycle OK) | 48 of 139 packed |
| Flex joiners (near 2 leaders) | 139 |

### Leader seats (city top-left tile)

**Hunt 2 / Trap 2 leaders**
- `696,812`
- `698,812`
- `700,812`
- `700,814`
- `700,816`
- `696,818`
- `698,818`
- `700,818`

**Hunt 1 / New-trap leaders**
- `688,812`
- `690,812`
- `692,812`
- `688,814`
- `688,816`
- `688,818`
- `690,818`
- `692,818`

**BOTH / flex leaders** (reach either trap within leader radius)
- `694,812`
- `694,814`
- `694,816`
- `694,818`

### Known blockers respected

- `alliance_banner` @ 695,820 (1×1) [building]
- `woodmill_near_trap` @ 702,815 (1×1) [building]
- `woodmill_north` @ 699,823 (1×1) [building]
- `iron_mine` @ 704,830 (1×1) [building]
- `alliance_mill` @ 695,834 (1×1) [building]
- `plains_hq` @ 705,823 (5×5) [building]
- `city_ace` @ 696,814 (2×2) [city]
- `city_hazy` @ 706,821 (2×2) [city]
- `city_pinky` @ 708,822 (2×2) [city]

## Optimizer score-best (alternate)

D=11 W lat=+1 → new trap **`687, 815`** (score 272.6). Wider gap packs more joiners; less worksheet-like.

## Top 8 poses

| # | D | Dir | Lat | New trap | Score | L2 | L1 | FlexJ | JoinOK |
|---|---|-----|-----|----------|-------|----|----|-------|--------|
| 1 | 11 | W | +1 | `687,815` | 272.6 | 12 | 12 | 159 | 56 | **score-best**
| 2 | 9 | W | +1 | `689,815` | 266.4 | 12 | 12 | 147 | 50 |
| 3 | 7 | W | +1 | `691,815` | 265.6 | 12 | 12 | 139 | 48 | **primary**
| 4 | 12 | W | +1 | `686,815` | 257.9 | 10 | 12 | 171 | 58 |
| 5 | 11 | W | -1 | `687,817` | 256.6 | 10 | 12 | 159 | 59 |
| 6 | 12 | E | -1 | `710,815` | 255.8 | 10 | 12 | 171 | 56 |
| 7 | 11 | W | +0 | `687,816` | 255.7 | 10 | 12 | 159 | 58 |
| 8 | 11 | E | -1 | `709,815` | 253.7 | 10 | 12 | 159 | 56 |

