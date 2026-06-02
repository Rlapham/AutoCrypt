# Phase 2b — Session Synthesis (dataset acquisition + profiler re-run)

*Continuation of Phase 2 (THE KILL-GATE). The prior session built the profiler and got a
CONDITIONAL GO on a ~19-min snapshot; this session's job was to get a trustworthy
multi-day dataset flowing and re-run the profiler. Authoritative state lives in
`Project_spec.md`; this captures what happened, the decisions, and the honest caveats.*

## Headline (read this first)

1. **The "free poll" path the last session approved was incomplete — and I caught it.**
   `autocrypt poll` writes **only `PoolCreated`** records (universe enumeration); it never
   collects swaps. The profiler's signal *and* expectancy are computed entirely from swap
   flow, so running `poll` for two weeks would have produced a complete list of *launches*
   and **zero trade history** — the profiled universe would have stayed frozen at the
   snapshot. The prior synthesis's "run poll to accumulate a gap-free window" recipe was
   wrong on this point.
2. **Built the real fix: `autocrypt collect`** — a single-process forward-collector that
   each cycle (a) enumerates new pools → `PoolCreated`, (b) admits them to a **rolling,
   age-bounded cohort**, and (c) tails each cohort pool's **swaps** for up to 24h, so we
   capture the launch→run-up arc rather than just the first seconds. It is **running now**
   and accumulating. This is the free path that actually feeds the kill-gate.
3. **Bitquery: human is HOLDING for a real sales quote** (pricing is custom-quoted, not
   public). I provided a grounded **spend estimate** (≈$1–3k one-time; details below) but
   the human chose "get a real quote first," so **no spend, no signup this session.** I
   built the **Bitquery adapter scaffold** (provider-agnostic, spend-gated, mappers tested)
   so it's a true swap-in the moment a quote is approved.
4. **Re-ran `autocrypt profile`: the curve is essentially unchanged** (blind −12.4%,
   p75 **+6.8% over 19 fires, permutation p=0.008**), because today's collection has not
   yet accumulated multi-day swap history — that is wall-clock-bound. **The GO/NO-GO is
   still PENDING the real-data curve; nothing here changes the CONDITIONAL GO.**

## What was built / changed (state of the code)

- **`src/autocrypt/ingestion/collect.py` + `autocrypt collect` (NEW).** The forward-collector.
  - Cohort discipline: admit by **creation** (survivorship-safe; rugs/duds kept), hold each
    pool and tail its swaps for `--max-pool-age-h` (default 24h), evict **by age only** then
    refill freed slots — so newer launches can't evict a still-young pool. Bounded to
    `--watch-max` (default 40) pools so one sweep fits the provider's 120 req/min limiter.
  - Idempotent (store upserts on `event_id`); `knowable_at = block_time + latency` exactly as
    backfill, so collected rows are comparable to historical.
  - **Honesty fix:** the per-tick progress counter reports **net-new rows** (store delta), not
    rows attempted — `write_events` does INSERT-OR-REPLACE, so re-fetched/duplicate swaps must
    not inflate the number. Caught this when `swaps_written` (3,378) outran the store delta
    (+448) on the first run.
- **`src/autocrypt/providers/bitquery.py` (NEW, SCAFFOLD).** Provider-agnostic Bitquery adapter.
  - Pure mappers (`to_swap`, `to_pool_created`, `swap_to_wallet_event`) emit the **same
    canonical records** as DexPaprika — verified against a representative DEXTrades node.
  - **Spend-gated:** network fetchers raise `PaidSpendNotAuthorizedError` unless constructed
    with **both** a real key **and** `enable_paid=True`. A key landing in `.env` cannot trigger
    a paid query by accident — the YELLOW gate is enforced in code, not just by convention.
  - Drafted GraphQL (`DEX_TRADES_QUERY`, archive dataset) is included but flagged: **validate
    field paths against a live trial response before any bulk backfill.**
- **Tests:** `tests/test_collect.py` (cohort admit/retire/hold) + `tests/test_bitquery.py`
  (canonical mapping + the spend guard). **35 tests green** (was 27), ruff + mypy clean.
