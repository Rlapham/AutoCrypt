"""Load swap/pool data from the store into a profiler-friendly in-memory shape.

The profiler is a backtest harness: it holds all the data but only *exposes* records
with `knowable_at <= T` to the signal function (the replay gate), while outcomes are
measured from `event_time`. Keeping both times on every swap is what makes that
discipline enforceable in code rather than by convention.

Times are carried as epoch seconds (float, UTC) — cheap to compare and difference in
the hot loop, with no timezone ambiguity (the store is TIMESTAMPTZ throughout).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime

from autocrypt.storage.store import EventStore


@dataclass(slots=True)
class SwapRow:
    """One swap, reduced to the fields the profiler needs (epoch-seconds times)."""

    event_time: float  # valid time (on-chain block time), UTC epoch seconds
    knowable_at: float  # the ONLY decision gate, UTC epoch seconds
    side: str  # "buy" | "sell" (w.r.t. base token)
    price_usd: float  # USD per base token at the trade
    amount_usd: float  # USD magnitude of the trade
    quote_amount: float  # quote (SOL/USDC) magnitude of the trade
    signer: str  # the trading wallet


@dataclass(slots=True)
class PoolData:
    """All swaps for one pool, plus its creation time (the survivorship anchor)."""

    pool_address: str
    base_mint: str | None
    quote_mint: str | None
    created_at: float | None  # pool_created event_time (epoch s), None if unknown
    swaps: list[SwapRow] = field(default_factory=list)  # sorted by knowable_at

    @property
    def first_swap_time(self) -> float | None:
        return self.swaps[0].event_time if self.swaps else None

    @property
    def last_swap_time(self) -> float | None:
        return self.swaps[-1].event_time if self.swaps else None


def _epoch(ts: datetime | None) -> float | None:
    return ts.timestamp() if ts is not None else None


def load_pools(store: EventStore, min_swaps: int = 1) -> list[PoolData]:
    """Load every created pool and its swaps, sorted by `knowable_at`.

    The universe is enumerated from `pool_created` (creation-time, outcome-independent),
    so dead/rugged pools stay in the denominator. Pools with swaps but no creation
    record are still included (created_at=None) — dropping them would be a (small)
    survivorship leak.
    """
    # Creation times for the survivorship anchor.
    created: dict[str, dict[str, object]] = {}
    for row in store.con.execute(
        "SELECT pool_address, base_mint, quote_mint, event_time "
        "FROM events WHERE event_type='pool_created' AND pool_address IS NOT NULL"
    ).fetchall():
        created[row[0]] = {
            "base_mint": row[1],
            "quote_mint": row[2],
            "created_at": _epoch(row[3]),
        }

    pools: dict[str, PoolData] = {}
    for addr, meta in created.items():
        pools[addr] = PoolData(
            pool_address=addr,
            base_mint=meta["base_mint"],  # type: ignore[arg-type]
            quote_mint=meta["quote_mint"],  # type: ignore[arg-type]
            created_at=meta["created_at"],  # type: ignore[arg-type]
        )

    cur = store.con.execute(
        "SELECT pool_address, event_time, knowable_at, payload, amount_usd "
        "FROM events WHERE event_type='swap' AND pool_address IS NOT NULL "
        "ORDER BY knowable_at, block_slot"
    )
    for pool_address, event_time, knowable_at, payload_json, amount_usd in cur.fetchall():
        p = json.loads(payload_json)
        price_usd = p.get("price_usd")
        quote_amount = p.get("quote_amount")
        if price_usd is None or amount_usd is None:
            continue  # cannot value this trade
        try:
            price = float(price_usd)
            amt_usd = float(amount_usd)
            qamt = float(quote_amount) if quote_amount is not None else 0.0
        except (TypeError, ValueError):
            continue
        if price <= 0 or amt_usd <= 0:
            continue
        pool = pools.get(pool_address)
        if pool is None:
            # Swap pool with no creation record — keep it (survivorship), created_at unknown.
            pool = PoolData(
                pool_address=pool_address,
                base_mint=p.get("base_mint"),
                quote_mint=p.get("quote_mint"),
                created_at=None,
            )
            pools[pool_address] = pool
        pool.swaps.append(
            SwapRow(
                event_time=event_time.timestamp(),
                knowable_at=knowable_at.timestamp(),
                side=str(p.get("side") or ""),
                price_usd=price,
                amount_usd=amt_usd,
                quote_amount=qamt,
                signer=str(p.get("signer") or ""),
            )
        )

    return [p for p in pools.values() if len(p.swaps) >= min_swaps]
