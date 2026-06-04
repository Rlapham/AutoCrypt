"""M3 — the transparent deep-pool signal battery (rules-based, point-in-time).

Four standard, transparent signals (Project_spec §5: "start rules-based … transparent
composite score crossing a threshold"). Each is LONG-ONLY — Track M is a short-*holding*
strategy (buy, hold a few days, sell), never short-selling — and each returns a single
float where **higher = stronger buy**, plus `None` when undefined (not enough history).

Discipline: a signal evaluated at bar index ``i`` may read closes/highs/volumes ``0..i``
ONLY (the decision gate is `knowable_at[i]`). The kill-gate slices the visible history
before calling in, so these functions cannot look ahead even by accident.

  * `ts_momentum`   — trailing L-bar return (time-series momentum / trend-following).
  * `mean_reversion`— negative z-score vs the trailing mean (buy the dip).
  * `breakout`      — close vs the prior L-bar high, with a volume-expansion gate.
  * cross-sectional momentum is computed in the engine (it needs the whole panel on a
    date to rank), but its per-pool RAW feature is just `ts_momentum`.
"""

from __future__ import annotations

import statistics


def ts_momentum(closes: list[float], i: int, lookback: int) -> float | None:
    """Trailing `lookback`-bar simple return ending at bar i. Higher = stronger uptrend."""
    if i < lookback or i >= len(closes):
        return None
    p0 = closes[i - lookback]
    p1 = closes[i]
    if p0 <= 0 or p1 <= 0:
        return None
    return p1 / p0 - 1.0


def mean_reversion(closes: list[float], i: int, lookback: int) -> float | None:
    """Negative z-score of close[i] vs the trailing `lookback` closes (ending at i-1).

    Higher score ⇒ more *oversold* (price far below its recent mean) ⇒ stronger dip-buy.
    Uses the window strictly BEFORE i so the reference mean does not include the bar we
    are scoring. Undefined when the window is flat (no dispersion to normalise by).
    """
    if i < lookback or i >= len(closes):
        return None
    window = closes[i - lookback : i]
    if len(window) < 2:
        return None
    mean = statistics.fmean(window)
    sd = statistics.pstdev(window)
    if sd <= 0 or mean <= 0 or closes[i] <= 0:
        return None
    return -(closes[i] - mean) / sd


def breakout(
    closes: list[float],
    highs: list[float],
    volumes: list[float],
    i: int,
    lookback: int,
    *,
    vol_mult: float = 1.0,
) -> float | None:
    """Close[i] vs the prior `lookback`-bar high, gated on volume expansion.

    Score = close[i] / max(high[i-lookback:i]) - 1, i.e. how far the close pokes above
    the prior range (negative if still inside it — a non-fire after thresholding). The
    breakout only counts if current volume ≥ `vol_mult` x the trailing average volume
    (a classic confirmation: range breaks on rising participation are the tradeable ones);
    otherwise the signal is suppressed to -inf so it never clears a positive threshold.
    """
    if i < lookback or i >= len(closes):
        return None
    prior_high = max(highs[i - lookback : i])
    if prior_high <= 0 or closes[i] <= 0:
        return None
    score = closes[i] / prior_high - 1.0
    # Volume confirmation gate.
    vwin = volumes[i - lookback : i]
    avg_vol = statistics.fmean(vwin) if vwin else 0.0
    if avg_vol > 0 and volumes[i] < vol_mult * avg_vol:
        return float("-inf")  # un-confirmed break: never fires above a positive threshold
    return score
