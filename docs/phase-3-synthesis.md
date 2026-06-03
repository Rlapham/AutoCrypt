# Phase 3 — Session Synthesis (wallet-attribution edge BUILT + tested; NO-GO strengthens)

*Phase 2 had flipped to a provisional NO-GO on the **derivative composite** signal (−16%).
This session, rather than idle for a month waiting on the Dune free-credit reset, the operator
chose to **build the rest of the architecture and validate the plan on the data we already
have**. The headline: the **wallet-attribution model — the project's actual claimed defensible
edge (Project_spec §2), which the kill-gate had never tested — is also strongly negative**, and
for a *structural* reason that no signal can fix. Authoritative state: `Project_spec.md`.*

## Headline (read this first)

1. **Built the Phase-3 wallet-attribution model** (`src/autocrypt/attribution/`), the lead-weighted
   "which wallets demonstrably buy *before* run-ups, and are they buying now?" edge — and wired it
   into the **exact same** survivorship-complete, point-in-time, cost-realistic kill-gate profiler
   (new `autocrypt profile --mode attribution`). Derivative path unchanged.
2. **It loses badly on the real cohort.** Blind expectancy **−28.1%** (vs the derivative's −16%),
   best-threshold **−27.3%**, n=995 fires over 262 pools. **Not significant** (permutation p=0.117
   at best, before the multiple-comparison discount).
3. **The smarter the money, the worse the return — monotonically.** Raising the attribution-lift
   threshold (select for higher-track-record wallets) drives expectancy −28% → −31% → −42% →
   **−82%** (top ~5% of "smart money" buys: 2% hit rate). The signal **anti-predicts** returns at
   the high end. This is the *manufactured-pump / exit-liquidity* failure mode Project_spec §2
   flagged for social chatter — now shown for on-chain wallet signals: the highest-"lead" wallets
   are pump-setup/wash wallets you do **not** want to follow into a 60s hold.
4. **The structural killer: marked drift ≈ 0%.** Even conditioning on demonstrated smart money
   buying *now*, the mean **no-cost** 60s forward return is **−0.03%** (and ≈0 at 30s/120s too).
   There is simply **no gross short-hold edge to capture** on this cohort; the ~28% round-trip cost
   on thin fresh-launch pools then guarantees a loss. No entry signal can overcome ~0 drift vs
   ~20–28% costs.
5. **Robust across every sweep and every labelling choice.** Run-up definition +50%/+100%/+200%:
   blind −28.0%/−28.1%/−28.2% (invariant). Depth ×0.5/×1/×2: −36.8%/−28.1%/−21.7% (never flips).
   Horizon 30/60/120s: ≈ −28 to −30%. Rug on/off: both deeply negative.
6. **Verdict: the NO-GO is now STRONGER and better-explained.** Both the derivative signal AND the
   claimed wallet-attribution edge fail on this window, and the dominant cause (≈0 gross drift vs
   large costs) is **signal-independent**. The honest limit is unchanged: it is one ~1h creation
   window. Report: `docs/phase-3-attribution-dune.md` (full +100% curve + sweeps).

## Derivative vs attribution — side by side (blind, h=60s, $250)

| signal | blind exp | best-thr exp | marked drift | cost drag | permutation (best) |
|---|---|---|---|---|---|
| Derivative composite (Phase 2f) | −15.99% | −15.16% | +0.43% | 16.4% | p=0.022 (still −15%) |
| **Wallet attribution (Phase 3)** | **−28.12%** | **−27.28%** | **−0.03%** | **28.1%** | **p=0.117 (n.s.)** |

Attribution fires concentrate on thinner pools (higher cost drag) and, unlike the derivative
signal, **tightening it makes returns worse, not flat** — the opposite of an edge.

## Run-up-definition robustness (blind expectancy; tighter threshold → expectancy)

| run-up def | blind | mid-thr | top-thr |
|---|---|---|---|
| +50% / 300s | −28.04% | −29.4% | **−83.6%** |
| +100% / 300s | −28.12% | −31.3% | **−82.1%** |
| +200% / 300s | −28.22% | −34.6% | **−72.4%** |

The "smart money anti-edge" holds regardless of how a run-up is defined.

## Why this is trustworthy (and its honest limits)

- **Point-in-time, no look-ahead.** A wallet's lead-score at decision time T uses ONLY trials whose
  outcome was knowable at ≤ T (success = price-crossing print's `knowable_at`; failure = entry
  knowable + run-up window). Pinned by tests (`test_score_is_point_in_time`,
  `test_failure_only_knowable_after_window`, signal ignores future swaps).
- **Survivorship-safe.** Attempts are enumerated over every created pool incl. rugs/duds (they are
  the failures in the denominator). Book: **59,597 resolved trials / 32,475 wallets / 3,625 pools**
  — real evidence, not a toy. Population lead rate 20.3% (run-ups are common on fresh launches,
  which itself limits how discriminating "led a run-up" can be).
- **Same realistic costs/censoring** as the derivative kill-gate (constant-product own-impact both
  legs; forward-truncated entries censored, not scored).
- **Honest limits:** (a) ONE ~1h creation window (representativeness still unconfirmed — the planned
  $0 confirmation needs the Dune monthly reset). (b) Wallet track records are necessarily built
  *within* that hour, so histories are short, esp. early in the window — attribution is best-tested
  on a longer dataset. BUT the decisive finding (marked drift ≈ 0) is **independent of attribution
  quality**, and the high-lift anti-correlation suggests more history would sharpen the *wrong*
  signal, not rescue it.

## What was built / changed (state of the code)

- **NEW `src/autocrypt/attribution/`** — the model:
  - `wallet_book.py`: run-up labelling (`_pool_attempts`, with a sparse-table range-max so a failed
    trial is O(1)), point-in-time `WalletScoreBook` (`score_at`/`base_rate_at` via bisect),
    Beta-Binomial shrinkage to the population base rate. `AttributionConfig`.
  - `signal.py`: `compute_attribution` — buy-USD-weighted mean lift of scored recent buyers
    (tail-scan of the visible window). `AttributionSignalConfig`.
- **Profiler integration (behaviour-preserving for the derivative path):**
  - `profiler/signals.py`: `SignalSnapshot` gains `attr_*` fields (defaulted off) + `defined_for()`.
  - `profiler/profiler.py`: `Profiler(cfg, book=None)`; computes attribution per decision and gates
    definedness by `signal_field`. **Perf:** the decision loop now passes a bounded tail slice
    `swaps[lo:i+1]` (covers the widest lookback) instead of all history — provably identical, turns
    per-pool O(n²) → O(n·window) (decisive on deep pools; full report 12min-hang → ~5.7min).
  - `profiler/report.py`: `build_report(..., signal_field, attr_cfg)` builds the book once from the
    FULL universe (min_swaps=1, maximal wallet history) and renders an attribution-mode report.
  - `cli.py`: `profile --mode derivative|attribution [--runup-pct --runup-window]`.
- **`storage/store.py`: `EventStore(path, read_only=True)`** — DuckDB shared-lock readers, so several
  profile sweeps can run over one store concurrently (used for the +50/+100/+200 sweep). `cli profile`
  now opens read-only.
- **`profiler/__init__.py`: lazy (PEP 562) re-exports** — fixes a package-level import cycle
  (attribution depends on `profiler.dataset`; eager init pulled the whole chain).
- **Tests:** `tests/test_attribution.py` (+6, pinning run-up labelling, point-in-time scoring,
  shrinkage, and the signal's no-look-ahead). **63/63 green, ruff clean.**

## Data artifacts (NOT committed — `data/` is git-ignored)

- Profiled `data/autocrypt_dune.duckdb` (the 2f cohort; 2026-05-19 00:00–00:57 UTC, 318,545 swaps).
- Reports written: `docs/phase-3-attribution-dune.md` (+100%, full). The +50%/+200% sweep used
  throwaway docs that were folded into this synthesis and removed.

## Decision (RESOLVED 2026-06-03) + open items

- **✅ PIVOT vs SHELVE → SHELVE.** The operator chose to **shelve the automated short-hold Solana
  strategy.** The kill-gate is closed **NO-GO**: two independent signals (derivative + attribution)
  and a structural ≈0-drift finding all point the same way, and the cause is microstructural
  (drift-vs-cost), not fixable by a better signal. **No Phase 4–6, no live capital, no pivot build
  started.** Pivots considered and declined for now: **Base** (cleaner labels but higher fees, and
  our finding is drift/cost not label quality) and **longer-hold/judgmental** (root-cause-addressing
  but a different, unbuilt, barely-autonomous strategy needing new long-horizon data + profiler).
- **Retained for possible future use** (not committed work): the attribution model + the profiler
  harness — reusable if a longer-horizon thesis is ever pursued, or for the optional $0 confirmation.
- **Optional $0 representativeness confirmation** after the Dune free reset (~2026-07-02): one clean
  second window, re-run BOTH modes. Lower-stakes given two structural negatives; only worth doing if
  the operator wants the single-window caveat closed before fully archiving.
- Paid escalation (Dune Plus ~$399 / CoinGecko Analyst $129) — **not** chosen.

## Honesty log

- **Tested the actual thesis, did not dodge it.** The kill-gate had only tested the derivative
  composite; this session built and tested the wallet-attribution edge the whole project rests on.
  It failed too. Reported plainly; no threshold cherry-picked (the best threshold is still −27%, and
  tighter is monotonically worse).
- **Distinguished "validate the architecture" from "validate the edge."** The plan/architecture is
  validated end-to-end (book, point-in-time discipline, integration, 63 tests). The EDGE it measures
  is negative on this data. We did not relabel a negative as a GO.
- **Stated the genuine limits** (single 1h window; short in-window wallet histories) without using
  them to explain away the result — the decisive ≈0-drift finding is signal- and history-independent.

## Suggested commit plan (human runs git — CLAUDE.md §4)

Work branch: **`Phase2`** (or rename to `Phase3` — operator's call). Suggested logical commits:

1. **feat(attribution): lead-weighted wallet-attribution model (point-in-time, survivorship-safe)**
   — `src/autocrypt/attribution/` (new package).
2. **feat(profiler): score attribution on the kill-gate harness + O(n·window) decision loop**
   — `src/autocrypt/profiler/{signals,profiler,report}.py`, `profiler/__init__.py` (cycle fix).
3. **feat(store): read-only EventStore for concurrent analytics readers**
   — `src/autocrypt/storage/store.py`, `src/autocrypt/cli.py` (`profile --mode`, read-only open).
4. **test(attribution): pin run-up labelling + point-in-time scoring + no-look-ahead** (+6 tests)
   — `tests/test_attribution.py`.
5. **docs(phase-3): attribution kill-gate result + synthesis + spec update**
   — `docs/phase-3-attribution-dune.md`, `docs/phase-3-synthesis.md`, `Project_spec.md`.

Do **not** commit `data/` or `.env`.

---

## ▶ Kickoff prompt for the next session — paste into a fresh Claude Code terminal

The project is **shelved** as of 2026-06-03 (kill-gate NO-GO, decision made). There is no
queued next phase. Use the prompt below only if/when the operator decides to revisit.

```text
Read CLAUDE.md, then Project_spec.md, then docs/phase-3-synthesis.md, then
docs/phase-3-attribution-dune.md. Confirm back to me in 3-4 sentences where we are before
doing anything else.

CONTEXT: AutoCrypt is SHELVED (operator decision 2026-06-03). The Phase 2/3 kill-gate is a
closed NO-GO for automated short-hold Solana: on the real ~1h Dune cohort BOTH the derivative
composite (-16%) and the wallet-attribution edge (-28% blind, anti-predictive, p=0.117 n.s.)
lose, and the cause is structural (mean no-cost 60s drift ~0% vs ~20-28% costs) -- not fixable
by a better signal. The architecture/model/harness are validated and retained (63 tests green).

I am NOT resuming a pivot or any build unless you explicitly direct one. Possible revisit
paths if you want them (each YELLOW, none started): (a) optional $0 representativeness
confirmation -- if Dune free credits have reset (~2026-07-02), re-run BOTH `autocrypt profile`
modes on one fresh clean window to close the single-window caveat; (b) a longer-hold/judgmental
thesis (needs new long-horizon data + a long-horizon profiler); (c) Base. Do NOT spend money.
RED unchanged. Tell me which, if any, you want -- otherwise this stays shelved.
```
