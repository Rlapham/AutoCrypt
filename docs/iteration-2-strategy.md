# Iteration 2 — Strategy & Phase Plan

> Iteration 1 reached a **conclusive NO-GO** for automated short-hold low-cap Solana and was
> shelved (see `docs/phase-3-synthesis.md`). This document is the strategy for **Iteration 2**,
> the pivot. `Project_spec.md` remains the authoritative state; this doc is the detailed plan it
> points to.

## 0. The thesis, in one line

**Stop trying to predict fresh-launch pumps** (Iteration 1 proved that corner is structurally a
loser), and instead pursue edges that **escape the two structural laws we discovered** — via
**deep-pool, longer-horizon** trading. Two tracks run concurrently:

- **Track M (Option 2) — Mid-cap deep-pool momentum/mean-reversion. IMMEDIATE & PARALLEL.**
  Testable *now* with free data we already ingest. Fast, cheap read; also a control on whether our
  machine can find *any* edge where costs are survivable.
- **Track G (Option 1) — Graduation-momentum + days-horizon "accumulator" cohort. THE MAIN GOAL.**
  Higher ceiling, more tool reuse, but gated on a multi-day dataset that must **start accruing now**.

Track M buys us a quick signal while Track G's long pole (data) fills in.

## 1. What Iteration 1 proved (the design constraints)

These are *laws* — they held across every signal, sweep, and labelling choice — and every
Iteration-2 idea must clear them:

- **Law 1 — the cost wall.** Fresh-launch ≤120s drift ≈ 0% gross; round-trip cost ~20–28% (own
  impact on thin pools). **An edge must have gross return > cost drag.** ⇒ go where pools are deep
  (cost ↓) and/or holds are long (fixed cost amortised, larger moves captured).
- **Law 2 — the smart-money inversion.** The wallets that most reliably precede fast pumps are the
  pump apparatus; following them = exit liquidity. Copy-trading is reactive by construction. ⇒ don't
  be late retail; either find a *different* cohort at a *longer* horizon, or use the orchestrator
  signal *defensively* (fade/avoid).

## 2. The asset we carry into Iteration 2

The verdict machine and its discipline transfer wholesale; only the cohort/horizon/venue change:

- **The profiler** (`src/autocrypt/profiler/`): survivorship-complete, point-in-time,
  realistic-cost (fees + own impact, both legs), with frequency-vs-expectancy curve, permutation
  test, and depth/horizon/rug sweeps. Horizon and signal_field are already parameterised.
- **The wallet-attribution book** (`src/autocrypt/attribution/`): point-in-time, survivorship-safe,
  re-labellable (just change the "success" definition) — reused as-is in Track G, and as the
  **orchestrator rug/avoid overlay** (Direction 3) in both tracks.
- **Free read-only data adapters** (Phase 1): DexPaprika + GeckoTerminal (+ CoinGecko) — already
  cover liquid-token OHLCV, which is exactly what Track M needs at $0.
- **The honesty discipline** (CLAUDE.md): kill-gate first, never tune to a positive, report nulls
  plainly, survivorship + no-look-ahead are load-bearing.

## 3. The shared kill-gate bar (unchanged from Iteration 1)

A track is **GO** only if a point on its frequency-vs-expectancy curve is, *simultaneously*:
1. **Profitable after realistic costs** (net expectancy > 0 by a margin, not within noise);
2. **Point-in-time** (signal uses only `knowable_at ≤ T`) and **survivorship-complete** (universe
   enumerated independent of survival; dead/delisted/rugged included);
3. **Better than blind** (beats fire-on-everything) **and better than random** (permutation p low,
   after a multiple-comparison discount);
4. **Robust** across the sensitivity sweeps (cost/depth, horizon, regime/time-window);
5. Backed by **enough fires** for the statistics to mean something (no n=19 reruns).

Anything less is a NO-GO, reported plainly. No track advances to paper/live on a tuned number.

---

## 4. Track M (Option 2) — Mid-cap deep-pool — DETAILED PHASES (immediate, parallel)

*Goal: a fast, cheap, honest kill-gate on whether standard momentum/mean-reversion clears costs in
an arena where Law 1 is satisfied (deep pools). Uses free data we already ingest — no waiting.*

