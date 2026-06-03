"""The attribution decision signal: 'is demonstrated smart money buying THIS pool NOW?'

At decision time T we look at the wallets that bought the pool in the recent window
(`knowable_at <= T` only) and weight each by its demonstrated lead-score (from the
`WalletScoreBook`, also gated to T). The composite is the buy-USD-weighted mean *lift* of
the scored recent buyers: >0 means the wallets currently accumulating have historically
preceded run-ups more than the crowd. This is the entry signal the wallet-attribution
thesis predicts; the profiler then prices the actual tradable outcome with full costs.

Undefined (will not fire) when no recent buyer has enough resolved track record yet — early
in a dataset that is most decision times, which is an honest limit, not a bug.
"""

from __future__ import annotations

from dataclasses import dataclass

from autocrypt.attribution.wallet_book import AttributionConfig, WalletScoreBook
from autocrypt.profiler.dataset import SwapRow


@dataclass(slots=True)
class AttributionSignalConfig:
    attr_window_s: float = 60.0  # recent-buyer window feeding the signal
    min_attempts: int = 3  # a recent buyer must have >= this resolved trials to count
    attribution: AttributionConfig = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.attribution is None:
            self.attribution = AttributionConfig()


@dataclass(slots=True)
class AttributionResult:
    defined: bool
    score: float  # buy-USD-weighted mean lift of scored recent buyers
    smart_share: float  # share of recent buy USD from above-base-rate wallets
    n_scored_buyers: int


_UNDEFINED = AttributionResult(defined=False, score=0.0, smart_share=0.0, n_scored_buyers=0)


def compute_attribution(
    visible_swaps: list[SwapRow],
    now_ts: float,
    book: WalletScoreBook,
    cfg: AttributionSignalConfig,
) -> AttributionResult:
    """Attribution signal at `now_ts`. `visible_swaps` MUST be gated to knowable_at <= T."""
    start = now_ts - cfg.attr_window_s
    # visible_swaps is sorted by knowable_at, so the recent window is a tail slice: scan
    # backward and stop at the first swap older than the window (O(window), not O(history)).
    buy_usd: dict[str, float] = {}
    for s in reversed(visible_swaps):
        if s.knowable_at < start:
            break
        if s.knowable_at <= now_ts and s.side == "buy" and s.signer and s.amount_usd > 0:
            buy_usd[s.signer] = buy_usd.get(s.signer, 0.0) + s.amount_usd
    total_buy_usd = sum(buy_usd.values())
    if total_buy_usd <= 0:
        return _UNDEFINED

    weighted_lift = 0.0
    scored_weight = 0.0
    smart_usd = 0.0
    n_scored = 0
    for wallet, usd in buy_usd.items():
        sc = book.score_at(wallet, now_ts)
        if sc.attempts < cfg.min_attempts:
            continue
        n_scored += 1
        weighted_lift += usd * sc.lift
        scored_weight += usd
        if sc.lift > 0:
            smart_usd += usd

    if n_scored == 0 or scored_weight <= 0:
        return _UNDEFINED
    return AttributionResult(
        defined=True,
        score=weighted_lift / scored_weight,
        smart_share=smart_usd / total_buy_usd,
        n_scored_buyers=n_scored,
    )
