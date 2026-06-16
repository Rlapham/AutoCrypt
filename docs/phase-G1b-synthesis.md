# Phase G1b Synthesis — collection continuity fix (the real arc-ceiling cause)

*Session date: 2026-06-16. Track G (graduation accumulator — THE MAIN GOAL), Iteration 2.
Triggered by a "what's the status of the collector / how close is the data to the goal"
check that turned into a root-cause fix. GREEN work (code + free data + local process mgmt);
no paid spend, no keys, no funds, no git.*

## Goal of this session

Answer "how close is the accumulating data to the Track-G goal?" honestly, then unblock
whatever was found. The goal-gate is unchanged: Track G needs genuine graduations with
**multi-DAY post-graduation arcs (ideally ≥168h)** so the accumulator label can *resolve*
and the G2 kill-gate can run with enough fires.

## Headline finding — we are NOT close, and the prior durability story was incomplete

Census on a live snapshot (read-only copy, single-writer rule respected):

- **1,287 genuine graduations** (rate 1.44%), **post-grad swap coverage 260/1,287 (20%)** —
  a big win vs the pre-fix 2/185, so the G1 graduation-aware *admission* fix works.
- **BUT the decisive metric — arc length — is failing.** Of the 260 covered graduations:
  10 have ≥1h of post-grad swaps, **3** have ≥6h, and **0** have ≥24h (let alone ≥7d).
  Median graduation arc **0.2h (~12 min)**.
- **The ceiling is global, not graduation-specific:** across *all* 5,173 pools that ever got
  a swap, the **longest arc in the entire DB is 15.9h. Zero pools reach 24h.** That is not
  tokens dying fast — it is a hard collection-continuity ceiling.

### Why (two compounding causes, both now fixed)

1. **The collector was crash-looping on 429 retry-exhaustion — 308 times in the log.**
   `HTTPProvider.get_json` retries a 429/5xx five times then **reraises**; that
   `RetryableHTTPError` propagated out of `_tail_watchlist`/`_enumerate_new_pools`, out of
   `asyncio.run`, and **crashed the whole process**. launchd `KeepAlive` restarted it with an
   **empty in-memory watchlist**, dropping every pinned graduation. So no pool was ever tailed
   across more than one crash-free run — capping every arc at one awake-session (~16h observed)
   and starving the multi-day accumulator. This, more than sleep, was the dominant cause.
2. **Laptop sleep + restart lost state anyway.** Ingestion-by-day showed ~5–12h/day with whole
   days missing (Jun 4–6, Jun 14–15). A launchd LaunchAgent does not run while the Mac is
   asleep; on wake `KeepAlive` starts a *fresh* process (same state loss as the crash). The
   G1 note "durability RESOLVED via launchd (survives reboot/crash)" was only half true: the
   *process* came back, but its **arc-accruing state did not**.

## What was built + deployed (all three verified live)

1. **Per-pool 429 resilience (the dominant fix).** `_tail_watchlist` now wraps each pool's
   tail in `try/except RetryableHTTPError` → logs `tail_pool_skipped` and continues; the tick
   completes and writes whatever it collected. `_enumerate_new_pools` is guarded the same way
   (`enumerate_truncated`). A 429 storm now means "this tick collected a bit less," not "crash
   + lose the watchlist." `src/autocrypt/ingestion/collect.py`.
2. **State checkpoint (so pins survive restart).** `_save_state`/`_load_state` persist the
   watchlist (with tz-aware `created_at`), the `bc_mints` graduation-detector memory, and
   `retired` to `<db>.collector_state.json`, atomically (`tmp` + `os.replace`) **after every
   tick**. `run_collect(state_path=...)` reloads on startup; missing/corrupt/old-version file →
   start fresh (never crash). CLI `collect --state-file` (default `<db>.collector_state.json`).
   Age-out still measures a graduation's hold window from its true creation time, so a reloaded
   grad keeps its remaining 168h.
