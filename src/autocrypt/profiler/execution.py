"""Realistic execution cost model: fees + own price impact on BOTH legs.

Marked ROI != realized ROI in thin liquidity (Project_spec §4.3). A buy moves a thin
market, and the exit moves it again — usually harder, because we're dumping into a pool
that may be shallower than when we entered. We model this with a constant-product (xy=k)
AMM so impact scales with size-relative-to-depth, and we charge:

  * a swap fee on each leg (input-side, e.g. pump.fun ~1%),
  * a fixed cost per leg (priority fee + Jito/MEV-protect tip),
  * the curve slippage itself (this IS own price impact).

All math is in QUOTE (SOL) units, so the net return is unit-free and independent of any
USD conversion. The profiler converts a USD position size to quote before calling in.

Entry (buy size_q quote into reserve Q0, mid price p0 ⇒ base reserve B0 = Q0/p0):
    dq_eff = size_q * (1 - fee)
    db     = B0 * dq_eff / (Q0 + dq_eff)          # base acquired
Exit after horizon (sell db base into reserve Q1, mid p1 ⇒ B1 = Q1/p1):
    y          = db / B1
    dq_out     = Q1 * y/(1+y) * (1 - fee)         # quote returned
    net_return = (dq_out - size_q - fixed_total) / size_q
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class RoundTrip:
    """Outcome of one simulated buy-hold-sell round trip (quote units)."""

    net_return: float  # realized fraction after fees + impact + fixed costs
    marked_return: float  # naive p1/p0 - 1 (what a no-cost backtest would show)
    cost_drag: float  # marked_return - net_return (total execution drag)
    entry_impact: float  # buy fill premium vs mid (fraction)
    exit_impact: float  # sell fill discount vs mid (fraction)
    base_acquired: float  # base tokens bought (quote/price units)


@dataclass(slots=True)
class ExecutionModel:
    """Constant-product round-trip cost model.

    fee_bps: swap fee per leg in basis points (100 = 1%, pump.fun-like default).
    fixed_cost_quote: priority fee + MEV-protect tip per leg, in quote (SOL) units.
    """

    fee_bps: float = 100.0
    fixed_cost_quote: float = 0.0005

    @property
    def fee(self) -> float:
        return self.fee_bps / 10_000.0

    def round_trip(
        self,
        size_quote: float,
        p_entry: float,
        q_entry: float,
        p_exit: float,
        q_exit: float,
    ) -> RoundTrip:
        """Simulate buying `size_quote` of quote, holding, then selling it all back.

        p_entry/p_exit: mid prices at entry/exit (any consistent unit — used as p1/p0).
        q_entry/q_exit: effective quote reserve (depth) at entry/exit, same quote unit.
        """
        fee = self.fee
        marked = p_exit / p_entry - 1.0

        # Degenerate depth ⇒ cannot fill at any sane price; treat as a total loss of
        # the position (you cannot realistically enter/exit). Conservative, not optimistic.
        if q_entry <= 0 or q_exit <= 0 or size_quote <= 0 or p_entry <= 0 or p_exit <= 0:
            return RoundTrip(
                net_return=-1.0,
                marked_return=marked,
                cost_drag=marked + 1.0,
                entry_impact=0.0,
                exit_impact=0.0,
                base_acquired=0.0,
            )

        b0 = q_entry / p_entry
        dq_eff = size_quote * (1.0 - fee)
        db = b0 * dq_eff / (q_entry + dq_eff)  # base acquired
        eff_buy_price = size_quote / db  # quote per base, incl fee + impact
        entry_impact = eff_buy_price / p_entry - 1.0

        b1 = q_exit / p_exit
        y = db / b1
        dq_out_gross = q_exit * y / (1.0 + y)
        dq_out = dq_out_gross * (1.0 - fee)
        eff_sell_price = dq_out_gross / db  # pre-fee mid-relative for impact reporting
        exit_impact = 1.0 - eff_sell_price / p_exit

        fixed_total = 2.0 * self.fixed_cost_quote
        net = (dq_out - size_quote - fixed_total) / size_quote
        return RoundTrip(
            net_return=net,
            marked_return=marked,
            cost_drag=marked - net,
            entry_impact=entry_impact,
            exit_impact=exit_impact,
            base_acquired=db,
        )
