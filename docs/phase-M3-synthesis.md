# Phase M3 Synthesis — mid-cap deep-pool signal battery + KILL-GATE

*Session date: 2026-06-03. Track M (mid-cap deep-pool), Iteration 2. Ran autonomously.*

## Goal

M2 removed the structural disqualifier that killed Iteration 1 (Law 1, the cost wall:
round-trip friction is ~1% on these deep pools, not 20–28%). M3 is the actual **kill-gate**:
do any transparent deep-pool signals — time-series momentum, cross-sectional momentum,
mean-reversion, a volume-gated breakout — clear the §3 bar (profitable-after-cost ∧
point-in-time ∧ beats blind+random ∧ robust ∧ enough fires) on the mid-cap universe? On the
survivorship-**biased** control this can only ever be NO-GO/"unproven", never a GO.

## Headline verdict — NO-GO on all four signals (and cleanly so)

| signal | scored fires | blind exp. | best-threshold exp. | binding failure |
|---|---:|---:|---:|---|
| `ts_mom` (time-series momentum) | 2,855 | −0.78% | +2.13% (n=143) | not better than random — discounted p=0.52 |
| `xs_mom` (cross-sectional momentum) | 2,814 | −0.71% | +2.32% (n=286) | not better than random — discounted p=0.58 |
| `mean_rev` (mean-reversion) | 2,855 | −0.78% | +11.01% (n=143) | not better than random — discounted p=0.22 |
| `breakout` (volume-gated) | 1,807 | −0.25% | −0.25% (blind) | never profitable after cost |

92 speculative-only in-band pools (pegged/LST/stable/wrapped dropped; pools with <16 bars
dropped). Hold horizon 5 days, lookback 10, position = min($10k, 0.4%×reserve) [the M2
capacity rule], cost = 30 bps/leg + own impact both legs at 0.5×reserve depth. Full evidence:
**`docs/phase-M3-killgate.md`** (regenerate: `… autocrypt midcap-killgate --out …`).

**The failure is decisive, not marginal — and it does NOT lean on the survivorship caveat.**
Even on a universe rigged to inflate returns, no signal selects better-than-random entries
once you discount for testing several thresholds. We didn't have to invoke "but it's biased"
to reach NO-GO; the gate closed on its own statistics first.

## Why the apparent positive tails are artifacts, not edge

The tight-threshold cells look tempting (mean_rev +11%, xs_mom +2.3%). They are mirages, for
four independent reasons that all point the same way:

1. **Mean is positive but MEDIAN is negative.** At mean_rev's best cell: mean +11.01%, median
   −3.33%. The mean is dragged up by a few survivor moonshots (p75 ≈ 0%, p25 ≈ −9%). That is
   the exact shape a survivorship-biased lottery produces — most trades lose, a handful of
   tokens-that-happened-to-survive-and-rip carry the average.
2. **Tiny samples.** The positive cells are n=143–286 fires out of 2,855, spread over ~5–10×
   variance. The permutation test says a random draw of the same size beats them 4–58% of the
   time — i.e. they are inside the noise (raw p as low as 0.045 for mean_rev, but ×5 thresholds
   tested ⇒ discounted 0.22; nowhere near 0.05).
3. **Regime-fragile.** Split the window in half: every signal is *negative* in the early half
   (−1.6% to −1.7%) and ~flat-to-slightly-positive in the late half (+0.2%). An edge that only
   exists in the back half of one 6-month survivor sample is a time artifact, not a signal.