3. **`caffeinate -ims` wrapper** in `scripts/g0_collect.sh` so idle/disk/system sleep is held
   off while the collector runs (assertion dies with the process). **Caveat documented:**
   caffeinate cannot defeat lid-close sleep on battery — operator must keep the lid open or be
   on AC for continuous overnight collection.

### Full-kill teardown (operator's hard requirement)

`scripts/g0_stop.sh` stops the collector **completely and durably** despite `KeepAlive`:
`launchctl bootout` (stop now + disarm KeepAlive) → `launchctl disable` (no auto-start at next
login) → `pkill` strays (caffeinate + collector) → verify nothing holds the DuckDB lock. To
bring it back: `launchctl enable` then `bootstrap` (commands in the script header).

### Live verification

- First tick after deploy completed (did not crash) and logged
  `tail_pools_skipped skipped=1 watched=52` — a 429 pool was skipped, the tick still finished.
- Checkpoint written: 52 pools / 12 graduations / 260 bc_mints.
- Restart reloaded it: `collector_state_loaded watched=52 grad_watched=12 bc_mints=260`.
- Process tree stable (`caffeinate -ims → uv → autocrypt collect`), launchd `state = running`,
  **PID stable across the monitoring window (no crash-loop).**
- **132/132 tests green, ruff clean, mypy clean on `collect.py`** (+5 tests: state round-trip,
  missing/corrupt/version-mismatch fallbacks, and the 429-skip resilience path).

## Decisions & why

- **Fixed the crash-loop even though the ask was "persistence + caffeinate."** The data showed
  persistence alone could never engage — a process that crashes before completing a tick never
  writes a checkpoint. Resilience is the prerequisite that makes the other two matter.
- **Skip-the-pool, don't widen retries.** Increasing `stop_after_attempt` would just lengthen
  ticks and still crash eventually. Skipping a hot pool for one tick (it stays watched, retried
  next tick) is survivorship-neutral and keeps the loop alive.
- **Respected the single-writer rule** — census ran against a file copy, never the live DB.

## Open questions / follow-ups

1. **Ripening is now possible but still takes wall-clock.** With arcs finally able to exceed
   ~16h, re-run the arc census in a few days; once a meaningful number of graduations clear
   24h→72h→168h, run G1 `grad-walletbook` then the G2 kill-gate. Still weeks out, but no longer
   structurally stuck.
