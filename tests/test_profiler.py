"""Tests for the Phase 2 profiler — execution math, liquidity inversion, signal
derivatives, and (critically) the no-look-ahead discipline. No network."""

from __future__ import annotations

import math

from autocrypt.profiler.dataset import PoolData, SwapRow
from autocrypt.profiler.execution import ExecutionModel
from autocrypt.profiler.liquidity import LiquidityEstimator
from autocrypt.profiler.profiler import Profiler, ProfilerConfig
from autocrypt.profiler.signals import SignalConfig, compute_signal


# ── execution model ───────────────────────────────────────────────────────────
def test_zero_cost_deep_pool_matches_marked() -> None:
    """With no fees, no fixed cost, and a near-infinite pool, net ≈ marked return."""
    em = ExecutionModel(fee_bps=0.0, fixed_cost_quote=0.0)
    rt = em.round_trip(size_quote=0.001, p_entry=1.0, q_entry=1e9, p_exit=1.10, q_exit=1e9)
    assert math.isclose(rt.marked_return, 0.10, rel_tol=1e-6)
    assert rt.net_return < rt.marked_return  # tiny residual impact
    assert rt.net_return > 0.099  # but essentially equal


def test_costs_create_drag() -> None:
    em = ExecutionModel(fee_bps=100.0, fixed_cost_quote=0.0005)
    rt = em.round_trip(size_quote=1.0, p_entry=1.0, q_entry=50.0, p_exit=1.0, q_exit=50.0)
    assert rt.marked_return == 0.0
    assert rt.net_return < 0.0  # flat price but you still lose to fees + impact
    assert rt.cost_drag > 0.0


def test_exit_into_thinner_pool_is_harder() -> None:
    """A shallower exit pool than entry pool ⇒ larger exit impact, worse net."""
    em = ExecutionModel(fee_bps=0.0, fixed_cost_quote=0.0)
    deep = em.round_trip(1.0, p_entry=1.0, q_entry=100.0, p_exit=1.0, q_exit=100.0)
    thin = em.round_trip(1.0, p_entry=1.0, q_entry=100.0, p_exit=1.0, q_exit=20.0)
    assert thin.exit_impact > deep.exit_impact
    assert thin.net_return < deep.net_return


def test_degenerate_depth_is_total_loss() -> None:
    em = ExecutionModel()
    rt = em.round_trip(1.0, p_entry=1.0, q_entry=0.0, p_exit=1.0, q_exit=0.0)
    assert rt.net_return == -1.0


# ── liquidity inversion ─────────────────────────────────────────────────────────
def test_liquidity_recovers_known_reserve() -> None:
    """Synthesize constant-product buys from a known Q and recover it.

    For a buy of dq into reserve Q the mid price moves p' = p*(1+dq/Q)^2.
    """
    q_true = 100.0
    est = LiquidityEstimator(window=20, min_ratio_move=1e-6)
    price = 1.0
    est.observe(price, 0.0, "buy")  # seed prev_price (zero size ignored)
    for _ in range(15):
        dq = 1.0
        ratio = (1.0 + dq / q_true) ** 2
        price *= ratio
        est.observe(price, dq, "buy")
    recovered = est.quote_reserve()
    assert recovered is not None
    assert math.isclose(recovered, q_true, rel_tol=0.05)


def test_liquidity_ignores_tiny_moves() -> None:
    est = LiquidityEstimator(min_ratio_move=1e-2)
    est.observe(1.0, 1.0, "buy")
    est.observe(1.0000001, 1.0, "buy")  # sub-threshold move → ignored
    assert est.quote_reserve() is None


# ── signal derivatives ─────────────────────────────────────────────────────────
def _swap(kt: float, side: str, usd: float, signer: str) -> SwapRow:
    return SwapRow(
        event_time=kt - 2.0,
        knowable_at=kt,
        side=side,
        price_usd=1.0,
        amount_usd=usd,
        quote_amount=usd,
        signer=signer,
    )


def test_signal_undefined_without_enough_trades() -> None:
    cfg = SignalConfig(lookback_s=60.0, min_trades_per_half=3)
    swaps = [_swap(float(i), "buy", 10.0, f"w{i}") for i in range(2)]
    snap = compute_signal(swaps, now_ts=60.0, cfg=cfg)
    assert not snap.defined


def test_buy_pressure_acceleration_positive() -> None:
    """Older half mixed, recent half all buys ⇒ positive buy-pressure acceleration."""
    cfg = SignalConfig(lookback_s=60.0, min_trades_per_half=3)
    now = 100.0
    # older half: window [40,70) → put sells/buys mixed
    older = [_swap(45.0 + i, "sell" if i % 2 else "buy", 10.0, f"o{i}") for i in range(6)]
    # recent half: window [70,100] → all buys, new wallets
    recent = [_swap(72.0 + i, "buy", 10.0, f"r{i}") for i in range(6)]
    snap = compute_signal(older + recent, now_ts=now, cfg=cfg)
    assert snap.defined
    assert snap.buy_pressure_accel > 0
    assert snap.unique_buyer_growth >= 0


def test_signal_excludes_future_knowable() -> None:
    """No look-ahead: a swap with knowable_at > now must not enter the signal window."""
    cfg = SignalConfig(lookback_s=60.0, min_trades_per_half=3)
    now = 100.0
    base = [_swap(72.0 + i, "buy", 10.0, f"r{i}") for i in range(3)]
    base += [_swap(45.0 + i, "buy", 10.0, f"o{i}") for i in range(3)]
    snap_before = compute_signal(base, now_ts=now, cfg=cfg)
    # Add a huge FUTURE sell (knowable_at = 130 > now). It must not change the signal.
    future = [*base, _swap(130.0, "sell", 1e6, "future")]
    snap_after = compute_signal(future, now_ts=now, cfg=cfg)
    assert snap_before.score == snap_after.score


# ── profiler end-to-end (synthetic, no DB) ─────────────────────────────────────
def test_profiler_runs_and_respects_pointintime() -> None:
    """A pool with a steady buy stream produces scored trades; censored ones are split out."""
    # Alternating buy/sell with clearly-detectable moves (> the depth detector's
    # min_ratio_move) and a mild upward drift, so depth is estimable and trades fire.
    swaps = []
    price = 1.0
    for i in range(300):
        buy = i % 2 == 0
        price *= 1.005 if buy else 0.996  # net upward drift, both > 0.1%
        swaps.append(
            SwapRow(
                event_time=float(i),
                knowable_at=float(i) + 2.0,
                side="buy" if buy else "sell",
                price_usd=price,
                amount_usd=20.0,
                quote_amount=20.0,
                signer=f"w{i % 11}",
            )
        )
    pool = PoolData("POOL", "BASE", "QUOTE", created_at=0.0, swaps=swaps)
    cfg = ProfilerConfig(horizon_s=30.0, warmup_s=20.0, position_size_usd=100.0)
    scored, censored, minutes, used = Profiler(cfg).run([pool])
    assert used == 1
    assert minutes > 0
    assert len(scored) >= 1
    # Late fires (within one horizon of the data end) must be censored, not scored.
    last_et = swaps[-1].event_time
    assert all(t.decision_ts - 2.0 + cfg.horizon_s <= last_et for t in scored)
