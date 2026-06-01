"""Phase 2 — the signal-frequency & expectancy profiler (THE KILL-GATE).

Answers, with evidence: does a profitable operating point exist for an on-chain
pre-run-up signal on low-cap Solana, after realistic slippage / fees / own-price-impact,
on a survivorship-proof, point-in-time dataset?

Discipline (load-bearing — see CLAUDE.md + docs/event-schema.md):
  * No look-ahead. Signals are computed ONLY from swaps with `knowable_at <= T`.
    Outcomes (forward returns) are measured from `event_time > T`, but the *decision*
    at T sees only what was knowable at T.
  * Survivorship-proof. The denominator is every pool created in the window
    (enumerated by creation, outcome-independent) — dead/rugged pools included.
  * Realistic execution. A constant-product cost model charges fees + own price
    impact on BOTH the entry and the (harder) exit leg, with depth estimated
    point-in-time from observed price impact.
  * Honesty over optimism. A null result is a valid outcome; we never tune to
    manufacture a positive.
"""

from autocrypt.profiler.execution import ExecutionModel, RoundTrip
from autocrypt.profiler.liquidity import LiquidityEstimator
from autocrypt.profiler.profiler import (
    Profiler,
    ProfilerConfig,
    ThresholdResult,
    profile_curve,
)
from autocrypt.profiler.signals import SignalConfig, SignalSnapshot, compute_signal

__all__ = [
    "ExecutionModel",
    "LiquidityEstimator",
    "Profiler",
    "ProfilerConfig",
    "RoundTrip",
    "SignalConfig",
    "SignalSnapshot",
    "ThresholdResult",
    "compute_signal",
    "profile_curve",
]
