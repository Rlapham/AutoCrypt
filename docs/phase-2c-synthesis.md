# Phase 2c — Session Synthesis (cheaper-archive research + collector check)

*Continuation of Phase 2 (THE KILL-GATE). Prior session (2b) built the forward-collector and a
spend-gated Bitquery scaffold, and held the Bitquery purchase for a real quote. This session:
checked the collector, declined the Bitquery spend, and — at the operator's direction — scouted
cheaper historical-data sources. Authoritative state lives in `Project_spec.md`.*

## Headline (read this first)

1. **Collector is healthy but young.** `autocrypt collect` (pid 17322) is running, ~13 min into
   this run, ~4,778 net-new swap+wallet rows on a 40-pool cohort, 0 aged out. **Effective window
   is still only this evening's launch snapshot (~3 hrs of `event_time`)** — multi-day / multi-hour
   horizon data is wall-clock-bound and cannot exist yet. Nothing here moves the verdict.
2. **Bitquery purchase declined.** Operator has no quote, chose to proceed free, and judged the
   ~$2–6k estimate too high. **No spend, no signup.**
3. **Pivoted to cheaper sources and found a strong $0 path.** Decoded-DEX-trade **data warehouses**
   (Flipside, Dune) give survivorship-complete, decoded Solana swap history including rugs/duds —
   *better* survivorship than our current DexPaprika view, at ~$0. **Operator approved
   Flipside-free as the primary archive, Dune as the SQL cross-check.** Bitquery is shelved.
4. **Profiler NOT re-run this session — honestly, on purpose.** Collect holds DuckDB's single-writer
   lock; the auto-classifier (correctly, per the "keep collect running" instruction) refused to
   stop it. A re-run would only reproduce the existing curve anyway (same cohort + ~13 min more
   swaps), so it was not worth a pause. **Kill-gate verdict unchanged: CONDITIONAL GO, unproven.**

## The provider research (the session's real output)

See `docs/provider-evaluation.md` → "Phase 2c addendum" for the full table and sources. Summary:

- **Flipside (chosen primary, free):** SQL over `solana.defi.ez_dex_swaps` — decoded swaps across
  Raydium/Orca/Meteora/PumpSwap/Jupiter, all tokens, deep history. Free Data API (Community tier).
- **Dune (cross-check):** `dex_solana.trades` decoded table. Free = 2,500 credits/mo + API; a bulk
  14d pull burns credits → modest overage or ~$399/mo Plus. Use to validate Flipside, not as bulk.
- **CoinGecko Analyst ($129/mo):** turnkey OHLCV+trades, full history from 2021, long-tail
  coverage — cheap insurance if the free warehouse caps prove too tight. (This is paid → YELLOW.)
- **Helius:** Solana-native; earmarked for the **live feed (Phase 4)**, not the historical backfill.
- **Bitquery:** shelved (~$2–6k, unnecessary). **Polygon.io:** not a fit (no low-cap Solana launches).

**Why warehouses win on survivorship:** they index *all* on-chain swaps, so dead/rugged tokens are
present by construction — exactly the Project_spec §4.1 requirement, for free.

## What was built / changed (state of the code)

- **No code changes this session** — research + docs only. The collector and the spend-gated
  Bitquery scaffold from Phase 2b are untouched and intact. 35 tests still green (not re-run).
- **Docs:** this synthesis + the "Phase 2c addendum" in `docs/provider-evaluation.md` +
  `Project_spec.md` status/open-questions update.

## Key decisions & why

- **Declined Bitquery spend** — operator has no quote and the estimate is high; the free warehouse
  path is both cheaper and better for survivorship, so paying is not justified now.
- **Flipside-free primary, Dune cross-check** — decoded + survivorship-complete at $0 beats every
  paid option for a one-time historical backfill; Dune gives an independent decoded source to
  cross-check Flipside's numbers (guards against a single-provider decode bug).
- **Did NOT kill the collector to force a profiler re-run** — honesty/operational-safety over
  going-through-the-motions: the re-run would have been uninformative and would have interrupted
  the only multi-day data accrual we have.

## Open questions / forks for the human

- **YELLOW (spend) — now mostly moot.** Bitquery shelved. The only remaining paid option on the
  table is CoinGecko Analyst ($129/mo) as a fallback *if* Flipside's free caps prove too tight —
  would need an explicit go + cap then. No spend authorized now.
- **YELLOW #2 — GO/NO-GO re-confirmation: still PENDING the real-data curve.** Unchanged. Do **not**
  start Phase 3 until the profiler runs on a trustworthy multi-day dataset (Flipside backfill or a
  matured `collect` window) with explicit sign-off.
- **Collector durability (operational):** still a `nohup` process — survives the session but **not a
  reboot/sleep**. For a reliable multi-week run it should be a launchd job (one-liner in kickoff).
  Not installed unprompted (writes to `~/Library/LaunchAgents`).
