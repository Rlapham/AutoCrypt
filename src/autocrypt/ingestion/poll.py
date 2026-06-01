"""Periodic polling mode (read-only).

Polls for newly-created pools on a slow cadence and writes PoolCreated records. Run
continuously, this is the free-tier path to *forward-collect* a complete, gap-free
window over time (the historical backfill cannot reach far back on a free tier).
Idempotent: the store dedupes on event_id, so overlapping ticks are safe.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from autocrypt.logging import get_logger
from autocrypt.providers.dexpaprika import DexPaprika
from autocrypt.schema import BaseEvent
from autocrypt.storage.store import EventStore

log = get_logger("poll")


async def poll_new_pools_once(
    store: EventStore,
    dp: DexPaprika,
    *,
    run_id: str,
    pages: int = 2,
    page_limit: int = 100,
    latency: timedelta = timedelta(seconds=2),
) -> int:
    """One polling tick: fetch the newest pools and persist PoolCreated records."""
    observed = datetime.now(UTC)
    events: list[BaseEvent] = []
    fetched = 0
    async for pool in dp.iter_pools_by_creation(
        max_pools=pages * page_limit, page_limit=page_limit, max_pages=pages
    ):
        fetched += 1
        pc = dp.to_pool_created(pool, run_id=run_id, latency=latency)
        if pc is not None:
            pc.observed_at = observed  # audit only
            events.append(pc)
    written = store.write_events(events)
    log.info("poll_tick", fetched=fetched, written=written)
    return written


async def run_poll(
    store: EventStore,
    *,
    run_id: str,
    interval_s: float = 60.0,
    max_iterations: int | None = None,
    pages: int = 2,
) -> int:
    """Run the polling loop. `max_iterations=None` runs until cancelled."""
    dp = DexPaprika()
    total = 0
    i = 0
    try:
        while max_iterations is None or i < max_iterations:
            total += await poll_new_pools_once(store, dp, run_id=run_id, pages=pages)
            i += 1
            if max_iterations is None or i < max_iterations:
                await asyncio.sleep(interval_s)
    finally:
        await dp.aclose()
    return total
