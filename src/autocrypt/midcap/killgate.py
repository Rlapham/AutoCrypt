"""M3 — the mid-cap deep-pool KILL-GATE (frequency-vs-expectancy on daily bars).

This is Track M's verdict instrument. It adapts the M2 cost model + the Iteration-1 kill-gate
DISCIPLINE (survivorship-complete universe, point-in-time decisions, frequency-vs-expectancy
curve, blind baseline, permutation test, robustness sweeps) onto the daily-OHLCV mid-cap
store. The Phase-2 `Profiler` is swap-/second-native and infers depth; M3 is bar-/day-native
and reads depth from `reserve_usd`, so it is a sibling engine rather than a reuse — but it
shares the one piece that must not change between iterations: the constant-product
`ExecutionModel` (so "1% cost now" is the same ruler as Iteration-1's "20-28%").

For each in-band pool and each eligible decision bar ``i`` (≥ warmup, signal defined):
  * the signal is computed from closes/highs/volumes ``0..i`` only (no look-ahead);
  * we BUY at close[i] and SELL at close[i+H] — one position per pool at a time (cooldown =
    horizon ⇒ non-overlapping, independent fires);
  * the round trip is charged fees + own price impact on both legs (constant-product) at a
    CAPACITY-SCALED size: notional = min(max_usd, capacity_frac x reserve_usd) — the M2 rule
    that keeps friction ~1%, encoded so expectancy is net at a *realistic* per-pool size, not
    a flat dollar that would be too big for the shallow pools and too small for the deep ones;
  * trades whose exit runs past the pool's last bar are CENSORED (reported, never scored).

Trades are generated ONCE at the blind threshold (fire on every defined signal); the curve,
permutation test and verdict all filter that single point-in-time pass — exact, not re-run.

Survivorship asymmetry (load-bearing): the universe is today's survivors, so a POSITIVE here
is only an upper bound. The honest verdict ceiling on this control is NO-GO/"unproven", never
a GO. Never tune to a positive.
"""

from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass

from autocrypt.midcap.bars import PoolBars, load_pool_bars
from autocrypt.midcap.barsignals import breakout, mean_reversion, ts_momentum
from autocrypt.profiler.execution import ExecutionModel
from autocrypt.storage.store import EventStore

SIGNALS = ("ts_mom", "xs_mom", "mean_rev", "breakout")
NEG_INF = float("-inf")


@dataclass(frozen=True)
class KillGateConfig:
    """One signal + its execution/capacity assumptions for a kill-gate run."""

    signal: str = "ts_mom"  # one of SIGNALS
    lookback: int = 10  # bars used by the signal
    horizon: int = 5  # hold period in bars (entry close[i] → exit close[i+H])
    warmup: int = 10  # min bars of history before the first decision
    capacity_frac: float = 0.004  # per-pool notional ≤ 0.4% of reserve (M2 capacity rule)
    max_notional_usd: float = 10_000.0  # hard cap regardless of depth
    fee_bps: float = 30.0  # swap fee per leg (mid-cap DEX tier)
    fixed_cost_usd: float = 0.20  # priority fee + Jito tip per leg
    depth_frac: float = 0.5  # quote-side share of reserve_usd (balanced xy=k)
    depth_mult: float = 1.0  # depth sensitivity multiplier (sweep)
    vol_mult: float = 1.0  # breakout volume-confirmation multiple

    def position_usd(self, reserve_usd: float) -> float:
        return min(self.max_notional_usd, self.capacity_frac * reserve_usd)

    def depth_usd(self, reserve_usd: float) -> float:
        return reserve_usd * self.depth_frac * self.depth_mult


@dataclass(slots=True)
class BarTrade:
    """One simulated, scored round-trip (a fire with full horizon data)."""

    pool_address: str
    decision_time: float  # knowable_at of the decision bar
    signal_value: float
    net_return: float
    marked_return: float
    cost_drag: float


@dataclass(slots=True)
class ThresholdStat:
    threshold: float
    n_fires: int
    n_pools: int
    fire_frac: float  # fires at this threshold / fires at blind
    hit_rate: float
    expectancy: float  # mean net return per fire — THE number
    median_net: float
    mean_marked: float
    mean_cost_drag: float
    p25_net: float
    p75_net: float


@dataclass(slots=True)
class SignificancePoint:
    threshold: float
    n: int
    mean_net: float
    p_value: float


