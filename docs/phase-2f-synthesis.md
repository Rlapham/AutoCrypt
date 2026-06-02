# Phase 2f — Session Synthesis (real data IN; kill-gate flips to provisional NO-GO)

*Continuation of Phase 2 (THE KILL-GATE). Prior session (2e) built the runnable Dune
ingestion path but was blocked on the operator key. This session the key arrived, the
real-data backfill ran, the profiler re-ran on it — and the conditional-GO did **not**
survive. Authoritative state: `Project_spec.md`.*

## Headline (read this first)

1. **Operator key + saved query are IN.** `DUNE_API_KEY` provisioned to `.env` (git-ignored).
   Cohort query saved as **query_id 7637616**.
2. **Three live bugs found + fixed** (the validation path doing its job):
   - `performance:"medium"` → **`"free"`** — paid tiers 402/400 on the free plan.
   - `_parse_dt` now strips Dune's literal **`" UTC"`** timestamp suffix.
   - Backfill now **stops gracefully on the free-tier 402** (`DuneCreditCapError`) — persists
     the partial pull + flags `hit_credit_cap`, instead of crashing mid-pagination.
3. **Query re-scoped to a NEW-LAUNCH COHORT.** The naive "every SOL/USDC trade" pull measured
   **~906k rows/HOUR** (the whole SOL/USDC flow incl. blue-chips) — infeasible + contaminated.
   The cohort query keeps only base tokens whose **first** SOL/USDC trade is in `[since,till)`
   and emits each one's first **2h** of trades (lookback 1h to cut left-censoring). Output
   columns unchanged → mappers untouched. Validation: **field_paths_ok, 5000/5000 mapped, 0
   skipped, 277 launches/hr**.
4. **THE RESULT — kill-gate flips.** On the real cohort (**616 pools, n=1,763 fires @60s**):
   - **Blind −15.99%**; **best-threshold signal −15.16%** (still a loss); signal gets *worse*
     as you tighten (−16% → −21% → −25% → −33%).
   - **Negative across every sweep:** depth ×0.5/×1/×2 = −22.6%/−16.0%/−11.4% (never flips);
     horizons 30/60/120s ≈ −16%; rug on/off both negative. Permutation: only thr=−0.343 has
     low p (0.022) and it *still* returns −15.16% (and before the multiple-comparison discount).
   - Cost drag **~16%** (fees + own impact on thin pools) vs **~0%** marked 60s drift dominates.
   - The Phase-1 snapshot's **+6.8% / p=0.008 (n=19)** was almost certainly small-sample noise.
   Report: `docs/phase-2-profile-dune.md`.
5. **Free Dune is EXHAUSTED.** The one ~1h cohort backfill consumed ~the entire monthly free
   allowance (~335k rows); a fresh clean pull immediately **402'd at row 0**. Confirmed empirically.
6. **Verdict: provisional NO-GO** for the automated short-hold Solana strategy. Operator chose
   to **confirm at $0 after the monthly credit reset** (one small clean second window) before
   finalizing — no spend. **No Phase 3.**

## Why the negative result is trustworthy (not just "truncated junk")

The free 402 truncated the pull to the first ~57 min of one hour's launches. That limits
**coverage**, not validity:
- The profiler **censors** forward-truncated entries (dropped 196) — expectancy is measured
  only on complete ≤120s round-trips, so truncation doesn't corrupt returns.
- Cohort selection is **by creation** (launches born 00:00–00:57) — survivorship-safe by
  construction; rugs/duds included.
- So the run is a **legitimate point-in-time kill-gate result**. Its honest limit is that it's
  a **single ~1-hour creation window**. The only thing a clean second window adds is a
  representativeness check on that one window.

**Scope caveat:** this tests the *automated short-hold* (≤120s) Solana expression — the one
that's built. It does **not** test longer-hold / judgmental run-ups (a different strategy).

## What was built / changed (state of the code)

- `src/autocrypt/providers/dune.py`:
  - `DEX_TRADES_SQL` rewritten to the **new-launch cohort** (CTEs: `bounds` → `scan` with
    1h lookback / 2h tracking → `cohort` by first-trade-in-window → join). Same 11 output cols.
  - `execute_query(performance="free")` (was `"medium"`); body omits `performance` if falsy.
  - `_parse_dt` strips the ` UTC` suffix.
  - New `DuneCreditCapError`; `iter_trade_rows` catches httpx 402 → raises it (carrying rows/offset).
- `src/autocrypt/ingestion/dune_backfill.py`: `run_dune_backfill` wraps the stream in
  try/except `DuneCreditCapError` → persists partial, sets `hit_credit_cap`, adds an honest note.
  New `hit_credit_cap` field on `DuneBackfillReport`.
- `.env` (NEW, git-ignored) — `DUNE_API_KEY`; `.env.example` gains a `DUNE_API_KEY=` placeholder.
- `tests/test_dune_backfill.py`: +1 test (`CreditCappedDune`) pinning the 402-partial-persist path.
  **57/57 green, ruff clean.**
- `docs/phase-2-profile-dune.md` (NEW) — the real-data kill-gate curve.

## Data artifacts (NOT committed — `data/` is git-ignored)

- `data/autocrypt_dune.duckdb` — the profiled cohort (653,922 events: 318,545 swaps, 3,724
  launches; 2026-05-19 00:00–00:57 UTC, truncated by 402). Kept in a **separate DB** so the
  `collect` writer lock was never touched.
- `data/autocrypt_dune_clean.duckdb` — empty (the 402-at-row-0 probe). Throwaway.
- `autocrypt collect` (pid 17322) still running, saturated (~8.6k rows / 40 pools). Harmless.