- **`docs/phase-2-profile-rerun.md`** — the profiler output on the current store (this session).
  `docs/phase-2-profile.md` is left intact as the originally signed-off evidence.

## The dataset status (the actual session goal)

- **Free forward-collection: RUNNING.** `autocrypt collect` (pid as of session end ~17320),
  `nohup` → `data/collect.log`, 60s interval, 40-pool cohort, 24h hold. Each pool is tailed
  ~every 60s for 24h, capturing its full early-life swap history; cohort refills as pools age out.
- **Effective window so far:** still only the launch-phase snapshot from today (event_time
  ~17:27→20:38 EDT). The collector has begun adding swaps and has swept the universe
  enumeration up to **~3,400 `pool_created`** rows, but **multi-day run-up horizons need
  days of wall-clock** — they cannot exist yet.
- **Coverage limit (honest):** at 120 req/min and ~hundreds of Solana launches/min, a 40-pool
  cohort samples only a sliver of launches. We track that sample *properly* (full histories,
  survivorship-safe), but breadth across the whole universe needs a paid tier / Bitquery
  archive. This is exactly the gap the Bitquery path is meant to close.

## Bitquery spend estimate (provided; NOT a quote)

Pricing is sales-quoted (`bitquery.io/pricing` shows only free Developer + "talk to our team").
Anchors verified June 2026: legacy/surfaced tiers $249/$449/$999/$1,999/mo; third-party
(Cledara) avg actual spend ~$6,496/yr; free Developer = 1k trial points, 10 req/min, 10
rows/request (unusable for bulk). For our scope (~14d, SOL+USDC, enumerate-by-creation,
~3–5M swap rows, one-time export): **Route A** (one paid month, pull via API, then cancel)
≈ **$1,000–$2,500**; **Route B** (Datashare bulk export) ≈ **$1,500–$3,000**. Recommendation
to bring to sales: quote BOTH, take the cheaper; confidence **low-to-medium** (±50%).

## Key decisions & why

- **Caught and fixed the swap-less `poll` gap rather than collecting useless data for weeks.**
  Honesty-over-velocity: a two-week poll run would have *looked* productive while feeding the
  profiler nothing.