@dataclass(slots=True)
class SignalReport:
    cfg: KillGateConfig
    n_pools_universe: int
    n_pools_used: int
    n_scored: int
    n_censored: int
    blind: ThresholdStat
    curve: list[ThresholdStat]
    significance: list[SignificancePoint]
    horizon_sweep: dict[int, ThresholdStat]  # horizon bars -> blind stat
    depth_sweep: dict[float, ThresholdStat]  # depth_mult -> blind stat
    lookback_sweep: dict[int, ThresholdStat]  # lookback bars -> blind stat
    window_split: dict[str, ThresholdStat]  # 'early'/'late' -> blind stat
    quantiles: dict[str, float]
    verdict: str
    best: ThresholdStat | None


# ── percentiles / stats helpers ───────────────────────────────────────────────


def _percentile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return sorted_vals[lo]
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def _quantiles_from(vals: list[float]) -> tuple[list[float], dict[str, float]]:
    """Signal-value quantiles → ascending dedup thresholds + a labelled dict."""
    finite = sorted(v for v in vals if math.isfinite(v))
    if not finite:
        return [], {}
    qs = {f"p{int(p * 100)}": _percentile(finite, p) for p in (0.0, 0.25, 0.5, 0.75, 0.9, 0.95)}
    return sorted(set(qs.values())), qs


# ── signal-value computation (point-in-time; XS needs the whole panel) ─────────


def _local_values(pool: PoolBars, cfg: KillGateConfig) -> dict[int, float]:
    """Per-bar signal value for a single-pool (local) signal. Index → value."""
    closes = pool.closes
    out: dict[int, float] = {}
    n = len(closes)
    for i in range(n):
        if cfg.signal == "ts_mom":
            v = ts_momentum(closes, i, cfg.lookback)
        elif cfg.signal == "mean_rev":
            v = mean_reversion(closes, i, cfg.lookback)
        elif cfg.signal == "breakout":
            v = breakout(closes, pool.highs, [b.volume_usd for b in pool.bars], i, cfg.lookback,
                         vol_mult=cfg.vol_mult)
        else:  # xs_mom handled by _xs_values
            v = None
        if v is not None:
            out[i] = v
    return out


def _xs_values(pools: list[PoolBars], cfg: KillGateConfig) -> dict[str, dict[int, float]]:
    """Cross-sectional momentum: rank each pool's trailing return across the universe ON
    THE SAME DATE. Point-in-time safe — every ranked value is the contemporaneous trailing
    return (knowable at that date), and the rank uses only same-date values.

    Returns the percentile rank in [0,1] (1 = strongest momentum in the cross-section that
    day) per (pool, bar index). Days with <3 defined names are skipped (no cross-section).
    """
    # raw[pool] = {i: trailing return}; also group by event_time for ranking.
    raw: dict[str, dict[int, float]] = {}
    by_date: dict[float, list[tuple[str, int, float]]] = {}
    for p in pools:
        closes = p.closes
        rmap: dict[int, float] = {}
        for i in range(len(closes)):
            v = ts_momentum(closes, i, cfg.lookback)
            if v is None:
                continue
            rmap[i] = v
            by_date.setdefault(p.bars[i].event_time, []).append((p.pool_address, i, v))
        raw[p.pool_address] = rmap

    out: dict[str, dict[int, float]] = {p.pool_address: {} for p in pools}
    for _date, entries in by_date.items():
        if len(entries) < 3:
            continue  # too thin to rank
        entries_sorted = sorted(entries, key=lambda e: e[2])
        m = len(entries_sorted)
        for rank, (addr, i, _v) in enumerate(entries_sorted):
            out[addr][i] = rank / (m - 1)  # 0..1, 1 = highest momentum that day
    return out


def signal_values(pools: list[PoolBars], cfg: KillGateConfig) -> dict[str, dict[int, float]]:
    if cfg.signal == "xs_mom":
        return _xs_values(pools, cfg)
    return {p.pool_address: _local_values(p, cfg) for p in pools}


# ── trade simulation ──────────────────────────────────────────────────────────


