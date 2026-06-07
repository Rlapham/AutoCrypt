# Phase G0/G1 Synthesis — graduation-event detection + accumulator relabel

*Session date: 2026-06-03. Track G (graduation accumulator — THE MAIN GOAL), Iteration 2.
Ran autonomously. Pivoted here after the operator took the M3 YELLOW fork: close Track M's
daily price-only battery (NO-GO) and concentrate on Track G.*

## Goal

Track M's mid-cap daily-OHLCV signal battery hit its kill-gate and is a clean NO-GO (M3).
The operator closed it and pivoted to **Track G**, whose thesis is to enter *graduated*
tokens (survivors that migrated from a bonding curve to a deep AMM pool) and ride a
multi-day **accumulator** arc — explicitly avoiding Iteration-1's dead fresh-launch corner.
This session's mandate: (1) build **G0 graduation-event detection** (the discrete
liquidity-deepening milestone) from the accruing multi-day store, and (2) **G1** — re-label
the attribution "success" to *"survives AND appreciates over N days"* and rebuild a
*followable* accumulator wallet cohort, all under the §3 kill-gate discipline.

## Headline outcomes

1. **Both background collectors were dead at session start** (the G0 collector had died on a
   transient DNS `ConnectError` with no restart loop). Relaunched both behind a **resilient
   restart wrapper** (`scripts/g0_collect_interim.sh`) so a network blip self-heals. Caught
   and avoided a **duplicate** snapshot-loop (the pre-existing PID 3003 was alive but invisible
   to `grep autocrypt` because the script name has no "autocrypt" in it).
2. **G0 graduation-event detector — BUILT, TESTED, and validated.** New `grad/graduation.py`
   classifies each pool's `dex` venue into a lifecycle phase (bonding-curve vs AMM) and
   detects a graduation as a mint's **first AMM-venue pool created at/after its
   bonding-curve pool**, stamped point-in-time at the AMM pool's `knowable_at`,
   survivorship-complete (every bonding-curve-origin mint is the denominator). On ~10h of
   real data: **genuine graduation rate = 1.71%** (181/10,557) — strikingly consistent with
   the historical ~0.7–1%+ "graduate" rate cited in `Project_spec §3`. Strong validity check.
3. **A decisive collection-design gap found AND fixed.** The G0 census showed **0–2/181
   genuine graduations had ANY post-graduation AMM swap**: the collector tailed newest pools
   by creation (≈99% bonding-curve), so the later-created, rarer AMM pool of a graduated
   token almost never won a watchlist slot. **Track G's entire thesis is unobservable
   without post-graduation data.** Fixed: `collect --amm-reserved` reserves watchlist
   capacity for AMM (graduation-target) pools. Verified live — swap mix flipped to
   **pumpswap-heavy** (21.6k pumpswap vs 7.9k pumpfun) post-fix, and `raydium*/orca` swaps
   now appear. A real **cap-overshoot bug** in the first version (watchlist hit 66 vs
   watch_max 60) was caught from runtime logs and fixed + regression-tested.
4. **G1 accumulator relabel — BUILT and TESTED, honestly NOT YET RUN.** `grad/accumulator_
   label.py` encodes the new success definition: an entry succeeds iff within `n_days` the
   token both **appreciates** (≥ +X%) **and survives** (never rugs below a floor, still
   trading at the horizon). It resolves **at the horizon** (no early-crossing shortcut — a
   moon-then-rug is a *failure*, which is exactly the orchestrator trade we must not learn
   from). It is point-in-time (resolution knowable at `entry_knowable + window`). **It is not
   run on real data because there is none yet** (0–2/181 post-grad coverage). Fabricating a
   wallet book on absent data would violate the honesty discipline; the label is ready to
   drive a `WalletScoreBook` rebuild the moment the now-fixed collector ripens.

## Why we did NOT produce a G1 verdict (and shouldn't have)

Two independent blockers, both honest:
- **No post-graduation data.** 0–2 of 181 genuine graduations have a single post-grad swap.
  There is nothing to label.
- **No elapsed time.** The graduation store holds only ~10h of wall-clock; an N-day
  accumulator label has *no resolved outcomes* until N days pass. Even with perfect
  collection, G1's first score is weeks out.

So the correct G0/G1 deliverable is **the instruments** (detector + relabel) + **the
unblock** (collector fix), not a number. This mirrors the project's core discipline: report
nulls/blocks plainly, never manufacture a positive on a thin or biased sample.

## What was built

- **`src/autocrypt/grad/graduation.py`** — venue→phase taxonomy (`BONDING_CURVE_VENUES`
  = {pumpfun, meteora_dbc}; `AMM_VENUES` = {pumpswap, raydium, raydium_clmm, orca, meteora,
  meteora_daam_v2, manifest}; unknown ⇒ OTHER, never a graduation target), `detect_graduations`
  (point-in-time, survivorship-complete), a **co-launch guard** (BC→AMM lag < `min_lag_s`
  ⇒ `suspect_colaunch`), post-grad swap coverage counting, and a markdown census renderer.
