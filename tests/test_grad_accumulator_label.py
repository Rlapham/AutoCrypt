"""Tests for the G1 accumulator success relabel (survive-AND-appreciate, days-horizon).

These pin the label's load-bearing properties, which distinguish it from Iteration-1's
fast-pump label:
- success requires BOTH appreciation AND survival (a moon-then-rug is a FAILURE);
- the outcome resolves at the HORIZON, not at first target-crossing (no early resolution);
- only in-window observations count, and "alive at horizon" needs a late observation;
- no look-ahead: resolution_knowable = entry_knowable + window.
"""

from __future__ import annotations

from autocrypt.grad.accumulator_label import (
    DAY_S,
    AccumulatorLabel,
    PricePoint,
    label_accumulator_entry,
)


def _path(entry_t: float, points: list[tuple[float, float]]) -> list[PricePoint]:
    """points = [(days_after_entry, price)] → forward PricePoints (knowable = event+2s)."""
    return [
        PricePoint(event_time=entry_t + d * DAY_S, knowable_at=entry_t + d * DAY_S + 2.0, price=p)
        for d, p in points
    ]


CFG = AccumulatorLabel(n_days=7.0, appreciate_pct=0.5, survival_floor=0.2)


def test_survive_and_appreciate_is_success():
    entry_t, entry_k = 1000.0, 1002.0
    # rises to +60% by day 3 and is still trading (last obs day 6.9, within the 0.2 tail)
    fwd = _path(entry_t, [(1, 1.2), (3, 1.6), (6.9, 1.5)])
    out = label_accumulator_entry(1.0, entry_t, entry_k, fwd, CFG)
    assert out.success is True
    assert out.appreciated and not out.rugged and out.alive_at_horizon
    # resolves at the HORIZON, not at the day-3 crossing
    assert out.resolution_knowable == entry_k + 7.0 * DAY_S


def test_moon_then_rug_is_failure():
    entry_t, entry_k = 0.0, 2.0
    # +100% on day 1 (appreciates) then collapses to -90% by day 4 (below 0.2 floor) = rug
    fwd = _path(entry_t, [(1, 2.0), (4, 0.1), (6.9, 0.05)])
    out = label_accumulator_entry(1.0, entry_t, entry_k, fwd, CFG)
    assert out.appreciated is True
    assert out.rugged is True
    assert out.success is False  # the survival gate kills the fast-pump-then-dump


def test_appreciates_but_dies_before_horizon_fails_alive_gate():
    entry_t, entry_k = 0.0, 2.0
    # appreciates and never breaches the floor, but stops trading after day 2 (no late obs)
    fwd = _path(entry_t, [(0.5, 1.4), (2.0, 1.7)])
    out = label_accumulator_entry(1.0, entry_t, entry_k, fwd, CFG)
    assert out.appreciated is True
    assert out.rugged is False
    assert out.alive_at_horizon is False  # nothing in the final 20% of the 7-day window
    assert out.success is False


def test_never_appreciates_is_failure():
    entry_t, entry_k = 0.0, 2.0
    fwd = _path(entry_t, [(1, 1.1), (3, 1.2), (6.9, 1.05)])  # peaks +20%, target is +50%
    out = label_accumulator_entry(1.0, entry_t, entry_k, fwd, CFG)
    assert out.appreciated is False
    assert out.success is False
    assert abs(out.peak_return - 0.2) < 1e-9


def test_observation_past_horizon_is_ignored():
    entry_t, entry_k = 0.0, 2.0
    # the +50% only happens on day 9 — OUTSIDE the 7-day window → not counted
    fwd = _path(entry_t, [(1, 1.1), (6.9, 1.1), (9, 2.0)])
    out = label_accumulator_entry(1.0, entry_t, entry_k, fwd, CFG)
    assert out.appreciated is False
    assert out.success is False


def test_no_lookahead_resolution_time():
    entry_t, entry_k = 500.0, 503.0
    out = label_accumulator_entry(1.0, entry_t, entry_k, [], CFG)
    assert out.resolution_knowable == entry_k + CFG.window_s
    assert out.success is False  # empty path: nothing appreciates


def test_disabling_alive_gate_allows_success_without_late_obs():
    cfg = AccumulatorLabel(n_days=7.0, appreciate_pct=0.5, survival_floor=0.2,
                           require_alive_at_horizon=False)
    entry_t, entry_k = 0.0, 2.0
    fwd = _path(entry_t, [(0.5, 1.4), (2.0, 1.7)])  # appreciates, no late obs
    out = label_accumulator_entry(1.0, entry_t, entry_k, fwd, cfg)
    assert out.success is True  # alive gate off → appreciation + no rug is enough
