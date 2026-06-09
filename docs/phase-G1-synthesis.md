# Phase G1 Synthesis — graduation-aware collection (the Track-G data unblock)

*Session date: 2026-06-07. Track G (graduation accumulator — THE MAIN GOAL), Iteration 2.
Ran autonomously. One YELLOW checkpoint taken (durability + collector admission policy).*

## Goal

Advance Track G toward the G2 kill-gate *data permitting*. The G0/G1 instruments were already
built (graduation detector + accumulator relabel); the open question was whether the
post-graduation data had ripened enough to rebuild a wallet book and run G1/G2.

## Headline outcome — data has NOT ripened, and we found out WHY (two compounding bugs, one fixed)

It had not. But the reason is the valuable finding: **Track G is blocked by collection
*infrastructure*, not by its thesis.** Three compounding causes, with hard evidence:

1. **Collection died on the Jun-7 reboot — ~4 days lost.** The machine rebooted today at
   15:45; the graduation store hadn't been written since Jun 3 22:54. The `nohup` collectors
   don't survive reboot (known, but it just bit us for 4 days). Relaunched both immediately.
2. **Post-grad coverage was still 2/185** (census re-run on the Jun-3 snapshot). The
   `--amm-reserved` fix from the G0 session never got a fair run before the reboot.
3. **The collector design structurally could not catch graduations** — the new, decisive
   finding. On relaunch, the **first tick** logged `admitted=60, watched=60, retired=0`: the
   watchlist saturates to `watch_max` on tick 1, and with `--max-pool-age-h 168` those 60
   pools **freeze for 7 days**. But a graduation's AMM pool is created *minutes-to-hours after*
   its bonding-curve pool (census lag p50 4.9m, p90 20.7m, max 345m) — by which point every
   slot is full and locked. So graduations were systematically locked out. Confirmed
   downstream: of the 50 AMM pools that ever got swaps, the **longest arc is 1.32h and ZERO
   reach 6h**, let alone the multi-*day* arcs Track G needs.

So G1/G2 could not run (fabricating a wallet book on 2 graduations would violate the honesty
discipline). The right deliverable was to **fix the collection so the data can ripen** — which
this session did and deployed.

## What was built — graduation-aware admission + tier-based retention

Redesigned the forward collector's cohort policy (`src/autocrypt/ingestion/collect.py`) so it
actively targets graduations instead of locking onto whatever 60 pools happen to be newest at
startup:

- **`bc_mints` (point-in-time graduation detector).** The collector now accumulates every mint
  ever enumerated on a bonding-curve venue. A candidate is a **graduation** iff it is an
  AMM-venue pool whose mint is already in `bc_mints` (`_is_graduation`). This uses no
  look-ahead — a bonding-curve pool is always created before its AMM pool, so the label is
  knowable when the AMM pool appears. Direct-AMM pools (deep from birth, no prior BC) are
  explicitly **not** graduations.
- **Graduation pools are PINNED.** `_admit_candidates` admits graduations first and they are
  *never locked out*: if the watchlist is full, the **oldest discovery pool is evicted** (and
  retired) to make room. They are held for the full `--max-pool-age-h` (168h) to capture the
  multi-day accumulator arc.
- **Discovery churns fast.** Non-graduation pools (bonding-curve / direct-AMM / other) fill
  only `watch_max − grad_reserved` slots and age out after the short `--discovery-age-h` (6h,
  > the p90 graduation lag, so a curve pool is still watched when it graduates). This keeps the
  watchlist from freezing and keeps graduation headroom permanently open (`_age_out` is now
  tier-based).
- **Observability.** The tick log now emits `grad_watched` and `bc_mints` so coverage is
  visible live.
- **CLI:** `collect --grad-reserved` (alias `--amm-reserved` kept so the running wrapper never
  crashes on restart) + `--discovery-age-h`; `--max-pool-age-h` default raised 24h → 168h.
- **Wrapper** `scripts/g0_collect_interim.sh` updated to the new flags + corrected comment.
- **Tests:** `tests/test_collect.py` rewritten to pin the new contract — graduation
  detection, pinning, eviction-of-oldest-discovery, reserved headroom, tier-based retention,
  never-overshoot-watch_max, and the all-grad safety valve (10 tests). **119/119 green, ruff
  clean** (was 116).

## Deployed + validated live (the result)

Restarted the live collector with the new code (the deploy is the YELLOW admission-policy
change; taken because the old frozen-watchlist behavior was actively wasting the main goal's
collection time, the fix is tested + reversible, and the operator chose manual-relaunch
durability so gaps are costly). On the **very first tick** of the new code:

```
admitted=35  watched=35  grad_watched=5  bc_mints=264  retired=0
```

**5 graduation pools pinned on tick 1 — versus the old design's 2/185 over ~10 hours.**
`watched=35` = 30 discovery (capped at `60−30`) + 5 graduations, with 25 grad slots still open.
A live, decisive confirmation that the lockout is fixed. These 5+ graduations now need *days*
of uptime to accrue their arcs, so G1/G2 remain weeks out — but the pipeline is finally capable
of delivering the data it's meant to.

