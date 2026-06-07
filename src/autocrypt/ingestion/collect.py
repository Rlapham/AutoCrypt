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
from datetime import UTC, datetime, timedelta

from autocrypt.grad.graduation import venue_phase
from autocrypt.logging import get_logger
from autocrypt.providers.dexpaprika import DexPaprika
from autocrypt.schema import BaseEvent, Commitment
from autocrypt.storage.store import EventStore

log = get_logger("collect")


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


async def _enumerate_new_pools(
    store: EventStore,
    dp: DexPaprika,
    watchlist: dict[str, dict],
    retired: set[str],
    *,
    run_id: str,
    pages: int,
    page_limit: int,
    watch_max: int,
    amm_reserved: int,
    latency: timedelta,
) -> int:
    """Fetch newest pools, persist PoolCreated, and admit new ones to the cohort.

    PoolCreated is always written for every enumerated pool (the survivorship-complete
    universe — unaffected by admission). A pool is *admitted to the swap-tailing cohort*
    only while there is free capacity and it has not been retired by age-out, so an
    admitted pool is held and tailed for hours/days (see `_age_out`), capturing its arc.

    AMM-PRIORITY ADMISSION (Track G fix). The newest-by-creation stream is ~99%
    bonding-curve pools, so without a reserve the watchlist fills with pre-graduation
    pools and the (later-created, rarer) AMM pool of a *graduated* token almost never gets
    a slot — leaving Track G with zero post-graduation swap coverage. We therefore:
      1. admit AMM-venue pools FIRST (they are the graduation targets we most want to tail
         through the multi-day accumulator arc), and
      2. reserve `amm_reserved` of the `watch_max` slots for AMM pools — bonding-curve /
         other pools may fill only up to `watch_max - amm_reserved`, keeping headroom for
         AMM pools that appear in later ticks.
    Survivorship is untouched: every enumerated pool is still written as PoolCreated; only
    which pools get their *swaps* tailed changes.

    Returns the number of pools newly admitted to the cohort this tick.
    """
    observed = datetime.now(UTC)
    events: list[BaseEvent] = []
    # Dedupe this tick's candidates by address (the stream can repeat across pages).
    fresh: dict[str, object] = {}
    async for pool in dp.iter_pools_by_creation(
        max_pools=pages * page_limit, page_limit=page_limit, max_pages=pages
    ):
        pc = dp.to_pool_created(pool, run_id=run_id, latency=latency)
        if pc is None:
            continue
        pc.observed_at = observed  # audit only
        events.append(pc)
        addr = pc.pool_address
        if addr not in watchlist and addr not in retired and addr not in fresh:
            fresh[addr] = pc
    store.write_events(events)
    return _admit_candidates(
        watchlist, list(fresh.values()), watch_max=watch_max, amm_reserved=amm_reserved
    )


def _admit_candidates(
    watchlist: dict[str, dict],
    candidates: list,
    *,
    watch_max: int,
    amm_reserved: int,
) -> int:
    """Admit this tick's fresh candidates to the watchlist with AMM priority + reserve.

    Pure (no I/O): mutates `watchlist`, returns the number admitted. AMM-venue pools are
    admitted first up to `watch_max`; non-AMM pools fill only up to `watch_max -
    amm_reserved`, so a reserve of slots is always available for AMM (graduation-target)
    pools that surface in later ticks. See `_enumerate_new_pools` for the why.
    """

    def _admit(pc: object) -> None:
        watchlist[pc.pool_address] = {  # type: ignore[attr-defined]
            "ctx": _ctx_from_pool_created(pc),
            "created_at": pc.event_time,  # type: ignore[attr-defined]
            "phase": venue_phase(pc.dex),  # type: ignore[attr-defined]
        }

    amm = [pc for pc in candidates if venue_phase(pc.dex) == "AMM"]
    other = [pc for pc in candidates if venue_phase(pc.dex) != "AMM"]
    admitted = 0
    for pc in amm:  # 1) AMM (graduation targets) may use the full capacity
        if len(watchlist) >= watch_max:
            break
        _admit(pc)
        admitted += 1
    non_amm_cap = max(0, watch_max - amm_reserved)
    for pc in other:  # 2) non-AMM fill only the unreserved portion, leaving AMM headroom
        # Respect BOTH the total cap (rate-limiter guard) AND the non-AMM sub-cap. The
        # total check matters when AMM pools already filled past `non_amm_cap` slots this
        # tick — without it the watchlist could overshoot watch_max.
        if len(watchlist) >= watch_max:
            break
        if sum(1 for e in watchlist.values() if e.get("phase") != "AMM") >= non_amm_cap:
            break
        _admit(pc)
        admitted += 1
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
    for entry in watchlist.values():
        ctx = entry["ctx"]
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
    before = store.count()
    store.write_events(events)
    return store.count() - before


def _age_out(watchlist: dict[str, dict], retired: set[str], *, max_pool_age_s: float) -> int:
    """Retire pools whose early-life window has fully elapsed, freeing cohort slots.

    Eviction is by AGE ONLY (not recency): an admitted pool is tailed continuously for
    `max_pool_age_s` after its creation, so we capture the whole launch→run-up arc, then
    it retires and frees a slot for a newer pool. Retired addresses are remembered so a
    still-listed old pool is not re-admitted. Returns the number retired this tick.
    """
    now = datetime.now(UTC)
    stale = [
        a
        for a, e in watchlist.items()
        if (now - e["created_at"]).total_seconds() > max_pool_age_s
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
    amm_reserved: int = 20,
    max_pool_age_s: float = 86400.0,
    tx_pages: int = 2,
    latency: timedelta = timedelta(seconds=2),
) -> int:
    """Run the forward-collection loop. `max_iterations=None` runs until cancelled.

    `amm_reserved` of `watch_max` slots are kept for AMM-venue (graduation-target) pools so
    the post-graduation accumulator arc actually gets tailed (see `_enumerate_new_pools`).

    Returns total swap/wallet records written (PoolCreated writes are not counted here).
    """
    dp = DexPaprika()
    watchlist: dict[str, dict] = {}
    retired: set[str] = set()
    seen: set[str] = set()
    total = 0
    i = 0
    try:
        while max_iterations is None or i < max_iterations:
            # age-out first so freed slots can be filled by this tick's enumeration
            aged = _age_out(watchlist, retired, max_pool_age_s=max_pool_age_s)
            admitted = await _enumerate_new_pools(
                store, dp, watchlist, retired, run_id=run_id, pages=enum_pages,
                page_limit=page_limit, watch_max=watch_max, amm_reserved=amm_reserved,
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
                new_rows=written,  # net-new swap+wallet rows (post-dedup)
                total_new_rows=total,
            )
            i += 1
            if max_iterations is None or i < max_iterations:
                await asyncio.sleep(interval_s)
    finally:
        await dp.aclose()
    return total