## Open questions / forks

- **Confirmation (chosen path): wait for the Dune free monthly reset, then pull ONE small
  (<300k-row, ~20min) clean second window and re-profile.** $0. Key was created ~2026-06-02, so
  the reset is likely ~2026-07-02 (operator: confirm your billing-cycle date).
- **If the second window confirms ~−16%:** finalize NO-GO; decide **pivot vs shelve** — pivot
  candidates: Base (cleaner wallet labels), or a longer-hold/judgmental thesis (a different,
  unbuilt strategy + a profiler that supports long horizons).
- **Paid escalation (YELLOW, not chosen):** Dune Plus ~$399/mo or CoinGecko Analyst $129/mo —
  only if an immediate clean confirmation is wanted. Bring a real quote + cap first.
- **QC WARN:** `logical_duplicates` — Dune has no `instruction_index`, so multi-swap-per-tx
  rows share `(tx,instr,type)` but keep distinct `event_id`s (nothing dropped). Acceptable;
  revisit if multi-hop double-counting needs a cleaner natural key.

## Honesty log

- **Reported the negative result plainly and did not re-spin it.** The conditional-GO came from
  a 19-fire snapshot; on n=1,763 the edge reverses. That is the kill-gate working, not a failure
  to fix. No threshold was cherry-picked to manufacture a positive.
- **Corrected my own over-statement of "truncated."** The data is coverage-limited, not
  invalid — the profiler censors and selection is creation-based.
- **Did not spend money to confirm a robustly-negative result** — chose the $0 reset path.
- **Three real bugs were caught only by hitting the live API** — validating against a live pull
  (per 2c/2d) was load-bearing, exactly as flagged.

## Suggested commit plan (human runs git — CLAUDE.md §4)

Work branch: **`Phase2`**. Suggested logical commits:

1. **fix(dune): free-tier performance tier + ` UTC` timestamp parsing**
   — `src/autocrypt/providers/dune.py` (`execute_query`, `_parse_dt`).
2. **feat(dune): new-launch cohort query + graceful 402 (credit-cap) handling**
   — `src/autocrypt/providers/dune.py` (`DEX_TRADES_SQL`, `DuneCreditCapError`,
     `iter_trade_rows`), `src/autocrypt/ingestion/dune_backfill.py` (`hit_credit_cap`).
3. **test(dune): pin the 402 partial-persist path** — `tests/test_dune_backfill.py`.
4. **docs(phase-2): real-data kill-gate curve + 2f synthesis + spec update**
   — `docs/phase-2-profile-dune.md`, `docs/phase-2f-synthesis.md`, `Project_spec.md`,
     `.env.example`.

Do **not** commit `data/` (DBs, logs) or `.env`. `.env` is git-ignored — verify it is not staged.

---

## ▶ Kickoff prompt for the next session — paste into a fresh Claude Code terminal

```text
Read CLAUDE.md, then Project_spec.md, then docs/phase-2f-synthesis.md, then
docs/phase-2-profile-dune.md (the real-data kill-gate curve). Confirm back to me in 3-4
sentences where we are and this session's goal before doing anything else.

CONTEXT: Phase 2 (KILL-GATE). The real Dune cohort FLIPPED the conditional-GO to a
provisional NO-GO for the automated short-hold (<=120s) Solana strategy: blind -15.99%,
best-threshold signal -15.16% over n=1,763, negative across depth/horizon/rug sweeps and
the permutation test. The Phase-1 snapshot's +6.8%/p=0.008 was n=19 small-sample noise.
The result is valid (profiler censors truncated entries; cohort is creation-selected) but
covers a SINGLE ~1h creation window — free Dune credits are exhausted (~335k rows/mo;
the one backfill used them up; a fresh pull 402s at row 0).

DECISION ON RECORD: confirm at $0 after the Dune free monthly credit reset (one small
<300k-row, ~20min clean second window), then finalize NO-GO. NOT chosen: paying to confirm.

GOAL THIS SESSION (all $0 / GREEN unless noted):
  1. Check whether Dune free credits have reset (operator: report remaining credits, or I
     attempt a tiny dune-validate over a 5-min window — if it 402s, not reset yet; stop).
  2. If reset: dune-backfill a fresh ~20min creation window (query_id 7637616) into a
     separate clean DB (DB_URL=duckdb:///data/autocrypt_dune_confirm.duckdb so the collect
     writer lock is untouched), aiming for a COMPLETE (non-402-truncated) pull. qc it.
  3. RE-RUN autocrypt profile on it. Compare the curve to docs/phase-2-profile-dune.md.
     - If still ~-16% across sweeps -> FINALIZE NO-GO. Present the pivot-vs-shelve fork
       (Base / longer-hold judgmental thesis / stop). YELLOW: get explicit human sign-off.
     - If it materially flips positive -> the single-window result was unrepresentative;
       widen the investigation before any GO.
  4. Do NOT start Phase 3. Do NOT spend money without an explicit cap (YELLOW).

If credits are NOT reset yet: report that, leave everything as-is, and tell me the
expected reset date so we can time the next run. Don't pay to work around it.

Autonomy: GREEN for all read-only/simulated/backtest/code (collector, profiler, Dune
validate/backfill on FREE credits). YELLOW: any PAID tier (Dune Plus ~$399/mo or CoinGecko
Analyst $129/mo — needs a cap) and the final NO-GO / pivot sign-off. RED unchanged.

First concrete step: determine whether free credits have reset (ask me, or a 5-min
dune-validate probe); if reset, run the ~20min confirmation backfill + qc + profile.
```