## Key decisions & why

1. **Diagnose-then-fix the collection, don't force a verdict.** With 2 graduations and <10h of
   horizon, any wallet book / GO-NO-GO would be manufactured. The honest, highest-leverage move
   for the main goal was to fix *why* the data isn't accruing. (Per the kickoff's own guidance
   for thin data.)
2. **Graduation-specific pinning, not generic AMM-priority.** The G0 `--amm-reserved` fix
   reserved slots for *all* AMM pools — but direct-AMM pools (1,028) swamp graduations (185),
   so reserved slots still mostly missed graduations, and the tick-1 freeze defeated it anyway.
   Pinning *graduations specifically* (mint ∈ bc_mints) + short discovery retention attacks the
   2/185 directly.
3. **Deployed the fix this session.** Leaving the broken collector running until a manual deploy
   would repeat the failure we just diagnosed (lost days). Tested (119 green) + smoke-validated
   + reversible. Reversion path documented below.
4. **Durability stays interim nohup (operator's call).** Operator chose manual relaunch over
   repo-relocation / Full-Disk-Access-for-launchd. Implication: **collection must be relaunched
   after every reboot** (commands in the kickoff). This is now the single biggest risk to the
   main goal — every reboot is lost data.

## Open questions / follow-ups

> **UPDATE 2026-06-07 (post-G1): durability #1 is RESOLVED.** The durable fix described below as
> "the cleanest" was deployed: the repo was relocated to `~/Dev/AutoCrypt` (out of the
> TCC-protected `~/Documents`) and the collector now runs under a launchd LaunchAgent
> `com.autocrypt.collector` (`RunAtLoad`+`KeepAlive`, runs `scripts/g0_collect.sh`), verified
> bootstrapped + running with KeepAlive observed auto-restarting it. Collection now survives
> reboot (auto-starts at login) and crash. **Consequence: do NOT run the manual `nohup`
> relaunch from the kickoff below — a second writer collides on the single-writer DuckDB lock.**
> The Track-M snapshot loop is NOT under launchd and is currently stopped (optional; Track M is a
> closed NO-GO). One real reboot test remains as final human confirmation.

1. **Durability is the binding risk.** ~~Manual-relaunch means any reboot silently kills
   collection (it just cost 4 days).~~ **RESOLVED — see the update banner above (launchd
   LaunchAgent, repo relocated out of `~/Documents`).** Historical note: the chosen fix was repo
   relocation, which avoids macOS TCC entirely.
2. **Grad-slot saturation (a future tuning knob, not yet a problem).** Graduations are pinned
   168h; if live+dead graduations ever approach `watch_max`, discovery (hence finding *new*
   graduations) gets squeezed. Mitigations if it appears: raise `--watch-max`, shorten grad
   retention, or early-retire graduations that go silent. Watch `grad_watched` vs `watch_max`.
3. **G1/G2 are data-gated, weeks out.** Re-run the census periodically; once a meaningful number
   of graduations have multi-day post-grad arcs, wire `grad/accumulator_label` into a
   `WalletScoreBook` rebuild (G1) and run the G2 kill-gate per strategy §3.
4. **Reversion.** To revert the admission policy: `git revert` the collect-policy commit (or run
   `collect --grad-reserved 0`, though that only removes the reserve, not the pinning) and
   restart the wrapper.

## State of the code

`src/autocrypt/ingestion/collect.py` (graduation-aware admission + tier-based retention),
`src/autocrypt/cli.py` (`collect` flags), `tests/test_collect.py`, `scripts/g0_collect_interim.sh`.
**119/119 green, ruff clean.** No paid spend, no keys, no funds, no trading. Track-M store
untouched. Census re-run → `docs/phase-G0-census.md` (current: 185 genuine grads, 1.68% rate,
2/185 pre-fix coverage). Background daemons at session end (since superseded — see the
durability UPDATE above; the G0 collector now runs durably under launchd `com.autocrypt.collector`
via `scripts/g0_collect.sh`, not the `g0_collect_interim.sh` nohup shown here):

| Process | PID (at write) | Writes to | Purpose |
|---|---|---|---|
| `g0_collect_interim.sh` → `autocrypt collect` (grad-aware) | 3157→3159→3160 | `autocrypt_graduation.duckdb` | G0/G1 cohort, graduation-pinned, 7-day arc |
| `midcap_snapshot_loop.sh` | 2725 | `autocrypt_midcap.duckdb` | Track-M survivorship-safe daily snapshot |

---

## Commit plan (human runs git — see CLAUDE.md §4)

Target branch: `M3` (or a fresh `phase-G1` branch off it). Suggested logical units:

1. **feat(collect): graduation-aware admission + tier-based retention** —
   `src/autocrypt/ingestion/collect.py`, `collect` flags in `src/autocrypt/cli.py`,
   `tests/test_collect.py`, `scripts/g0_collect_interim.sh`.
2. **docs: G1 synthesis + census refresh + spec update** — `docs/phase-G1-synthesis.md`,
   `docs/phase-G0-census.md`, `Project_spec.md`.

---

```text
Read CLAUDE.md, then Project_spec.md, then docs/iteration-2-strategy.md, then
docs/phase-G1-synthesis.md (and docs/phase-G0-census.md). Confirm in 3-4 sentences where we
are and this session's goal before doing anything else.

CONTEXT: Iteration 2, Track G (the main goal): enter GRADUATED tokens (bonding-curve → deep
AMM) and ride a multi-day "accumulator" arc. Track M is a closed NO-GO. G0 built a
point-in-time, survivorship-complete graduation detector (1.68% genuine rate) + a G1
accumulator relabel (survives AND appreciates over N days, resolves at horizon). Both are
BUILT but G1/G2 are DATA-GATED.

LAST SESSION (G1, 2026-06-07): found Track G was blocked by COLLECTION INFRASTRUCTURE, not
thesis. (a) Collection had died on a reboot — 4 days lost. (b) Post-grad coverage stuck at
2/185. (c) DECISIVE: the collector saturated its watchlist on tick 1 and froze it for 7
days, so graduations (AMM pool appears minutes-to-hours after the BC pool) were locked out;
of 50 AMM pools ever tailed, longest arc 1.32h, ZERO ≥6h. FIXED + DEPLOYED: graduation-aware
admission — graduation pools (AMM pool for a mint already seen on a bonding curve) are PINNED
(never locked out, evict oldest discovery if full) and held 168h for the multi-day arc;
discovery pools age out at 6h so the watchlist never freezes. Validated LIVE: first tick
grad_watched=5 (vs 2/185 over 10h before). 119/119 green, ruff clean. DURABILITY since
RESOLVED (post-G1): repo relocated to ~/Dev/AutoCrypt + launchd LaunchAgent
com.autocrypt.collector (RunAtLoad+KeepAlive) — collection now survives reboot/crash.

THIS SESSION:
  1. CHECK THE COLLECTOR IS HEALTHY (it is now durable under launchd — do NOT start a manual
     nohup collector; a second writer collides on the single-writer DuckDB lock):
       - Verify running:  launchctl print "gui/$(id -u)/com.autocrypt.collector" | grep state
                          (or `ps aux | grep "autocrypt collect"` — expect exactly ONE chain)
       - If somehow stopped: launchctl kickstart -k "gui/$(id -u)/com.autocrypt.collector"
       - Track-M snapshot loop is NOT under launchd and is optional (Track M is a closed NO-GO);
         only relaunch if you specifically want fresh Track-M snapshots:
         nohup bash scripts/midcap_snapshot_loop.sh > data/midcap_snapshot.log 2>&1 &
  2. RE-RUN THE CENSUS to measure how post-grad coverage has ripened since the fix:
       cp data/autocrypt_graduation.duckdb /tmp/grad_snap.duckdb
       [ -f data/autocrypt_graduation.duckdb.wal ] && cp data/autocrypt_graduation.duckdb.wal /tmp/grad_snap.duckdb.wal
       DB_URL=duckdb:////tmp/grad_snap.duckdb uv run autocrypt grad-detect --out docs/phase-G0-census.md
     Report the post-grad coverage number plainly (how many genuine graduations now have
     multi-DAY post-grad arcs). Also check `grad_watched` in data/g0_collect.err.log (the
     launchd collector logs there; the old data/g0_collect.interim.log is the retired nohup path).
  3. IF a meaningful number of graduations now have multi-day arcs → G1: wire
     grad/accumulator_label.label_accumulator_entry into a WalletScoreBook rebuild (reuse
     attribution/wallet_book.py) over the GRADUATED cohort to surface a *followable*
     accumulator wallet cohort; re-validate point-in-time + survivorship. Then G2: run the
     graduation-momentum KILL-GATE through the profiler at multi-hour/day horizons, entry
     conditioned on graduation + accumulator-cohort buying, orchestrator-fade overlay as a
     rug/avoid gate. Apply §3 (profitable-after-cost ∧ point-in-time ∧ survivorship-complete
     ∧ beats blind+random w/ multiple-comparison discount ∧ robust ∧ enough fires). GO/NO-GO
     is YELLOW.
  4. IF still too thin (likely — ripening takes weeks of UPTIME): do NOT force G1/G2. Report
     coverage plainly and let it accrue. (Durability is no longer a risk — launchd now keeps the
     collector alive across reboot/crash.) NOTE: the G1 accumulator WalletScoreBook wiring was
     BUILT AHEAD on 2026-06-07 (`grad/wallet_book.py` + CLI `grad-walletbook`); when coverage
     ripens, just run `grad-walletbook` against a snapshot copy rather than building from scratch.

Autonomy: GREEN code/backtest/free data; YELLOW paid tiers + universe/label changes +
collector admission policy + each GO/NO-GO; RED unchanged. Single-writer rule: the live
`collect` writer holds the graduation DB lock — run grad-detect against a file COPY. The
snapshot loop owns autocrypt_midcap.duckdb during its brief daily write.
```
