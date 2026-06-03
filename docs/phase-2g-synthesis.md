# Phase 2g — Session Synthesis (credit-reset check: NOT reset; no-op, timed wait)

*Continuation of Phase 2 (THE KILL-GATE). Prior session (2f) ran the real Dune cohort and
the conditional-GO flipped to a **provisional NO-GO** (blind −15.99%, signal −15.16% over
n=1,763, negative across all sweeps + permutation). The decision on record is to confirm at
$0 with one clean second window **after the Dune free monthly credit reset**, then finalize
NO-GO. Authoritative state: `Project_spec.md`.*

## Headline (read this first)

This session was a **timing check, by design a near-no-op**. The plan's first step is to
determine whether the Dune free monthly credits have reset before spending a backfill on the
confirmation window.

- **Credits are NOT reset.** The `DUNE_API_KEY` was created ~**2026-06-02** and today is
  **2026-06-02** — i.e. **day 0 of the billing cycle**. The free allowance was exhausted last
  session (2f); a monthly reset would fall ~**2026-07-02**. Operator elected to **skip the
  probe** (no point burning an API call that would 402 on day 0) and wait for the reset.
- **Nothing was changed.** No code, no data, no DB, no spend. The 2f state stands verbatim:
  provisional NO-GO on a single ~1h creation window, pending one free confirmation window.
- **No probe call was made** — avoided wasting the (already-exhausted) free allowance.

## State of the code / data (unchanged from 2f)

- Code: 57/57 tests green, ruff clean (as of 2f). No edits this session.
- `data/autocrypt_dune.duckdb` — the profiled 2f cohort (653,922 events; 2026-05-19
  00:00–00:57 UTC, 402-truncated). Untouched.
- `data/autocrypt_dune_clean.duckdb` — empty throwaway (the 2f 402-at-row-0 probe). Untouched.
- `autocrypt collect` background process — may or may not still be alive (a `nohup` process
  does not survive reboot). Harmless either way; not relied on for the kill-gate.

## The plan, unchanged, deferred to the reset

When credits reset (~2026-07-02, operator to confirm billing-cycle date):

1. Backfill a fresh ~20-min creation window (`query_id 7637616`) into a **separate clean DB**
   (`DB_URL=duckdb:///data/autocrypt_dune_confirm.duckdb`, so the `collect` writer lock is
   untouched), aiming for a **COMPLETE (non-402-truncated)** pull. QC it.
2. Re-run `autocrypt profile` on it; compare the curve to `docs/phase-2-profile-dune.md`.
   - Still ~−16% across sweeps → **FINALIZE NO-GO**; present pivot-vs-shelve fork
     (Base / longer-hold judgmental thesis / stop) for explicit human sign-off (YELLOW).
   - Materially flips positive → the single-window 2f result was unrepresentative; widen the
     investigation before any GO.
3. Do NOT start Phase 3. Do NOT spend money without an explicit cap (YELLOW).

## Open questions / forks

- **Reset date precision.** ~2026-07-02 is inferred from a ~2026-06-02 key-creation date.
  Operator: confirm the Dune billing-cycle reset day so the next run is timed, not guessed.
- Everything else carries forward from 2f unchanged (paid escalation YELLOW & not chosen;
  pivot candidates Base / longer-hold judgmental; QC `logical_duplicates` WARN acceptable).

## Honesty log

- **Did not burn a probe to "look busy."** The date math (day 0) made a 402 a near-certainty;
  reporting that plainly and waiting is the correct $0 move.
- **No work was manufactured.** This session legitimately had nothing to do but confirm timing.

## Suggested commit plan (human runs git — CLAUDE.md §4)

Work branch: **`Phase2`**. Single docs-only commit:

1. **docs(phase-2): 2g credit-reset check (not reset; deferred to ~2026-07-02) + spec update**
   — `docs/phase-2g-synthesis.md`, `Project_spec.md`.

Do **not** commit `data/` or `.env`.

---

## ▶ Kickoff prompt for the next session — paste into a fresh Claude Code terminal (run on/after ~2026-07-02)

```text
Read CLAUDE.md, then Project_spec.md, then docs/phase-2g-synthesis.md, then
docs/phase-2-profile-dune.md (the real-data kill-gate curve). Confirm back to me in 3-4
sentences where we are and this session's goal before doing anything else.

CONTEXT: Phase 2 (KILL-GATE). The real Dune cohort flipped the conditional-GO to a
PROVISIONAL NO-GO for the automated short-hold (<=120s) Solana strategy: blind -15.99%,
best-threshold signal -15.16% over n=1,763, negative across depth/horizon/rug sweeps and
the permutation test. The Phase-1 +6.8%/p=0.008 was n=19 noise. Decision on record: confirm
at $0 with ONE clean second window after the Dune free monthly credit reset, then finalize
NO-GO. The 2g session confirmed credits were NOT reset (key created ~2026-06-02; day 0 of
the cycle) and deferred to ~2026-07-02. NOTHING changed since 2f.

GOAL THIS SESSION (all $0 / GREEN unless noted):
  1. Confirm Dune free credits have reset (operator reports remaining credits, OR I run a
     tiny dune-validate over a 5-min window -- if it 402s, not reset yet; stop and report).
  2. If reset: dune-backfill a fresh ~20min creation window (query_id 7637616) into a
     separate clean DB (DB_URL=duckdb:///data/autocrypt_dune_confirm.duckdb so the collect
     writer lock is untouched), aiming for a COMPLETE (non-402-truncated) pull. qc it.
  3. RE-RUN autocrypt profile on it. Compare the curve to docs/phase-2-profile-dune.md.
     - Still ~-16% across sweeps -> FINALIZE NO-GO. Present the pivot-vs-shelve fork
       (Base / longer-hold judgmental thesis / stop). YELLOW: get explicit human sign-off.
     - Materially flips positive -> single-window result was unrepresentative; widen the
       investigation before any GO.
  4. Do NOT start Phase 3. Do NOT spend money without an explicit cap (YELLOW).

If credits are STILL not reset: report it, leave everything as-is, give the next expected
reset date. Don't pay to work around it.

Autonomy: GREEN for all read-only/simulated/backtest/code (collector, profiler, Dune
validate/backfill on FREE credits). YELLOW: any PAID tier (Dune Plus ~$399/mo or CoinGecko
Analyst $129/mo -- needs a cap) and the final NO-GO / pivot sign-off. RED unchanged.

First concrete step: determine whether free credits have reset; if reset, run the ~20min
confirmation backfill + qc + profile.
```