4. **Depth-fragile.** Halving the depth assumption (depth×0.5, the M2 "pools were shallower
   historically" worry) drives blind expectancy to −2.1% to −2.2% across the board. The verdict
   sign is not stable to the one assumption we can't observe historically.

## The structural reading — Law 1's inequality still isn't satisfied, even cheaply

M2 made costs small in *absolute* terms (~1% at ≤$1k). But at a **realistic capacity-scaled
size** (~0.4% of reserve, which is $5–10k on the median $1.44M pool — M2 showed $5k→2.0%,
$10k→3.3%), the realized round-trip **cost drag is ~2%**. Meanwhile the **5-day marked drift
the signals capture is only ~+1.3% on average** (and that +1.3% is itself survivorship-
inflated). So `gross > cost` (Law 1's inequality) is *barely or not* satisfied at the
blind/aggregate level even on inflated data — which is why **blind expectancy is slightly
negative for every signal.** The signals' job is to find a subset where gross clears cost by a
margin; none does so beyond noise. M2 escaped the *20–28%* wall; it did not manufacture a
*move large and predictable enough* to clear even the ~2% residual at tradeable size.

This is the daily-bar, mid-cap analogue of Iteration 1's finding: the cost is survivable now,
but the **edge in the price series, at this resolution, is ≈ 0 vs costs.**

## What this means for Track M (a YELLOW GO/NO-GO fork — operator call)

**Kill-gate result: Track M's transparent momentum/mean-reversion battery is a NO-GO at daily
resolution on the biased control.** Per the autonomy policy each track's GO/NO-GO is a YELLOW
checkpoint, so this is flagged for the operator rather than unilaterally closing the track.

**My recommendation: stop signal-hunting on Track M's biased daily control, and concentrate on
Track G (the stated main goal).** Reasoning, with the main tradeoff:
- Continuing to try more signals / thresholds on *this* dataset is precisely the overfitting
  trap the honesty discipline warns against — on a biased control, the more knobs you turn the
  more likely you manufacture a fake positive (mean_rev's +11% is already a preview).
- The honest next step for Track M would be the **unbiased forward re-test**: the daily
  snapshot loop has been accruing a survivorship-*safe* universe series since M1. But that
  needs months of wall-clock to have power, so it is a *background* asset, not this week's work.
- Track G (graduation-momentum + multi-day accumulator cohort) is the higher-ceiling thesis and
  its data has been ripening in parallel (G0 collector). That is where the next real session
  should go.
- **Tradeoff / counter-argument:** M3 only tested *four standard* signals at *daily* resolution
  with *one* horizon family. A fair objection is that the mid-cap edge (if any) lives at
  intraday resolution or in features we didn't build (liquidity-velocity, holder flow), which
  this OHLCV-only control can't see. That doesn't rescue a GO here, but it means "Track M is
  dead" is too strong — "Track M's *daily price-only* battery is a NO-GO" is the precise claim.

## What was built

- **`src/autocrypt/midcap/bars.py`** — the OHLCV-bar dataset adapter. Loads the in-band
  universe + each pool's daily bar series (point-in-time: `event_time = close_time`,
  `knowable_at = close_time + latency`, so a daily close is only knowable after the day ends),
  carries `reserve_usd` depth + the speculative flag. Read-only.
- **`src/autocrypt/midcap/barsignals.py`** — the transparent signal battery as pure
  point-in-time functions: `ts_momentum`, `mean_reversion` (negative z-score, dip-buy),
  `breakout` (close vs prior high, suppressed to −inf without volume confirmation). All
  long-only (Track M is short-*holding*, not short-selling); higher = stronger buy.
- **`src/autocrypt/midcap/killgate.py`** — the day-native kill-gate engine. Reuses the *one*
  thing that must not change between iterations — the constant-product `ExecutionModel` — but
  is bar-/day-native (reads depth from `reserve_usd`, capacity-scales size to ≤0.4% reserve,
  cooldown = horizon for independent non-overlapping fires). Produces the
  frequency-vs-expectancy curve, blind baseline, seeded permutation test, robustness sweeps
  (horizon / depth / lookback / early-vs-late window), and an honest verdict whose ceiling is
  "UNPROVEN", never GO. Cross-sectional momentum ranks each pool's trailing return across the
  universe on the same date (point-in-time safe).
- **CLI `midcap-killgate`** — read-only; `--speculative-only` (default on), `--horizon`,
  `--lookback`, `--fee-bps`, `--out <md>`.
- **Tests:** `tests/test_midcap_killgate.py` (14: each signal's sign/undefined behaviour, the
  volume gate, the capacity rule, no-look-ahead censoring, cooldown, XS within-date ranking +
  thin-cross-section skip, the curve/sweep wiring, and an explicit *"a biased winners-only
  universe must NOT return GO"* guard). **97/97 green, ruff clean** (was 83; +14).
- **Docs:** `docs/phase-M3-killgate.md` (full evidence), this synthesis.

## Key decisions & why

1. **A sibling engine, not a forced reuse of the swap `Profiler`.** The Phase-2 profiler is
   swap-/second-native and *infers* depth; daily OHLCV with reserve-based depth is a different
   shape. Shoehorning bars into `SwapRow`/`LiquidityEstimator` would have smuggled in the wrong
   depth model. I reused the *cost engine* (`ExecutionModel`) verbatim — the only piece that
   must be identical so "1% now vs 20% then" stays an honest ruler — and rebuilt the harness.
2. **Capacity-scaled position size, encoded.** Per the M2 finding, notional = min($10k,
   0.4%×reserve), not a flat dollar. This is why realized cost drag is ~2% (not the ≤$1k
   headline ~1%) — and reporting that honestly is the point: it is the cost a real book of this
   size would pay, and it is what makes blind negative.
3. **"Beats random after a multiple-comparison discount" as the hard gate.** Several thresholds
   × four signals invites a false positive. The permutation test + a crude `p × n_thresholds`
   discount is what turns mean_rev's seductive +11% into the NO-GO it deserves to be.
4. **Speculative-only by default.** The verdict must not lean on deep pegged pairs; the M2
   `_is_speculative` classifier drops them (92 of 113 pools remain after the bar-count filter).
5. **Did not tune to a positive.** I report the tempting tails *and* dismantle them, rather than
   quietly picking the threshold that looks best. That is the whole discipline.

## Open questions / follow-ups

1. **YELLOW fork (above): close Track M's daily battery and pivot effort to Track G?** Operator
   call. My recommendation: yes — let Track M's forward snapshot series keep accruing for an
   eventual unbiased re-test, and spend the next session on Track G.
2. **Unbiased re-test (background).** The survivorship-safe forward snapshot has been recording
   since M1; in a few months it will have enough dead/delisted names to re-run this exact
   kill-gate without the bias. The machinery is now in place to do that with a one-line source
   swap.
3. **Resolution / feature limits.** This control is daily OHLCV only — no intraday, no
   swap-level flow, no holder/liquidity-velocity features. A future Track-M revival (if any)
   would need a richer feed; the NO-GO is specifically about *daily price-only* signals.
4. **Track G is the main goal and its data is ripening.** G0 collector + the graduation-event
   detection (still TODO) are the next real build.

## State of the code

`src/autocrypt/midcap/{universe,mcap_rank,costs,bars,barsignals,killgate}.py` + the `midcap-*`
CLI commands are tested; **97/97 green, ruff clean**. No paid spend, no keys, no funds, no
trading. Track M store `data/autocrypt_midcap.duckdb` (113-pool in-band universe + 16,177 1d
bars + forward snapshots) untouched by this read-only session. Iteration-1 stores untouched.

## Background processes (alive at session start — NOT re-launched this session)

| Process | PID | Writes to | Purpose |
|---|---|---|---|
| `autocrypt collect` (nohup) | 3006 | `data/autocrypt_graduation.duckdb` | G0 graduation cohort, 7-day hold |
| `midcap_snapshot_loop.sh` (nohup) | 3003 | `data/autocrypt_midcap.duckdb` | daily clean (top-pools) universe snapshot |

Both were **already running** at session start (survived from the M2 session — no reboot), so
neither was re-launched. Durable fix still pending: grant Full Disk Access to `/usr/local/bin/uv`
then enable `~/Library/LaunchAgents/com.autocrypt.collector.plist`, or relocate the repo out of
`~/Documents`. The kill-gate ran read-only, so it held no DB lock against the snapshot loop.

---

```text
Read CLAUDE.md, then Project_spec.md, then docs/iteration-2-strategy.md, then
docs/phase-M3-synthesis.md (and docs/phase-M3-killgate.md). Confirm in 3-4 sentences where
we are and this session's goal before doing anything else.

CONTEXT: Iteration 2. Track M (mid-cap deep-pool) reached its KILL-GATE in M3 and is a NO-GO:
all four transparent signals (TS momentum, XS momentum, mean-reversion, volume-gated breakout)
fail on the survivorship-BIASED daily-OHLCV control -- none beats random selection after a
multiple-comparison discount (best discounted p=0.22), blind expectancy is slightly negative
(~-0.3 to -0.8%), and the tempting tight-threshold tails (mean_rev +11%) are artifacts:
negative MEDIAN, tiny n, regime-fragile (early half negative), depth-fragile. Structural cause:
even with M2's cost escape, realistic capacity-scaled cost drag (~2%) >= the ~1.3% survivorship-
inflated 5-day marked drift -- Law 1's inequality gross>cost is not met at tradeable size.
Built bars.py + barsignals.py + killgate.py + CLI midcap-killgate + 14 tests (97/97 green,
ruff clean). Evidence: docs/phase-M3-killgate.md.

YELLOW DECISION ON THE TABLE (operator): close Track M's daily price-only battery (recommended)
and pivot this session to TRACK G -- the stated MAIN GOAL -- letting Track M's survivorship-SAFE
forward snapshot series keep accruing for an eventual unbiased re-test. If you agree:

THIS SESSION = Track G / G1 (with G0 graduation-event detection as the prerequisite build):
  1. CHECK G0 DATA: how much has data/autocrypt_graduation.duckdb accrued? (it's been
     collecting on a 7-day hold). Implement GRADUATION-EVENT DETECTION -- the discrete
     liquidity-deepening milestone -- from the raw multi-day store. This is the G0 TODO.
  2. G1: re-label the attribution "success" from "+X% in 300s" to "survives AND appreciates
     over N days", and rebuild the wallet book on that label to surface a *followable*
     accumulator cohort (distinct from Iteration-1's orchestrators). Re-validate point-in-time
     + survivorship.
  3. Keep the kill-gate discipline: anything you find must clear §3 (profitable-after-cost,
     point-in-time, beats blind+random w/ multiple-comparison discount, robust, enough fires).
  (If instead you want to keep pushing Track M: the honest move is the UNBIASED forward
   re-test, which needs months of snapshot accrual -- not more signal-hunting on the biased
   control. Do NOT tune the M3 battery to a positive.)

CHECK BACKGROUND JOBS FIRST (both DIE on reboot -- re-launch if `ps aux | grep autocrypt`
shows nothing):
  - G0 graduation:  DB_URL=duckdb:///data/autocrypt_graduation.duckdb nohup uv run autocrypt \
      collect --interval 90 --iterations 0 --enum-pages 3 --watch-max 60 --max-pool-age-h 168 \
      --tx-pages 2 > data/g0_collect.interim.log 2>&1 &
  - Track M daily snapshot: nohup bash scripts/midcap_snapshot_loop.sh > data/midcap_snapshot.log 2>&1 &

Autonomy: GREEN code/backtest/free data; YELLOW paid tiers + universe/label changes + GO/NO-GO;
RED unchanged. Single-writer rule: the snapshot loop owns autocrypt_midcap.duckdb during its
brief daily write -- run profilers read-only; don't run two writers on that file at once.
```
