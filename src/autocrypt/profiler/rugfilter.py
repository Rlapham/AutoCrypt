"""Rug pre-filter — a pre-trade gate (Project_spec §4.4). STUB, honestly labelled.

A proper rug filter needs TokenMeta (mint/freeze authority, LP lock/burn, honeypot) and
HolderSnapshot (concentration) — record types that are DEFINED in the schema but NOT yet
populated by any ingestion path (phase-1 synthesis open question). Until those exist,
this can only apply weak *swap-derived* heuristics, computed strictly point-in-time:

  * single-wallet dominance: one signer is an outsized share of recent buy volume
    (a classic pre-rug / wash-trade tell),
  * price already collapsed: mid price is far below its recent peak (likely already
    rugged — do not buy the falling knife).

It returns a pass/block decision so the profiler can wire it as a gate input and report
how the firing universe changes with the gate on/off. Calibrating real thresholds is
Phase 3 work once TokenMeta/Holder data is flowing.
"""

from __future__ import annotations

from dataclasses import dataclass

from autocrypt.profiler.dataset import SwapRow


@dataclass(slots=True)
class RugFilterConfig:
    lookback_s: float = 120.0
    max_single_wallet_buy_share: float = 0.80  # block if one wallet > this of buy vol
    max_drawdown_from_peak: float = 0.70  # block if price < (1-this) * recent peak
    min_trades: int = 5  # below this, not enough to judge — pass (don't over-block)


@dataclass(slots=True)
class RugVerdict:
    blocked: bool
    reason: str
    single_wallet_buy_share: float
    drawdown_from_peak: float


def rug_check(visible_swaps: list[SwapRow], now_ts: float, cfg: RugFilterConfig) -> RugVerdict:
    """Point-in-time rug gate (swap-derived heuristics only — see module docstring)."""
    window = [s for s in visible_swaps if s.knowable_at >= now_ts - cfg.lookback_s]
    if len(window) < cfg.min_trades:
        return RugVerdict(False, "insufficient-data-pass", 0.0, 0.0)

    buys = [s for s in window if s.side == "buy"]
    buy_total = sum(s.amount_usd for s in buys)
    by_wallet: dict[str, float] = {}
    for s in buys:
        if s.signer:
            by_wallet[s.signer] = by_wallet.get(s.signer, 0.0) + s.amount_usd
    top_share = (max(by_wallet.values()) / buy_total) if buy_total > 0 and by_wallet else 0.0

    peak = max(s.price_usd for s in window)
    last = window[-1].price_usd
    drawdown = (peak - last) / peak if peak > 0 else 0.0

    if top_share > cfg.max_single_wallet_buy_share:
        return RugVerdict(True, "single-wallet-dominance", top_share, drawdown)
    if drawdown > cfg.max_drawdown_from_peak:
        return RugVerdict(True, "price-collapsed", top_share, drawdown)
    return RugVerdict(False, "pass", top_share, drawdown)
