"""GeckoTerminal adapter (free, 30 req/min) — OHLCV backfill + new-pool discovery.

OHLCV LOOK-AHEAD GUARD: GeckoTerminal's candle timestamp is the bar's OPEN (period
start). A bar's open/high/low/close are not knowable until the period CLOSES, so we
derive `close_time = open_time + interval` and stamp `event_time = close_time`,
`knowable_at = close_time + latency`. The schema rejects any bar where
event_time != close_time, so a mis-stamp fails loudly rather than silently leaking.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from autocrypt.providers.base import HTTPProvider
from autocrypt.schema import Commitment, OHLCVBar, Source, knowable_at_for_bar

DEFAULT_BAR_LATENCY = timedelta(seconds=2)

# (timeframe, aggregate) -> (interval label, seconds)
_INTERVALS: dict[str, tuple[str, str, int]] = {
    "1m": ("minute", "1", 60),
    "5m": ("minute", "5", 300),
    "15m": ("minute", "15", 900),
    "1h": ("hour", "1", 3600),
    "4h": ("hour", "4", 14400),
    "1d": ("day", "1", 86400),
}


class GeckoTerminal(HTTPProvider):
    base_url = "https://api.geckoterminal.com/api/v2"
    per_minute = 18.0  # docs say 30/min but the OHLCV path 429s near that; stay well under
    source = Source.geckoterminal
    network = "solana"

    async def new_pools(self, page: int = 1) -> list[dict[str, Any]]:
        """The freshest newly-created pools (a live firehose; spans only minutes)."""
        data = await self.get_json(f"/networks/{self.network}/new_pools", params={"page": page})
        return data.get("data", []) if isinstance(data, dict) else []

    async def top_pools_raw(self, page: int = 1) -> list[dict[str, Any]]:
        """The current top pools by the API's default ranking (liquidity/volume).

        SURVIVORSHIP NOTE: this is a *current* snapshot of pools that still exist and
        rank today. It is NOT point-in-time universe membership — a pool that was liquid
        months ago but has since died/delisted is absent. Use only for a clearly-labelled
        survivorship-BIASED control, or snapshot it forward over wall-clock to build a
        clean point-in-time set. The endpoint caps at ~10 pages (≈200 pools)."""
        data = await self.get_json(f"/networks/{self.network}/pools", params={"page": page})
        return data.get("data", []) if isinstance(data, dict) else []

    async def pool_ohlcv_raw(
        self, pool_address: str, interval: str = "1h", limit: int = 1000
    ) -> list[list[Any]]:
        """Return GeckoTerminal's raw ohlcv_list ([ts_open, o, h, l, c, vol], ...)."""
        if interval not in _INTERVALS:
            raise ValueError(f"unsupported interval {interval!r}; pick {list(_INTERVALS)}")
        timeframe, aggregate, _ = _INTERVALS[interval]
        data = await self.get_json(
            f"/networks/{self.network}/pools/{pool_address}/ohlcv/{timeframe}",
            params={"aggregate": aggregate, "limit": limit, "currency": "usd"},
        )
        try:
            return data["data"]["attributes"]["ohlcv_list"]
        except (KeyError, TypeError):
            return []

    async def iter_pool_ohlcv(
        self,
        pool_address: str,
        *,
        base_mint: str | None,
        quote_mint: str | None,
        interval: str,
        run_id: str,
        limit: int = 1000,
        latency: timedelta = DEFAULT_BAR_LATENCY,
        not_after: datetime | None = None,
    ) -> AsyncIterator[OHLCVBar]:
        """Fetch OHLCV and yield canonical OHLCVBar records (correctly close-stamped).

        LOOK-AHEAD GUARD: GeckoTerminal returns the CURRENT, still-forming bar whose
        close_time is in the future and whose OHLC values are not final. We skip any
        bar that has not closed by `not_after` (default now) — only closed bars are facts.
        """
        _, _, seconds = _INTERVALS[interval]
        cutoff = not_after or datetime.now(UTC)
        rows = await self.pool_ohlcv_raw(pool_address, interval=interval, limit=limit)
        for row in rows:
            if not row or len(row) < 6:
                continue
            ts_open, o, h, low, c, vol = row[0], row[1], row[2], row[3], row[4], row[5]
            open_time = datetime.fromtimestamp(int(ts_open), tz=UTC)
            close_time = open_time + timedelta(seconds=seconds)
            if close_time > cutoff:
                continue  # bar still forming → not yet knowable (no look-ahead)
            yield OHLCVBar(
                source=self.source,
                event_time=close_time,  # bar known only at close (no look-ahead)
                knowable_at=knowable_at_for_bar(close_time, latency),
                source_ref=f"{pool_address}:{interval}:{int(ts_open)}",
                ingest_run_id=run_id,
                commitment=Commitment.backfill,
                pool_address=pool_address,
                base_mint=base_mint,
                quote_mint=quote_mint,
                interval=interval,
                open_time=open_time,
                close_time=close_time,
                open=Decimal(str(o)),
                high=Decimal(str(h)),
                low=Decimal(str(low)),
                close=Decimal(str(c)),
                volume_usd=Decimal(str(vol)) if vol is not None else None,
                currency="usd",
            )
