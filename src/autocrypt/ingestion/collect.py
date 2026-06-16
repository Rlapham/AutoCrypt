"""Forward-collection mode (read-only) — the FREE multi-day dataset builder.

This is the command to run unattended for days/weeks to accumulate a
survivorship-complete, swap-level Solana window over wall-clock time.

Why this exists separately from `poll` and `stream`:
- `poll` writes ONLY PoolCreated (universe enumeration) — no swaps, so a profiler
  run over a poll-only store sees no new trade history. It is necessary but not
  sufficient for the kill-gate.
- `stream` tails swaps but for a FIXED watchlist chosen once at startup; it never
  picks up pools created after it began.

`collect` does both in a single process (single DuckDB writer): each cycle it
(1) enumerates the newest pools → PoolCreated + adds them to a rolling watchlist,
(2) ages out pools older than `max_pool_age_s` (their early-life run-up window has
passed and we keep the watchlist bounded so a sweep fits the rate limiter),
(3) tails recent swaps for every watched pool → Swap + WalletEvent.

Selection is by CREATION, never by survival, so rugged/dead pools stay in the set
(survivorship-safe). Idempotent: the store dedupes on `event_id`, so overlapping
ticks and re-fetched pages are safe. `knowable_at = block_time + latency`, exactly
as backfill reconstructs it, so live-collected and historical rows stay comparable.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from autocrypt.grad.graduation import venue_phase
from autocrypt.logging import get_logger
from autocrypt.providers.base import RetryableHTTPError
from autocrypt.providers.dexpaprika import DexPaprika
from autocrypt.schema import BaseEvent, Commitment
from autocrypt.storage.store import EventStore

log = get_logger("collect")

# Bump when the on-disk state layout changes incompatibly (a mismatch is ignored,
# not migrated — the collector just starts fresh, which is safe).
_STATE_VERSION = 1


def _load_state(path: Path) -> tuple[dict[str, dict], set[str], set[str]]:
    """Reload watchlist + graduation-detector memory (`bc_mints`) + `retired` from a
    prior run so PINNED GRADUATIONS KEEP BEING TAILED ACROSS PROCESS RESTARTS.

    This is the fix for the Track-G arc ceiling: the watchlist/bc_mints lived only in
    memory, so every restart (laptop sleep, launchd KeepAlive, reboot) dropped the pin
    set and re-enumerated from scratch. A graduation pinned yesterday was never
    re-tailed today, so no pool accrued more than one continuous-run's worth of swaps —
    capping every arc at the awake-session length (~16h observed) and starving the
    multi-day accumulator the kill-gate needs. Persisting + reloading lets a graduation's
    arc resume after a restart, up to its full `max_pool_age_s` measured from creation.

    A missing or corrupt file yields empty state (start fresh) rather than crashing the
    collector. Returns (watchlist, bc_mints, retired)."""
    if not path.exists():
        return {}, set(), set()
    try:
        raw = json.loads(path.read_text())
        if raw.get("version") != _STATE_VERSION:
            log.warning("collector_state_version_mismatch", found=raw.get("version"))
            return {}, set(), set()
        watchlist: dict[str, dict] = {
            addr: {
                "ctx": e["ctx"],
                "created_at": datetime.fromisoformat(e["created_at"]),
                "phase": e["phase"],
                "tier": e["tier"],
            }
            for addr, e in raw.get("watchlist", {}).items()
        }
        bc_mints = set(raw.get("bc_mints", []))
        retired = set(raw.get("retired", []))
        log.info(
            "collector_state_loaded",
            watched=len(watchlist),
            grad_watched=sum(1 for e in watchlist.values() if e.get("tier") == "grad"),
            bc_mints=len(bc_mints),
            retired=len(retired),
        )
        return watchlist, bc_mints, retired
    except (ValueError, KeyError, OSError) as exc:  # corrupt/partial file → start fresh
        log.warning("collector_state_load_failed", error=str(exc))
        return {}, set(), set()


def _save_state(
    path: Path,
    watchlist: dict[str, dict],
    bc_mints: set[str],
    retired: set[str],
) -> None:
    """Persist collector state atomically (temp file + `os.replace`) so a crash/sleep at
    any moment resumes the same pinned cohort. Best-effort: a write error is logged, never
    fatal to collection. `datetime` `created_at` is stored as ISO so `_age_out` keeps
    measuring a graduation's hold window from its true creation time across restarts."""
    try:
        payload = {
            "version": _STATE_VERSION,
            "watchlist": {
                addr: {
                    "ctx": e["ctx"],
                    "created_at": e["created_at"].isoformat(),
                    "phase": e["phase"],
                    "tier": e["tier"],
                }
                for addr, e in watchlist.items()
            },
            "bc_mints": sorted(bc_mints),
            "retired": sorted(retired),
        }
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload))
        os.replace(tmp, path)
    except OSError as exc:
        log.warning("collector_state_save_failed", error=str(exc))


