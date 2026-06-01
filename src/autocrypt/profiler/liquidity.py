"""Point-in-time effective-depth estimation from observed price impact.

We have NO direct liquidity data (pool_created.init_liquidity_usd is null, and
LiquidityChange/HolderSnapshot are unpopulated — see phase-1 synthesis). So we infer
the pool's *effective* quote-reserve depth from the price impact that real trades
already revealed, under a constant-product (xy=k) mid-price model:

    a buy of quote size `dq` moves the mid price by  p'/p = (1 + dq/Q)^2
    ⇒  Q ≈ dq / (sqrt(p'/p) - 1)            (and symmetrically for sells)

Each trade is one noisy observation of Q; we keep a rolling median over a recent
window for robustness. This is an ESTIMATE, not ground truth — depth is the single
biggest modelling assumption behind own-price-impact, so the profiler also sweeps a
depth multiplier and reports sensitivity (honesty over optimism: if the verdict hinges
on a fragile depth guess, that must be visible).

Strictly point-in-time: callers feed only trades with `knowable_at <= T`.
"""

from __future__ import annotations

import math
from collections import deque


class LiquidityEstimator:
    """Rolling constant-product depth estimate (effective quote reserve), per pool.

    Feed trades in time order via `observe()`; read the current estimate via
    `quote_reserve()`. Units follow the `quote_amount` you feed (SOL or USDC).
    """

    def __init__(
        self,
        window: int = 40,
        min_ratio_move: float = 1e-3,
        floor: float = 1e-6,
    ) -> None:
        self.window = window
        # Ignore moves smaller than this (price noise / same-block prints) — they make
        # the inversion explode toward +inf.
        self.min_ratio_move = min_ratio_move
        self.floor = floor
        self._implied: deque[float] = deque(maxlen=window)
        self._prev_price: float | None = None

    def observe(self, price_usd: float, quote_amount: float, side: str) -> None:
        """Update the estimate with one trade (its price + quote size + side)."""
        prev = self._prev_price
        self._prev_price = price_usd
        if prev is None or prev <= 0 or price_usd <= 0 or quote_amount <= 0:
            return
        ratio = price_usd / prev
        if side == "buy":
            # price should rise; need ratio > 1 by a meaningful margin
            if ratio <= 1.0 + self.min_ratio_move:
                return
            denom = math.sqrt(ratio) - 1.0
        elif side == "sell":
            # price should fall; need ratio < 1 by a meaningful margin
            if ratio >= 1.0 - self.min_ratio_move:
                return
            denom = (1.0 / math.sqrt(ratio)) - 1.0
        else:
            return
        if denom <= 0:
            return
        implied_q = quote_amount / denom
        if implied_q > self.floor and math.isfinite(implied_q):
            self._implied.append(implied_q)

    def quote_reserve(self) -> float | None:
        """Current robust depth estimate (median of recent implied reserves)."""
        if not self._implied:
            return None
        vals = sorted(self._implied)
        n = len(vals)
        mid = n // 2
        return vals[mid] if n % 2 else 0.5 * (vals[mid - 1] + vals[mid])

    @property
    def n_observations(self) -> int:
        return len(self._implied)
