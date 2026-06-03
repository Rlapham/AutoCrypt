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

from __future__ import annotations

import importlib

# Lazy (PEP 562) re-exports. Eagerly importing `profiler.profiler` here would make merely
# importing a leaf like `profiler.dataset` pull in the whole profiler → attribution chain,
# creating a package-level import cycle (attribution depends on profiler.dataset). Lazy
# attribute access keeps the convenience API (`from autocrypt.profiler import Profiler`)
# while letting leaf modules be imported without triggering the cycle.
_LAZY = {
    "ExecutionModel": "autocrypt.profiler.execution",
    "RoundTrip": "autocrypt.profiler.execution",
    "LiquidityEstimator": "autocrypt.profiler.liquidity",
    "Profiler": "autocrypt.profiler.profiler",
    "ProfilerConfig": "autocrypt.profiler.profiler",
    "ThresholdResult": "autocrypt.profiler.profiler",
    "profile_curve": "autocrypt.profiler.profiler",
    "SignalConfig": "autocrypt.profiler.signals",
    "SignalSnapshot": "autocrypt.profiler.signals",
    "compute_signal": "autocrypt.profiler.signals",
}

__all__ = list(_LAZY)


def __getattr__(name: str) -> object:
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(module), name)