def _ctx_from_pool_created(pc: object) -> dict:
    """Extract the per-pool context `to_swap` needs from a PoolCreated record."""
    return {
        "pool_address": pc.pool_address,  # type: ignore[attr-defined]
        "base_mint": pc.base_mint,  # type: ignore[attr-defined]
        "quote_mint": pc.quote_mint,  # type: ignore[attr-defined]
        "base_decimals": pc.base_decimals,  # type: ignore[attr-defined]
        "quote_decimals": pc.quote_decimals,  # type: ignore[attr-defined]
        "dex": pc.dex,  # type: ignore[attr-defined]
    }


def _is_graduation(pc: object, bc_mints: set[str]) -> bool:
    """A candidate is a graduation iff it is an AMM-venue pool whose mint we have already
    seen on a bonding curve. Point-in-time: `bc_mints` holds only mints enumerated at/before
    this tick, and a bonding-curve pool is always created before its AMM pool, so this label
    uses no look-ahead. Direct-AMM pools (deep from birth, no prior BC) are NOT graduations."""
    return (
        venue_phase(pc.dex) == "AMM"  # type: ignore[attr-defined]
        and pc.base_mint in bc_mints  # type: ignore[attr-defined]
    )


async def _enumerate_new_pools(
    store: EventStore,
    dp: DexPaprika,
    watchlist: dict[str, dict],
    retired: set[str],
    bc_mints: set[str],
    *,
    run_id: str,
    pages: int,
    page_limit: int,
    watch_max: int,
    grad_reserved: int,
    latency: timedelta,
) -> int:
    """Fetch newest pools, persist PoolCreated, learn bonding-curve mints, and admit.

    PoolCreated is always written for every enumerated pool (the survivorship-complete
    universe — unaffected by admission). `bc_mints` accumulates every mint ever seen on a
    bonding-curve venue, so a later AMM pool for that mint can be recognised as a
    *graduation* (the constant-product analogue of "graduated to real liquidity").

    GRADUATION-AWARE ADMISSION (the Track-G fix). The earlier design saturated the
    watchlist on the first tick and then *froze* it for `max_pool_age` (every slot held
    for days), so the later-created AMM pool of a graduating token — appearing minutes to
    hours after its bonding-curve pool — never won a slot (post-grad coverage ≈ 1%).
    Now admission is tiered (see `_admit_candidates`): graduation pools are PINNED (never
    locked out, evicting the oldest discovery pool if the watchlist is full) and held for
    the full multi-day arc; everything else is short-lived discovery that churns out fast
    (see `_age_out`) to keep slots open for the next graduation.
    Survivorship is untouched: every enumerated pool is still written as PoolCreated; only
    which pools get their *swaps* tailed changes.

    Returns the number of pools newly admitted to the cohort this tick.
    """
    observed = datetime.now(UTC)
    events: list[BaseEvent] = []
    # Dedupe this tick's candidates by address (the stream can repeat across pages).
    fresh: dict[str, object] = {}
    # Same crash-resilience as tailing: if a 429/5xx storm exhausts retries mid-enumeration,
    # keep whatever pages we already got and proceed to tailing rather than crashing the
    # collector (a crash drops the watchlist and resets every graduation arc).
    try:
        async for pool in dp.iter_pools_by_creation(
            max_pools=pages * page_limit, page_limit=page_limit, max_pages=pages
        ):
            pc = dp.to_pool_created(pool, run_id=run_id, latency=latency)
            if pc is None:
                continue
            pc.observed_at = observed  # audit only
            events.append(pc)
            # Learn bonding-curve mints from EVERY enumerated pool (not just admitted ones),
            # so a graduation is recognised even if its bonding-curve pool was never tailed.
            if venue_phase(pc.dex) == "BC":
                bc_mints.add(pc.base_mint)
            addr = pc.pool_address
            if addr not in watchlist and addr not in retired and addr not in fresh:
                fresh[addr] = pc
    except RetryableHTTPError as exc:
        log.warning("enumerate_truncated", error=str(exc), got=len(events))
    store.write_events(events)
    return _admit_candidates(
        watchlist,
        list(fresh.values()),
        retired,
        bc_mints,
        watch_max=watch_max,
        grad_reserved=grad_reserved,
    )


