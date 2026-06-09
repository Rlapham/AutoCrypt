"""Tests for the G1 accumulator wallet-attribution book over the graduated cohort (no network).

Load-bearing properties pinned here:
- a trial is one wallet's FIRST post-graduation buy, labelled survive-AND-appreciate;
- SURVIVORSHIP: a graduation that moons-then-rugs still produces a trial (a FAILURE), it is
  not dropped — rugged graduations are the denominator's failures;
- POST-GRADUATION gate: swaps knowable before the graduation milestone are excluded;
- NO LOOK-AHEAD / DATA-GATING: trials resolve at the horizon, the book counts only RESOLVED
  trials, and the cohort reports "not ripened" until a wallet has enough resolved trials;
- the refactored `WalletScoreBook.from_attempts` reproduces `build`'s point-in-time scoring.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from autocrypt.attribution.wallet_book import Attempt, AttributionConfig, WalletScoreBook
from autocrypt.grad.accumulator_label import DAY_S, AccumulatorLabel
from autocrypt.grad.wallet_book import (
    GradCohortPool,
    accumulator_attempts,
    build_accumulator_book,
    load_graduated_cohort,
)
from autocrypt.profiler.dataset import SwapRow
from autocrypt.schema import PoolCreated, Source, Swap, TradeSide, knowable_at_for_tx
from autocrypt.storage.store import EventStore

SOL = "So11111111111111111111111111111111111111112"
T0 = datetime(2026, 6, 3, 12, 0, 0, tzinfo=UTC)
LAT = timedelta(seconds=2)
CFG = AccumulatorLabel(n_days=7.0, appreciate_pct=0.5, survival_floor=0.2)


def _sr(t: float, side: str, price: float, signer: str) -> SwapRow:
    return SwapRow(
        event_time=t, knowable_at=t + 2.0, side=side,
        price_usd=price, amount_usd=50.0, quote_amount=50.0, signer=signer,
    )


def _cohort_pool(addr: str, leader: str, path: list[tuple[float, float]]) -> GradCohortPool:
    """A graduated pool where `leader` buys first at t=10s; `path` = [(days, price)] forward."""
    grad_k = 0.0
    swaps = [_sr(10.0, "buy", 1.0, leader)]
    swaps += [_sr(10.0 + d * DAY_S, "buy", p, f"other_{i}") for i, (d, p) in enumerate(path)]
    return GradCohortPool(addr, "MINT", "pumpfun->pumpswap", grad_knowable_at=grad_k, swaps=swaps)


# ── accumulator_attempts: success / failure / survivorship ──────────────────────
def test_survive_and_appreciate_is_a_success_trial() -> None:
    pool = _cohort_pool("P", "alice", [(1, 1.2), (3, 1.6), (6.9, 1.5)])  # +60%, alive late
    atts = accumulator_attempts(pool, CFG)
    by = {a.wallet: a for a in atts}
    assert by["alice"].success is True


def test_moon_then_rug_is_a_failure_trial_not_dropped() -> None:
    # Survivorship: carol's graduation pumps +100% then collapses below the floor → FAILURE,
    # but the trial is RETAINED (it is a failure in the denominator, never silently dropped).
    pool = _cohort_pool("P", "carol", [(1, 2.0), (4, 0.1), (6.9, 0.05)])
    atts = accumulator_attempts(pool, CFG)
    by = {a.wallet: a for a in atts}
    assert "carol" in by
    assert by["carol"].success is False


def test_only_first_buy_per_wallet_becomes_a_trial() -> None:
    swaps = [
        _sr(10.0, "buy", 1.0, "alice"),
        _sr(20.0, "buy", 1.1, "alice"),  # second buy — must NOT create a second trial
        _sr(30.0, "sell", 1.2, "alice"),
    ]
    pool = GradCohortPool("P", "MINT", "pumpfun->pumpswap", grad_knowable_at=0.0, swaps=swaps)
    atts = accumulator_attempts(pool, CFG)
    assert sum(1 for a in atts if a.wallet == "alice") == 1


def test_trial_resolves_at_horizon_no_lookahead() -> None:
    pool = _cohort_pool("P", "alice", [(3, 1.6)])
    atts = accumulator_attempts(pool, CFG)
    alice = next(a for a in atts if a.wallet == "alice")
    # entry_knowable = 12.0 (event 10 + 2 latency); resolution = entry_knowable + 7 days
    assert alice.resolution_knowable == 12.0 + 7.0 * DAY_S


# ── from_attempts equivalence (refactor safety) ─────────────────────────────────
def test_from_attempts_matches_manual_scoring() -> None:
    cfg = AttributionConfig(min_attempts=1, prior_strength=2.0, prior_base_rate=0.1)
    attempts = [
        Attempt("alice", 100.0, True),
        Attempt("alice", 200.0, True),
        Attempt("bob", 150.0, False),
    ]
    book = WalletScoreBook.from_attempts(attempts, cfg)
    assert book.n_attempts == 3 and book.n_wallets == 2
    far = 1e9
    assert book.score_at("alice", far).leads == 2
    assert book.score_at("bob", far).leads == 0
    assert book.score_at("alice", far).lift > book.score_at("bob", far).lift


# ── store-level: post-grad gate, ripening, survivorship end-to-end ──────────────
def _pc(mint: str, dex: str, pool: str, minute: float) -> PoolCreated:
    t = T0 + timedelta(minutes=minute)
    return PoolCreated(
        source=Source.synthetic, event_time=t, knowable_at=knowable_at_for_tx(t, LAT),
        pool_address=pool, dex=dex, base_mint=mint, quote_mint=SOL,
    )


def _swap(pool: str, mint: str, minute: float, sig: str, price: float, side: str = "buy") -> Swap:
    t = T0 + timedelta(minutes=minute)
    return Swap(
        source=Source.synthetic, event_time=t, knowable_at=knowable_at_for_tx(t, LAT),
        pool_address=pool, base_mint=mint, quote_mint=SOL, signer=sig,
        side=TradeSide.buy if side == "buy" else TradeSide.sell,
        base_amount=Decimal("1"), quote_amount=Decimal("50"),
        price_usd=Decimal(str(price)), amount_usd=Decimal("50"),
        tx_signature=f"{pool}-{sig}-{minute}", instruction_index=0,
    )


def test_post_graduation_gate_excludes_earlier_swaps(tmp_path) -> None:
    # BC pool at min 0, AMM (graduation) pool at min 10 (lag 600s > 120s → genuine).
    events = [
        _pc("MINT", "pumpfun", "BC", 0.0),
        _pc("MINT", "pumpswap", "AMM", 10.0),
        # A swap on the AMM pool a touch BEFORE the graduation knowable → must be excluded.
        _swap("AMM", "MINT", 9.0, "early", 1.0),
        _swap("AMM", "MINT", 11.0, "alice", 1.0),  # post-grad first buy
        _swap("AMM", "MINT", 20.0, "bob", 1.2),
    ]
    store = EventStore(tmp_path / "g.duckdb")
    store.write_events(events)
    cohort = load_graduated_cohort(store)
    store.close()
    assert len(cohort) == 1
    signers = {s.signer for s in cohort[0].swaps}
    assert "early" not in signers and "alice" in signers


def test_build_reports_not_ripened_when_horizon_not_elapsed(tmp_path) -> None:
    # Only minutes of data, 7-day horizon → nothing resolves → not ripened, nobody scorable.
    events = [
        _pc("MINT", "pumpfun", "BC", 0.0),
        _pc("MINT", "pumpswap", "AMM", 10.0),
        _swap("AMM", "MINT", 11.0, "alice", 1.0),
        _swap("AMM", "MINT", 20.0, "alice2", 1.8),
    ]
    store = EventStore(tmp_path / "g.duckdb")
    store.write_events(events)
    book, stats, attempts = build_accumulator_book(store)
    store.close()
    assert stats.n_cohort_pools == 1
    assert stats.n_attempts >= 1
    assert stats.n_resolved == 0
    assert stats.n_scorable_wallets == 0
    assert stats.ripened is False


def test_build_ripens_and_scores_after_horizon(tmp_path) -> None:
    # Short horizon + observations spanning past it, so a wallet's trial RESOLVES and scores.
    day = 1440.0  # minutes per day
    events = [
        _pc("MINT", "pumpfun", "BC", 0.0),
        _pc("MINT", "pumpswap", "AMM", 10.0),
        _swap("AMM", "MINT", 11.0, "alice", 1.0),  # entry
        _swap("AMM", "MINT", 11.0 + 0.5 * day, "x", 1.8),  # +80% within 1 day → appreciates
        _swap("AMM", "MINT", 11.0 + 0.95 * day, "y", 1.7),  # alive in the horizon tail
        _swap("AMM", "MINT", 11.0 + 2.0 * day, "z", 1.6),  # advances now_ts well past horizon
    ]
    store = EventStore(tmp_path / "g.duckdb")
    store.write_events(events)
    book, stats, attempts = build_accumulator_book(
        store,
        label_cfg=AccumulatorLabel(n_days=1.0, appreciate_pct=0.5, survival_floor=0.2),
        score_cfg=AttributionConfig(min_attempts=1, prior_strength=1.0),
    )
    store.close()
    assert stats.n_resolved >= 1
    assert stats.ripened is True
    alice = book.score_at("alice", stats.now_ts)
    assert alice.attempts >= 1 and alice.leads >= 1
