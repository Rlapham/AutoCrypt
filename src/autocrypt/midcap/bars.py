"""M3 — OHLCV-bar dataset for the mid-cap kill-gate.

The Phase-2 profiler (`profiler/dataset.py`) consumes swap-level `PoolData` and infers
depth from observed swap impact. The Track-M store has NO swaps — only daily `ohlcv_bar`
events — and depth is read directly from `reserve_in_usd` (the M2 cost model). So M3 needs
its own dataset shape: per-pool daily bar series + a constant depth, both carrying the
three-time discipline so the kill-gate can enforce no-look-ahead in code.

No-look-ahead, restated for daily bars (verified against the ingest): each bar is stamped
`event_time = close_time` (a daily bar is only *final* at the day's close, never at its
open) and `knowable_at = close_time + latency`. A decision taken at bar ``i`` therefore
sees closes ``0..i`` only; the outcome is measured forward from ``close[i]`` to
``close[i+H]`` (a realized future the decision did not peek at). Bars are carried in
`event_time` order with both times kept, so the gate is enforceable, not conventional.

Survivorship: the 113-pool universe is today's survivors (CoinGecko exposes no as-of
param). That is load-bearing for the verdict — any positive expectancy here is an UPPER
BOUND (could be pure survivorship), so this control can only ever yield NO-GO/"unproven",
never a GO. Irrelevant to costs (M2), decisive for expectancy (M3).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from autocrypt.midcap.costs import _is_speculative, _load_in_band_pools_ro
from autocrypt.storage.store import EventStore


@dataclass(slots=True)
class Bar:
    """One daily OHLCV bar, reduced to what the kill-gate needs (epoch-seconds times)."""

    event_time: float  # = bar close_time (valid time); the bar is final only here
    knowable_at: float  # close_time + latency; the ONLY decision gate
    open: float
    high: float
    low: float
    close: float
    volume_usd: float


@dataclass(slots=True)
class PoolBars:
    """All daily bars for one in-band pool, plus its (constant) depth & metadata."""

    pool_address: str
    name: str
    base_mint: str | None
    quote_mint: str | None
    reserve_usd: float  # quote+base TVL; depth model is reserve_usd * depth_frac
    is_speculative: bool  # False ⇒ both legs pegged (LST/stable/wrapped) — drop by default
    bars: list[Bar] = field(default_factory=list)  # sorted ascending by event_time

    @property
    def closes(self) -> list[float]:
        return [b.close for b in self.bars]

    @property
    def highs(self) -> list[float]:
        return [b.high for b in self.bars]


def _f(v: object) -> float | None:
    try:
        x = float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return x


def _load_bars_for(store: EventStore, pool_addresses: set[str]) -> dict[str, list[Bar]]:
    """Per-pool daily-bar series (ascending event_time) for the given pools. Read-only."""
    series: dict[str, list[Bar]] = {a: [] for a in pool_addresses}
    cur = store.con.execute(
        "SELECT pool_address, event_time, knowable_at, payload FROM events "
        "WHERE event_type='ohlcv_bar' AND pool_address IS NOT NULL "
        "ORDER BY pool_address, event_time"
    )
    for pool_address, event_time, knowable_at, payload_json in cur.fetchall():
        if pool_address not in series:
            continue
        p = json.loads(payload_json)
        close = _f(p.get("close"))
        if close is None or close <= 0:
            continue  # cannot value/scale this bar
        o = _f(p.get("open"))
        hi = _f(p.get("high"))
        lo = _f(p.get("low"))
        vol = _f(p.get("volume_usd"))
        series[pool_address].append(
            Bar(
                event_time=event_time.timestamp(),
                knowable_at=knowable_at.timestamp(),
                open=o if o and o > 0 else close,
                high=hi if hi and hi > 0 else close,
                low=lo if lo and lo > 0 else close,
                close=close,
                volume_usd=vol if vol and vol > 0 else 0.0,
            )
        )
    return series


def load_pool_bars(
    store: EventStore,
    *,
    source: str = "coingecko_mcap_ranked",
    speculative_only: bool = False,
    min_bars: int = 1,
) -> list[PoolBars]:
    """Load the in-band universe and attach each pool's daily OHLCV series.

    `source` selects the universe snapshot (default the M1b mcap-ranked funnel). Pools are
    enumerated independent of survival (every in-band name in the snapshot), so the
    denominator is fixed before any signal is computed. `speculative_only` drops the few
    pegged/pegged pairs (LST-SOL, stable-stable, wrapped) via the M2 classifier.
    """
    pool_rows = _load_in_band_pools_ro(store, source)
    bars_by_pool = _load_bars_for(store, {r.pool_address for r in pool_rows})
    out: list[PoolBars] = []
    for r in pool_rows:
        if r.reserve_usd is None or r.reserve_usd <= 0:
            continue
        spec = _is_speculative(r.name)
        if speculative_only and not spec:
            continue
        bars = bars_by_pool.get(r.pool_address, [])
        if len(bars) < min_bars:
            continue
        out.append(
            PoolBars(
                pool_address=r.pool_address,
                name=r.name,
                base_mint=r.base_mint,
                quote_mint=r.quote_mint,
                reserve_usd=r.reserve_usd,
                is_speculative=spec,
                bars=bars,
            )
        )
    return out