def _admit_candidates(
    watchlist: dict[str, dict],
    candidates: list,
    retired: set[str],
    bc_mints: set[str],
    *,
    watch_max: int,
    grad_reserved: int,
) -> int:
    """Admit this tick's fresh candidates with graduation pools PINNED above discovery.

    Pure (no I/O): mutates `watchlist`/`retired`, returns the number admitted.
      1. Graduation pools (`_is_graduation`) are admitted FIRST and are never locked out:
         if the watchlist is full, the oldest *discovery* pool is evicted (and retired so
         it is not re-admitted) to make room. These are the scarce Track-G targets.
      2. Discovery pools (bonding-curve, direct-AMM, other) fill only up to
         `watch_max - grad_reserved`, so a reserve of slots always stays open for the next
         graduation — and they age out fast (see `_age_out`) to keep that headroom.
    """

    def _admit(pc: object, tier: str) -> None:
        watchlist[pc.pool_address] = {  # type: ignore[attr-defined]
            "ctx": _ctx_from_pool_created(pc),
            "created_at": pc.event_time,  # type: ignore[attr-defined]
            "phase": venue_phase(pc.dex),  # type: ignore[attr-defined]
            "tier": tier,
        }

    def _oldest_discovery() -> str | None:
        disc = [(e["created_at"], a) for a, e in watchlist.items() if e.get("tier") != "grad"]
        return min(disc)[1] if disc else None

    grads = [pc for pc in candidates if _is_graduation(pc, bc_mints)]
    others = [pc for pc in candidates if not _is_graduation(pc, bc_mints)]
    admitted = 0

    for pc in grads:  # 1) graduations: pinned, never locked out
        if pc.pool_address in watchlist:  # type: ignore[attr-defined]
            continue
        if len(watchlist) >= watch_max:
            victim = _oldest_discovery()
            if victim is None:
                break  # watchlist is entirely graduations — cannot make room
            del watchlist[victim]
            retired.add(victim)
        _admit(pc, "grad")
        admitted += 1

    disc_cap = max(0, watch_max - grad_reserved)
    n_disc = sum(1 for e in watchlist.values() if e.get("tier") != "grad")
    for pc in others:  # 2) discovery: fill the unreserved portion only, leaving grad headroom
        if pc.pool_address in watchlist:  # type: ignore[attr-defined]
            continue
        if len(watchlist) >= watch_max or n_disc >= disc_cap:
            break
        _admit(pc, "disc")
        admitted += 1
        n_disc += 1
    return admitted


async def _tail_watchlist(
    store: EventStore,
    dp: DexPaprika,
    watchlist: dict[str, dict],
    seen: set[str],
    *,
    run_id: str,
    tx_pages: int,
    page_limit: int,
    latency: timedelta,
) -> int:
    """Tail recent swaps for every watched pool. Returns NET-NEW rows added this tick.

    The store upserts (INSERT OR REPLACE keyed on event_id), so we report the net-new
    row count (store delta), not rows attempted — re-fetched/overlapping swaps that
    collapse on event_id must not inflate the progress number.
    """
    events: list[BaseEvent] = []
    observed = datetime.now(UTC)
    skipped = 0
    for entry in watchlist.values():
        ctx = entry["ctx"]
        # A 429/5xx storm that exhausts get_json's retries used to propagate out of here
        # and CRASH the whole collector — launchd then restarted it with an empty watchlist,
        # dropping every pinned graduation. That crash-loop (300+ times in the logs) was the
        # dominant cause of the ~16h arc ceiling. Now one pool's retry-exhaustion just skips
        # that pool for this tick (it stays watched; next tick retries it), so the tick
        # completes, the state checkpoint is written, and graduation arcs keep accruing.
        try:
            async for tx in dp.iter_pool_transactions(
                ctx["pool_address"], page_limit=page_limit, max_pages=tx_pages
            ):
                swap = dp.to_swap(tx, **ctx, run_id=run_id, latency=latency)
                if swap is None:
                    continue
                swap.commitment = Commitment.confirmed
                swap.observed_at = observed
                eid = swap.event_id()
                if eid in seen:
                    continue
                seen.add(eid)
                we = dp.swap_to_wallet_event(swap)
                we.observed_at = observed
                events.append(swap)
                events.append(we)
        except RetryableHTTPError as exc:
            skipped += 1
            log.warning("tail_pool_skipped", pool=ctx["pool_address"], error=str(exc))
            continue
    if skipped:
        log.warning("tail_pools_skipped", skipped=skipped, watched=len(watchlist))
    before = store.count()
    store.write_events(events)
    return store.count() - before


