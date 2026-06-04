"""M2 — deep-pool execution-cost recalibration: is Iteration-1's Law 1 escaped?

Iteration 1 hit the **cost wall** (Law 1): on thin fresh-launch pools, round-trip
execution cost — own price impact + fees — ran ~20-28%, swamping the ~0% short-hold drift,
which made the whole corner a structural loser for ANY entry signal. Track M's bet is that
mid-cap **deep** pools (reserve ≥ $500k) shrink own impact to near-nothing, so fees + spread
dominate and round-trip cost collapses to **low single digits**. M2 tests that directly,
*before* any signal work — if the cost wall still stands, Track M is dead on arrival.

We reuse the SAME constant-product cost engine the kill-gate uses
(`profiler.execution.ExecutionModel`). Only the depth INPUT changes:

  * Iteration 1 INFERRED depth from observed swap price-impact on thin pools
    (`LiquidityEstimator`) → small Q → large own impact.
  * Track M takes depth DIRECTLY from the pool's `reserve_in_usd` (GeckoTerminal) →
    deep Q → own impact ~ size/Q is tiny.

Headline metric — **round-trip friction at flat price**: buy a position, then immediately
sell it back into the same pool. With no price move, the fraction lost is pure execution
cost (fees + own impact on both legs + fixed). This is exactly the number Iteration 1
reported as ~20-28%, so it is a like-for-like comparison.

Conservatism (honesty over optimism — we'd rather over-charge than under-charge):
  * Quote-side depth = ``reserve_usd * depth_frac`` (default 0.5: a balanced xy=k pool holds
    half its TVL on each side). For concentrated-liquidity pools this UNDERSTATES active
    depth near the mid, hence OVERSTATES our impact.
  * Depth is measured at enumeration time (today) and applied as a constant; the depth
    multiplier sweep (x0.5) covers the worry that historical depth was shallower.
  * Default fee 30 bps/leg (typical Raydium/Orca mid-cap tier); swept up to pump.fun's 100.

This module computes costs only — no signal, no expectancy, no GO. (Survivorship bias is
irrelevant to a *cost* measurement: depth and fees do not depend on whether a pool survived.)
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field

from autocrypt.midcap.universe import PoolRow
from autocrypt.profiler.execution import ExecutionModel
from autocrypt.storage.store import EventStore

# Tokens whose price is pegged/anchored (stables, liquid-staking SOL, wrapped majors).
# A pool whose BOTH legs are in this set is not a speculative mid-cap — it is an LST/stable/
# wrapped-asset pair with ~no idiosyncratic drift (e.g. mSOL/SOL, USDC/USDT, uniBTC/xBTC).
# Such pairs are genuinely deep and so flatter the cost picture; we report a speculative-only
# subset so the verdict does not lean on them. Heuristic, symbol-based, deliberately simple.
_PEGGED = {
    # stables
    "USDC", "USDT", "USDS", "USD", "PYUSD", "FDUSD", "DAI", "USDE", "USDH", "UXD",
    "JUPUSD", "PSTUSDC", "CASH", "USD1", "USDG", "AUSD", "USDY",
    # SOL & liquid-staking SOL
    "SOL", "WSOL", "MSOL", "JITOSOL", "BSOL", "DSOL", "JUPSOL", "INF", "JSOL",
    "LST", "BNSOL", "HSOL", "VSOL", "CGNTSOL", "EZSOL", "PICOSOL",
    # wrapped majors
    "BTC", "WBTC", "UNIBTC", "XBTC", "ZBTC", "CBBTC", "TBTC", "LBTC",
    "ETH", "WETH", "WSTETH", "CBETH",
}


@dataclass(frozen=True)
class CostParams:
    """Execution-cost assumptions for the deep-pool round trip (USD-denominated)."""

    fee_bps: float = 30.0  # swap fee per leg (Raydium/Orca mid-cap tier ~25-30 bps)
    fixed_cost_usd: float = 0.20  # priority fee + Jito tip per leg, in USD
    depth_frac: float = 0.5  # quote-side share of reserve_usd (0.5 = balanced xy=k pool)
    depth_mult: float = 1.0  # sensitivity multiplier on depth (sweep x0.5/x1/x2)

    @property
    def label(self) -> str:
        return f"fee={self.fee_bps:g}bps depthx{self.depth_frac * self.depth_mult:g}"


@dataclass
class PoolFriction:
    """Per-pool round-trip friction at flat price, across position sizes."""

    pool_address: str
    name: str
    reserve_usd: float
    quote_depth_usd: float
    n_bars: int
    is_speculative: bool
    # typical multi-day absolute move (context for "gross > cost", NOT an expectancy claim)
    typical_abs_move_h: float | None
    friction_by_size: dict[float, float] = field(default_factory=dict)


@dataclass(frozen=True)
class FrictionSummary:
    """Cross-pool friction distribution at one position size."""

    size_usd: float
    n_pools: int
    median: float
    p25: float
    p75: float
    p90: float
    worst: float
    frac_under_3pct: float
    frac_under_5pct: float


def round_trip_friction(size_usd: float, quote_depth_usd: float, params: CostParams) -> float:
    """Pure round-trip execution cost (fraction) at flat price for one pool.

    Buys ``size_usd`` of quote into a pool with quote-side depth ``quote_depth_usd`` and
    immediately sells it all back at the same mid price. Returns the fraction lost
    (``= -net_return`` since the marked return is zero). Larger = worse.
    """
    if quote_depth_usd <= 0 or size_usd <= 0:
        return 1.0
    model = ExecutionModel(fee_bps=params.fee_bps, fixed_cost_quote=params.fixed_cost_usd)
    rt = model.round_trip(
        size_quote=size_usd,
        p_entry=1.0,
        q_entry=quote_depth_usd,
        p_exit=1.0,
        q_exit=quote_depth_usd,
    )
    # marked_return == 0 (flat price) ⇒ friction == cost_drag == -net_return.
    return -rt.net_return


def _is_speculative(name: str) -> bool:
    """True unless BOTH legs of the pair are pegged (stable/LST/wrapped).

    ``name`` is the GeckoTerminal pool name, e.g. "WIF / SOL" or "mSOL / SOL". A pair with
    at least one non-pegged leg is a speculative mid-cap; a pegged/pegged pair is not.
    """
    legs = [p.strip().upper() for p in name.replace("-", "/").split("/") if p.strip()]
    if not legs:
        return True  # unknown ⇒ keep it (don't silently drop)
    return not all(leg in _PEGGED for leg in legs)


def _load_in_band_pools_ro(store: EventStore, source: str) -> list[PoolRow]:
    """Read the latest snapshot's in-band pools for a source — READ-ONLY (no DDL).

    Mirrors ``universe.load_in_band_pools`` but never issues the ``CREATE TABLE IF NOT
    EXISTS`` it runs, so the cost pass can open the store read-only (the table already
    exists once a universe has been enumerated).
    """
    latest = store.con.execute(
        "SELECT max(snapshot_at) FROM universe_snapshots WHERE source = ?", [source]
    ).fetchone()
    if not latest or latest[0] is None:
        return []
    rows = store.con.execute(
        "SELECT pool_address, name, base_mint, quote_mint, reserve_usd, fdv_usd, mcap_usd, "
        "       pool_created_at, h24_volume_usd "
        "FROM universe_snapshots WHERE source = ? AND snapshot_at = ? AND in_band "
        "ORDER BY reserve_usd DESC",
        [source, latest[0]],
    ).fetchall()
    return [
        PoolRow(
            pool_address=r[0],
            name=r[1] or "",
            base_mint=r[2],
            quote_mint=r[3],
            reserve_usd=r[4],
            fdv_usd=r[5],
            mcap_usd=r[6],
            pool_created_at=r[7],
            h24_volume_usd=r[8],
        )
        for r in rows
    ]


def _load_pool_closes(store: EventStore, pool_addresses: set[str]) -> dict[str, list[float]]:
    """Per-pool close-price series (ordered by event_time) for the given pools."""
    series: dict[str, list[float]] = {addr: [] for addr in pool_addresses}
    cur = store.con.execute(
        "SELECT pool_address, payload FROM events "
        "WHERE event_type='ohlcv_bar' AND pool_address IS NOT NULL "
        "ORDER BY pool_address, event_time"
    )
    for pool_address, payload_json in cur.fetchall():
        if pool_address not in series:
            continue
        try:
            close = float(json.loads(payload_json).get("close"))
        except (TypeError, ValueError):
            continue
        if close > 0:
            series[pool_address].append(close)
    return series


def _typical_abs_move(closes: list[float], horizon: int) -> float | None:
    """Median absolute H-bar return over the close series (volatility scale, not a signal)."""
    if len(closes) <= horizon:
        return None
    moves = [
        abs(closes[i + horizon] / closes[i] - 1.0)
        for i in range(len(closes) - horizon)
        if closes[i] > 0
    ]
    if not moves:
        return None
    moves.sort()
    n = len(moves)
    mid = n // 2
    return moves[mid] if n % 2 else 0.5 * (moves[mid - 1] + moves[mid])


def _percentile(sorted_vals: list[float], q: float) -> float:
    """Linear-interpolated percentile (q in [0,1]) of an already-sorted list."""
    if not sorted_vals:
        return float("nan")
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return sorted_vals[lo]
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def compute_pool_frictions(
    pools: list[PoolRow],
    closes: dict[str, list[float]],
    sizes_usd: list[float],
    params: CostParams,
    *,
    move_horizon: int = 5,
) -> list[PoolFriction]:
    """Round-trip friction per pool at each position size (flat-price, deterministic)."""
    out: list[PoolFriction] = []
    for r in pools:
        if r.reserve_usd is None or r.reserve_usd <= 0:
            continue
        quote_depth = r.reserve_usd * params.depth_frac * params.depth_mult
        c = closes.get(r.pool_address, [])
        out.append(
            PoolFriction(
                pool_address=r.pool_address,
                name=r.name,
                reserve_usd=r.reserve_usd,
                quote_depth_usd=quote_depth,
                n_bars=len(c),
                is_speculative=_is_speculative(r.name),
                typical_abs_move_h=_typical_abs_move(c, move_horizon),
                friction_by_size={
                    s: round_trip_friction(s, quote_depth, params) for s in sizes_usd
                },
            )
        )
    return out


def summarize_frictions(
    frictions: list[PoolFriction], sizes_usd: list[float]
) -> list[FrictionSummary]:
    """Cross-pool friction distribution per size (median/quartiles/tail + pass fractions)."""
    summaries: list[FrictionSummary] = []
    for s in sizes_usd:
        vals = sorted(pf.friction_by_size[s] for pf in frictions if s in pf.friction_by_size)
        if not vals:
            continue
        m = len(vals)
        summaries.append(
            FrictionSummary(
                size_usd=s,
                n_pools=m,
                median=_percentile(vals, 0.5),
                p25=_percentile(vals, 0.25),
                p75=_percentile(vals, 0.75),
                p90=_percentile(vals, 0.90),
                worst=vals[-1],
                frac_under_3pct=sum(1 for v in vals if v < 0.03) / m,
                frac_under_5pct=sum(1 for v in vals if v < 0.05) / m,
            )
        )
    return summaries


@dataclass
class CostReport:
    """Full M2 cost-recalibration result for one parameter set."""

    params: CostParams
    sizes_usd: list[float]
    pools: list[PoolFriction]
    summaries: list[FrictionSummary]
    move_horizon: int

    @property
    def n_pools(self) -> int:
        return len(self.pools)

    @property
    def n_speculative(self) -> int:
        return sum(1 for p in self.pools if p.is_speculative)


def recalibrate_costs(
    store: EventStore,
    *,
    source: str = "coingecko_mcap_ranked",
    sizes_usd: list[float] | None = None,
    params: CostParams | None = None,
    speculative_only: bool = False,
    move_horizon: int = 5,
) -> CostReport:
    """Load the in-band universe, compute round-trip friction, and summarize. Read-only."""
    sizes = sizes_usd or [100.0, 500.0, 1_000.0, 5_000.0, 10_000.0, 50_000.0]
    p = params or CostParams()
    pool_rows = _load_in_band_pools_ro(store, source)
    closes = _load_pool_closes(store, {r.pool_address for r in pool_rows})
    frictions = compute_pool_frictions(pool_rows, closes, sizes, p, move_horizon=move_horizon)
    if speculative_only:
        frictions = [f for f in frictions if f.is_speculative]
    summaries = summarize_frictions(frictions, sizes)
    return CostReport(
        params=p,
        sizes_usd=sizes,
        pools=frictions,
        summaries=summaries,
        move_horizon=move_horizon,
    )
