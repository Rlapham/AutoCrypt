# Phase M2 — Deep-pool execution-cost recalibration (the Law-1 re-test)

*Session date: 2026-06-03. Track M (mid-cap deep-pool), Iteration 2. Ran autonomously.*
*Reproduce: `DB_URL=duckdb:///data/autocrypt_midcap.duckdb uv run autocrypt midcap-costs`*

## The question M2 answers

Iteration 1 died on **Law 1 — the cost wall**: on thin fresh-launch pools, round-trip
execution cost (own price impact + fees) ran **~20–28%**, swamping the ~0% short-hold drift,
which made the corner a structural loser for *any* entry signal. Track M's whole premise is
that **mid-cap deep pools** (reserve ≥ $500k) shrink own impact to near-nothing, so fees +
spread dominate and round-trip cost collapses to **low single digits**. M2 tests that
directly — *before* any signal work. If the wall still stands, Track M is dead on arrival.

## Headline verdict — ✅ Law 1 is escaped at the sizes this strategy would trade

On the 113-pool biased-control universe, **round-trip friction at flat price** (buy then
immediately sell — pure execution cost, the exact like-for-like with Iteration 1's 20–28%):

| position $ | median | p25 | p75 | p90 | worst | <3% | <5% |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 100 | 1.03% | 1.01% | 1.05% | 1.07% | 1.1% | 100% | 100% |
| 500 | 0.82% | 0.74% | 0.93% | 1.03% | 1.1% | 100% | 100% |
| **1,000** | **0.91%** | 0.77% | 1.15% | 1.33% | 1.4% | **100%** | **100%** |
| 5,000 | 1.96% | 1.25% | 3.10% | 3.99% | 4.4% | 73% | 100% |
| 10,000 | 3.28% | 1.88% | 5.47% | 7.15% | 7.9% | 47% | 69% |
| 50,000 | 12.68% | 6.67% | 20.96% | 26.50% | 28.8% | 11% | 19% |

At **$100–$1,000 positions, median friction is ~0.8–0.9% and 100% of the 113 pools are under
3%.** That is low single digits — an order of magnitude below Iteration 1's wall. The cost
wall does not exist on these pools at sane trade sizes.

The number is dominated by the **fee floor** (2 legs × 30 bps = 0.60%) plus a tiny own-impact
term; at $100 the per-trade fixed cost ($0.20/leg) lifts it to ~1.0%. Own impact only becomes
material as size approaches a meaningful fraction of pool depth.

## What changed from Iteration 1 (why the wall fell)

Same constant-product cost engine (`profiler.execution.ExecutionModel`, fees + own impact on
**both** legs + fixed) — **only the depth input changed**:

- **Iteration 1** *inferred* depth from observed swap price-impact on thin fresh-launch pools
  (`LiquidityEstimator`) → small effective quote reserve → large own impact (the 20–28%).
- **Track M** takes depth **directly** from each pool's `reserve_in_usd` (GeckoTerminal):
  quote-side depth = `reserve_usd × 0.5` (a balanced xy=k pool holds half its TVL per side).
  Median in-band reserve is **$1.44M** (min $505k, max $37.2M) → own impact ~ size/Q is tiny.

Sanity anchor: feeding the engine an Iteration-1-like thin pool (reserve $20k) at a $1k
position reproduces **17.2%** friction — i.e. the model is unchanged; only the pools are deeper.

## Robustness — the verdict does not hinge on assumptions

**Sensitivity (median / p90 friction @ $1,000):**

| scenario | median | p90 |
|---|---:|---:|
| fee 25 bps | 0.81% | 1.24% |
| fee 30 bps (base) | 0.91% | 1.33% |
| fee 100 bps (pump.fun-pessimistic) | 2.30% | 2.71% |
| depth ×0.5 (historical pools shallower) | 1.19% | 2.02% |
| depth ×2 (concentrated-liquidity deeper) | 0.78% | 0.99% |

Every scenario — including charging the full pump.fun 100 bps fee, and halving depth to cover
the worry that pools were shallower historically than at today's enumeration snapshot — stays
in **low single digits**. The conclusion is not fragile to the cost assumptions.

**Speculative-only (drop the 6 pegged/pegged pairs — LST-SOL, stable-stable, wrapped):**
107 pools, **identical** result (median 0.91% @ $1k, 100% under 3%). The verdict does **not**
lean on deep-but-non-speculative pairs like mSOL/SOL.

## Capacity — the honest size limit

Friction is size-dependent, and that is the real constraint going forward (not a wall, a
ceiling):

- **≤ $1,000/position:** ~1% friction, all 113 pools. Comfortable.
- **$5,000:** median 2.0%, but only 73% of pools under 3% (the shallower half starts to bite).
- **$10,000:** median 3.3%, p90 7.2% — only 47% under 3%. Viable on the deeper pools only.
- **$50,000:** median 12.7% — too large for this universe's median $1.4M pool.

So Track M is a **small-to-mid-size book**: per-position notional should scale with each pool's
depth (≈ ≤ 0.4% of reserve keeps friction ~1%), not a flat dollar amount. M4 (capacity, GO
only) would formalise this; for the kill-gate it is enough that a low-cost operating size
exists on every pool.

## Context — the playing field is large relative to the cost (Law 1's inequality)

Law 1 is `gross return > cost drag`. M2 measures the cost side; the gross side is sized here
only to confirm the costs aren't the whole move: the **median absolute 5-day move** across these
pools is **~6.0%**, ~7× the $1k round-trip friction of 0.9%. This is **not an expectancy claim**
— it says nothing about *direction* or whether any signal can capture it (that is M3). It only
establishes that friction no longer eats the entire available move, as it did in Iteration 1.

## Caveats / honest limits (carried into M3)

1. **Survivorship-biased universe.** The 113 pools are today's survivors (CoinGecko exposes no
   as-of param). This is irrelevant to a *cost* measurement — depth and fees don't depend on
   survival — but it remains true that any *expectancy* M3 finds on this control can only be a
   NO-GO/"unproven", never a GO. M2 changes nothing about that asymmetry.