def _age_out(
    watchlist: dict[str, dict],
    retired: set[str],
    *,
    max_pool_age_s: float,
    discovery_age_s: float,
) -> int:
    """Retire pools whose tail window has elapsed, freeing cohort slots, by TIER.

    Eviction is by AGE ONLY (not recency). The window depends on the tier:
      - GRADUATION pools are held for `max_pool_age_s` (long) — we want the whole multi-day
        post-graduation accumulator arc, including a token that goes quiet then re-accumulates.
      - DISCOVERY pools (bonding-curve / direct-AMM / other) are held for `discovery_age_s`
        (short): long enough to catch a bonding-curve pool's graduation (median lag ~5min,
        p90 ~21min) before it churns out, short enough that the watchlist never freezes and
        graduation headroom stays open.
    Retired addresses are remembered so a still-listed old pool is not re-admitted.
    Returns the number retired this tick.
    """
    now = datetime.now(UTC)
    stale = [
        a
        for a, e in watchlist.items()
        if (now - e["created_at"]).total_seconds()
        > (max_pool_age_s if e.get("tier") == "grad" else discovery_age_s)
    ]
    for addr in stale:
        del watchlist[addr]
        retired.add(addr)
    return len(stale)


async def run_collect(
    store: EventStore,
    *,
    run_id: str,
    interval_s: float = 60.0,
    max_iterations: int | None = None,
    enum_pages: int = 2,
    page_limit: int = 100,
    watch_max: int = 40,
    grad_reserved: int = 20,
    max_pool_age_s: float = 604800.0,
    discovery_age_s: float = 21600.0,
    tx_pages: int = 2,
    latency: timedelta = timedelta(seconds=2),
    state_path: Path | None = None,
) -> int:
    """Run the forward-collection loop. `max_iterations=None` runs until cancelled.

    Graduation pools (an AMM pool for a mint already seen on a bonding curve) are pinned and
    held for `max_pool_age_s` to capture the multi-day post-graduation accumulator arc;
    `grad_reserved` of `watch_max` slots stay open for them, and discovery pools age out
    after the shorter `discovery_age_s` so the watchlist never freezes (see
    `_enumerate_new_pools` / `_age_out`).

    Returns total swap/wallet records written (PoolCreated writes are not counted here).
    """
    dp = DexPaprika()
    # Resume the pinned cohort + graduation-detector memory from disk so arcs survive
    # restarts (see `_load_state`); `None` (tests, ad-hoc runs) starts in-memory only.
    if state_path is not None:
        watchlist, bc_mints, retired = _load_state(state_path)
    else:
        watchlist, bc_mints, retired = {}, set(), set()
    seen: set[str] = set()
    total = 0
    i = 0
    try:
        while max_iterations is None or i < max_iterations:
            # age-out first so freed slots can be filled by this tick's enumeration
            aged = _age_out(
                watchlist, retired,
                max_pool_age_s=max_pool_age_s, discovery_age_s=discovery_age_s,
            )
            admitted = await _enumerate_new_pools(
                store, dp, watchlist, retired, bc_mints, run_id=run_id, pages=enum_pages,
                page_limit=page_limit, watch_max=watch_max, grad_reserved=grad_reserved,
                latency=latency,
            )
            written = await _tail_watchlist(
                store, dp, watchlist, seen, run_id=run_id, tx_pages=tx_pages,
                page_limit=page_limit, latency=latency,
            )
            total += written
            log.info(
                "collect_tick",
                admitted=admitted,
                retired=aged,
                watched=len(watchlist),
                grad_watched=sum(1 for e in watchlist.values() if e.get("tier") == "grad"),
                bc_mints=len(bc_mints),
                new_rows=written,  # net-new swap+wallet rows (post-dedup)
                total_new_rows=total,
            )
            # Checkpoint after every tick so a sleep/crash/restart resumes the same
            # pinned cohort and graduation arcs continue accruing (the Track-G fix).
            if state_path is not None:
                _save_state(state_path, watchlist, bc_mints, retired)
            i += 1
            if max_iterations is None or i < max_iterations:
                await asyncio.sleep(interval_s)
    finally:
        await dp.aclose()
    return total