def _run(pools: list[PoolBars], cfg: KillGateConfig) -> tuple[list[BarTrade], int, int]:
    """Generate scored + censored trades across all pools (blind: every defined signal).

    Returns (scored, n_censored, n_pools_used). Cooldown = horizon bars (non-overlapping
    holds ⇒ independent fires), mirroring the Phase-2 profiler.
    """
    values = signal_values(pools, cfg)
    model = ExecutionModel(fee_bps=cfg.fee_bps, fixed_cost_quote=cfg.fixed_cost_usd)
    scored: list[BarTrade] = []
    n_censored = 0
    used = 0
    for p in pools:
        sv = values.get(p.pool_address, {})
        if not sv:
            continue
        closes = p.closes
        n = len(closes)
        depth = cfg.depth_usd(p.reserve_usd)
        size = cfg.position_usd(p.reserve_usd)
        if depth <= 0 or size <= 0:
            continue
        used_pool = False
        next_allowed = cfg.warmup
        for i in range(cfg.warmup, n):
            if i < next_allowed:
                continue
            val = sv.get(i)
            if val is None or not math.isfinite(val):
                continue
            j = i + cfg.horizon
            if j >= n:
                n_censored += 1
                next_allowed = i + cfg.horizon
                continue
            rt = model.round_trip(
                size_quote=size,
                p_entry=closes[i],
                q_entry=depth,
                p_exit=closes[j],
                q_exit=depth,
            )
            scored.append(
                BarTrade(
                    pool_address=p.pool_address,
                    decision_time=p.bars[i].knowable_at,
                    signal_value=val,
                    net_return=rt.net_return,
                    marked_return=rt.marked_return,
                    cost_drag=rt.cost_drag,
                )
            )
            used_pool = True
            next_allowed = i + cfg.horizon
        if used_pool:
            used += 1
    return scored, n_censored, used