- **M1 — Survivorship-safe mid-cap universe & point-in-time data.** ⚠️ **#1 validity risk.** The
  naive move (backtest today's top-N liquid tokens) is massively survivorship-biased. We need a
  **point-in-time universe**: the set of tokens meeting a liquidity/mcap threshold *as of each
  historical date*, including those that later collapsed/delisted. **First task: verify whether the
  free GeckoTerminal/CoinGecko tiers expose historical universe membership** (echoing our hard-won
  rule: confirm provider access before depending). Define the threshold (e.g. liquidity ≥ $X and/or
  mcap band), ingest OHLCV (+ swaps where available) point-in-time, run `qc`. Deliverable: a
  survivorship-complete mid-cap event store.
- **M2 — Deep-pool cost recalibration.** Re-validate the execution/liquidity model for deep pools:
  own-impact should be small, so fees + spread dominate. **Confirm empirically that cost drag is now
  low single digits** (i.e. Law 1 is actually escaped) before trusting any expectancy. If cost drag
  is still large, stop and re-scope (the universe isn't deep enough).
- **M3 — Signal battery + KILL-GATE.** Implement a small battery of transparent deep-pool signals
  through the profiler: **time-series momentum / trend**, **cross-sectional momentum** (rank across
  the universe), **mean-reversion**, and a **volatility/volume breakout**. Run the
  frequency-vs-expectancy curve + permutation + sweeps per §3. **GO/NO-GO.** (Fold in the Direction-3
  orchestrator-avoid overlay if swap-level wallet data is available for these tokens.)
- **M4 — (GO only) Out-of-sample robustness + capacity.** Multiple disjoint time windows,
  regime splits (trend vs chop), and a capacity/slippage-at-size analysis (mid-caps are deeper but
  not infinite). Only a track that survives this proceeds to the shared downstream (§6).

## 5. Track G (Option 1) — Graduation-momentum + accumulator cohort — THE MAIN GOAL (parallel)

*Goal: the higher-ceiling thesis — enter graduated/surviving tokens at multi-hour/day horizons when
a re-labelled "accumulator" cohort is building, not when orchestrators are pumping. Maximal reuse of
the attribution book + profiler. Gated on data that must start accruing immediately.*

- **G0 — Start durable long-horizon collection NOW (the long pole).** Stand up a durable forward
  collector (the current `nohup` collector does not survive reboot — a launchd/cron job is the
  durable form) accumulating **multi-day point-in-time per-token data** for a graduation cohort, and
  implement **graduation-event detection** (the discrete liquidity-deepening milestone). Kicking
  this off in parallel with Track M is the whole point: the data ripens while M runs.
- **G1 — Re-labelled accumulator attribution.** Redefine the attribution "success" from
  "+X% in 300s" to **"survives and appreciates over N days."** Rebuild the wallet book on that label
  to surface a *followable* cohort (early accumulators / discretionary), distinct from the
  orchestrators Iteration 1 found. Re-validate point-in-time + survivorship.
- **G2 — Graduation-momentum KILL-GATE.** Profiler at multi-hour/day horizons on graduated tokens,
  entry conditioned on graduation + accumulator-cohort buying, with the orchestrator-fade overlay as
  a rug/avoid gate. Frequency-vs-expectancy + permutation + sweeps per §3. **GO/NO-GO.**
- **G3 — (GO only) Attribution model proper + robustness**, then rejoin the shared downstream (§6).

## 6. Shared downstream (unchanged from Iteration 1; applies to whichever track passes its gate)

Only reached by a track that is GO through its robustness phase. These carry over verbatim:
- **Paper trading on live data** — forward-test; divergence from backtest ⇒ hunt the look-ahead bug.
- **Execution + risk/guardrail layer + kill switches** — *build the brakes before the engine*:
  circuit breakers, position/drawdown caps, kill switch, custody plan. All simulation/paper.
- **Small live capital → monitored scale-up → decay monitoring.** Heavily human-gated. **RED.**

## 7. Cross-cutting: Direction 3 overlay

The Iteration-1 attribution book is a validated, point-in-time, survivorship-safe **detector of
pump-orchestrator wallets**. Reuse it as a **rug/avoid gate** (stronger than the current swap
heuristic stub) for *both* tracks, and (lower priority) research whether orchestrator *distribution*
is a tradeable exit/fade. Not a standalone strategy — a multiplier on the others.

## 8. Autonomy & safety (carried over)

GREEN: all read-only/simulated/backtest/code, free-tier data, building either track's harness. YELLOW:
any paid data tier (bring a quote + cap), schema/architecture decisions later phases hard-depend on
(e.g. the mid-cap universe definition, the accumulator label), and each track's GO/NO-GO sign-off.
RED unchanged (keys, real funds, mainnet tx, disabling safety controls, secrets-in-git, geo-evasion).

---

## ▶ Kickoff prompt for the next session — paste into a fresh Claude Code terminal

```text
Read CLAUDE.md, then Project_spec.md, then docs/iteration-2-strategy.md. Confirm back to me
in 3-4 sentences where we are and this session's goal before doing anything else.

CONTEXT: Iteration 1 is a conclusive NO-GO (shelved). We have pivoted to Iteration 2, which
runs two concurrent tracks against the same kill-gate machine: Track M (mid-cap deep-pool
momentum/mean-reversion -- IMMEDIATE & PARALLEL, testable now on free data) and Track G
(graduation-momentum + days-horizon accumulator cohort -- THE MAIN GOAL, gated on a multi-day
dataset that must start accruing now).

THIS SESSION = Phase M1 (Track M) + kick off G0 data collection in parallel.
  Track M / M1 (do first -- it's the cheap fast read):
    1. RESOLVE THE #1 VALIDITY RISK: can the free GeckoTerminal/CoinGecko tiers give a
       SURVIVORSHIP-SAFE point-in-time mid-cap universe (tokens meeting a liquidity/mcap
       threshold AS OF each historical date, incl. ones that later died)? Verify access
       BEFORE building. If not free, surface it as a YELLOW data-access decision -- do not
       silently backtest today's top-N (survivorship-biased = invalid).
    2. Define the mid-cap universe threshold (YELLOW: later phases depend on it -- propose,
       get a nod). Ingest point-in-time OHLCV via the existing free adapters; run qc.
  Track G / G0 (kick off in parallel so data ripens):
    3. Stand up a DURABLE forward collector (launchd/cron, survives reboot) for a graduation
       cohort + graduation-event detection. Start it accruing.
Then M2 (deep-pool cost recalibration -- confirm cost drag is actually low single digits)
once M1 data exists.

Kill-gate bar (docs/iteration-2-strategy.md §3): profitable after realistic costs AND
point-in-time AND survivorship-complete AND beats blind+random AND robust across sweeps AND
enough fires. Never tune to a positive. Report nulls plainly.

Autonomy: GREEN for code/backtest/free-data. YELLOW: paid tiers (quote+cap), the universe
definition + accumulator label, and each GO/NO-GO. RED unchanged. Do NOT start paper/live.
```