- **Cohort-hold (age-evict) over newest-N (recency-evict)** for the collector — the latter
  captures only launch-second dynamics (the very limitation we're escaping); the former
  captures hours-long run-ups for a tracked sample.
- **Bitquery built but spend-gated, not wired** — respects the human's "get a real quote
  first" and the YELLOW spend gate, while making the eventual swap-in a one-line enable.
- **Did NOT overwrite the signed-off `phase-2-profile.md`**; wrote the re-run alongside it.

## Open questions / forks for the human

- **YELLOW (spend) — Bitquery: still OPEN, human is getting a real quote.** No spend authorized.
  When a number comes back, set a not-to-exceed cap; I then enable the adapter (`enable_paid`),
  run a 1-query free-tier trial to validate field paths, then the bounded backfill + `qc`.
- **YELLOW #2 — GO/NO-GO re-confirmation: still PENDING the real-data curve.** Today's re-run is
  unchanged; do **not** start Phase 3 on it. Re-decide once `collect` (and/or Bitquery) has
  accumulated multi-day, multi-hour-horizon data.
- **Durability of the collector (operational):** it's a `nohup` process — survives the session
  but **not a reboot/shutdown/sleep**. For a reliable 1–2 week run it should be a launchd job.
  I did not install one unprompted (it writes to your `LaunchAgents`); see the kickoff for the
  one-liner, or ask me to add it next session.

## Honesty log (what was caught / corrected this session)

- **`poll` collects no swaps** — the headline catch; corrected by building `collect`.
- **`swaps_written` inflated by INSERT-OR-REPLACE** — corrected to report net-new rows.
- **Re-run curve barely moved** — reported plainly as "no new trustworthy data yet," not
  dressed up as a re-confirmation.
- **Bitquery field paths are unvalidated** — flagged in the module; a live trial is required
  before trusting a backfill.

## Suggested commit plan (human runs git — see CLAUDE.md §4)

Work branch: **`Phase2`** (current branch). Suggested commits:
1. **feat(ingest): forward-collector (`autocrypt collect`) for survivorship-safe swap history**
   — `src/autocrypt/ingestion/collect.py`, the `collect` command in `src/autocrypt/cli.py`.
2. **feat(providers): Bitquery adapter scaffold — spend-gated, provider-agnostic mappers**
   — `src/autocrypt/providers/bitquery.py`.
3. **test: collector cohort logic + Bitquery mappers/spend-guard**
   — `tests/test_collect.py`, `tests/test_bitquery.py`.
4. **docs(phase-2): profiler re-run, Phase 2b synthesis, spec update**
   — `docs/phase-2-profile-rerun.md`, `docs/phase-2b-synthesis.md`, `Project_spec.md`.

Do not commit `data/` (store, `*.log`). `docs/phase-2-profile-rerun.md` is regenerable via
`uv run autocrypt profile`.

---

## ▶ Kickoff prompt for the next session — paste into a fresh Claude Code terminal

```text
Read CLAUDE.md, then Project_spec.md, then docs/phase-2b-synthesis.md, then
docs/phase-2-profile-rerun.md. Skim docs/event-schema.md + docs/data-dictionary.md.
Confirm back to me in 3-4 sentences where we are and this session's goal before doing
anything else.

CONTEXT: Phase 2 (KILL-GATE). Profiler is built; CONDITIONAL GO stands but is UNPROVEN
(curve still on a ~3-hr launch snapshot: blind -12%, signal +6.8% net over 19 fires,
p=0.008). Last session I caught that the approved free `poll` collects NO swaps, built
`autocrypt collect` (a real forward-collector: enumerate new pools + tail their swaps for
a 24h-held cohort), and launched it. I also built a spend-gated Bitquery adapter scaffold
(NOT wired to spend). Bitquery purchase is HELD pending a real sales quote.

GOAL THIS SESSION:
  1. Confirm `autocrypt collect` is still running (ps / data/collect.log); report how much
     multi-day swap history it has now accumulated and the effective window. If it died,
     restart it (and consider a launchd job for reboot-survival — one-liner below). Keep it
     running.
  2. Bitquery: ask me if I now have a real quote + a not-to-exceed spend cap.
     - If YES + a specific authorized amount: enable the adapter (Bitquery(..., enable_paid=True)),
       run ONE free-tier trial query first to VALIDATE the drafted GraphQL field paths in
       src/autocrypt/providers/bitquery.py against a live response, then backfill the agreed
       ~14d SOL+USDC enumerate-by-creation universe and `autocrypt qc` it. Never exceed the cap.
     - If NO: proceed on the collect dataset alone; note coverage honestly.
  3. RE-RUN `autocrypt profile` on the best trustworthy data and present the UPDATED
     frequency-vs-expectancy curve + permutation p. That curve is the headline / the GO/NO-GO
     instrument. Watch for: horizon-censoring now correlating with real pool deaths/rugs
     (mark-to-rug, don't silently drop); depth still estimated; check the signal holds
     out-of-window. Only re-confirm GO and start Phase 3 with explicit human sign-off.

Durability one-liner if collect died and you want reboot-survival (ask me before installing
to ~/Library/LaunchAgents): wrap `uv run autocrypt collect --interval 60 --iterations 0
--watch-max 40 --tx-pages 2 --max-pool-age-h 24` in a launchd .plist with KeepAlive.

Autonomy: GREEN for all read-only/simulated/backtest/code work (collector, profiler, the
Bitquery MAPPERS, a single free-tier validation query). YELLOW: any PAID Bitquery call/signup
(needs an explicit per-amount cap from me — enabling `enable_paid` against a paid plan spends
money), and the GO/NO-GO re-confirmation before Phase 3. RED unchanged (no keys/funds/live/
safety-bypass).

First concrete step: report collect status + accumulated window, ask the Bitquery quote/cap
question, then re-run `autocrypt profile` on the best available trustworthy data.
```
