"""M3 kill-gate tests — signals, capacity rule, point-in-time discipline, engine."""

from __future__ import annotations

import math

from autocrypt.midcap.bars import Bar, PoolBars
from autocrypt.midcap.barsignals import breakout, mean_reversion, ts_momentum
from autocrypt.midcap.killgate import (
    KillGateConfig,
    _run,
    profile_signal,
    signal_values,
)

# ── signal battery ────────────────────────────────────────────────────────────


def test_ts_momentum_sign_and_undefined():
    closes = [1.0, 1.1, 1.2, 1.3, 1.5]
    assert ts_momentum(closes, 4, 4) == 0.5  # 1.5/1.0 - 1
    assert ts_momentum(closes, 2, 4) is None  # not enough history
    down = [2.0, 1.0]
    assert ts_momentum(down, 1, 1) == -0.5


def test_mean_reversion_oversold_is_positive():
    # Trailing window with real dispersion (mean ~1.0), then a sharp drop ⇒ oversold ⇒
    # positive (buy-the-dip) score.
    closes = [1.0, 1.1, 0.9, 1.0, 0.7]
    v = mean_reversion(closes, 4, 4)
    assert v is not None and v > 0
    # Same window, a spike UP ⇒ negative score (overbought, don't buy).
    closes_up = [1.0, 1.1, 0.9, 1.0, 1.3]
    vu = mean_reversion(closes_up, 4, 4)
    assert vu is not None and vu < 0


def test_mean_reversion_flat_window_undefined():
    assert mean_reversion([1.0, 1.0, 1.0, 1.0, 1.0], 4, 4) is None  # zero dispersion


def test_breakout_above_prior_high_with_volume():
    closes = [1.0, 1.0, 1.0, 1.0, 1.2]
    highs = [1.0, 1.05, 1.0, 1.05, 1.2]
    vols = [10.0, 10.0, 10.0, 10.0, 100.0]  # volume expansion on the break
    v = breakout(closes, highs, vols, 4, 4, vol_mult=1.0)
    assert v is not None and v > 0  # 1.2 / 1.05 - 1 > 0


def test_breakout_suppressed_without_volume():
    closes = [1.0, 1.0, 1.0, 1.0, 1.2]
    highs = [1.0, 1.05, 1.0, 1.05, 1.2]
    vols = [100.0, 100.0, 100.0, 100.0, 1.0]  # break on COLLAPSING volume
    v = breakout(closes, highs, vols, 4, 4, vol_mult=1.0)
    assert v == float("-inf")  # un-confirmed ⇒ never clears a positive threshold


def test_breakout_inside_range_is_negative():
    closes = [1.0, 1.0, 1.0, 1.0, 1.02]
    highs = [1.0, 1.10, 1.0, 1.10, 1.02]  # prior high 1.10 not exceeded
    vols = [10.0, 10.0, 10.0, 10.0, 50.0]
    v = breakout(closes, highs, vols, 4, 4, vol_mult=1.0)
    assert v is not None and v < 0


# ── helpers to build synthetic pools ──────────────────────────────────────────


def _pool(addr: str, closes: list[float], *, reserve: float = 1_000_000.0, day0: int = 0) -> PoolBars:
    """A pool with daily bars; event_time/knowable_at one day apart per bar (epoch s)."""
    day = 86_400.0
    bars = [
        Bar(
            event_time=(day0 + k) * day,
            knowable_at=(day0 + k) * day + 2.0,
            open=c,
            high=c,
            low=c,
            close=c,
            volume_usd=100.0,
        )
        for k, c in enumerate(closes)
    ]
    return PoolBars(
        pool_address=addr,
        name=f"{addr} / SOL",
        base_mint=None,
        quote_mint=None,
        reserve_usd=reserve,
        is_speculative=True,
        bars=bars,
    )


# ── capacity rule ─────────────────────────────────────────────────────────────


def test_capacity_rule_scales_with_depth_and_caps():
    cfg = KillGateConfig(capacity_frac=0.004, max_notional_usd=10_000.0)
    assert cfg.position_usd(1_000_000.0) == 4_000.0  # 0.4% of reserve
    assert cfg.position_usd(100_000_000.0) == 10_000.0  # capped
    assert cfg.depth_usd(1_000_000.0) == 500_000.0  # 0.5 x reserve x 1.0


# ── point-in-time discipline ──────────────────────────────────────────────────


