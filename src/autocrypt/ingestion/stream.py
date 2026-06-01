"""Live streaming mode (read-only).

Tails the newest swaps for a watchlist of pools at a low-latency cadence and emits
Swap + WalletEvent records in near-real-time. Implemented as a fast short-poll tail
with in-memory dedup; this is the functional live feed for Phase 1. A true push
stream (DexPaprika SSE / Bitquery gRPC CoreCast / websockets) is a drop-in upgrade
behind the same `EventStore.write_events` sink and is deferred as an optimization.

Live records carry `commitment=confirmed` and `knowable_at = block_time + latency`,
exactly as backfill reconstructs it — so live and historical are directly comparable
(the Phase 4 forward-test depends on that symmetry).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from autocrypt.logging import get_logger
from autocrypt.providers.dexpaprika import DexPaprika
from autocrypt.schema import BaseEvent, Commitment
from autocrypt.storage.store import EventStore

log = get_logger("stream")


async def _tail_pool_once(
    store: EventStore,
    dp: DexPaprika,
    pool_ctx: dict,
    seen: set[str],
    *,
    run_id: str,
    latency: timedelta,
) -> int:
    """Fetch the newest page of a pool's swaps; persist any not seen this session."""
    observed = datetime.now(UTC)
    events: list[BaseEvent] = []
    async for tx in dp.iter_pool_transactions(
        pool_ctx["pool_address"], page_limit=100, max_pages=1
    ):
        swap = dp.to_swap(tx, **pool_ctx, run_id=run_id, latency=latency)
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
    return store.write_events(events)


async def run_stream(
    store: EventStore,
    pool_contexts: list[dict],
    *,
    run_id: str,
    interval_s: float = 3.0,
    duration_s: float | None = 30.0,
    latency: timedelta = timedelta(seconds=2),
) -> int:
    """Tail a watchlist of pools for `duration_s` seconds (None = until cancelled).

    `pool_contexts` items: {pool_address, base_mint, quote_mint, base_decimals,
    quote_decimals, dex}. Returns total records written.
    """
    dp = DexPaprika()
    seen: set[str] = set()
    total = 0
    start = asyncio.get_event_loop().time()
    try:
        while True:
            for ctx in pool_contexts:
                total += await _tail_pool_once(store, dp, ctx, seen, run_id=run_id, latency=latency)
            log.info("stream_tick", watched=len(pool_contexts), total_written=total)
            if duration_s is not None and (asyncio.get_event_loop().time() - start) >= duration_s:
                break
            await asyncio.sleep(interval_s)
    finally:
        await dp.aclose()
    return total