- **Flipside validation unknowns (next session):** free-tier credit/row caps vs a full 14d pull;
  pool-*creation* enumeration from a swaps table (first-swap proxy or a creation-table join).

## Honesty log (what was caught / corrected this session)

- **Profiler re-run skipped, said so plainly** — not dressed up; the lock block + lack of new data
  made it uninformative, so it was not forced.
- **"Free" caps are unvalidated** — flagged that Flipside's free-tier limits against a *full* pull
  are unverified; the recommendation is "scout," not "proven."
- **Polygon.io ruled out explicitly** — it doesn't cover the low-cap Solana launch universe, so it
  was not silently included as a cheap option.

## Suggested commit plan (human runs git — see CLAUDE.md §4)

Work branch: **`Phase2`** (current branch). This session is docs-only; suggested commits:
1. **docs(phase-2): cheaper-archive research — Flipside-free primary, Dune cross-check; shelve Bitquery**
   — `docs/provider-evaluation.md` (Phase 2c addendum).
2. **docs(phase-2): Phase 2c synthesis + spec status update**
   — `docs/phase-2c-synthesis.md`, `Project_spec.md`.

Note: the Phase 2b code (collector, Bitquery scaffold, tests) + `docs/phase-2b-synthesis.md` +
`docs/phase-2-profile-rerun.md` from the prior session may still be uncommitted on this branch —
check `git status`; they carry their own commit plan in `docs/phase-2b-synthesis.md`. Do not commit
`data/` (store, `*.log`).

---

## ▶ Kickoff prompt for the next session — paste into a fresh Claude Code terminal

```text
Read CLAUDE.md, then Project_spec.md, then docs/phase-2c-synthesis.md, then
docs/provider-evaluation.md (the "Phase 2c addendum"). Skim docs/event-schema.md +
docs/data-dictionary.md. Confirm back to me in 3-4 sentences where we are and this
session's goal before doing anything else.

CONTEXT: Phase 2 (KILL-GATE). Profiler built; CONDITIONAL GO stands but UNPROVEN (curve
still on a ~3-hr launch snapshot: blind -12%, signal +6.8% net over 19 fires, p=0.008).
Bitquery is SHELVED (too pricey, ~$2-6k). Decision: build a FREE Flipside Data API adapter
as the primary historical archive (decoded, survivorship-complete Solana DEX swaps), Dune
`dex_solana.trades` as the SQL cross-check. The forward-collector `autocrypt collect` is
running but only has hours of data (wall-clock-bound).

GOAL THIS SESSION (all $0 / GREEN unless noted):
  1. Confirm `autocrypt collect` is still running (ps / data/collect.log); report accumulated
     window. If it died, restart it. (Optional, ask first: install the launchd job for
     reboot-survival.)
  2. Build a provider-agnostic FLIPSIDE adapter mirroring src/autocrypt/providers/bitquery.py:
     pure mappers (Flipside ez_dex_swaps row -> canonical Swap/WalletEvent; derive PoolCreated
     from each token's FIRST swap as a creation proxy). Add tests like tests/test_bitquery.py.
     Free Flipside account + API key go in .env (NEVER committed) — ask me to create the key if
     needed; signup is $0 but I should confirm before you depend on it.
  3. Run ONE free validation query to confirm: field paths, free-tier credit/row caps against a
     real pull, and survivorship (dead/rugged tokens present). Report caps honestly.
  4. If caps allow, backfill the ~14d SOL+USDC enumerate-by-(first-swap) universe via Flipside,
     `autocrypt qc` it, then RE-RUN `autocrypt profile` on it and present the UPDATED
     frequency-vs-expectancy curve + permutation p. That curve is the GO/NO-GO instrument.
     Watch: horizon-censoring vs real pool deaths/rugs (mark-to-rug, don't drop); depth still
     estimated; signal holding out-of-window. Re-confirm GO / start Phase 3 ONLY with explicit
     human sign-off.

NOTE: running `autocrypt profile` needs the DuckDB writer lock, which `collect` holds — you'll
need to briefly pause collect (ask me / I authorize a stop+restart; it's idempotent and
survivorship-safe) or point the profiler at a separate backfilled DB.

Durability one-liner (ask before installing to ~/Library/LaunchAgents): wrap `uv run autocrypt
collect --interval 60 --iterations 0 --enum-pages 2 --watch-max 40 --tx-pages 2
--max-pool-age-h 24` in a launchd .plist with KeepAlive.

Autonomy: GREEN for all read-only/simulated/backtest/code work (collector, profiler, Flipside
+ Dune ADAPTERS and free validation queries, free signups). YELLOW: any PAID tier (e.g.
CoinGecko Analyst $129/mo if free caps are too tight — needs an explicit cap), and the GO/NO-GO
re-confirmation before Phase 3. RED unchanged (no keys/funds/live/safety-bypass).

First concrete step: report collect status, then start the Flipside adapter + a free validation
query.
```
