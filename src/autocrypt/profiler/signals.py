"""Candidate pre-run-up signals, expressed as DERIVATIVES (Project_spec §2).

Levels are lagging and already arbitraged; the thesis is that the *rate of change* and
*acceleration* of buy pressure / unique-buyer growth / trade rate lead a run-up. We
compute a transparent composite over a lookback window split into an OLDER and a RECENT
half, so every component is a derivative (recent vs older), not a level.

No look-ahead: the caller passes only swaps with `knowable_at <= T`, and we window by
`knowable_at` (what we could have known), never `event_time`.
"""

from __future__ import annotations

from dataclasses import dataclass

from autocrypt.profiler.dataset import SwapRow


@dataclass(slots=True)
class SignalConfig:
    lookback_s: float = 60.0  # total window; split into two halves
    min_trades_per_half: int = 3  # below this the signal is undefined (won't fire)
    # composite weights (transparent, rules-based; ML is a later phase)
    w_buy_pressure_accel: float = 1.0
    w_unique_buyer_growth: float = 1.0
    w_trade_rate_growth: float = 1.0


@dataclass(slots=True)
class SignalSnapshot:
    """All signal components at one decision time (None ⇒ undefined, cannot fire)."""

    defined: bool
    score: float  # composite (the thing profiler thresholds by default)
    buy_pressure_recent: float
    buy_pressure_accel: float  # recent buy-pressure minus older
    unique_buyer_growth: float  # (recent uniques - older) / older
    trade_rate_growth: float  # (recent count - older) / older
    n_recent: int
    n_older: int


_UNDEFINED = SignalSnapshot(
    defined=False,
    score=float("-inf"),
    buy_pressure_recent=0.0,
    buy_pressure_accel=0.0,
    unique_buyer_growth=0.0,
    trade_rate_growth=0.0,
    n_recent=0,
    n_older=0,
)


def _buy_pressure(swaps: list[SwapRow]) -> float:
    """Net buy fraction in [-1, 1]: (buy_usd - sell_usd) / total_usd."""
    buy = sum(s.amount_usd for s in swaps if s.side == "buy")
    sell = sum(s.amount_usd for s in swaps if s.side == "sell")
    tot = buy + sell
    return (buy - sell) / tot if tot > 0 else 0.0


def compute_signal(
    visible_swaps: list[SwapRow], now_ts: float, cfg: SignalConfig
) -> SignalSnapshot:
    """Compute the composite derivative signal at decision time `now_ts`.

    `visible_swaps` MUST already be gated to `knowable_at <= now_ts`.
    """
    half = cfg.lookback_s / 2.0
    older_start = now_ts - cfg.lookback_s
    mid = now_ts - half

    older = [s for s in visible_swaps if older_start <= s.knowable_at < mid]
    recent = [s for s in visible_swaps if mid <= s.knowable_at <= now_ts]

    if len(older) < cfg.min_trades_per_half or len(recent) < cfg.min_trades_per_half:
        return _UNDEFINED

    bp_recent = _buy_pressure(recent)
    bp_older = _buy_pressure(older)
    bp_accel = bp_recent - bp_older

    uniq_recent = len({s.signer for s in recent if s.signer})
    uniq_older = len({s.signer for s in older if s.signer})
    ubg = (uniq_recent - uniq_older) / uniq_older if uniq_older > 0 else 0.0

    trg = (len(recent) - len(older)) / len(older)

    score = (
        cfg.w_buy_pressure_accel * bp_accel
        + cfg.w_unique_buyer_growth * ubg
        + cfg.w_trade_rate_growth * trg
    )
    return SignalSnapshot(
        defined=True,
        score=score,
        buy_pressure_recent=bp_recent,
        buy_pressure_accel=bp_accel,
        unique_buyer_growth=ubg,
        trade_rate_growth=trg,
        n_recent=len(recent),
        n_older=len(older),
    )
