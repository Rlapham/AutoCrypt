# Phase 2 — Session Synthesis (Signal-frequency & expectancy profiler — THE KILL-GATE)

*Synthesis of the Phase 2 session. Authoritative state lives in `Project_spec.md`; this
captures what was built, what the evidence says, the decisions taken and why, what is still
open, and the next-session kickoff. **The GO/NO-GO result is the headline — and it is a
YELLOW gate awaiting human sign-off, not a settled verdict.***

## Goal (recap)
Answer, with honest evidence: **does a profitable operating point exist for an on-chain
pre-run-up signal on low-cap Solana, after realistic slippage / fees / own-price-impact, on a
survivorship-proof, point-in-time dataset?** Honesty over optimism — a null result is valid;
do not tune to manufacture a positive.

## Headline (read this first)
1. **The profiler is built, tested, and point-in-time-correct** — the real Phase 2 machinery
   (replay-gated derivative signals → constant-product execution-cost model with own price
   impact on both legs → survivorship-complete frequency-vs-expectancy curve → permutation
   significance test → sensitivity sweeps). 27 tests green, ruff + mypy clean.
2. **On the existing dataset the result is "promising but unproven."** Blind entry loses hard
   (**−12%/trade at 60s**, because realistic costs add **~20 points** of drag to a +7.6%
   marked drift). But the derivative signal **does select better-than-random entries**: at the
   75th-pct threshold, **+6.9% net expectancy over 19 fires, 47% hit, permutation p = 0.007**
   (survives a 4-threshold Bonferroni discount, ≈0.028).
3. **But this CANNOT be the kill-gate verdict.** The dataset is a **~19-minute, single-window,
   launch-phase snapshot** (83 pools). It measures intra-first-minutes dynamics, not "did this
   token run up over hours/days." n is tiny, depth is *estimated* not measured, and 26 fires
   are censored. The honest call is **conditional GO to acquire a proper dataset and re-run the
   now-built profiler — not GO-live, not STOP.** Both YELLOW gates are now live for the human.

## What was built (state of the code)
New package `src/autocrypt/profiler/` + CLI `autocrypt profile` + `tests/test_profiler.py`:

- **`dataset.py`** — loads the survivorship-complete universe (enumerated from `pool_created`,
  outcome-independent) and each pool's swaps as epoch-seconds rows carrying BOTH `event_time`
  and `knowable_at`, so the no-look-ahead discipline is enforceable in code.
- **`signals.py`** — candidate signal as **derivatives** (Project_spec §2): a transparent
  composite of buy-pressure *acceleration*, unique-buyer *growth*, and trade-rate *growth*,
  computed over a lookback window split into older/recent halves. Windowed by `knowable_at` —
  future records cannot enter the signal (pinned by `test_signal_excludes_future_knowable`).
- **`liquidity.py`** — we have **no direct liquidity data** (`init_liquidity_usd` is null;
  LiquidityChange/Holder unpopulated), so depth is *inferred* from observed price impact via
  constant-product inversion (`Q ≈ dq/(√(p'/p)−1)`), kept as a rolling median. It is an
  ESTIMATE — hence the depth-sensitivity sweep.
- **`execution.py`** — constant-product round-trip charging swap fees + a fixed priority/MEV
  tip + the curve slippage (= own price impact) on **both** legs; exit into a possibly-thinner
  pool is naturally harder. Returns net vs marked return and the cost drag.
- **`rugfilter.py`** — pre-trade rug gate **stub**, honestly labelled: swap-derived heuristics
  (single-wallet buy dominance; price-collapsed-from-peak) only, because TokenMeta/Holder data
  isn't populated yet. Wired as a gate input; the report shows on/off.
- **`profiler.py`** — the instrument: walk candidate decision times per pool, fire when the
  signal clears a threshold (and the rug gate passes), simulate the round-trip, record net
  return. One open position per pool (cooldown = horizon). Trades whose horizon runs past the
  data end are **censored and reported, never silently scored**.
- **`report.py`** + `autocrypt profile` — renders `docs/phase-2-profile.md`: the curve, a blind
  baseline, horizon/depth/rug sweeps, and a seeded permutation test.

## The evidence (full table: `docs/phase-2-profile.md`)
Universe 80 pools (57 with enough history), 60s horizon, $250/trade, fees + own impact both legs.

| threshold | fires | hit | **net expectancy** | marked | cost drag |
|---|---|---|---|---|---|
| blind | 83 | 33.7% | **−12.07%** | +7.58% | +19.65% |
| p75 (0.605) | 19 | 47.4% | **+6.93%** | +28.26% | +21.33% |
| p90 (1.597) | 9 | 55.6% | **+3.57%** | +19.92% | +16.35% |

- **Cost drag is the dominant fact** (~20 pts/round-trip), and it is robust: the depth sweep
  (0.5×–2×) keeps blind expectancy negative throughout (−19% → −7.6%). The "blind entry loses"
  conclusion is not a depth-estimate artifact.
