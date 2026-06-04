"""Tests for M2 deep-pool cost recalibration — pure cost math, no network.

These pin the load-bearing claims of the M2 gate: (1) the SAME constant-product engine
reproduces Iteration-1's cost wall on a thin pool but collapses to low single digits on a
deep one (depth is the only thing that changed), (2) flat-price friction is monotone in
position size and in the fee, (3) deeper pools are cheaper, (4) the pegged/pegged classifier
separates LST/stable/wrapped pairs from speculative mid-caps, and (5) the cross-pool
aggregation reports the right pass-fractions and percentiles.
"""

from __future__ import annotations

from autocrypt.midcap.costs import (
    CostParams,
    PoolFriction,
    _is_speculative,
    _percentile,
    _typical_abs_move,
    round_trip_friction,
    summarize_frictions,
)

BASE = CostParams()  # fee 30 bps/leg, fixed $0.20/leg, depth_frac 0.5


def test_deep_pool_escapes_the_cost_wall_thin_pool_hits_it() -> None:
    """The cost wall is about DEPTH, not the engine: same model, deep vs thin pool."""
    # Iteration-1-like thin pool: $20k reserve -> $10k quote depth, $1k position.
    thin = round_trip_friction(1_000.0, 10_000.0, BASE)
    # Mid-cap deep pool at the $500k floor: $250k quote depth, same position.
    deep = round_trip_friction(1_000.0, 250_000.0, BASE)
    assert thin > 0.15  # ~17%: reproduces Iteration 1's 20-28% wall
    assert deep < 0.03  # low single digits: Law 1 escaped
    assert deep < thin / 5


def test_friction_floor_is_two_legs_of_fee() -> None:
    """At negligible size relative to depth, friction -> ~2 * fee (both legs)."""
    f = round_trip_friction(100.0, 10_000_000.0, CostParams(fee_bps=30.0, fixed_cost_usd=0.0))
    assert 0.0059 < f < 0.0062  # ~0.60% = 2 * 0.30%


def test_friction_monotone_in_size_and_fee() -> None:
    """Bigger position (more own impact) and higher fee both raise friction."""
    sizes = [100.0, 1_000.0, 10_000.0, 50_000.0]
    fr = [round_trip_friction(s, 250_000.0, BASE) for s in sizes]
    # Strictly increasing once own impact dominates the fixed-cost floor (skip $100).
    assert fr[1] < fr[2] < fr[3]
    cheap = round_trip_friction(1_000.0, 250_000.0, CostParams(fee_bps=25.0))
    dear = round_trip_friction(1_000.0, 250_000.0, CostParams(fee_bps=100.0))
    assert dear > cheap


def test_deeper_pool_is_cheaper() -> None:
    shallow = round_trip_friction(5_000.0, 250_000.0, BASE)
    deeper = round_trip_friction(5_000.0, 2_500_000.0, BASE)
    assert deeper < shallow


def test_degenerate_depth_is_total_loss_not_optimistic() -> None:
    assert round_trip_friction(1_000.0, 0.0, BASE) == 1.0
    assert round_trip_friction(0.0, 250_000.0, BASE) == 1.0


def test_pegged_pair_classifier() -> None:
    # Speculative: at least one non-pegged leg.
    assert _is_speculative("WIF / SOL")
    assert _is_speculative("BOME / USDC")
    assert _is_speculative("Fartcoin / SOL")
    # Non-speculative: BOTH legs pegged (LST-SOL, stable-stable, wrapped-wrapped).
    assert not _is_speculative("mSOL / SOL")
    assert not _is_speculative("USDC / USDT")
    assert not _is_speculative("uniBTC / xBTC")
    # Unknown/blank -> keep it (don't silently drop).
    assert _is_speculative("")


def test_typical_abs_move() -> None:
    # Steady +10%/bar series -> |2-bar move| is a constant 21%.
    closes = [100.0, 110.0, 121.0, 133.1, 146.41]
    m = _typical_abs_move(closes, 2)
    assert m is not None and abs(m - 0.21) < 1e-9
    assert _typical_abs_move([100.0, 110.0], 5) is None  # too short


def test_percentile_interpolates() -> None:
    vals = [0.0, 1.0, 2.0, 3.0, 4.0]
    assert _percentile(vals, 0.5) == 2.0
    assert _percentile(vals, 0.25) == 1.0
    assert abs(_percentile(vals, 0.9) - 3.6) < 1e-9
    assert _percentile([5.0], 0.5) == 5.0


def test_summarize_pass_fractions() -> None:
    sizes = [1_000.0]
    pools = [
        PoolFriction("a", "A/SOL", 1e6, 5e5, 100, True, None, {1_000.0: 0.01}),
        PoolFriction("b", "B/SOL", 1e6, 5e5, 100, True, None, {1_000.0: 0.025}),
        PoolFriction("c", "C/SOL", 1e6, 5e5, 100, True, None, {1_000.0: 0.04}),
        PoolFriction("d", "D/SOL", 1e6, 5e5, 100, True, None, {1_000.0: 0.06}),
    ]
    s = summarize_frictions(pools, sizes)[0]
    assert s.n_pools == 4
    assert s.frac_under_3pct == 0.5  # 0.01, 0.025
    assert s.frac_under_5pct == 0.75  # 0.01, 0.025, 0.04
    assert s.worst == 0.06
