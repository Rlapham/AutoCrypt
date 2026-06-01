"""Historical backfill orchestrator (read-only).

Builds a survivorship-safe local store: enumerate Solana pools by CREATION time
(independent of survival → rugs/dead pools included), then pull each pool's swap
history (+ optional OHLCV). Every record is point-in-time stamped by the schema.

HONESTY NOTE (read before trusting coverage): a *complete* 14-day enumeration means
paging through the full launch firehose (~tens of thousands of pools/day). That is not
feasible on a free tier in one run. This engine therefore enforces explicit budgets
(`max_pools`, `max_enum_pages`) and reports the EFFECTIVE window actually covered — it
never silently claims the requested window. Full coverage needs either long-running
forward collection (poll mode) or a paid historical archive (Bitquery) — a Phase 2 item.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from autocrypt.logging import get_logger
from autocrypt.providers.dexpaprika import DexPaprika, _parse_dt
from autocrypt.providers.geckoterminal import GeckoTerminal
from autocrypt.schema import BaseEvent
from autocrypt.storage.store import EventStore

log = get_logger("backfill")


@dataclass
class BackfillReport:
    run_id: str
    requested_window_start: datetime
    requested_window_end: datetime
    effective_window_start: datetime | None = None  # oldest pool actually included
    effective_window_end: datetime | None = None  # newest pool actually included
    pools_seen: int = 0
    pools_out_of_window: int = 0
    pools_dropped_dust: int = 0
    pools_backfilled: int = 0
    pools_tx_errors: int = 0
    pools_ohlcv_errors: int = 0
    pools_per_day: dict[str, int] = field(default_factory=dict)
    events_written: int = 0
    events_by_type: dict[str, int] = field(default_factory=dict)
    capped: bool = False
    notes: list[str] = field(default_factory=list)

    def coverage_complete(self) -> bool:
        """True only if we reached back to the requested window start without capping."""
        return (
            not self.capped
            and self.effective_window_start is not None
            and self.effective_window_start <= self.requested_window_start
        )


async def run_backfill(
    store: EventStore,
    *,
    run_id: str,
    now: datetime,
    window_days: int = 14,
    max_pools: int = 300,
    max_enum_pages: int = 60,
    per_day_cap: int = 80,
    min_transactions: int = 5,
    with_ohlcv: bool = False,
    ohlcv_interval: str = "1h",
    tx_pages_per_pool: int = 50,
    batch_size: int = 500,
) -> BackfillReport:
    """Run the historical backfill. Returns a report with honest coverage stats."""
    window_end = now
    window_start = now - timedelta(days=window_days)
    report = BackfillReport(
        run_id=run_id,
        requested_window_start=window_start,
        requested_window_end=window_end,
    )

    dp = DexPaprika()
    gt = GeckoTerminal() if with_ohlcv else None
    buffer: list[BaseEvent] = []
    per_day: dict[str, int] = defaultdict(int)

    def flush() -> None:
        if buffer:
            n = store.write_events(buffer)
            report.events_written += n
            for e in buffer:
                report.events_by_type[e.event_type.value] = (
                    report.events_by_type.get(e.event_type.value, 0) + 1
                )
            buffer.clear()

    try:
        # 1) Enumerate the universe by creation time (newest-first), day-stratified.
        universe: list[dict] = []
        page = 0
        async for pool in dp.iter_pools_by_creation(
            max_pools=10**9, page_limit=100, max_pages=max_enum_pages
        ):
            page += 1
            report.pools_seen += 1
            created_raw = pool.get("created_at")
            if not created_raw:
                continue
            created = _parse_dt(created_raw)

            if created < window_start:
                # desc order → we've walked past the window; stop enumerating.
                report.notes.append("reached window start during enumeration")
                break
            if created > window_end:
                continue

            day = created.date().isoformat()
            if per_day[day] >= per_day_cap:
                continue  # day already sampled to cap (stratified sampling)
            # "ever-tradeable" filter: skip pure never-traded dust (not survivorship —
            # rugs/dead pools that DID trade still have txns and are kept).
            if (pool.get("transactions") or 0) < min_transactions:
                report.pools_dropped_dust += 1
                continue

            per_day[day] += 1
            universe.append(pool)
            report.effective_window_end = max(report.effective_window_end or created, created)
            report.effective_window_start = min(report.effective_window_start or created, created)
            if len(universe) >= max_pools:
                report.capped = True
                report.notes.append(f"hit max_pools={max_pools}; window may be partial")
                break
        else:
            report.notes.append(f"exhausted max_enum_pages={max_enum_pages}")

        report.pools_per_day = dict(sorted(per_day.items()))
        log.info(
            "universe_built",
            pools=len(universe),
            seen=report.pools_seen,
            dust=report.pools_dropped_dust,
            days=len(per_day),
        )

        # 2) Per-pool: emit PoolCreated + swaps (+ wallet events) (+ optional OHLCV).
        for pool in universe:
            pc = dp.to_pool_created(pool, run_id=run_id)
            if pc is None:
                continue
            buffer.append(pc)
            ctx: dict[str, Any] = {
                "pool_address": pc.pool_address,
                "base_mint": pc.base_mint,
                "quote_mint": pc.quote_mint,
                "base_decimals": pc.base_decimals,
                "quote_decimals": pc.quote_decimals,
                "dex": pc.dex,
                "run_id": run_id,
            }
            # Swaps (DexPaprika). A single bad pool must not abort the whole run.
            try:
                async for tx in dp.iter_pool_transactions(
                    pc.pool_address, page_limit=100, max_pages=tx_pages_per_pool
                ):
                    swap = dp.to_swap(tx, **ctx)
                    if swap is None:
                        continue
                    buffer.append(swap)
                    buffer.append(dp.swap_to_wallet_event(swap))
                    if len(buffer) >= batch_size:
                        flush()
            except Exception as exc:  # log + skip pool, keep the run going
                report.pools_tx_errors += 1
                log.warning("pool_tx_failed", pool=pc.pool_address, error=str(exc))

            # OHLCV (GeckoTerminal) is best-effort; rate-limit 429s skip the pool.
            if gt is not None:
                try:
                    async for bar in gt.iter_pool_ohlcv(
                        pc.pool_address,
                        base_mint=pc.base_mint,
                        quote_mint=pc.quote_mint,
                        interval=ohlcv_interval,
                        run_id=run_id,
                    ):
                        buffer.append(bar)
                        if len(buffer) >= batch_size:
                            flush()
                except Exception as exc:  # OHLCV is optional, never fatal
                    report.pools_ohlcv_errors += 1
                    log.warning("pool_ohlcv_failed", pool=pc.pool_address, error=str(exc))

            report.pools_backfilled += 1
            flush()  # flush per pool so a long run is incrementally durable

        flush()
    finally:
        await dp.aclose()
        if gt is not None:
            await gt.aclose()

    if not report.coverage_complete():
        report.notes.append(
            "COVERAGE PARTIAL: effective window narrower than requested 14d — see HONESTY NOTE"
        )
    return report