def test_no_lookahead_exit_beyond_data_is_censored():
    # 12 bars, warmup 10, horizon 5 ⇒ decision at i=10 needs i+5=15 (absent) ⇒ censored.
    closes = [1.0 + 0.01 * k for k in range(12)]
    pool = _pool("A", closes)
    cfg = KillGateConfig(signal="ts_mom", lookback=5, horizon=5, warmup=10)
    scored, n_censored, used = _run([pool], cfg)
    assert scored == []  # nothing scorable
    assert n_censored >= 1  # the in-range decision had no future bar


def test_scored_trade_uses_only_past_for_signal_and_future_for_outcome():
    # Uptrend ⇒ ts_mom defined & positive; entry close[i], exit close[i+H] both real bars.
    closes = [1.0 + 0.02 * k for k in range(40)]
    pool = _pool("B", closes)
    cfg = KillGateConfig(signal="ts_mom", lookback=5, horizon=5, warmup=5)
    scored, _, used = _run([pool], cfg)
    assert used == 1 and scored
    t = scored[0]
    # marked return must equal close[i+H]/close[i]-1 for SOME valid i (monotone up ⇒ >0).
    assert t.marked_return > 0
    # net is below marked (costs always drag).
    assert t.net_return < t.marked_return


def test_cooldown_is_horizon_non_overlapping():
    closes = [1.0 + 0.01 * k for k in range(40)]
    pool = _pool("C", closes)
    cfg = KillGateConfig(signal="ts_mom", lookback=5, horizon=5, warmup=5)
    scored, _, _ = _run([pool], cfg)
    # decision indices start at 5, then every 5 bars ⇒ at most ceil((40-5)/5) fires.
    assert len(scored) <= math.ceil((40 - 5) / 5)


# ── cross-sectional momentum ──────────────────────────────────────────────────


def test_xs_momentum_ranks_within_date():
    # Three pools, same dates. Pool HI rises fastest ⇒ top rank (1.0); LO ⇒ 0.0.
    hi = _pool("HI", [1.0 + 0.05 * k for k in range(20)])
    mid = _pool("MID", [1.0 + 0.02 * k for k in range(20)])
    lo = _pool("LO", [1.0 + 0.001 * k for k in range(20)])
    cfg = KillGateConfig(signal="xs_mom", lookback=5)
    vals = signal_values([hi, mid, lo], cfg)
    # pick a date index present for all (say i=10)
    assert vals["HI"][10] == 1.0
    assert vals["LO"][10] == 0.0
    assert 0.0 < vals["MID"][10] < 1.0


def test_xs_momentum_skips_thin_cross_section():
    # Only 2 pools ⇒ <3 names per date ⇒ no ranking produced.
    a = _pool("A", [1.0 + 0.05 * k for k in range(20)])
    b = _pool("B", [1.0 + 0.01 * k for k in range(20)])
    cfg = KillGateConfig(signal="xs_mom", lookback=5)
    vals = signal_values([a, b], cfg)
    assert vals["A"] == {} and vals["B"] == {}


# ── engine / verdict ──────────────────────────────────────────────────────────


def test_profile_signal_reports_curve_and_verdict():
    pools = [
        _pool(f"P{n}", [1.0 + 0.01 * k + 0.001 * n for k in range(60)], reserve=2_000_000.0)
        for n in range(6)
    ]
    cfg = KillGateConfig(signal="ts_mom", lookback=10, horizon=5, warmup=10)
    rep = profile_signal(pools, cfg)
    assert rep.n_scored > 0
    assert rep.blind.n_fires == rep.n_scored
    assert isinstance(rep.verdict, str) and rep.verdict
    # sweeps populated
    assert set(rep.horizon_sweep) == {3, 5, 10}
    assert set(rep.depth_sweep) == {0.5, 1.0, 2.0}


def test_biased_control_never_returns_go():
    # Even a strongly up-trending (winner-only) synthetic universe must NOT yield a GO.
    pools = [
        _pool(f"W{n}", [1.0 * (1.03 ** k) for k in range(80)], reserve=5_000_000.0)
        for n in range(8)
    ]
    cfg = KillGateConfig(signal="ts_mom", lookback=10, horizon=5, warmup=10)
    rep = profile_signal(pools, cfg)
    assert "GO" not in rep.verdict or "NO-GO" in rep.verdict or "UNPROVEN" in rep.verdict
    # explicitly: the word "GO" only appears inside NO-GO / (nothing else)
    assert not rep.verdict.startswith("GO")