- **`src/autocrypt/grad/accumulator_label.py`** — the G1 survive-AND-appreciate relabel:
  `AccumulatorLabel` config + `label_accumulator_entry` (hold-to-horizon resolution, exact
  in-window filtering, "alive at horizon" gate). Pure/deterministic.
- **Collector fix** — `ingestion/collect.py`: `_admit_candidates` (extracted pure helper)
  admits AMM pools first up to `watch_max` and caps non-AMM at `watch_max - amm_reserved`,
  with a total-cap guard; `collect --amm-reserved` (default 20; the interim wrapper runs 30).
  Survivorship intact: `PoolCreated` is still written for every enumerated pool.
- **CLI `grad-detect`** — read-only census over the graduation store (point DB_URL at a
  snapshot copy; the live `collect` writer holds the DuckDB lock continuously).
- **Tests** — `tests/test_grad_graduation.py` (8), `tests/test_grad_accumulator_label.py`
  (7), `tests/test_collect.py` (+4 admission/cap tests). **116/116 green, ruff clean** (was 97).
- **Docs** — `docs/phase-G0-census.md` (regenerable evidence), this synthesis.

## Key decisions & why

1. **Graduation = venue transition, stamped at the AMM pool's `knowable_at`.** The collected
   data has no reserve/liquidity time-series (init liquidity is null; no `liquidity_change`,
   no OHLCV). The on-chain-observable, point-in-time milestone is the appearance of an
   AMM-class pool for a mint that started on a bonding curve — the constant-product analogue
   of "graduated to real liquidity."
2. **Co-launch artifacts flagged, not counted.** `meteora_dbc → meteora_daam_v2` pairs are
   created within ~0.6 min (the DAMM pool is seeded at launch alongside the DBC pool — a
   config artifact, 422 of 496 transitions), so their `pool_created` time is *not* a faithful
   graduation moment. The `suspect_colaunch` flag (lag < 120s) separates them; only the 181
   genuine graduations (predominantly `pumpfun → pumpswap`, faithful migration timestamps)
   feed the rate. Not flagging these would have ~3×-inflated the graduation rate.
3. **Fixed collection rather than only documenting the gap.** The 0/181 coverage means months
   of current collection would yield nothing for Track G. The `--amm-reserved` fix is the
   single highest-leverage action for the main goal, so it was implemented and deployed now.
   *(Flagged as a near-YELLOW change to a running pipeline — see open questions; trivially
   revertible via `--amm-reserved 0`.)*
4. **Did not run G1 on absent data.** Built and tested the label; refused to produce a wallet
   book / verdict with 0–2 post-grad samples and <10h of horizon. Honesty over a fake result.

## Open questions / follow-ups

1. **Operator confirm the collector change (near-YELLOW).** `--amm-reserved 30` reallocates
   half the swap-tailing watchlist from bonding-curve to AMM pools. It does not touch the
   survivorship-complete `PoolCreated` enumeration, only which pools get their *swaps* tailed.
   Revert with `--amm-reserved 0` if undesired. Recommend keeping it — Track G is dead without it.
2. **G1 is data-gated, not idea-gated.** Next real G1 session needs the post-fix collector to
   have accrued multi-day arcs for a meaningful number of graduated pools. Rough cadence:
   re-run `grad-detect` periodically; once post-grad coverage is, say, ≥ a few dozen
   graduations with ≥ N-day arcs, wire `accumulator_label` into a `WalletScoreBook` rebuild
   and run the G2 kill-gate. Realistically **weeks** of wall-clock.
3. **Durable collection still interim.** Both collectors are `nohup` (die on reboot); the
   launchd form is blocked by macOS TCC on `~/Documents` (grant Full Disk Access to
   `/usr/local/bin/uv`, or relocate the repo). Until then, re-launch on reboot via the
   commands in the kickoff.
4. **Single-writer/lock note.** The live `collect` writer holds the graduation DB lock
   continuously (unlike the midcap snapshot loop, which sleeps), so `grad-detect` runs against
   a **file-copy snapshot**, not the live file. Documented in the CLI help.

## State of the code

`src/autocrypt/grad/{graduation,accumulator_label}.py` + CLI `grad-detect` + the
`collect --amm-reserved` admission fix are tested; **116/116 green, ruff clean.** No paid
spend, no keys, no funds, no trading. Track-M store untouched. Background daemons at session
end (both interim `nohup`, die on reboot):

| Process | PID (at write) | Writes to | Purpose |
|---|---|---|---|
| `g0_collect_interim.sh` → `autocrypt collect` | 6618→6620→6621 | `autocrypt_graduation.duckdb` | G0/G1 cohort, AMM-reserved, 7-day hold |
| `midcap_snapshot_loop.sh` | 3003 | `autocrypt_midcap.duckdb` | Track-M survivorship-safe daily snapshot |

