"""G1 — the "accumulator" success relabel (days-horizon, survive-AND-appreciate).

Iteration-1 / Track-M labelled a wallet entry a *success* if price reached
``entry*(1+pct)`` within a few hundred SECONDS (a fast pump). That label surfaced the
pump *orchestrators* — copying them is exit liquidity (Law 2). Track G's thesis is
different: enter a *graduated* token and ride a multi-DAY accumulator arc. So the success
definition is relabelled:

    a wallet's entry SUCCEEDS iff, within ``n_days`` of entry, the token both
      (1) APPRECIATES — price reaches ``entry_price * (1 + appreciate_pct)``, and
      (2) SURVIVES — it has not rugged: it is still trading at the horizon and never
          collapsed below ``entry_price * survival_floor`` during the window.

Condition (2) is the new, load-bearing ingredient. A fast pump that then rugs to zero is a
*failure* under this label even if it briefly mooned — which is exactly the orchestrator
trade we want to NOT learn from. Requiring survival-to-horizon is what makes the surfaced
cohort *followable* (early accumulators / discretionary holders) rather than the
pump-and-dump apparatus.

NO-LOOK-AHEAD / POINT-IN-TIME. This is a hold-to-horizon label: you only know whether a
token *survived and appreciated over n_days* once n_days have elapsed. So the outcome
becomes knowable at ``entry_knowable_at + n_days`` — NOT at the moment price first crosses
the target (that early-resolution shortcut is correct for a fast-pump label, wrong here:
a token can cross the target on day 1 and rug on day 3). Downstream wallet scoring may use
a trial only once it is resolved at ``knowable <= T``, identical to the existing
``WalletScoreBook`` gate; this module just supplies the relabelled outcome + resolution
time so that book can be rebuilt on the graduated cohort without any look-ahead.

This module is the LABEL only — pure, deterministic, unit-tested. Wiring it onto a full
wallet book is a one-liner over the existing ``attribution`` machinery, deferred until the
forward collector has accrued post-graduation arcs (the G0 census found 0/176 coverage
before the AMM-reserve collector fix; the label has nothing to score until that ripens).
"""

from __future__ import annotations

from dataclasses import dataclass

DAY_S = 86_400.0


@dataclass(slots=True)
class AccumulatorLabel:
    """Knobs for the days-horizon survive-and-appreciate success definition."""

    n_days: float = 7.0  # hold/observation horizon in days
    appreciate_pct: float = 0.5  # success needs price to reach entry*(1+this) (+50% default)
    survival_floor: float = 0.2  # rug if price ever falls below entry*this (-80% = dead)
    require_alive_at_horizon: bool = True  # must still be trading near the horizon end

    @property
    def window_s(self) -> float:
        return self.n_days * DAY_S


@dataclass(slots=True)
class PricePoint:
    """One post-entry observation: when it became true, when knowable, and the price."""

    event_time: float  # valid time (epoch seconds) — on-chain order
    knowable_at: float  # decision gate (epoch seconds)
    price: float


@dataclass(slots=True)
class LabelOutcome:
    """The resolved accumulator outcome for one entry, point-in-time."""

    success: bool
    resolution_knowable: float  # earliest wall-clock the outcome could be known
    appreciated: bool  # reached the target at some point in the window
    rugged: bool  # fell below the survival floor within the window
    alive_at_horizon: bool  # had an observation in the back of the window
    peak_return: float  # max (price/entry - 1) over the window (diagnostic)


# A token counts as "still alive at the horizon" if it has at least one observation in the
# final slice of the window; this fraction sets how wide that slice is.
_HORIZON_TAIL_FRAC = 0.2


def label_accumulator_entry(
    entry_price: float,
    entry_event_time: float,
    entry_knowable_at: float,
    forward: list[PricePoint],
    cfg: AccumulatorLabel,
) -> LabelOutcome:
    """Resolve one wallet entry under the accumulator (survive-AND-appreciate) label.

    `forward` is the price path AFTER the entry in event-time ascending order. The outcome
    resolves at the horizon (``entry_knowable_at + window_s``) — a hold-to-horizon bet —
    because survival is only known once the window has fully elapsed. `appreciated` can be
    reached early, but a later rug still flips the entry to a failure, so we scan the whole
    window. Only observations with ``entry_event_time < event_time <= entry_event_time +
    window_s`` count; "alive at horizon" means at least one such observation lands in the
    final ``_HORIZON_TAIL_FRAC`` of the window (the token is still trading near the end).
    """
    target = entry_price * (1.0 + cfg.appreciate_pct)
    floor = entry_price * cfg.survival_floor
    resolution = entry_knowable_at + cfg.window_s
    if entry_price <= 0:
        return LabelOutcome(False, resolution, False, False, False, 0.0)

    window_end_event = entry_event_time + cfg.window_s
    tail_start_event = entry_event_time + cfg.window_s * (1.0 - _HORIZON_TAIL_FRAC)
    appreciated = rugged = alive_at_horizon = False
    peak_return = 0.0
    for p in forward:
        if p.event_time <= entry_event_time:
            continue  # defensive: not strictly forward of the entry
        if p.event_time > window_end_event:
            break  # past the horizon (forward is event-time ascending)
        if p.price <= 0:
            continue
        r = p.price / entry_price - 1.0
        if r > peak_return:
            peak_return = r
        if p.price >= target:
            appreciated = True
        if p.price <= floor:
            rugged = True
        if p.event_time >= tail_start_event:
            alive_at_horizon = True

    alive_ok = alive_at_horizon or not cfg.require_alive_at_horizon
    success = appreciated and (not rugged) and alive_ok
    return LabelOutcome(
        success=success,
        resolution_knowable=resolution,
        appreciated=appreciated,
        rugged=rugged,
        alive_at_horizon=alive_at_horizon,
        peak_return=peak_return,
    )