2. **Lid-close-on-battery is the remaining continuity risk** (caffeinate can't beat it). If
   overnight gaps persist, the durable answer is an always-on host (cheap VPS / Pi) — an
   operator call (machine/cost), not a code change.
3. **Checkpoint growth.** `bc_mints`/`retired` grow over weeks (sorted JSON, ~32K at 260 mints).
   Fine for now; if the file gets large, prune `retired` or cap `bc_mints` age. Watch file size.

## State of the code

`src/autocrypt/ingestion/collect.py` (429 resilience + state persistence),
`src/autocrypt/cli.py` (`collect --state-file`), `scripts/g0_collect.sh` (caffeinate),
`scripts/g0_stop.sh` (NEW — full teardown), `tests/test_collect.py` (+5 tests). The collector
runs durably under launchd `com.autocrypt.collector` via `scripts/g0_collect.sh`, now wrapped
in `caffeinate -ims` and checkpointing to `data/autocrypt_graduation.collector_state.json`.
**No paid spend, no keys, no funds, no git.**

---

## Commit plan (human runs git — see CLAUDE.md §4)

Target branch: a fresh `phase-G1b` branch off `main` (or current working branch). Logical units:

1. **fix(collect): survive 429 storms + persist watchlist across restarts** —
   `src/autocrypt/ingestion/collect.py`, `src/autocrypt/cli.py`, `tests/test_collect.py`.
   *Per-pool/per-enumeration `RetryableHTTPError` resilience so a tick completes instead of
   crash-looping; atomic per-tick state checkpoint reloaded on startup so pinned graduations
   keep accruing arcs across restart/sleep/reboot. +5 tests; 132 green, ruff+mypy clean.*
2. **chore(collect): caffeinate wrapper + full-stop teardown script** —
   `scripts/g0_collect.sh` (wrap in `caffeinate -ims`), `scripts/g0_stop.sh` (new).
3. **docs: G1b synthesis + spec status update** — `docs/phase-G1b-synthesis.md`,
   `Project_spec.md`.

---

```text
Read CLAUDE.md, then Project_spec.md, then docs/iteration-2-strategy.md, then
docs/phase-G1b-synthesis.md (and docs/phase-G1-synthesis.md). Confirm in 3-4 sentences where
we are and this session's goal before doing anything else.

CONTEXT: Iteration 2, Track G (the main goal): enter GRADUATED tokens (bonding-curve → deep
AMM) and ride a multi-day "accumulator" arc. G0 built a point-in-time, survivorship-complete
graduation detector (~1.4-1.7% genuine rate) + a G1 accumulator relabel (survives AND
appreciates over N days). Both BUILT; G1/G2 are DATA-GATED on multi-day post-grad arcs.

LAST SESSION (G1b, 2026-06-16): diagnosed why arcs were capped at ~16h despite weeks of
calendar time. Census: 1,287 genuine grads, post-grad coverage 260/1,287 (admission fix
works), BUT longest arc across ALL 5,173 swapping pools = 15.9h, ZERO ≥24h. Root cause: the
collector crash-looped on 429 retry-exhaustion (308x) — each crash + launchd restart dropped
the in-memory watchlist; laptop sleep did the same. FIXED + DEPLOYED + VERIFIED: (a) per-pool
429 resilience (skip the pool, finish the tick — no more crash), (b) atomic per-tick state
checkpoint (<db>.collector_state.json) reloaded on startup so pinned grads survive restart
(verified: reloaded 52 pools/12 grads), (c) caffeinate -ims in g0_collect.sh. Teardown:
scripts/g0_stop.sh fully stops + disables the launchd agent. 132 green, ruff+mypy clean.

THIS SESSION:
  1. CHECK COLLECTOR HEALTH (durable launchd; do NOT start a second writer):
       launchctl print "gui/$(id -u)/com.autocrypt.collector" | grep state   (expect running)
       ps aux | grep "autocrypt collect"   (expect ONE chain: caffeinate -ims → uv → collect)
       Confirm PID is STABLE over a few minutes (no crash-loop) and that
       data/autocrypt_graduation.collector_state.json is being updated each tick.
  2. RE-RUN THE ARC CENSUS to see if arcs have started clearing 24h/72h/168h:
       cp data/autocrypt_graduation.duckdb /tmp/grad_snap.duckdb
       [ -f data/autocrypt_graduation.duckdb.wal ] && cp data/autocrypt_graduation.duckdb.wal /tmp/grad_snap.duckdb.wal
       DB_URL=duckdb:////tmp/grad_snap.duckdb uv run autocrypt grad-detect --out docs/phase-G0-census.md
       Then query post-grad arc-length distribution per genuine graduation (≥1h/6h/24h/72h/168h)
       — that distribution, not raw coverage, is the gate. Report it plainly.
  3. IF a meaningful number of grads now have multi-DAY arcs → G1: run grad-walletbook against
     a snapshot COPY to surface a followable accumulator cohort; then G2: graduation-momentum
     KILL-GATE through the profiler at multi-hour/day horizons (entry = graduation +
     accumulator-cohort buying; orchestrator-fade overlay as rug gate). Apply strategy §3
     (profitable-after-cost ∧ point-in-time ∧ survivorship-complete ∧ beats blind+random w/
     multiple-comparison discount ∧ robust ∧ enough fires). GO/NO-GO is YELLOW.
  4. IF still thin (likely for a while): do NOT force G1/G2. Report the arc distribution and let
     it accrue. If overnight ingestion gaps persist, the lid-close-on-battery caveat is the
     remaining continuity risk — propose an always-on host (operator call) rather than coding
     around it.

Autonomy: GREEN code/backtest/free data/local process mgmt; YELLOW paid tiers + universe/label
changes + collector admission policy + each GO/NO-GO; RED unchanged. Single-writer rule: the
live collect writer holds the graduation DB lock — run grad-detect against a file COPY.
```
