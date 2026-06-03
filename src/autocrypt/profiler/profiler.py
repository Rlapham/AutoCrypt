"""The frequency-vs-expectancy profiler — Phase 2's central instrument.

For each pool in a survivorship-complete universe, walk candidate decision times. At each
time T compute the derivative signal from ONLY what was knowable at T. If the signal
clears a threshold (and the rug gate passes), simulate a realistic round-trip entry/exit
over a fixed horizon and record the net return after fees + own price impact. Sweeping the
threshold traces the **frequency-vs-expectancy curve**: how often you fire vs what you earn
per fire. The kill-gate question is whether any point on that curve is profitable.

Discipline recap:
  * Signal at T uses `knowable_at <= T` only (no look-ahead). Outcomes use realized
    future prices/depth — legitimate, because the *decision* saw only the past.
  * Universe = every created pool (denominator includes pools that died).
  * One open position per pool at a time (cooldown = horizon) so fires are independent.
  * Trades whose exit horizon runs past the data end are CENSORED and reported, never
    silently scored. (In the phase-1 snapshot, censoring is an administrative window-cut,
    not pool death — flagged in the synthesis; for a real dataset it would matter.)
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field, replace

from autocrypt.attribution.signal import AttributionSignalConfig, compute_attribution
from autocrypt.attribution.wallet_book import WalletScoreBook
from autocrypt.profiler.dataset import PoolData, SwapRow
from autocrypt.profiler.execution import ExecutionModel
from autocrypt.profiler.liquidity import LiquidityEstimator
from autocrypt.profiler.rugfilter import RugFilterConfig, rug_check
from autocrypt.profiler.signals import SignalConfig, compute_signal


@dataclass(slots=True)
class ProfilerConfig:
    horizon_s: float = 60.0  # hold period (entry → exit)
    position_size_usd: float = 250.0  # capital deployed per trade
    warmup_s: float = 60.0  # min pool history before first decision
    signal: SignalConfig = field(default_factory=SignalConfig)
    execution: ExecutionModel = field(default_factory=ExecutionModel)
    rug: RugFilterConfig = field(default_factory=RugFilterConfig)
    use_rug_filter: bool = True
    depth_multiplier: float = 1.0  # sensitivity knob on the (estimated) depth
    signal_field: str = "score"  # which SignalSnapshot field to threshold
    attribution: AttributionSignalConfig = field(default_factory=AttributionSignalConfig)


@dataclass(slots=True)
class Trade:
    """One simulated, scored round-trip (a 'fire' that had full horizon data)."""

    pool_address: str
    decision_ts: float
    signal_value: float
    net_return: float
    marked_return: float
    cost_drag: float
    rug_blocked: bool


@dataclass(slots=True)
class ThresholdResult:
    threshold: float
    n_fires: int  # signal cleared threshold AND rug-gate passed AND scorable
    n_rug_blocked: int  # cleared threshold but rug gate blocked
    n_censored: int  # cleared threshold but horizon ran past data end
    n_pools_fired: int
    fire_rate_per_pool_min: float  # fires per pool-minute of eligible time
    hit_rate: float  # fraction of fires with net_return > 0
    expectancy: float  # mean net return per fire (THE number)
    median_net: float
    mean_marked: float  # mean no-cost return (for cost-drag context)
    mean_cost_drag: float
    p25_net: float
    p75_net: float

    def as_row(self) -> dict[str, float]:
        return {
            "threshold": self.threshold,
            "n_fires": self.n_fires,
            "n_rug_blocked": self.n_rug_blocked,
            "n_censored": self.n_censored,
            "n_pools_fired": self.n_pools_fired,
            "fire_rate_per_pool_min": self.fire_rate_per_pool_min,
            "hit_rate": self.hit_rate,
            "expectancy": self.expectancy,
            "median_net": self.median_net,
            "mean_marked": self.mean_marked,
            "mean_cost_drag": self.mean_cost_drag,
            "p25_net": self.p25_net,
            "p75_net": self.p75_net,
        }


def _percentile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    idx = q * (len(sorted_vals) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = idx - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


@dataclass(slots=True)
class _TimelinePoint:
    kt: float  # knowable_at
    et: float  # event_time
    price: float
    depth: float | None  # estimated effective quote reserve at this point


class Profiler:
    """Runs the candidate strategy across all pools and produces per-fire trades.

    Trades are generated ONCE (at threshold = -inf, i.e. fire on every defined signal);
    thresholds are then applied by filtering on the recorded `signal_value`. This keeps
    the (expensive) point-in-time replay a single pass and makes the curve exact rather
    than re-simulated per threshold.
    """

    def __init__(self, cfg: ProfilerConfig, book: WalletScoreBook | None = None) -> None:
        self.cfg = cfg
        # Cross-pool wallet track records for the attribution signal. None ⇒ derivative-only
        # (the original behaviour); attribution signal_fields require a book to be defined.
        self.book = book

    def _sol_usd(self, swaps: list[SwapRow]) -> float | None:
        ratios = [s.amount_usd / s.quote_amount for s in swaps if s.quote_amount > 0]
        if not ratios:
            return None
        return statistics.median(ratios)

    def _build_timeline(self, swaps: list[SwapRow]) -> list[_TimelinePoint]:
        est = LiquidityEstimator(window=self.cfg.signal.min_trades_per_half * 8 or 40)
        tl: list[_TimelinePoint] = []
        for s in swaps:
            est.observe(s.price_usd, s.quote_amount, s.side)
            q = est.quote_reserve()
            tl.append(
                _TimelinePoint(
                    kt=s.knowable_at,
                    et=s.event_time,
                    price=s.price_usd,
                    depth=(q * self.cfg.depth_multiplier) if q is not None else None,
                )
            )
        return tl

    @staticmethod
    def _last_at_or_before(tl: list[_TimelinePoint], t: float, key: str) -> _TimelinePoint | None:
        """Last timeline point with key-time <= t (linear scan; pools are small)."""
        found: _TimelinePoint | None = None
        for pt in tl:
            tv = pt.kt if key == "kt" else pt.et
            if tv <= t:
                found = pt
            else:
                break
        return found

    def run_pool(self, pool: PoolData) -> tuple[list[Trade], list[Trade], float]:
        """Return (scored_trades, censored_trades, eligible_pool_minutes) for one pool."""
        swaps = pool.swaps
        if len(swaps) < 2 * self.cfg.signal.min_trades_per_half:
            return [], [], 0.0
        sol_usd = self._sol_usd(swaps)
        if sol_usd is None or sol_usd <= 0:
            return [], [], 0.0
        size_quote = self.cfg.position_size_usd / sol_usd

        tl = self._build_timeline(swaps)
        first_kt = swaps[0].knowable_at
        last_et = swaps[-1].event_time

        eligible_start = first_kt + self.cfg.warmup_s
        eligible_minutes = max(0.0, (swaps[-1].knowable_at - eligible_start)) / 60.0

        scored: list[Trade] = []
        censored: list[Trade] = []
        next_allowed_ts = eligible_start  # cooldown gate

        # Every signal consumer (compute_signal, compute_attribution, rug_check) only ever
        # reads swaps within its own lookback of the decision time, so we pass a bounded TAIL
        # slice [lo:i+1] covering the widest window rather than all of history. This is exactly
        # equivalent (each consumer re-filters by knowable_at) but turns the per-pool decision
        # loop from O(n²) into O(n·window) — decisive on the few very deep pools.
        max_window = max(
            self.cfg.signal.lookback_s,
            self.cfg.rug.lookback_s,
            self.cfg.attribution.attr_window_s,
        )
        lo = 0
        for i, s in enumerate(swaps):
            t = s.knowable_at
            while swaps[lo].knowable_at < t - max_window:
                lo += 1
            if t < eligible_start or t < next_allowed_ts:
                continue
            visible = swaps[lo : i + 1]  # covers [t - max_window, t]; knowable_at <= t
            sig = compute_signal(visible, t, self.cfg.signal)
            if self.book is not None:
                attr = compute_attribution(visible, t, self.book, self.cfg.attribution)
                sig = replace(
                    sig,
                    attr_defined=attr.defined,
                    attr_score=attr.score if attr.defined else float("-inf"),
                    attr_smart_share=attr.smart_share,
                    attr_n_scored_buyers=attr.n_scored_buyers,
                )
            if not sig.defined_for(self.cfg.signal_field):
                continue
            sig_val = float(getattr(sig, self.cfg.signal_field))

            # Rug gate (recorded either way so we can report on/off).
            verdict = rug_check(visible, t, self.cfg.rug)
            rug_blocked = self.cfg.use_rug_filter and verdict.blocked

            # Enter at the price/depth knowable at T.
            entry_pt = self._last_at_or_before(tl, t, "kt")
            if entry_pt is None or entry_pt.depth is None or entry_pt.price <= 0:
                continue

            # Exit one horizon later, in event-time. Censored if data ends first.
            exit_et = s.event_time + self.cfg.horizon_s
            if exit_et > last_et:
                censored.append(Trade(pool.pool_address, t, sig_val, 0.0, 0.0, 0.0, rug_blocked))
                next_allowed_ts = t + self.cfg.horizon_s
                continue
            exit_pt = self._last_at_or_before(tl, exit_et, "et")
            if exit_pt is None or exit_pt.depth is None or exit_pt.price <= 0:
                next_allowed_ts = t + self.cfg.horizon_s
                continue

            rt = self.cfg.execution.round_trip(
                size_quote=size_quote,
                p_entry=entry_pt.price,
                q_entry=entry_pt.depth,
                p_exit=exit_pt.price,
                q_exit=exit_pt.depth,
            )
            scored.append(
                Trade(
                    pool_address=pool.pool_address,
                    decision_ts=t,
                    signal_value=sig_val,
                    net_return=rt.net_return,
                    marked_return=rt.marked_return,
                    cost_drag=rt.cost_drag,
                    rug_blocked=rug_blocked,
                )
            )
            next_allowed_ts = t + self.cfg.horizon_s

        return scored, censored, eligible_minutes

    def run(self, pools: list[PoolData]) -> tuple[list[Trade], list[Trade], float, int]:
        """Run all pools. Returns (scored, censored, total_eligible_minutes, n_pools_used)."""
        all_scored: list[Trade] = []
        all_censored: list[Trade] = []
        total_minutes = 0.0
        used = 0
        for pool in pools:
            scored, censored, minutes = self.run_pool(pool)
            if minutes > 0 or scored or censored:
                used += 1
            all_scored.extend(scored)
            all_censored.extend(censored)
            total_minutes += minutes
        return all_scored, all_censored, total_minutes, used


def summarize_threshold(
    threshold: float,
    scored: list[Trade],
    censored: list[Trade],
    eligible_minutes: float,
) -> ThresholdResult:
    """Apply a threshold to pre-generated trades and compute the curve point.

    A fire = signal_value >= threshold. Rug-blocked fires are excluded from scored P&L
    but counted; censored fires (above threshold) are reported, not scored.
    """
    above = [t for t in scored if t.signal_value >= threshold]
    passed = [t for t in above if not t.rug_blocked]
    rug_blocked = sum(1 for t in above if t.rug_blocked)
    censored_above = sum(1 for t in censored if t.signal_value >= threshold)

    if not passed:
        return ThresholdResult(
            threshold=threshold,
            n_fires=0,
            n_rug_blocked=rug_blocked,
            n_censored=censored_above,
            n_pools_fired=0,
            fire_rate_per_pool_min=0.0,
            hit_rate=0.0,
            expectancy=0.0,
            median_net=0.0,
            mean_marked=0.0,
            mean_cost_drag=0.0,
            p25_net=0.0,
            p75_net=0.0,
        )

    nets = sorted(t.net_return for t in passed)
    hit = sum(1 for t in passed if t.net_return > 0) / len(passed)
    return ThresholdResult(
        threshold=threshold,
        n_fires=len(passed),
        n_rug_blocked=rug_blocked,
        n_censored=censored_above,
        n_pools_fired=len({t.pool_address for t in passed}),
        fire_rate_per_pool_min=(len(passed) / eligible_minutes if eligible_minutes > 0 else 0.0),
        hit_rate=hit,
        expectancy=statistics.fmean(t.net_return for t in passed),
        median_net=statistics.median(nets),
        mean_marked=statistics.fmean(t.marked_return for t in passed),
        mean_cost_drag=statistics.fmean(t.cost_drag for t in passed),
        p25_net=_percentile(nets, 0.25),
        p75_net=_percentile(nets, 0.75),
    )


def profile_curve(
    pools: list[PoolData],
    cfg: ProfilerConfig,
    thresholds: list[float],
) -> tuple[list[ThresholdResult], dict[str, float]]:
    """Run the profiler once and return (curve over thresholds, run metadata)."""
    prof = Profiler(cfg)
    scored, censored, minutes, used = prof.run(pools)
    curve = [summarize_threshold(thr, scored, censored, minutes) for thr in thresholds]
    meta = {
        "n_pools_in_universe": float(len(pools)),
        "n_pools_used": float(used),
        "total_scored_fires_at_min_threshold": float(len(scored)),
        "total_censored_at_min_threshold": float(len(censored)),
        "total_eligible_pool_minutes": minutes,
    }
    return curve, meta
