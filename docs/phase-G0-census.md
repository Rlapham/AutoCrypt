# G0 — Graduation-event detection (census)

- Window (pool creations): **2026-06-03 12:31 → 2026-06-03 22:53 UTC**  (~10.4h of wall-clock)
- `pool_created` rows: **12,641** over **12,011** distinct mints
- Graduation = first AMM-venue pool created at/after a bonding-curve pool for the same mint; milestone stamped at the AMM pool's `knowable_at` (no look-ahead).
- Co-launch guard: BC→AMM lag < **120s** ⇒ flagged `suspect_colaunch` (config artifact, not a genuine curve-fill).


## Funnel (survivorship-complete)

| stage | count |
|---|---:|
| bonding-curve-origin mints (denominator) | 10,983 |
| → graduated (BC→AMM, incl. suspect) | 509 |
| → **genuine** graduations (lag ≥ 120s) | 185 |
| → suspect co-launch artifacts | 324 |
| never graduated (died on the curve) | 10,474 |
| direct-AMM launches (deep from birth, no BC) | 1,028 |

**Genuine graduation rate: 1.68%** (185/10983 bonding-curve-origin mints).


## Genuine-graduation lag (bonding-curve create → AMM create)

| p10 | p50 | p90 | min | max |
|---:|---:|---:|---:|---:|
| 2.3m | 4.9m | 20.7m | 2.0m | 345.5m |

## Transitions (BC venue → AMM venue)

| transition | count |
|---|---:|
| meteora_dbc->meteora_daam_v2 | 434 |
| pumpfun->pumpswap | 47 |
| meteora_dbc->meteora | 24 |
| pumpfun->meteora_daam_v2 | 3 |
| pumpfun->meteora | 1 |

## Post-graduation swap coverage (the collection gap)

Of **185** genuine graduations, **2** (1%) have ANY swap on their AMM pool knowable at/after graduation. Root cause: the forward collector tailed newest pools by creation (overwhelmingly bonding-curve), so the later-created AMM pool of a graduated token rarely won a watchlist slot. **Fix deployed (G0 session):** `collect --amm-reserved` reserves watchlist capacity for AMM (graduation-target) pools, so coverage should climb from here as graduated pools accrue their multi-day arcs. This historical census still reflects the pre-fix data; G1/G2 need the post-fix coverage to ripen before they can run.

