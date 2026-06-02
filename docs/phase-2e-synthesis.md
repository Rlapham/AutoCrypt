# Phase 2e — Session Synthesis (Dune ingestion path built; prereq still pending)

*Continuation of Phase 2 (THE KILL-GATE). Prior session (2d) pivoted the historical
archive to Dune-primary (Flipside free signup closed) and built provider-agnostic Dune +
Flipside adapters with pure tested mappers. This session built the **CLI ingestion path**
that turns the Dune adapter into runnable validate/backfill commands — the thing the
operator's key will unblock in one command. Authoritative state lives in `Project_spec.md`.*

## Headline (read this first)

1. **Collector alive but saturated.** `autocrypt collect` (pid 17322) is still running.
   It has **plateaued at ~8,600 net-new swap+wallet rows** on its 40-pool rolling cohort —
   the launch burst of that cohort is over, `admitted=0`/`retired=0` for hours. The log
   also shows a **~10-hour gap (02:39 → 12:33 UTC)**: the laptop slept, confirming the
   known "nohup survives the session but not sleep" caveat in the wild. Window is unchanged
   (a single launch snapshot) — **does not move the verdict.** Left running; harmless.
2. **Operator prereq is NOT met.** There is **no `.env`** (only `.env.example`), so **no
   `DUNE_API_KEY`** and **no saved-query `query_id`**. That blocks the validation execution
   (step 3) and the backfill (step 4) — both need the operator action from the 2d kickoff.
