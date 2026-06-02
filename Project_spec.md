# Project Spec — Solana Run-Up Detector

**Authoritative source of project state.** Updated at the end of every session. If this doc and any other source disagree, this doc wins (except for live external facts like API pricing, which must be re-verified at build time).

---

## Current status

- **Phase:** 2 (signal-frequency & expectancy profiler — THE KILL-GATE) — **profiler built & run;
  GO/NO-GO is CONDITIONAL GO, still PENDING a real-data curve.** Latest session (Phase 2d): built
  the free-warehouse adapters and **verified provider access before depending on it** — Flipside's
  free self-signup turned out to be **effectively closed** (enterprise/"demo" model as of June 2026;
  the API surface also appears to have moved to a `public/v3` REST endpoint). **Decision
  (operator-approved): pivot to DUNE as the PRIMARY free archive** (`dex_solana.trades`, decoded +
  survivorship-complete; Dune's free tier is open self-signup and publicly recommitted for 2026).
  Built provider-agnostic **Dune AND Flipside adapters** with pure tested mappers (Flipside stays as
  a swap-in if access reopens); added `flipside`/`dune` sources + API-key settings. **51/51 tests
  green, ruff clean.** `autocrypt collect` still running (young; wall-clock-bound). Profiler **not
  re-run** (no new real data yet — no key → no validation/backfill). Verdict unchanged. **No Phase 3
  until the real-data curve is signed off.** See `docs/phase-2d-synthesis.md` and
  `docs/provider-evaluation.md` (Phase 2d addendum).
  *Prior (Phase 2c):* declined the Bitquery spend (~$2–6k); scouted cheaper archives; originally
  chose Flipside-primary/Dune-cross-check (now revised by 2d). See `docs/phase-2c-synthesis.md`.
  *Prior (Phase 2b):* caught that free `poll` collects no swaps, built `autocrypt collect`
  (survivorship-safe forward-collector) + a spend-gated Bitquery scaffold. See `docs/phase-2b-synthesis.md`.
- **Go/no-go evidence is IN, but not decisive.** On the Phase 1 store: blind entry loses
  (−12%/trade @60s; ~20 pts of fees + own-impact drag on a +7.6% marked drift), BUT the
  derivative signal selects better-than-random entries (**+6.9% net expectancy over 19 fires,
  47% hit, permutation p=0.007**). **Promising but unproven** — the dataset is a ~19-minute,
  single-window, launch-phase snapshot (83 pools), so it measures first-minutes dynamics, not
  the run-ups the thesis is about. Verdict reads as **CONDITIONAL GO: fund a real dataset and
  re-run the (now-built) profiler before committing to Phase 3.** Full evidence:
  `docs/phase-2-profile.md`; analysis: `docs/phase-2-synthesis.md`.
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

- **Phase 0 — Scaffolding / context handoff.** ✅ Done (this repo).
- **Phase 1 — Data ingestion + historical backfill (Solana), read-only.** ✅ **Done.** Built: env-only-secrets Python/uv scaffold; canonical point-in-time event schema (7 types, 3-time `event_time`/`knowable_at`/`observed_at` discipline, signed off); read-only DexPaprika + GeckoTerminal adapters (free tiers, no paid spend); DuckDB store with a `knowable_at` replay gate + Parquet export; stream/poll/backfill ingestion; `autocrypt qc` data-quality checks; data dictionary. *Deliverable met:* a populated point-in-time store (~47.2k events) + a live read-only feed. *Caveat:* coverage is the freshest launches, not a full 14 days — full history needs forward-collection or paid Bitquery (Phase 2). Schema + decisions: `docs/event-schema.md`, `docs/provider-evaluation.md`, `docs/data-dictionary.md`, `docs/phase-1-synthesis.md`.
- **Phase 2 — Signal-frequency & expectancy profiler + backtest engine. ⛔ THE KILL-GATE.**
  **Profiler BUILT & RUN (`src/autocrypt/profiler/`, `autocrypt profile`).** It instruments the
  composite-derivative signal at multiple thresholds, point-in-time and survivorship-complete,
  with realistic fees + own price impact (constant-product, both legs), and outputs the
  frequency-vs-expectancy curve + a permutation significance test + depth/horizon/rug sweeps.
  ☑ machinery; ☑ run on Phase 1 store; ☑ honest caveats documented; ☑ **free forward-collector
  built & running** (`autocrypt collect` — `poll` alone was swap-less); ◐ **trustworthy
  multi-day dataset accumulating** (wall-clock-bound; Bitquery archive held for a quote);
  ☐ **GO/NO-GO human sign-off on the real-data curve** (YELLOW #2, open).
  *Result so far:* blind loses, signal beats random at the 75th-pct threshold but on n=19 over a
  ~19-min launch snapshot ⇒ **conditional GO recommended** (fund the real dataset, re-run, then
  decide automated-Solana / manual-ETH / stop). Get explicit sign-off before any Phase 3 work.
- **Phase 3 — Signal & wallet-attribution model.** (Only if Phase 2 passes.) Build/validate the lead-weighted attribution model and the composite scorer against the backtester.
- **Phase 4 — Paper trading on live data.** Forward-test: confirm the live signal matches the backtest. Divergence ⇒ hunt the look-ahead bug. Still no real funds.
- **Phase 5 — Execution + risk/guardrail layer + kill switches.** Build the brakes (circuit breakers, kill switch, custody plan) **before** the engine touches money. Everything here is built and tested in simulation/paper. Going live is RED.
- **Phase 6 — Small live capital → monitored scale-up → decay monitoring.** Heavily human-gated (RED transitions). Start tiny, watch realized-vs-backtest via the feedback loop, retire strategies that decay.

## 8. Open questions / forks for the human (decide when reached)

- **✅ RESOLVED — Phase 2 GO/NO-GO (YELLOW #2): CONDITIONAL GO.** Signal beats random (p=0.007)
  but on a 19-min snapshot ⇒ acquire a real dataset, re-run the profiler, then choose the shape
  (automated-Solana / manual-ETH / stop). No Phase 3 until the real-data curve is signed off.
- **⏳ IN PROGRESS — dataset (YELLOW #1).** (a) Free forward-collection — **RUNNING:**
  `autocrypt collect` (enumerate + tail swaps for a 24h-held survivorship-safe cohort), unattended
  via `nohup` → `data/collect.log`. Caveat: a `nohup` process does not survive reboot — a launchd
  job is the durable form (not installed unprompted). Coverage is a 40-pool rolling sample,
  wall-clock-bound (only hours of data so far). (b) **Historical archive — DIRECTION CHANGED AGAIN
  (Phase 2d):** Bitquery (~$2–6k) shelved; Flipside-free turned out **effectively closed** to new
  free self-signup (enterprise/demo model, June 2026) → **decision = DUNE `dex_solana.trades` as the
  PRIMARY free archive** (open signup, free plan publicly committed for 2026; decoded +
  survivorship-complete). **Dune AND Flipside adapters built + tested** (Flipside is a swap-in if
  access reopens). Next session: operator provisions a free `DUNE_API_KEY` + saves the adapter's
  `DEX_TRADES_SQL` as a Dune query (note its `query_id`), then I run ONE validation execution
  (confirm field paths + measure free **credit cost**/row caps + survivorship), then a ~14d backfill
  + profiler re-run. Open: Dune free is credit-metered (~2,500/mo) so a full pull may need
  scoping/overage; warehouse tables have no native pool address → surrogate (base,quote,project) key
  + first-trade creation proxy; field paths unvalidated vs a live pull. Only paid fallback =
  CoinGecko Analyst $129/mo (needs a cap). See `docs/provider-evaluation.md` (Phase 2d addendum).
- **Chain pivot** to Base if attribution degrades in Solana noise.
- **Capital amount** for Phase 6, and **per-position / max-drawdown limits** (set the numbers).
- ~~**Canonical event schema** sign-off in Phase 1 — YELLOW.~~ ✅ **Resolved** (signed off as
  proposed: 7 types, 3-time envelope, DuckDB primary, `confirmed`, 2 s latency, 14-day target).
- **`.claude/settings.json`** does not exist yet (README references it). Human to create the
  allow/deny autonomy rules (auto-mode guard blocked Claude from adding permission rules itself).
