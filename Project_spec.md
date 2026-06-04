# Project Spec — Solana Run-Up Detector

**Authoritative source of project state.** Updated at the end of every session. If this doc and any other source disagree, this doc wins (except for live external facts like API pricing, which must be re-verified at build time).

---

## Current status

- **NOW: ITERATION 2 — M3 done: Track M daily signal battery is a NO-GO (kill-gate closed). YELLOW
  fork open: pivot to Track G (main goal). Track M's forward snapshot keeps accruing for an
  unbiased re-test.**
  Iteration 1 is a **conclusive, shelved NO-GO** for automated short-hold low-cap Solana (both
  signals lose; cause is structural: ≈0% short-hold drift vs ~20–28% costs). **Iteration 2** reuses
  the verdict machine via two concurrent tracks: **Track M (mid-cap deep-pool, immediate)** and
  **Track G (graduation accumulator, the main goal)**. Full plan: **`docs/iteration-2-strategy.md`**.
  - **M1b (2026-06-03) — the universe blocker is RESOLVED, free.** The mcap-ranked **inverted
    funnel** (CoinGecko `/coins/markets` Solana-ecosystem, FDV band → `/coins/list` id→Solana-mint →
    GeckoTerminal deepest pool → reserve ≥ $500k) yields **n=113 in-band** mid-cap deep-pool names
    (vs M1's n=1): 786 FDV-in-band candidates → 627 with a pool → 113 in-band (16 ≥ $5M reserve,
    45 ≥ $2M, 72 ≥ $1M). FDV is taken authoritatively from CoinGecko (fixes M1's SOL-quoted-pool
    FDV confusion). **No paid pull needed → the YELLOW depth-vs-paid fork is moot.** Biased-control
    OHLCV ingested: **16,177 daily bars / 113 pools / ~6mo depth, `qc`-clean (no look-ahead)** in
    `data/autocrypt_midcap.duckdb` (snapshot `source='coingecko_mcap_ranked'`). Still
    survivorship-BIASED → can only NO-GO/"unproven", never a GO. Built `providers/coingecko.py`,
    `GeckoTerminal.token_pools_raw`, `midcap/mcap_rank.py`, `load_in_band_pools` /
    `build_control_from_pools`, CLI `midcap-enumerate` + `midcap-control-snapshot`. Two live bugs
    caught+fixed (keyless CoinGecko 429 → graceful partial; GeckoTerminal 404 → no-pool, was
    crashing the run). **74/74 tests green, ruff clean.** See **`docs/phase-M1b-synthesis.md`**.
  - **M2 (2026-06-03) — deep-pool cost recalibration: PASS, Law 1 escaped.** Reused the SAME
    constant-product `ExecutionModel` (fees + own impact, both legs) but fed depth **directly from
    `reserve_in_usd`** (median in-band $1.44M) instead of inferring it from thin-pool swaps.
    Headline = **round-trip friction at flat price** (pure execution cost — the exact like-for-like
    with Iteration-1's 20-28%): **~0.8-0.9% median at $100-$1k positions, 100% of the 113 pools
    under 3%.** Robust to pump.fun 100bps fee (2.3%), depth x0.5 (1.19%), and dropping the 6
    pegged/pegged pairs (unchanged). Sanity anchor: the engine reproduces 17.2% on an Iteration-1-
    like $20k pool — model identical, pools just deep. The one real constraint is **capacity**, not
    a wall: per-position notional should scale with depth (~<=0.4% of reserve keeps friction ~1%;
    $10k+ only on the deeper half, $50k too big for the median pool). NOT an expectancy/GO — costs
    only (survivorship is irrelevant to a cost measurement). Built `src/autocrypt/midcap/costs.py`
    + CLI `midcap-costs` + 9 tests. **83/83 green, ruff clean.** See `docs/phase-M2-cost-profile.md`
    + `docs/phase-M2-synthesis.md`.
  - **M3 (2026-06-03) — signal battery + KILL-GATE: NO-GO on all four signals.** Built the
    OHLCV-bar adapter (`midcap/bars.py`), the transparent battery (`midcap/barsignals.py`: TS
    momentum, XS momentum, mean-reversion, volume-gated breakout — long-only, point-in-time),
    and a day-native kill-gate engine (`midcap/killgate.py`) that reuses the M2 `ExecutionModel`
    verbatim, capacity-scales size to ≤0.4% of reserve, and runs the frequency-vs-expectancy
    curve + seeded permutation test + robustness sweeps (horizon/depth/lookback/early-vs-late).
    On the 92-pool speculative-only biased control (~2,855 fires/signal): **every signal is a
    NO-GO.** None beats random after a multiple-comparison discount (best discounted p=0.22,
    mean_rev); blind expectancy is slightly negative (−0.3% to −0.8%) because realistic
    capacity-scaled **cost drag ~2% ≥ the ~1.3% survivorship-inflated 5-day marked drift** — Law
    1's `gross > cost` still isn't met at tradeable size. The tempting tight-threshold tails
    (mean_rev +11%, n=143) are artifacts: **negative median**, tiny n, regime-fragile (early half
    negative), depth-fragile (depth×0.5 → −2%). The failure does NOT lean on survivorship — the
    gate closed on its own statistics first. CLI `midcap-killgate` + 14 tests. **97/97 green,
    ruff clean.** See `docs/phase-M3-killgate.md` + `docs/phase-M3-synthesis.md`. **YELLOW fork
    open (operator): close Track M's daily price-only battery (recommended) and pivot to Track G
    — the main goal — letting the survivorship-safe forward snapshot accrue for an unbiased
    re-test; do NOT tune the battery to a positive.**
  - **M3-precursor note:** the NO-GO is specifically about *daily, price-only* signals on a
    biased control. It does not test intraday resolution or richer features (liquidity velocity,
    holder flow), which this OHLCV-only universe can't see.
  - **M1 (2026-06-03) — survivorship risk resolved + a second structural finding.** Verified live:
    a **survivorship-safe point-in-time mid-cap universe is NOT free** — GeckoTerminal exposes only
    *today's* top ~200 pools (no as-of param) + ~6mo daily / ~41d hourly OHLCV for *survivors*;
    backtesting today's top-N is the survivorship trap. **Operator YELLOW resolved:** free
    survivorship-**BIASED** control + start forward snapshots, **no paid pull** (bias only inflates →
    a biased backtest can only NO-GO/“unproven”, never a false GO). **Band signed off:** reserve_in_usd
    ≥ $500k AND FDV ∈ [$1M,$250M]. **BUT** that band yields **n=1** from the free top-pools endpoint —
    Solana liquidity is **barbelled** (majors deep, rest thin), so volume-ranked top-pools is the
    *wrong enumeration source* for mid-caps. Built `src/autocrypt/midcap/` (parse + band + forward
    snapshot + biased-control ingest) + CLI `midcap-snapshot`/`midcap-control` + 4 tests (**67/67
    green, ruff clean**). Forward snapshot #1 taken (clean series started); biased control not
    meaningfully run at n=1. See **`docs/phase-M1-synthesis.md`**.
  - **M1b (done 2026-06-03) — usable universe achieved (n=113, free).** mcap-ranked enumeration
    (CoinGecko `/coins/markets` → Solana mint → deepest GeckoTerminal pool → depth filter), the
    inverted funnel. Yielded 113 in-band names at the signed-off band — the YELLOW loosen-vs-pay
    fork was not needed. See the M1b bullet above + `docs/phase-M1b-synthesis.md`.
  - **G0 (done, with caveat):** the old nohup collector was **dead**; rebuilt durable (launchd) but
    **macOS TCC blocks it** (repo under `~/Documents`). Operator chose **interim nohup** (running,
    accruing to `data/autocrypt_graduation.duckdb`) — **dies on reboot**; durable fix = grant Full
    Disk Access to `uv` or relocate the repo. A second nohup takes daily Track-M universe snapshots.
  *Everything below is Iteration-1 history, retained for context.*

- **Phase:** 2/3 (KILL-GATE) — **NO-GO now STRONGER: the claimed wallet-attribution edge was BUILT
  and tested on real data and ALSO loses badly.** Latest session (Phase 3): rather than idle a month
  waiting on the Dune free-credit reset, the operator chose to build the rest of the architecture and
  validate the plan on the data in hand. Built the **lead-weighted wallet-attribution model**
  (`src/autocrypt/attribution/`) — the project's *actual claimed defensible edge* (§2), which the
  kill-gate had never tested — and ran it on the same survivorship-complete, point-in-time,
  cost-realistic profiler (`autocrypt profile --mode attribution`). Result on the real cohort
  (**995 fires / 262 pools**): **blind −28.1%, best-threshold −27.3%, permutation p=0.117 (n.s.)**;
  and **tightening the signal toward "smarter" money makes returns monotonically WORSE (→ −82%)** —
  it anti-predicts (the manufactured-pump / exit-liquidity failure mode of §2, now shown on-chain).
  **The decisive cause is structural and signal-independent: mean no-cost 60s drift ≈ 0%**, so
  ~20–28% round-trip costs on thin fresh-launch pools guarantee a loss for ANY entry signal.
  Negative across run-up defs (+50/+100/+200%), depth (×0.5–×2), horizon (30/120s), rug on/off.
  **Architecture/plan validated end-to-end (63 tests green, ruff clean); the EDGE is negative on this
  data.** Honest limit unchanged: ONE ~1h creation window; in-window wallet histories are short.
  **✅ YELLOW DECISION RESOLVED (2026-06-03): the operator chose to SHELVE the automated short-hold
  Solana strategy.** Kill-gate is closed NO-GO; no Phase 4–6, no live capital, no pivot build started.
  The attribution model + profiler harness are retained for a possible future longer-horizon thesis
  or the $0 Dune-reset confirmation, but no further work is committed. No money spent. See
  `docs/phase-3-synthesis.md` + `docs/phase-3-attribution-dune.md`.
  *Prior (Phase 2g, 2026-06-02):* credit-reset timing check — not reset (day 0); see
  `docs/phase-2g-synthesis.md`.
  *Prior (Phase 2f):* the conditional-GO on the derivative composite FLIPPED to a provisional NO-GO
  on real data (blind −16%, signal −15%, n=1,763). The operator's
  Dune key + saved cohort query (`query_id 7637616`) arrived; the real-data backfill + profiler ran.
  On the real cohort (**616 pools, n=1,763 fires @60s**): **blind −15.99%, best-threshold signal
  −15.16%** (still a loss), signal gets *worse* as you tighten it, and it's **negative across every
  sweep** (depth ×0.5–×2 = −22.6%/−16%/−11.4% never flips; horizons 30/60/120s; rug on/off) and the
  permutation test. The Phase-1 snapshot's +6.8%/p=0.008 was **n=19 small-sample noise.** The result
  is **valid** (profiler censors forward-truncated entries; cohort is creation-selected =
  survivorship-safe) but covers a **single ~1h creation window** — free Dune is **exhausted** (~335k
  rows/mo; the one backfill used them up; a fresh pull 402'd at row 0). Three live bugs were caught +
  fixed (free performance tier, ` UTC` timestamp parsing, graceful 402 handling); query re-scoped to a
  new-launch cohort. **57/57 tests green, ruff clean.** **Decision on record: confirm at $0 after the
  Dune monthly credit reset** (one small clean second window), then finalize NO-GO. **No Phase 3.**
  See `docs/phase-2f-synthesis.md` + `docs/phase-2-profile-dune.md`.
  *Phase 2g (2026-06-02): credit-reset timing check — NOT reset (no-op).* Key created
  ~2026-06-02 = **day 0** of the billing cycle; free allowance still exhausted from 2f. Operator
  elected to skip the probe (a 402 was near-certain) and wait. **Next confirmation run timed to
  ~2026-07-02** (operator to confirm billing-cycle reset day). Nothing changed: no code, no data,
  no spend; 2f state stands verbatim. See `docs/phase-2g-synthesis.md`.
  *Prior (Phase 2e):* built the runnable Dune ingestion path (`dune-validate` / `dune-backfill` +
  `ingestion/dune_backfill.py`); was blocked on the operator key. See `docs/phase-2e-synthesis.md`.
  *Prior (Phase 2d):* verified provider access before depending — Flipside free self-signup
  **effectively closed** (enterprise/demo, June 2026) → **pivot to DUNE as PRIMARY free archive**
  (`dex_solana.trades`, decoded + survivorship-complete; open signup, recommitted for 2026). Built
  provider-agnostic Dune + Flipside adapters with pure tested mappers (Flipside = swap-in). See
  `docs/phase-2d-synthesis.md` and `docs/provider-evaluation.md` (Phase 2d addendum).
  *Prior (Phase 2c):* declined the Bitquery spend (~$2–6k); scouted cheaper archives; originally
  chose Flipside-primary/Dune-cross-check (now revised by 2d). See `docs/phase-2c-synthesis.md`.
  *Prior (Phase 2b):* caught that free `poll` collects no swaps, built `autocrypt collect`
  (survivorship-safe forward-collector) + a spend-gated Bitquery scaffold. See `docs/phase-2b-synthesis.md`.
- **Go/no-go evidence is now DECISIVE-NEGATIVE on real data (provisional NO-GO).** The Phase-1
  snapshot looked like a CONDITIONAL GO (signal +6.9% net over **19 fires**, p=0.007) — but on the
  real Dune cohort (**n=1,763 fires**, 616 pools) the edge **reverses**: blind −15.99%, best-threshold
  signal −15.16%, negative across depth/horizon/rug sweeps and the permutation test, and the signal
  makes returns *worse* as it tightens. Cost drag ~16% vs ~0% marked drift dominates. The snapshot's
  edge was **small-sample noise.** Valid (profiler censors truncated entries; creation-selected
  cohort) but single ~1h creation window. **Verdict: provisional NO-GO for automated short-hold
  Solana**; confirm with one free second window after the Dune monthly reset, then finalize.
  Real-data evidence: `docs/phase-2-profile-dune.md`; analysis: `docs/phase-2f-synthesis.md`.
  (Snapshot evidence: `docs/phase-2-profile.md` / `docs/phase-2-synthesis.md`.)
- **No funds, no keys, no trading-execution code, no paid spend.**
- **Phase 1 result (unchanged):** read-only ingestion + canonical point-in-time schema (signed
  off) + DuckDB store + QC; ~47.2k events (23.5k swaps, 91 pools, 10k+ wallets) from free APIs.
  Honest caveat that bit Phase 2 exactly as predicted: coverage is the freshest launches
  (~19 min), NOT a full 14 days — deep history needs paid-Bitquery or long `poll` (YELLOW #1).

---

## 1. What this project is

An attempt to build a system that detects **on-chain signals that precede large price run-ups in low-cap Solana tokens**, and (if the edge proves real) acts on them with **short-holding-period trades** aiming for high ROI. "Short" here means short *holding period* — enter early into a run-up and exit fast — not short-selling.

The system should run **autonomously where it is safe to do so** (data, research, paper trading), with **hard human gates** on anything involving real funds or keys.

### Honest framing (do not lose this)
This is a **high-variance, statistically-losing-by-default** arena. Most participants in low-cap Solana speculation lose money; most of these tokens are losing trades. The entire project is a bet that a *specific, measurable* edge (wallet attribution, below) survives realistic costs. **Phase 2 is a kill-gate:** if an honest, survivorship-proof backtest does not show a profitable operating point after realistic slippage/fees/impact, the correct outcome is to stop or pivot — not to tune the test until it looks good. Report null results plainly.

This is not financial or legal advice. The operator is a US-based individual and is solely responsible for tax and regulatory compliance. (Note: every swap is a taxable event in the US; high-frequency trading creates a heavy reporting burden — factor this into "ROI.")

## 2. The core thesis and where the edge is

Decisions reached through this session's reasoning:

- **Public-only operator.** No access to private alpha groups/channels. This *pushes the edge onto on-chain data*, not social.
- **Social chatter is NOT the primary entry signal.** By the time ticker mentions spike publicly, most of the move has happened, and much of that chatter is *manufactured* by holders — i.e. it is the exit-liquidity mechanism aimed at people running the naive "high chatter → buy" strategy. On-chain typically *leads* social.
  - Corollary: social-chatter *peak* is better used as an **exit / crowding signal** than an entry signal. Treat it as overlay, not core.
- **The defensible edge = wallet attribution.** Label wallets by their *demonstrated historical lead* on run-ups (which addresses reliably buy *before* moves), and weight "this wallet is buying" by that demonstrated lead. The edge is in the attribution model, not in the act of scraping.
- **Express signals as derivatives, not levels.** Rate-of-change / acceleration of buy pressure, unique buyers, liquidity, holder concentration — because *levels* are lagging and already arbitraged.
- **Frequency is a dial, not a fact.** The signal threshold sets how often the system fires, anywhere from several/minute (loose) to a few/week (strict). Critically, these are **two different edges**:
  - **High-frequency = statistical edge.** Small positive expectancy per trade; the law of large numbers carries the book. *Must* be automated; *must* be near-zero fees (⇒ Solana).
  - **Low-frequency = judgmental edge.** Few, large, human-reviewed, high-conviction trades. ETH becomes viable (fees are a rounding error on large trades); barely "autonomous."
  - **Do not conflate them.** Cranking a statistical strategy's threshold up to once-a-week does NOT give "the same edge, fewer trades" — it gives a sample too small for statistics, silently switching you to needing a judgmental edge you didn't build for.

## 3. Chain decision

- **Start on Solana.** Rationale: for "highest ROI," **opportunity density** and **near-zero per-trade fees** dominate, and only Solana has both. It is the center of gravity for low-cap/meme speculation in 2026, with sub-cent swaps. Roughly ~30k tokens/day launch on the dominant launchpad; only ~0.7–1%+ "graduate" to real DEX liquidity, so the *tradeable* new-token universe is on the order of ~200–270/day (≈ one every 5–8 min) — before signal filtering.
- **Base = pre-committed fallback.** If the attribution edge degrades in Solana's noise (Phase 2 will show this), pivot to Base: cleaner/more-persistent wallet labels, fees still low enough (~$0.20–1/swap) to allow frequency.
- **Ethereum L1 is ruled OUT as an execution venue** for this strategy — mainnet fees ($2–100/swap) kill high-frequency low-cap trading. (Its ecosystem via L2s is fine; mainnet is not.) ETH-manual is only the fallback shape *if* Phase 2 says the edge is selective/judgmental rather than statistical.

**Chain choice is treated as an empirically decidable hypothesis, resolved by Phase 2, not by intuition.**

## 4. Non-negotiable constraints (safety & validity)

These exist because they are the specific ways this kind of project fails. Violating them is a bug.

1. **Survivorship bias is the #1 backtest killer.** The backtest universe MUST include every token including the ones that went nowhere or rugged — not just winners. Patterns found only on survivors are fake.
2. **No look-ahead.** Point-in-time replay only; every record stamped with when it *could have been known*. The attribution model may only see what it could have known at decision time.
3. **Realistic execution simulation.** Model slippage, gas, failed txns, and **your own price impact** (your buy moves a thin market). Marked ROI ≠ realized ROI in low-cap liquidity. Exits are harder than entries; model scaling out.
4. **Rug filtering is mandatory**, as a pre-trade gate: honeypot detection, mint-authority status, LP-lock status, holder concentration. A "signal-rich" detector without this is a fast way to buy traps.
5. **Custody discipline** (when/if live): isolated hot wallet holding only deployable capital; hardware-backed signing; the bulk of funds nowhere near the bot; trade-only keys; withdrawals disabled where possible. **Never commit secrets.**
6. **Circuit breakers + kill switch** before any live capital: max position size, max daily loss, max total drawdown → global halt; both manual and automated triggers (stale data feed, anomalous fill). **Build the brakes before the engine.**
7. **Validate before execute; paper before capital; small before scale.**
8. **No geo-evasion** (no VPN to reach restricted offshore venues).

## 5. Architecture (target system)

Runtime pipeline:
`Data ingestion → Signal engineering → Signal scoring → Risk gate → Execution + custody → Monitoring`

- **Data ingestion:** three modes — streaming (live new-pool/swap/tracked-wallet events), polling (periodic state like holder counts), historical backfill (for the backtester). Point-in-time-correct timestamps throughout. Likely two providers: one for the live stream, one as historical-truth/cross-check.
- **Signal engineering:** the wallet-attribution model (lead-weighted), plus derivative features (buy/sell-pressure imbalance, unique-buyer acceleration, liquidity velocity, holder-concentration shift) and rug-filter features.
- **Signal scoring:** **start rules-based** (transparent composite score crossing a threshold); graduate to ML only with enough clean labeled history. Score feeds *position size*. **Exit logic is a first-class signal**, not an afterthought (take-profit/stop, time-stop, chatter-peak, tracked-wallet *distribution*, liquidity pull).
- **Risk gate:** pre-trade gauntlet — rug filters → slippage estimate vs *actual intended size* → exposure caps → blacklist. Portfolio-level circuit breakers + kill switch sit above it.
- **Execution + custody:** DEX router calls with hard slippage cap, routed via MEV-protected path (e.g. Jito on Solana). Isolated hot wallet, hardware-backed signing. Tx-confirmation/retry/partial-fill/failed-tx handling. Scale out of thin liquidity.
- **Monitoring + cross-cutting:** real-time position monitoring; health checks that **halt on stale feed**; alerting (Telegram/push) on fills/errors/breaker-trips; an **audit log of every decision** (not just trades) — the raw material for the feedback loop. State must survive restart and **reconcile against on-chain truth** on startup (chain is the source of truth). Secrets managed properly. Every threshold is versioned config, never a hardcoded number.

Parallel **research/backtest track + feedback loop:** survivorship-proof, point-in-time, realistic-execution backtester. Judge on drawdown, Sharpe/Sortino, profit factor, survivorship-adjusted base rates — never raw ROI. Feedback loop continuously compares live vs backtest expectation; divergence = early warning of edge decay or a bug.

## 6. Tooling candidates (verify pricing/availability at build time — these move)

- **On-chain data:** Bitquery (raw streaming + deep historical backfill, mempool, 40+ chains) as the truth/backfill layer; Birdeye (Solana real-time low-cap terminal) for live; DexPaprika / GeckoTerminal / CoinGecko free tiers for cheap breadth.
- **Wallet labels / smart money:** Nansen (deep labels, but Solana coverage narrower than ETH), Arkham (broad entity labels). Useful as *seed* labels; the project's own attribution model is the real asset.
- **Execution:** Solana web3 SDKs + Jito for MEV-protected execution. (Sniper-bot products like Trojan/BullX exist but are custodial/closed/fee-heavy — avoid for an edge strategy.)
- **Backtesting/framework reference:** Jesse is notable for **zero-look-ahead** backtesting design; Freqtrade/CCXT are the broader ecosystem. We will likely build a bespoke Solana on-chain backtester since these are CEX/price-series oriented.

## 7. Phase plan (one phase per session; see CLAUDE.md §2 for workflow)

### Iteration 2 (CURRENT) — two concurrent tracks (detail: `docs/iteration-2-strategy.md`)

Thesis: escape Iteration 1's two structural laws (cost wall; smart-money inversion) by trading
**deep-pool / longer-horizon**. Shared kill-gate bar = profitable-after-costs ∧ point-in-time ∧
survivorship-complete ∧ beats-blind+random ∧ robust ∧ enough-fires (strategy doc §3).

- **Track M (Option 2) — Mid-cap deep-pool momentum/mean-reversion. IMMEDIATE & PARALLEL.**
  - **M1** — survivorship-safe point-in-time mid-cap universe + free OHLCV ingest. ✅ **Done.**
    Risk resolved (survivorship-safe universe is NOT free → biased-control+forward-snapshot path);
    band signed off (reserve ≥ $500k ∧ FDV $1M–$250M); machinery built+tested.
  - **M1b** — mcap-ranked inverted funnel to get a USABLE universe. ✅ **Done (2026-06-03):**
    n=113 in-band names (free, no paid pull); biased-control OHLCV ingested (16,177 1d bars / 113
    pools / ~6mo, qc-clean). See `docs/phase-M1b-synthesis.md`.
  - **M2** — deep-pool cost recalibration. ✅ **Done & PASSED (2026-06-03):** Law 1 escaped —
    flat-price round-trip friction ~0.8-0.9% median at $100-$1k (100% of 113 pools < 3%), vs
    Iteration-1's 20-28%; robust across fee/depth sweeps + speculative-only. Constraint is capacity
    (size ~ pool depth), not a wall. `costs.py` + CLI `midcap-costs` + 9 tests. See
    `docs/phase-M2-cost-profile.md`.
  - **M3** — signal battery (TS/XS momentum, mean-reversion, breakout) + **KILL-GATE**. ✅ **Done
    (2026-06-03): NO-GO.** All four signals fail on the biased daily-OHLCV control — none beats
    random after a multiple-comparison discount; blind expectancy slightly negative (cost ~2% ≥
    ~1.3% inflated drift); positive tails are survivorship artifacts (negative median, tiny n,
    regime-/depth-fragile). Built `midcap/{bars,barsignals,killgate}.py` + CLI `midcap-killgate`
    + 14 tests. See `docs/phase-M3-killgate.md`. **YELLOW: pivot to Track G (recommended).**
  - **M4** — (GO only) out-of-sample robustness + capacity. ☐ **N/A unless M3 reopens with a GO.**
- **Track G (Option 1) — Graduation-momentum + days-horizon accumulator cohort. THE MAIN GOAL.**
  - **G0** — start durable long-horizon collection NOW (launchd/cron) + graduation-event detection. ◐
    **Collection RUNNING (interim nohup → `autocrypt_graduation.duckdb`, 7-day hold); durable launchd
    form built but blocked by macOS TCC (grant FDA to `uv` or relocate repo). Graduation-event
    *detection* still TODO (derivable from the raw multi-day store).**
  - **G1** — re-labelled "accumulator" attribution (success = survives+appreciates over N days). ☐
  - **G2** — graduation-momentum **KILL-GATE** (+ orchestrator-fade overlay). ☐
  - **G3** — (GO only) attribution model proper + robustness. ☐
- **Cross-cutting** — Direction 3: reuse the Iteration-1 orchestrator detector as a rug/avoid gate
  for both tracks.
- **Shared downstream** (only a GO track reaches these; carried over verbatim from Iteration 1):
  Paper trading → Execution + risk/kill-switches (brakes before engine) → small live capital (RED).

### Iteration 1 (CLOSED — conclusive NO-GO, shelved) — retained for history

- **Phase 0 — Scaffolding / context handoff.** ✅ Done (this repo).
- **Phase 1 — Data ingestion + historical backfill (Solana), read-only.** ✅ **Done.** Built: env-only-secrets Python/uv scaffold; canonical point-in-time event schema (7 types, 3-time `event_time`/`knowable_at`/`observed_at` discipline, signed off); read-only DexPaprika + GeckoTerminal adapters (free tiers, no paid spend); DuckDB store with a `knowable_at` replay gate + Parquet export; stream/poll/backfill ingestion; `autocrypt qc` data-quality checks; data dictionary. *Deliverable met:* a populated point-in-time store (~47.2k events) + a live read-only feed. *Caveat:* coverage is the freshest launches, not a full 14 days — full history needs forward-collection or paid Bitquery (Phase 2). Schema + decisions: `docs/event-schema.md`, `docs/provider-evaluation.md`, `docs/data-dictionary.md`, `docs/phase-1-synthesis.md`.
- **Phase 2 — Signal-frequency & expectancy profiler + backtest engine. ⛔ THE KILL-GATE.**
  **Profiler BUILT & RUN (`src/autocrypt/profiler/`, `autocrypt profile`).** It instruments the
  composite-derivative signal at multiple thresholds, point-in-time and survivorship-complete,
  with realistic fees + own price impact (constant-product, both legs), and outputs the
  frequency-vs-expectancy curve + a permutation significance test + depth/horizon/rug sweeps.
  ☑ machinery; ☑ run on Phase 1 store; ☑ honest caveats documented; ☑ **free forward-collector
  built & running**; ☑ **real Dune cohort backfilled + profiler RE-RUN (2f)**; ◐ **$0 second-window
  confirmation pending the Dune monthly credit reset**; ☐ **final NO-GO + pivot-vs-shelve sign-off**
  (YELLOW #2).
  *Result:* on the real cohort (n=1,763) the signal **loses −15%** and is negative across every
  sweep — the snapshot's conditional GO was n=19 noise ⇒ **provisional NO-GO** for automated
  short-hold Solana. Confirm with one free second window post-reset, then finalize and choose
  automated-Solana(dead) / Base / longer-hold-judgmental / stop. No Phase 3 on this evidence.
- **Phase 3 — Signal & wallet-attribution model.** ◐ **Brought forward as architecture validation
  (the operator's call) rather than as a post-GO build.** The lead-weighted attribution model is
  BUILT (`src/autocrypt/attribution/`) and validated end-to-end against the kill-gate backtester —
  but on the real cohort it **LOSES (−28% blind, anti-predictive at the high end, p=0.117 n.s.)**, so
  this does **not** constitute a Phase-2 pass. The model/harness are reusable for any future pivot
  (Base / longer-hold) or for the $0 confirmation window. See `docs/phase-3-synthesis.md`.
- **Phase 4 — Paper trading on live data.** Forward-test: confirm the live signal matches the backtest. Divergence ⇒ hunt the look-ahead bug. Still no real funds.
- **Phase 5 — Execution + risk/guardrail layer + kill switches.** Build the brakes (circuit breakers, kill switch, custody plan) **before** the engine touches money. Everything here is built and tested in simulation/paper. Going live is RED.
- **Phase 6 — Small live capital → monitored scale-up → decay monitoring.** Heavily human-gated (RED transitions). Start tiny, watch realized-vs-backtest via the feedback loop, retire strategies that decay.

## 8. Open questions / forks for the human (decide when reached)

- **⛔ Phase 2/3 GO/NO-GO (YELLOW #2): NO-GO, now strengthened (real data, 2f + Phase 3).** The
  conditional GO came from a 19-fire snapshot; the real Dune cohort flips it on BOTH signals tested:
  the **derivative composite** (n=1,763, −16%) and the **wallet-attribution edge** (n=995, −28%
  blind, monotonically worse as you select for "smarter" money, p=0.117 n.s.). Decisive cause is
  **structural: ≈0% no-cost short-hold drift vs ~20–28% costs** — signal-independent. **✅ RESOLVED
  (2026-06-03): the operator chose to SHELVE automated short-hold Solana.** Kill-gate closed NO-GO.
  Pivots considered and not taken now: Base (higher fees; our finding is drift/cost not label
  quality), longer-hold/judgmental (root-cause-addressing but a different, unbuilt, barely-autonomous
  strategy needing new long-horizon data). A $0 representativeness confirmation after the Dune reset
  (~2026-07-02) remains available but is optional given two structural negatives. Paid confirmation
  (Dune Plus ~$399 / CoinGecko Analyst $129) was **not** chosen.
- **⏳ IN PROGRESS — dataset (YELLOW #1).** (a) Free forward-collection — **RUNNING:**
  `autocrypt collect` (enumerate + tail swaps for a 24h-held survivorship-safe cohort), unattended
  via `nohup` → `data/collect.log`. Caveat: a `nohup` process does not survive reboot — a launchd
  job is the durable form (not installed unprompted). Coverage is a 40-pool rolling sample,
  wall-clock-bound (only hours of data so far). (b) **Historical archive — DIRECTION CHANGED AGAIN
  (Phase 2d):** Bitquery (~$2–6k) shelved; Flipside-free turned out **effectively closed** to new
  free self-signup (enterprise/demo model, June 2026) → **decision = DUNE `dex_solana.trades` as the
  PRIMARY free archive** (open signup, free plan publicly committed for 2026; decoded +
  survivorship-complete). **Dune AND Flipside adapters built + tested** (Flipside is a swap-in if
  access reopens). **2e: the Dune ingestion path is now RUNNABLE** — `autocrypt dune-validate` (one
  free execution; validates field paths against a real pull + measures row volume/cost + survivorship)
  and `autocrypt dune-backfill` (windowed pull into the store) + `ingestion/dune_backfill.py`.
  STILL BLOCKED on the operator prereq: provision a free `DUNE_API_KEY` (no `.env` exists yet — copy
  `.env.example`) + save `DEX_TRADES_SQL` as a Dune query with `since`/`till` TIMESTAMP params (note
  its `query_id`). Then `dune-validate` over a small window → size the 14d backfill vs the credit
  cap → backfill + `qc` + profiler re-run. Open: Dune free is credit-metered (~2,500/mo) so a full pull may need
  scoping/overage; warehouse tables have no native pool address → surrogate (base,quote,project) key
  + first-trade creation proxy; field paths unvalidated vs a live pull. Only paid fallback =
  CoinGecko Analyst $129/mo (needs a cap). See `docs/provider-evaluation.md` (Phase 2d addendum).
- **Chain pivot** to Base if attribution degrades in Solana noise.
- **Capital amount** for Phase 6, and **per-position / max-drawdown limits** (set the numbers).
- ~~**Canonical event schema** sign-off in Phase 1 — YELLOW.~~ ✅ **Resolved** (signed off as
  proposed: 7 types, 3-time envelope, DuckDB primary, `confirmed`, 2 s latency, 14-day target).
- **`.claude/settings.json`** does not exist yet (README references it). Human to create the
  allow/deny autonomy rules (auto-mode guard blocked Claude from adding permission rules itself).