---

## Commit plan (human runs git — see CLAUDE.md §4)

Target branch: `M3` (or a fresh `phase-G0` branch off it). Suggested logical units:

1. **feat(grad): graduation-event detection (G0)** — `src/autocrypt/grad/__init__.py`,
   `src/autocrypt/grad/graduation.py`, CLI `grad-detect` in `src/autocrypt/cli.py`,
   `tests/test_grad_graduation.py`, `docs/phase-G0-census.md`.
2. **feat(collect): reserve watchlist capacity for graduated AMM pools** —
   `src/autocrypt/ingestion/collect.py`, `collect --amm-reserved` in `src/autocrypt/cli.py`,
   `tests/test_collect.py`, `scripts/g0_collect_interim.sh`.
3. **feat(grad): G1 accumulator survive-AND-appreciate relabel** —
   `src/autocrypt/grad/accumulator_label.py`, `tests/test_grad_accumulator_label.py`.
4. **docs: G0/G1 synthesis + spec update** — `docs/phase-G0-synthesis.md`, `Project_spec.md`,
   and `scripts/g0_collect_interim.sh` if not already in unit 2.

---

```text
Read CLAUDE.md, then Project_spec.md, then docs/iteration-2-strategy.md, then
docs/phase-G0-synthesis.md (and docs/phase-G0-census.md). Confirm in 3-4 sentences where we
are and this session's goal before doing anything else.

CONTEXT: Iteration 2. Track M (mid-cap daily battery) is a closed NO-GO (M3). We pivoted to
TRACK G — the main goal: enter GRADUATED tokens (bonding-curve → deep AMM) and ride a
multi-day "accumulator" arc. G0 built a point-in-time, survivorship-complete
graduation-event detector (grad/graduation.py, CLI grad-detect): genuine graduation rate
1.71% (~matches the known ~1%), co-launch artifacts flagged. THE KEY FINDING: the forward
collector was capturing ~0 post-graduation swaps (it tailed bonding-curve pools), so Track G
had no data. FIXED this session: collect --amm-reserved reserves watchlist slots for AMM
(graduation-target) pools (deployed; swap mix flipped pumpswap-heavy). G1's accumulator
relabel (survives AND appreciates over N days, resolves at horizon — a moon-then-rug is a
FAILURE) is BUILT + tested in grad/accumulator_label.py but NOT YET RUN: there is no
post-graduation data yet and <10h of horizon. 116/116 tests green, ruff clean.

THIS SESSION = advance Track G toward the G2 kill-gate, data permitting:
  1. CHECK BACKGROUND JOBS FIRST (both die on reboot — re-launch if `ps aux | grep
     "autocrypt collect"` shows nothing):
       - G0 collector (resilient wrapper, AMM-reserved):
           nohup bash scripts/g0_collect_interim.sh > data/g0_collect.interim.log 2>&1 &
       - Track-M snapshot loop:
           nohup bash scripts/midcap_snapshot_loop.sh > data/midcap_snapshot.log 2>&1 &
  2. RE-RUN THE CENSUS to see how post-grad coverage has ripened since the fix:
       cp data/autocrypt_graduation.duckdb /tmp/grad_snap.duckdb
       [ -f data/autocrypt_graduation.duckdb.wal ] && cp data/autocrypt_graduation.duckdb.wal /tmp/grad_snap.duckdb.wal
       DB_URL=duckdb:////tmp/grad_snap.duckdb uv run autocrypt grad-detect --out docs/phase-G0-census.md
     If a meaningful number of genuine graduations now have multi-day post-grad arcs:
  3. G1: wire grad/accumulator_label.label_accumulator_entry into a WalletScoreBook rebuild
     (reuse attribution/wallet_book.py machinery) over the GRADUATED cohort to surface a
     *followable* accumulator wallet cohort. Re-validate point-in-time + survivorship.
  4. G2: run the graduation-momentum KILL-GATE through the profiler at multi-hour/day
     horizons, entry conditioned on graduation + accumulator-cohort buying, with the
     orchestrator-fade overlay as a rug/avoid gate. Apply §3 (profitable-after-cost ∧
     point-in-time ∧ survivorship-complete ∧ beats blind+random w/ multiple-comparison
     discount ∧ robust ∧ enough fires). GO/NO-GO is YELLOW.
  If coverage is still too thin (likely — ripening takes weeks): do NOT force G1/G2 on a thin
  sample. Instead harden durability (launchd/FDA or repo relocation so collection survives
  reboot), and let the data accrue. Report the coverage number plainly.

Autonomy: GREEN code/backtest/free data; YELLOW paid tiers + universe/label changes + each
GO/NO-GO + the collector admission policy; RED unchanged. Single-writer rule: the live
`collect` writer holds the graduation DB lock — run grad-detect against a file COPY. The
snapshot loop owns autocrypt_midcap.duckdb during its brief daily write.
```