def _summarize(threshold: float, scored: list[BarTrade], n_blind: int) -> ThresholdStat:
    passed = [t for t in scored if t.signal_value >= threshold]
    if not passed:
        return ThresholdStat(threshold, 0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    nets = sorted(t.net_return for t in passed)
    return ThresholdStat(
        threshold=threshold,
        n_fires=len(passed),
        n_pools=len({t.pool_address for t in passed}),
        fire_frac=(len(passed) / n_blind if n_blind else 0.0),
        hit_rate=sum(1 for t in passed if t.net_return > 0) / len(passed),
        expectancy=statistics.fmean(t.net_return for t in passed),
        median_net=statistics.median(nets),
        mean_marked=statistics.fmean(t.marked_return for t in passed),
        mean_cost_drag=statistics.fmean(t.cost_drag for t in passed),
        p25_net=_percentile(nets, 0.25),
        p75_net=_percentile(nets, 0.75),
    )


def _permutation(
    scored: list[BarTrade], thresholds: list[float], n_resamples: int = 20_000, min_n: int = 12
) -> list[SignificancePoint]:
    """For each threshold: P(a random same-size subset of ALL fires has mean ≥ observed).

    Null = "the signal carries no information". A low p means the signal selected
    better-than-random entries — a stricter bar than merely beating blind. Seeded.
    Apply a multiple-comparison discount: several thresholds are tested per signal.
    """
    rng = random.Random(1234)
    nets = [t.net_return for t in scored]
    out: list[SignificancePoint] = []
    for thr in thresholds:
        subset = [t.net_return for t in scored if t.signal_value >= thr]
        k = len(subset)
        if k < min_n or k == len(nets):
            continue
        obs = sum(subset) / k
        hits = sum(1 for _ in range(n_resamples) if sum(rng.sample(nets, k)) / k >= obs)
        out.append(SignificancePoint(thr, k, obs, hits / n_resamples))
    return out


def _verdict(
    blind: ThresholdStat,
    best: ThresholdStat | None,
    significance: list[SignificancePoint],
    sweeps: list[ThresholdStat],
    min_fires: int = 30,
) -> str:
    """Honest one-line verdict. On a biased control the CEILING is 'unproven', never GO."""
    if best is None or best.n_fires < min_fires:
        return "NO-GO — too few fires for statistics"
    profitable = best.expectancy > 0 and blind.expectancy > -0.02
    beats_blind = best.expectancy > blind.expectancy
    # best permutation p among tested thresholds, with a crude multiple-comparison discount
    ps = [s.p_value for s in significance]
    min_p = min(ps) if ps else 1.0
    discounted = min_p * max(1, len(ps))
    beats_random = discounted < 0.05
    robust = all(s.expectancy > 0 for s in sweeps if s.n_fires >= min_fires)
    if not profitable:
        return f"NO-GO — best net expectancy {best.expectancy:+.2%} not profitable after cost"
    if not beats_blind:
        return f"NO-GO — does not beat blind ({best.expectancy:+.2%} vs {blind.expectancy:+.2%})"
    if not beats_random:
        return f"NO-GO — not better than random (discounted p={discounted:.3f})"
    if not robust:
        return "NO-GO — sign flips across sweeps (fragile)"
    return (
        f"UNPROVEN (upper bound only) — clears the gate on this BIASED control "
        f"(net {best.expectancy:+.2%}, discounted p={discounted:.3f}); survivorship forbids a GO"
    )


def profile_signal(pools: list[PoolBars], cfg: KillGateConfig) -> SignalReport:
    """Full kill-gate for one signal: curve + permutation + robustness sweeps + verdict."""
    scored, n_censored, used = _run(pools, cfg)
    n_blind = len(scored)
    blind = _summarize(NEG_INF, scored, n_blind)
    thresholds, qs = _quantiles_from([t.signal_value for t in scored])
    curve = [_summarize(thr, scored, n_blind) for thr in thresholds]
    significance = _permutation(scored, thresholds)

    # Best curve point by expectancy among those with enough fires.
    candidates = [c for c in curve if c.n_fires >= 30]
    best = max(candidates, key=lambda c: c.expectancy) if candidates else None

    # Robustness sweeps (blind expectancy at each setting — re-run the point-in-time pass).
    from dataclasses import replace

    horizon_sweep: dict[int, ThresholdStat] = {}
    for h in (3, 5, 10):
        s, _, _ = _run(pools, replace(cfg, horizon=h))
        horizon_sweep[h] = _summarize(NEG_INF, s, len(s))
    depth_sweep: dict[float, ThresholdStat] = {}
    for dm in (0.5, 1.0, 2.0):
        s, _, _ = _run(pools, replace(cfg, depth_mult=dm))
        depth_sweep[dm] = _summarize(NEG_INF, s, len(s))
    lookback_sweep: dict[int, ThresholdStat] = {}
    for lb in (5, 10, 20):
        s, _, _ = _run(pools, replace(cfg, lookback=lb))
        lookback_sweep[lb] = _summarize(NEG_INF, s, len(s))

    # Time-window split (regime robustness): split the SAME scored trades at the median
    # decision time. Early vs late must not disagree in sign for the edge to be real.
    window_split: dict[str, ThresholdStat] = {}
    if scored:
        times = sorted(t.decision_time for t in scored)
        mid = _percentile(times, 0.5)
        early = [t for t in scored if t.decision_time <= mid]
        late = [t for t in scored if t.decision_time > mid]
        window_split["early"] = _summarize(NEG_INF, early, len(early))
        window_split["late"] = _summarize(NEG_INF, late, len(late))

    sweep_stats = (
        list(horizon_sweep.values())
        + list(depth_sweep.values())
        + list(lookback_sweep.values())
        + list(window_split.values())
    )
    verdict = _verdict(blind, best, significance, sweep_stats)

    return SignalReport(
        cfg=cfg,
        n_pools_universe=len(pools),
        n_pools_used=used,
        n_scored=n_blind,
        n_censored=n_censored,
        blind=blind,
        curve=curve,
        significance=significance,
        horizon_sweep=horizon_sweep,
        depth_sweep=depth_sweep,
        lookback_sweep=lookback_sweep,
        window_split=window_split,
        quantiles=qs,
        verdict=verdict,
        best=best,
    )


@dataclass(slots=True)
class KillGateReport:
    source: str
    speculative_only: bool
    n_pools: int
    base_cfg: KillGateConfig
    signals: list[SignalReport]


def run_killgate(
    store: EventStore,
    *,
    source: str = "coingecko_mcap_ranked",
    speculative_only: bool = True,
    base_cfg: KillGateConfig | None = None,
    signals: tuple[str, ...] = SIGNALS,
) -> KillGateReport:
    """Load the bar universe and run the kill-gate over the signal battery. Read-only."""
    from dataclasses import replace

    base = base_cfg or KillGateConfig()
    pools = load_pool_bars(
        store, source=source, speculative_only=speculative_only, min_bars=base.warmup + base.horizon + 1
    )
    reports = [profile_signal(pools, replace(base, signal=sig)) for sig in signals]
    return KillGateReport(
        source=source,
        speculative_only=speculative_only,
        n_pools=len(pools),
        base_cfg=base,
        signals=reports,
    )


# ── markdown rendering ─────────────────────────────────────────────────────────


def _pct(x: float) -> str:
    return f"{x * 100:+.2f}%"


def _row(r: ThresholdStat, label: str | None = None) -> str:
    thr = label if label is not None else (
        "blind" if r.threshold == NEG_INF else f"{r.threshold:.3f}"
    )
    return (
        f"| {thr} | {r.n_fires} | {r.n_pools} | {r.fire_frac:.2f} | {r.hit_rate * 100:.1f}% | "
        f"**{_pct(r.expectancy)}** | {_pct(r.median_net)} | {_pct(r.mean_marked)} | "
        f"{_pct(r.mean_cost_drag)} | {_pct(r.p25_net)} / {_pct(r.p75_net)} |"
    )


_HDR = (
    "| threshold | fires | pools | fire-frac | hit | **expectancy** | median | marked | "
    "cost drag | p25/p75 |\n|---|---|---|---|---|---|---|---|---|---|"
)

_SIGNAL_DESC = {
    "ts_mom": "Time-series momentum — buy when the trailing L-bar return is high (trend).",
    "xs_mom": "Cross-sectional momentum — buy the universe's strongest trailing performers "
    "(percentile rank across all pools on the decision date).",
    "mean_rev": "Mean-reversion — buy oversold names (negative z-score vs the trailing mean).",
    "breakout": "Breakout — buy a close above the prior L-bar high, gated on volume expansion.",
}


def render_markdown(rep: KillGateReport) -> str:
    base = rep.base_cfg
    L: list[str] = []
    L.append("# Phase M3 — Mid-cap deep-pool KILL-GATE (signal battery)\n")
    L.append(
        f"- Universe (in-band, {'speculative-only' if rep.speculative_only else 'all'}): "
        f"**{rep.n_pools}** pools, source `{rep.source}` — **survivorship-BIASED** (today's "
        f"survivors). A positive is an UPPER BOUND; ceiling on this control is "
        f"**NO-GO/\"unproven\"**, never a GO.\n"
        f"- Hold horizon **{base.horizon} bars (days)**; lookback **{base.lookback}**; "
        f"position = min(${base.max_notional_usd:,.0f}, {base.capacity_frac:.1%} x reserve) "
        f"[M2 capacity rule]; cost = fees {base.fee_bps:g}bps/leg + own impact (both legs), "
        f"depth = {base.depth_frac:g}xreserve.\n"
        f"- Decisions are point-in-time (`knowable_at ≤ T`); entry close[i] → exit close[i+H]; "
        f"one position per pool at a time (cooldown = horizon); censored trades reported.\n"
    )

    L.append("\n## Verdict summary\n")
    L.append("| signal | scored | blind exp. | best exp. | verdict |\n|---|---|---|---|---|")
    for s in rep.signals:
        be = _pct(s.best.expectancy) if s.best else "—"
        L.append(
            f"| `{s.cfg.signal}` | {s.n_scored} | {_pct(s.blind.expectancy)} | {be} | "
            f"{s.verdict} |"
        )

    for s in rep.signals:
        L.append(f"\n---\n\n## `{s.cfg.signal}` — {_SIGNAL_DESC.get(s.cfg.signal, '')}\n")
        L.append(
            f"Pools used **{s.n_pools_used}/{s.n_pools_universe}**; scored fires "
            f"**{s.n_scored}**, censored **{s.n_censored}**. Verdict: **{s.verdict}**\n"
        )
        L.append("\n### Frequency-vs-expectancy curve\n")
        L.append(_HDR)
        L.append(_row(s.blind))
        for r in s.curve:
            L.append(_row(r))

        if s.significance:
            L.append("\n### Significance — does the signal beat RANDOM selection?\n")
            L.append(
                "Permutation test (20k resamples, seeded): P(a random subset of the same size "
                "has mean net ≥ the signal's). Apply a multiple-comparison discount (several "
                "thresholds tested).\n"
            )
            L.append("| threshold | n | mean net | p(random ≥ obs) |\n|---|---|---|---|")
            for sp in s.significance:
                L.append(f"| {sp.threshold:.3f} | {sp.n} | {_pct(sp.mean_net)} | {sp.p_value:.3f} |")

        L.append("\n### Robustness sweeps (blind expectancy)\n")
        L.append(_HDR)
        for h, r in sorted(s.horizon_sweep.items()):
            L.append(_row(r, label=f"horizon={h}d"))
        for dm, r in sorted(s.depth_sweep.items()):
            L.append(_row(r, label=f"depthx{dm:g}"))
        for lb, r in sorted(s.lookback_sweep.items()):
            L.append(_row(r, label=f"lookback={lb}"))
        for k in ("early", "late"):
            if k in s.window_split:
                L.append(_row(s.window_split[k], label=f"window={k}"))

    return "\n".join(L) + "\n"