- **The signal effect is real but small-sample**: monotone hit-rate climb (34%→47%→56%),
  expectancy crosses zero near the 75th pct, and the permutation test rejects "random selection"
  at p=0.007 (n=19). The highest-expectancy points (n=1, 4, 9) are noise — ignore them.
- **Horizon matters**: 120s blind ≈ 0% vs 30s −15% — longer holds let drift overcome fixed costs.
- **Rug gate helps**: ON −12% vs OFF −16% (the stub removes some losers).

## Why this is not yet a GO/NO-GO answer (the honest caveats)
1. **~19 minutes, one window, launch-phase only.** Outcomes are first-minutes price changes,
   not the run-ups the thesis is about. This is the Phase 1 coverage caveat biting exactly where
   it was predicted to.
2. **Tiny n at the profitable operating point** (19 fires). Real money needs hundreds.
3. **Depth is inferred, not measured** — the operating-point *profit* (unlike the blind *loss*)
   would move with the depth assumption.
4. **Censoring** (26 fires) is administrative here (window cut, not pool death); on a real
   multi-day set, horizon-censoring would correlate with rugs and must be handled (mark-to-rug,
   not drop).
5. **Multiple thresholds/horizons were tried** — the p-value carries a multiple-comparison tax.

## Key decisions & why
- **Express the signal as a composite of derivatives, rules-based and transparent** (not ML, not
  levels) — per Project_spec §2; ML is deferred until there's clean labelled history.
- **Infer depth from price impact** rather than fabricate a liquidity number, and **sweep it** —
  honesty about the biggest modelling assumption.
- **Generate trades once at threshold −∞, then filter** — the curve is exact and the expensive
  point-in-time replay is single-pass.
- **Permutation test against random selection**, a stricter bar than beating blind entry, to
  guard against "the signal is just picking volatile names."
