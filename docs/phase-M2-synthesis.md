# Phase M2 Synthesis — deep-pool cost recalibration (Law 1 escaped)

*Session date: 2026-06-03. Track M (mid-cap deep-pool), Iteration 2. Ran autonomously.*

## Goal

Before any signal work, confirm empirically that Iteration-1's **Law 1 — the cost wall**
(round-trip execution cost ~20-28% on thin fresh-launch pools, which swamped ~0% drift and
killed the whole corner) is actually **escaped** on the mid-cap deep-pool universe M1b built
(n=113, reserve >= $500k). If the wall still stands, Track M is dead on arrival and we stop.

## Headline result — PASS. The cost wall is gone at sane trade sizes.

Round-trip friction **at flat price** (buy then immediately sell back — pure execution cost,
the exact like-for-like with Iteration 1's 20-28%), across the 113-pool biased control:

| position $ | median friction | pools < 3% | pools < 5% |
|---:|---:|---:|---:|
| 100 | 1.03% | 100% | 100% |
| 500 | 0.82% | 100% | 100% |
| **1,000** | **0.91%** | **100%** | **100%** |
| 5,000 | 1.96% | 73% | 100% |
| 10,000 | 3.28% | 47% | 69% |
| 50,000 | 12.68% | 11% | 19% |

At **$100-$1,000 positions, median friction is ~0.8-0.9% with 100% of pools under 3%** — an
order of magnitude below Iteration 1. Robust to every sensitivity: pump.fun's 100 bps fee ->
2.3% median @ $1k; depth halved (historical-shallower worry) -> 1.19%; dropping the 6
pegged/pegged pairs (mSOL/SOL etc.) -> unchanged (0.91%). Full numbers + method:
**`docs/phase-M2-cost-profile.md`**.

**Why the wall fell:** same constant-product cost engine (`profiler.execution.ExecutionModel`,
unchanged), *only the depth input changed*. Iteration 1 inferred depth from thin-pool swap
price-impact (small Q -> big own impact); Track M reads depth directly from `reserve_in_usd`
(median in-band reserve $1.44M). Sanity anchor: feeding the engine an Iteration-1-like $20k
pool reproduces 17.2% friction — the model is identical, the pools are just deep.

## The one real constraint going forward: capacity, not a wall

Friction is size-dependent. This universe is a **small-to-mid book**: per-position notional
should scale with each pool's depth (~<= 0.4% of reserve keeps friction ~1%), not a flat
dollar figure. $5k is fine on ~73% of pools, $10k only on the deeper ~half, $50k is too big
for the median $1.4M pool. M4 (GO only) would formalise capacity; for the kill-gate it's
enough that a low-cost operating size exists on every pool — it does.

## Context (NOT an expectancy claim)

Median absolute 5-day move across these pools is ~6.0%, ~7x the $1k friction of 0.9%. This
only establishes that friction no longer eats the entire available move (Law 1's inequality
`gross > cost` is now *possible*). Whether any signal captures that move with positive
expectancy is M3's question, untouched here.

## What was built

- **`src/autocrypt/midcap/costs.py`** — the recalibration. `round_trip_friction` (flat-price
  pure execution cost via the unchanged `ExecutionModel`), `compute_pool_frictions`,
  `summarize_frictions` (median/quartiles/p90/worst + pass-fractions), `recalibrate_costs`
  (top-level), `_load_in_band_pools_ro` (read-only universe loader — no DDL),
  `_is_speculative` (symbol-based pegged-pair classifier), `_typical_abs_move` (volatility
  context). Depth = `reserve_usd * 0.5 * depth_mult`; conservative (overstates impact for
  concentrated-liquidity pools).
- **CLI `midcap-costs`** — friction grid + fee/depth sensitivity + volatility context.
  Read-only. Flags: `--source`, `--fee-bps`, `--fixed-cost-usd`, `--speculative-only`.
- **Tests:** `tests/test_midcap_costs.py` (9: thin-vs-deep wall, fee floor = 2 legs,
  monotone in size/fee, deeper-is-cheaper, degenerate-depth = total loss, pegged classifier,
  typical-move, percentile interpolation, aggregation pass-fractions). **83/83 green, ruff
  clean** (was 74; +9).
- **Docs:** `docs/phase-M2-cost-profile.md` (the evidence + verdict), this synthesis.

## Key decisions & why

1. **Headline metric = flat-price round-trip friction.** Isolates execution cost from price
   movement, and is the *exact* quantity Iteration 1 reported as 20-28% — so "1% now vs 20%
   then" is an honest like-for-like, not a redefinition.
2. **Depth = `reserve_usd * 0.5`, not full reserve.** A balanced xy=k pool holds half its TVL
   on the quote side; using the full reserve would understate impact. Conservative by choice.
3. **Reused the existing `ExecutionModel` verbatim.** The cost engine was never the problem in
   Iteration 1 — the *depth input* was. Changing only the input keeps the comparison clean and
   avoids smuggling in an optimism via a new model.
4. **Read-only loader added** rather than reusing `universe.load_in_band_pools` (which runs a
   `CREATE TABLE IF NOT EXISTS` that fails on a read-only connection). Keeps the cost pass
   non-mutating and safe to run while the daily snapshot loop owns the file.
5. **Did NOT touch signals.** M2 is strictly the cost gate; signal battery is M3.

## Open questions / follow-ups (for M3)

1. **M3 — signal battery + kill-gate (next session).** TS momentum, XS (cross-sectional)
   momentum, mean-reversion, breakout, through the profiler with the full §3 kill-gate. The
   profiler currently consumes swap-level `PoolData`; M3's first task is an **OHLCV-bar
   adapter** (the midcap store has `ohlcv_bar` only, no swaps) feeding daily closes +
   `reserve_usd` depth into the cost model per entry/exit. Cost side is now solved by M2.
2. **Capacity sizing rule** (per-pool notional <= ~0.4% reserve) should be encoded when M3
   simulates fills, so expectancy is reported net at a *realistic* per-pool size, not a flat $.
3. **Survivorship asymmetry stands.** Anything M3 finds on this biased control is NO-GO/
   "unproven" only — never a GO. The clean forward snapshot series keeps accruing for the
   eventual unbiased re-test.
4. **Universe noise** (a handful of LST/stable/wrapped "deepest pools") — the `_is_speculative`
   classifier is now available; M3 should run on the speculative-only subset by default.
5. **Optional M1b cleanups still pending** (not blocking): funnel incremental-write/early-stop
   (the ~2.5h grind), restricting the quote leg to SOL/USDC/USDT at enumeration time.

## State of the code

`src/autocrypt/midcap/{universe,mcap_rank,costs}.py` + `providers/coingecko.py` + the
`midcap-*` CLI commands are tested; **83/83 green, ruff clean**. No paid spend, no keys, no
funds, no trading. Track M store: `data/autocrypt_midcap.duckdb` (113-pool in-band universe +
16,177 1d bars + forward snapshots). Iteration-1 stores untouched.

## Background processes (re-launched this session; neither survives reboot)

| Process | PID (this session) | Writes to | Purpose |
|---|---|---|---|
| `autocrypt collect` (nohup) | 3006 | `data/autocrypt_graduation.duckdb` | G0 graduation cohort, 7-day hold |
| `midcap_snapshot_loop.sh` (nohup) | 3003 | `data/autocrypt_midcap.duckdb` | daily clean (top-pools) universe snapshot |

Both were **dead at session start** (reboot) and re-launched. Durable fix still pending: grant
Full Disk Access to `/usr/local/bin/uv` then enable
`~/Library/LaunchAgents/com.autocrypt.collector.plist`, OR relocate the repo out of `~/Documents`.
The snapshot loop sleeps 24h *before* its first write, so it held no DB lock during M2's
read-only cost pass (single-writer rule respected).

---

```text
Read CLAUDE.md, then Project_spec.md, then docs/iteration-2-strategy.md, then
docs/phase-M2-synthesis.md (and docs/phase-M2-cost-profile.md). Confirm in 3-4 sentences
where we are and this session's goal before doing anything else.

CONTEXT: Iteration 2, Track M (mid-cap deep-pool) + Track G (graduation, parallel). M2 is
DONE and PASSED: deep-pool cost recalibration confirmed Iteration-1's Law 1 (the cost wall)
is ESCAPED -- round-trip friction at flat price is ~0.8-0.9% median at $100-$1k positions
(100% of the 113 pools under 3%), vs Iteration-1's 20-28% on thin pools. Same constant-product
ExecutionModel, only the depth input changed (reserve_usd direct vs inferred). Robust to fee
100bps / depth x0.5 / dropping pegged pairs. The one real constraint is CAPACITY (size per
position should scale with pool depth, ~<=0.4% of reserve keeps friction ~1%; $10k+ only on
the deeper half). Built src/autocrypt/midcap/costs.py + CLI `midcap-costs` + 9 tests (83/83
green, ruff clean). Evidence: docs/phase-M2-cost-profile.md.

THIS SESSION = M3: signal battery + KILL-GATE (strategy doc section 4 / M3, gate section 3).
  1. FIRST BUILD: an OHLCV-bar adapter for the profiler. The midcap store has ONLY ohlcv_bar
     events (no swaps), but the profiler's dataset.load_pools expects swap-level PoolData.
     Feed daily closes + per-pool reserve_usd depth (the M2 cost model) into the kill-gate so
     expectancy is reported NET of realistic cost at a realistic per-pool size (encode the
     capacity rule: notional ~<= 0.4% of reserve, not a flat $).
  2. THEN implement a small transparent signal battery through the profiler: time-series
     momentum/trend, cross-sectional momentum (rank across the universe), mean-reversion, and
     a volatility/volume breakout. Run on the SPECULATIVE-ONLY subset by default (107 pools;
     use costs._is_speculative).
  3. KILL-GATE per strategy section 3: profitable-after-cost AND point-in-time AND beats
     blind+random (permutation p, multiple-comparison discount) AND robust across sweeps AND
     enough fires. Report nulls plainly. On this BIASED control a positive is only an upper
     bound -> NO-GO/"unproven" at best, NEVER a GO. Never tune to a positive.

CHECK BACKGROUND JOBS FIRST (both DIE on reboot -- re-launch if `ps aux | grep autocrypt`
shows nothing):
  - G0 graduation:  DB_URL=duckdb:///data/autocrypt_graduation.duckdb nohup uv run autocrypt \
      collect --interval 90 --iterations 0 --enum-pages 3 --watch-max 60 --max-pool-age-h 168 \
      --tx-pages 2 > data/g0_collect.interim.log 2>&1 &
  - Track M daily snapshot: nohup bash scripts/midcap_snapshot_loop.sh > data/midcap_snapshot.log 2>&1 &
Durable fix still pending: grant Full Disk Access to /usr/local/bin/uv (then enable
~/Library/LaunchAgents/com.autocrypt.collector.plist), OR relocate repo out of ~/Documents.

Autonomy: GREEN code/backtest/free data; YELLOW paid tiers + universe/label changes + GO/NO-GO;
RED unchanged. Single-writer rule: the snapshot loop owns autocrypt_midcap.duckdb during its
brief daily write -- run the profiler read-only; don't run two writers on that file at once.
```