3. **Built the missing Dune ingestion path (the session's deliverable, all $0).** The 2d
   adapter existed but **nothing called it** — no CLI command, and `doctor` didn't even
   report the Dune/Flipside keys. So when the key arrived there was no command to run. Now:
   - `autocrypt dune-validate --query-id N --since … --till …` — ONE free execution that
     validates field paths against a real pull, maps the sample through the canonical
     mappers, reads Dune's row-count/cost metadata, and reports survivorship breadth.
   - `autocrypt dune-backfill --query-id N --since … --till …` — the full windowed pull
     → Swap / WalletEvent / PoolCreated (first-trade-as-creation-proxy) into the store.
   - `doctor` now reports `dune_api_key` / `flipside_api_key` / `coingecko_api_key`.
4. **GO/NO-GO still UNPROVEN.** No key → no real pull → no profiler re-run. Kill-gate
   verdict unchanged: **CONDITIONAL GO, unproven.** No Phase 3.

## What was built / changed (state of the code)

- **`src/autocrypt/ingestion/dune_backfill.py`** (NEW) — the ingestion glue:
  - `validate_dune(dune, query_id, since, till)` → `DuneValidationReport`: executes the
    saved query for a SMALL window (one page), diffs the returned columns against the 11
    `EXPECTED_COLUMNS` (surfaces any missing column **loudly** rather than as an empty
    backfill), maps the sample through the **real** `to_swap`, and reports mapped/skipped,
    distinct base mints + markets (survivorship breadth), `amount_usd` coverage, whether a
    native pool column appeared, and Dune's raw metadata. Honest note baked in: **per-execution
    credit cost is not returned by the API — read it from Dune → Settings → Billing.**
  - `run_dune_backfill(store, dune, …)` → `DuneBackfillReport`: streams time-ordered rows,
    emits a PoolCreated the **first** time each surrogate market appears (earliest trade =
    creation proxy), plus Swap + WalletEvent per trade; batched, idempotent writes; reports
    a `hit_max_rows` cap honestly (a CAP to report, not a complete window).
  - `parse_window()` — CLI bound parser; naive → UTC (store + `block_time` are both UTC).
- **`src/autocrypt/providers/dune.py`** — added two thin public methods used by validation:
  `get_execution_status()` (carries `result_metadata`) and `fetch_results_page()` (raw,
  non-lower-cased rows so column names can be checked exactly as Dune returns them). No
  change to the mappers or `iter_trade_rows`.
- **`src/autocrypt/cli.py`** — new `dune-validate` + `dune-backfill` commands (rich report
  tables + next-step hints), a `_dune_or_exit()` helper that prints exact operator
  instructions when `DUNE_API_KEY` is absent, an `_with_aclose()` lifecycle helper, and
  the three warehouse keys added to `doctor`.
- **`tests/test_dune_backfill.py`** (NEW, 5 tests) — a `FakeDune` overrides only the network
  methods and keeps the real mappers: validates field-path reporting, the missing-column
  flag, the first-trade-as-pool-proxy rule (asserts the proxy is the **earliest** trade,
  slot 100 not 101), and backfill idempotency (re-run nets 0 new rows).
- **Tests: 56/56 green** (was 51 + 5). Ruff clean. No collector / adapter-mapper changes.

## Key decisions & why

- **Build the runnable path now, while the key is pending.** The 2d adapter was correct but
  inert — there was literally no way to *run* a validation. Wiring `dune-validate` /
  `dune-backfill` means the operator's key unblocks the kill-gate in **one command**, not a
  fresh build session. Pure $0 / GREEN code work.
- **Validation reuses the REAL mappers, not a parallel parser.** `validate_dune` maps the
  sampled rows through `to_swap` — so a green validation literally proves the swap-in
  contract the backfill depends on, instead of testing a lookalike.
- **Surface missing columns loudly.** A renamed/absent `dex_solana.trades` column would make
  the mappers silently yield `None` (an empty backfill that looks "successful"). The
  validation diffs columns and marks `field_paths_ok=False` so we never backfill on a broken
  schema assumption — the central honest-failure risk both 2c and 2d flagged.
- **Credit cost reported honestly as "read it from Billing."** Dune's API does not return a
  per-execution credit charge; pretending to compute one would be fiction. We report the
  measurable proxies (total row count, bytes, execution time) and point at the authoritative
  source. Matches the spend-approval pattern (estimate first, real number from the source).
- **Left the collector running, did not install launchd.** It's saturated and harmless;
  Dune is now the primary archive, so its durability is lower-stakes. launchd writes to
  `~/Library/LaunchAgents` and was flagged ask-first — not done unprompted.

## Open questions / forks for the human

- **THE blocker — Dune free key + saved query_id (operator action, from the 2d kickoff).**
  1. dune.com → Settings → API → create a free key → add to `.env` as `DUNE_API_KEY`
     (there is no `.env` yet — copy `.env.example`; never commit).
  2. New Dune query → paste `DEX_TRADES_SQL` (verbatim, in `src/autocrypt/providers/dune.py`
     and reproduced at the bottom of this doc) → declare **`since`** and **`till`** as
     TIMESTAMP parameters (names must match exactly) → save → give me the numeric
     **`query_id`**. Then I run `autocrypt dune-validate` immediately.
- **Dune free-tier credit cap (the validation unknown).** Free is credit-metered (~2,500/mo).
  The first `dune-validate` over a SMALL window (e.g. 1 hour) measures real row volume; we
  then size the 14d backfill against the cap, paginate, or accept a modest overage honestly.
  CoinGecko Analyst $129/mo remains the only paid fallback (YELLOW, needs a cap).
- **Writer-lock contention (unchanged).** `collect` holds DuckDB's single writer lock. Before
  `dune-backfill` + `profile`, either briefly stop+restart `collect` (idempotent,
  survivorship-safe — ask first) or point the backfill/profiler at a separate DB file.
- **GO/NO-GO re-confirmation — still PENDING the real-data curve.** No Phase 3 until the
  profiler runs on a trustworthy multi-day Dune dataset with explicit human sign-off.

## Honesty log (what was caught / corrected this session)

- **The 2d adapter was un-runnable.** "Adapter built + tested" (2d) did not mean "validation
  is one command away" — there was no CLI/ingestion caller and `doctor` didn't track the key.
  Caught and closed this session; without it, the operator's key would have unblocked nothing.
- **Field paths remain documented-but-unvalidated.** `validate_dune` is built to test them,
  but it has **not** run against a live Dune response (no key). The mappers stay defensive;
  the first real `dune-validate` is still the source of truth, exactly as 2c/2d said.
- **Collector progress is real but stalled, and not dressed up.** ~8,600 rows on a saturated
  40-pool cohort with a 10-hour sleep gap — reported as the wall-clock-bound snapshot it is,
  not as "the dataset grew."
- **No profiler re-run, no GO change.** No new real data ⇒ the verdict is unchanged, not
  re-spun.

## Suggested commit plan (human runs git — see CLAUDE.md §4)

Work branch: **`Phase2`**. Suggested logical commits:

1. **feat(ingestion): Dune validate + backfill path (`dune_backfill.py`)**
   — `src/autocrypt/ingestion/dune_backfill.py`, plus the two public adapter methods in
   `src/autocrypt/providers/dune.py` (`get_execution_status`, `fetch_results_page`).
2. **feat(cli): `dune-validate` / `dune-backfill` commands + warehouse keys in `doctor`**
   — `src/autocrypt/cli.py`.
3. **test(ingestion): Dune backfill/validation glue (FakeDune, 5 tests)**
   — `tests/test_dune_backfill.py`.
4. **docs(phase-2): 2e synthesis + spec update (Dune ingestion path built; prereq pending)**
   — `docs/phase-2e-synthesis.md`, `Project_spec.md`.

Do **not** commit `data/` (store, `*.log`) or the throwaway `.tmp/` dir. Prior-session code
+ docs may still be uncommitted on this branch — check `git status`.

---

## ▶ Kickoff prompt for the next session — paste into a fresh Claude Code terminal

```text
Read CLAUDE.md, then Project_spec.md, then docs/phase-2e-synthesis.md, then
docs/provider-evaluation.md (the Phase 2c/2d addenda). Skim docs/event-schema.md +
docs/data-dictionary.md. Confirm back to me in 3-4 sentences where we are and this
session's goal before doing anything else.

CONTEXT: Phase 2 (KILL-GATE). Profiler built; CONDITIONAL GO stands but UNPROVEN (curve
still on a ~3-hr launch snapshot: blind -12%, signal +6.8% net over 19 fires, p=0.008).
LAST SESSION (2e): built the runnable Dune ingestion path — `autocrypt dune-validate` and
`autocrypt dune-backfill` CLI commands + the validation/backfill glue
(src/autocrypt/ingestion/dune_backfill.py), 56/56 tests green, ruff clean. The Dune
adapter was correct but inert before; now the operator's key unblocks the kill-gate in one
command. Still BLOCKED on the operator prereq: no .env / no DUNE_API_KEY / no saved query_id.

OPERATOR PREREQ (do this before the session can progress past code):
  1. dune.com → Settings → API → free key → copy .env.example to .env, add DUNE_API_KEY
     (never commit).
  2. New Dune query → paste DEX_TRADES_SQL (verbatim, from src/autocrypt/providers/dune.py)
     → declare `since` and `till` as TIMESTAMP parameters (exact names) → save → give me
     the numeric query_id.

GOAL THIS SESSION (all $0 / GREEN unless noted):
  1. Confirm `autocrypt collect` status (ps / data/collect.log); report window. It is
     likely still saturated (~8.6k rows on a 40-pool cohort) — that's expected, Dune is the
     primary archive now. Restart only if dead.
  2. If the Dune key + query_id are in: run `autocrypt dune-validate --query-id N --since
     '<small 1h window>' --till '<...>'`. Confirm field_paths_ok, survivorship breadth, and
     measure the free-tier row volume → estimate the 14d credit cost. Report caps honestly.
  3. If validation passes and the cap allows: stop `collect` (ask me — idempotent,
     survivorship-safe) or point at a separate DB, then `autocrypt dune-backfill` the ~14d
     SOL+USDC window, `autocrypt qc` it, and RE-RUN `autocrypt profile`. Present the UPDATED
     frequency-vs-expectancy curve + permutation p — the GO/NO-GO instrument. Watch:
     horizon-censoring vs real pool deaths/rugs (mark-to-rug, don't drop); depth still
     estimated; signal holding out-of-window; surrogate pool key groups by (base,quote,project).
  4. Re-confirm GO / start Phase 3 ONLY with explicit human sign-off.

NOTE: `profile`/`dune-backfill` need the DuckDB writer lock that `collect` holds — pause
collect (ask first) or use a separate DB file.

Autonomy: GREEN for all read-only/simulated/backtest/code work (collector, profiler, Dune
adapter + validation/backfill, free signups). YELLOW: any PAID tier (e.g. CoinGecko Analyst
$129/mo if Dune free credits are too tight — needs an explicit cap) and the GO/NO-GO
re-confirmation before Phase 3. RED unchanged (no keys/funds/live/safety-bypass).

First concrete step: report collect status; if the Dune key + query_id are in, run
dune-validate over a small window; otherwise tell me exactly what you need from me.
```