- **Did NOT spend money or sign up for any paid tier** (YELLOW #1 deferred to human, below).

## Open questions / forks for the human (BOTH YELLOW — see Project_spec §8)
- **YELLOW #2 — the GO/NO-GO sign-off.** My recommendation: **CONDITIONAL GO** — the machinery
  is sound and the preliminary signal is real enough to justify the cost of a proper dataset, but
  do **not** start Phase 3 modelling on a 19-minute window. Decision the human owns: which shape
  the evidence selects (automated-Solana / manual-ETH / stop). I read it as "not stop, not yet
  commit — fund the real test."
- **YELLOW #1 — the dataset.** To actually answer the gate we need a survivorship-complete,
  multi-day, swap-level Solana history. Two paths (recommendation: do both):
  - **Free: forward-collection.** Run `autocrypt poll` for 1–2 weeks to accumulate a gap-free
    recent window. $0, but wall-clock-slow and only collects *going forward*.
  - **Paid: Bitquery archive** for *deep historical* swap-level backfill (the only way to get
    weeks of finalized history *now*). Phase-1 eval: free is trial-only (~1k–10k points,
    10 req/min); the commercial/archive plan is **custom-quoted — pricing must be re-verified at
    build time**. Concrete ask to bring back: a costed quote for ~14 days × SOL+USDC-quoted
    low-cap launches, enumerate-by-creation. **No spend without explicit human authorization.**

## Decisions received this session (human sign-off)
- **YELLOW #2 — GO/NO-GO: CONDITIONAL GO.** Do not start Phase 3 on the 19-min window; acquire a
  trustworthy multi-day dataset, re-run the profiler, then decide the shape.
- **YELLOW #1 — dataset: BOTH.** Start free `poll` forward-collection now, AND bring a costed
  Bitquery quote for approval before any spend. (Spend itself is still un-authorized.)

## YELLOW #1 follow-through — Bitquery ask + free-poll recipe
**Bitquery pricing is sales-quoted, not public** (verified at build time, June 2026):
`bitquery.io/pricing` lists only a **Commercial Plan = "talk to our team"** and **Datashares/
Exports = custom**; the free **Developer** tier is 1k–10k points (first month), **10 req/min,
10 rows/request** — unusable for a bulk backfill. Points = "resources consumed × price per
unit", no published points-per-dollar. **So a real number requires emailing sales@bitquery.io.**

*Concrete scope to request a quote on (sized so sales can price it):*
- Solana **DEXTrades + pool-creation** events, **SOL- and USDC-quoted** low-cap pools,
  **enumerate-by-creation** over a **contiguous ~14-day** window (survivorship-complete).
- Order-of-magnitude volume: ~200–270 *tradeable* graduations/day (Project_spec §3) ⇒
  **~3–4k pools** over 14d; at a few hundred–few thousand swaps each ⇒ **~3–5M swap rows**.
- One-time **historical archive / Datashare export** (Snowflake/BigQuery/S3) is acceptable and
  likely cheaper than paging the GraphQL API at 10 rows/request; optionally an ongoing stream.
- Provider-agnostic by design: a Bitquery adapter emits the same canonical records, so this is a
  swap-in, not a rewrite (Phase 1 decision).

*Free forward-collection (start now, $0, runs in parallel):* `autocrypt poll` is verified working
(smoke test this session wrote 100 records, idempotent on `event_id`). For a durable 1–2 week run,
run it unattended, e.g.:
```bash
# every 60s, run until stopped; logs to data/poll.log
nohup uv run autocrypt poll --interval 60 --iterations 0 --pages 2 >> data/poll.log 2>&1 &
# (or wrap the same command in a launchd .plist / cron @reboot for restart-survival)
```
Caveat: `poll` only collects *going forward* — it builds a clean recent window over wall-clock
time; it cannot recover the deep past (that's what the Bitquery archive is for).

## Honesty log (what was caught / corrected this session)
- A synthetic profiler test initially fired 0 trades — the test's price moves sat below the
  depth-detector's `min_ratio_move`, so no depth was estimated. This is *correct* behavior
  (pools whose price barely moves yield no depth signal); the test data was fixed, not the code.
- Resisted the temptation to headline the +35% (n=1) or "best threshold" number — it's overfit.
  The honest operating point is the +6.9% at n=19 with its p-value and caveats.

## Suggested commit plan (human runs git — see CLAUDE.md §4)
Work branch: **`phase-2`** (off `Phase1`/`main` per the human's convention). Suggested commits:
1. **feat(profiler): point-in-time signal/execution/liquidity/rug modules**
   — `src/autocrypt/profiler/{__init__,dataset,signals,liquidity,execution,rugfilter}.py`.
2. **feat(profiler): frequency-vs-expectancy profiler + report + `autocrypt profile`**
   — `src/autocrypt/profiler/{profiler,report}.py`, the `profile` command in
     `src/autocrypt/cli.py`.
3. **test(profiler): execution math, liquidity inversion, no-look-ahead discipline**
   — `tests/test_profiler.py`.
4. **docs(phase-2): profile output, synthesis, spec/CLAUDE updates**
   — `docs/phase-2-profile.md`, `docs/phase-2-synthesis.md`, `Project_spec.md`, `CLAUDE.md`.

`docs/phase-2-profile.md` is regenerable via `uv run autocrypt profile`. Do not commit `data/`.

---

## ▶ Kickoff prompt for the next session — paste into a fresh Claude Code terminal

```text
Read CLAUDE.md, then Project_spec.md, then docs/phase-2-synthesis.md, then
docs/phase-2-profile.md. Skim docs/event-schema.md + docs/data-dictionary.md. Confirm back to
me in 3-4 sentences where we are and this session's goal before doing anything else.

CONTEXT: Phase 2 built the frequency-vs-expectancy profiler (the kill-gate instrument) and ran
it on the Phase 1 store. Result: blind entry loses (-12%/trade; ~20pts cost drag), but the
derivative signal selects better-than-random entries (+6.9% net over 19 fires, permutation
p=0.007). PROMISING BUT UNPROVEN — the data is a ~19-minute launch-phase snapshot, not real
run-up horizons. The human signed off CONDITIONAL GO + acquire a real dataset BOTH ways
(free poll now + a costed Bitquery quote). No Phase 3 modelling until the real-data curve is
signed off.

GOAL THIS SESSION: get a trustworthy multi-day dataset flowing, then re-run the profiler.
  1. Confirm the free `autocrypt poll` forward-collection is running and accumulating (recipe in
     phase-2-synthesis.md "YELLOW #1 follow-through"); report how much it has gathered and the
     effective window. Keep it running.
  2. Bitquery: ask me whether I obtained a quote from sales (pricing is NOT public). 
     - If I authorize a specific paid spend: build the Bitquery adapter (provider-agnostic, same
       canonical records — a swap-in, not a rewrite), backfill the agreed universe
       (enumerate-by-creation, SOL+USDC, ~14d), `autocrypt qc` it.
     - If not yet: proceed on the poll dataset alone and note the coverage limit honestly.
  3. RE-RUN `autocrypt profile` on whatever trustworthy dataset exists; present the UPDATED
     frequency-vs-expectancy curve + permutation significance. That updated GO/NO-GO curve is the
     headline. Watch for: horizon-censoring now correlating with real pool deaths/rugs (handle
     mark-to-rug, don't silently drop); depth still estimated; check the signal holds out-of-window.

Autonomy: GREEN for all read-only/simulated/backtest/code work (incl. building the Bitquery
adapter and running poll). YELLOW: any paid spend / signup — do NOT sign up or spend without an
explicit per-amount authorization (the "bring a quote" approval is NOT a spend approval); and the
GO/NO-GO re-confirmation on the real-data curve before Phase 3. RED unchanged (no keys/funds/
live/safety-bypass).

First concrete step: report the poll collection status and the Bitquery-quote question, then
re-run `autocrypt profile` on the best available trustworthy data.
```