2. **Depth is today's snapshot, applied as a constant** to ~6mo of history. The ×0.5 depth
   sweep covers a uniformly-shallower past; it does not cover a pool that was *much* thinner
   early in its life. Real historical reserve is not in the free tier. Conservative mitigation:
   size by current depth and keep positions ≤ ~0.4% of reserve.
3. **`reserve_usd × 0.5` is a full-range xy=k proxy.** For concentrated-liquidity pools (Orca
   whirlpools) active depth near the mid is *higher*, so we **overstate** impact — the friction
   here is, if anything, pessimistic.
4. **No swap-level data for these pools** (OHLCV only), so we cannot yet add the Direction-3
   orchestrator/rug overlay at the trade level here. Not needed for the cost question.

## Verdict & next step

**Law 1 (the cost wall) is escaped** on the mid-cap deep-pool universe at realistic position
sizes (~1% round-trip friction at ≤ $1k, robust across fee/depth sweeps and after dropping
pegged pairs). Track M is **not** dead on arrival — the M2 gate is **PASS**. Proceed to **M3**:
the transparent signal battery (TS/XS momentum, mean-reversion, breakout) through the profiler,
with the full kill-gate (`docs/iteration-2-strategy.md` §3). M3 must still clear the *other*
five kill-gate criteria — profitable-after-cost expectancy, point-in-time, beats blind+random,
robust, enough fires — and on a biased control can only produce a NO-GO/"unproven". M2 has only
removed the structural disqualifier that killed Iteration 1; it is necessary, not sufficient.

## What was built

- **`src/autocrypt/midcap/costs.py`** — the recalibration: `round_trip_friction` (flat-price
  pure execution cost via the unchanged `ExecutionModel`), `compute_pool_frictions`,
  `summarize_frictions`, `recalibrate_costs`, read-only universe loader, a symbol-based
  speculative/pegged classifier, and a volatility-context helper.
- **CLI `midcap-costs`** — friction grid + fee/depth sensitivity + volatility context;
  read-only; `--speculative-only`, `--fee-bps`, `--fixed-cost-usd` flags.
- **Tests:** `tests/test_midcap_costs.py` (thin-vs-deep friction, monotonicity in size,
  fee/depth sensitivity, pegged-pair classifier, aggregation/percentiles).
