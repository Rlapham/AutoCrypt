"""Tests for the Phase-3 wallet-attribution model. The load-bearing property is the
no-look-ahead discipline: a wallet's lead-score at T must use ONLY trials whose outcome was
knowable at or before T, and the attribution signal must ignore future swaps. No network."""

from __future__ import annotations

from autocrypt.attribution.signal import AttributionSignalConfig, compute_attribution
from autocrypt.attribution.wallet_book import AttributionConfig, WalletScoreBook
from autocrypt.profiler.dataset import PoolData, SwapRow


def _swap(et: float, side: str, price: float, usd: float, signer: str, lat: float = 2.0) -> SwapRow:
    return SwapRow(
        event_time=et,
        knowable_at=et + lat,
        side=side,
        price_usd=price,
        amount_usd=usd,
        quote_amount=usd,
        signer=signer,
    )


def _runup_pool(addr: str, leader: str, runup: bool) -> PoolData:
    """A pool where `leader` buys first; price then either doubles (runup) or stays flat."""
    swaps = [_swap(0.0, "buy", 1.0, 50.0, leader)]
    for i in range(1, 6):
        price = 1.0 + (0.4 * i if runup else 0.0)  # reaches 2.0 (=+100%) if runup
        swaps.append(_swap(float(i * 10), "buy", price, 30.0, f"other{i}"))
    return PoolData(addr, "BASE", "QUOTE", created_at=0.0, swaps=swaps)


# ── run-up labelling + point-in-time wallet scoring ─────────────────────────────
def test_leader_scored_above_base_after_runups() -> None:
    cfg = AttributionConfig(runup_pct=1.0, runup_window_s=300.0, min_attempts=2, prior_strength=2.0)
    pools = [_runup_pool(f"P{i}", "alice", runup=True) for i in range(4)]
    pools += [_runup_pool(f"Q{i}", "bob", runup=False) for i in range(4)]
    book = WalletScoreBook.build(pools, cfg)

    far_future = 1e9
    alice = book.score_at("alice", far_future)
    bob = book.score_at("bob", far_future)
    assert alice.attempts == 4 and alice.leads == 4
    assert bob.attempts == 4 and bob.leads == 0
    assert alice.lift > 0 > bob.lift  # leader beats base rate; non-leader trails it


def test_score_is_point_in_time() -> None:
    """A wallet's score at T must not see trials resolved after T (no look-ahead)."""
    cfg = AttributionConfig(runup_pct=1.0, runup_window_s=300.0, min_attempts=1, prior_strength=1.0)
    # Two successful run-up pools, far apart in time.
    p1 = _runup_pool("P1", "alice", runup=True)  # entry et=0 → resolves when price hits 2.0
    p2 = PoolData("P2", "BASE", "QUOTE", created_at=10_000.0, swaps=[
        _swap(10_000.0, "buy", 1.0, 50.0, "alice"),
        _swap(10_050.0, "buy", 2.0, 30.0, "z"),  # +100% → resolves ~10_052
    ])
    book = WalletScoreBook.build([p1, p2], cfg)

    # Before the 2nd pool's entry even happens, alice has only the 1st trial resolved.
    early = book.score_at("alice", 5_000.0)
    assert early.attempts == 1
    late = book.score_at("alice", 20_000.0)
    assert late.attempts == 2


def test_failure_only_knowable_after_window() -> None:
    """A non-run-up trial must NOT count as resolved until the run-up window has elapsed."""
    cfg = AttributionConfig(runup_pct=1.0, runup_window_s=300.0, min_attempts=1, prior_strength=1.0)
    pool = _runup_pool("P", "carol", runup=False)  # carol enters at et=0, kt=2; never runs up
    book = WalletScoreBook.build([pool], cfg)
    # Just after entry: outcome not yet knowable (window not elapsed) → 0 attempts.
    assert book.score_at("carol", 100.0).attempts == 0
    # After entry_knowable(2) + window(300): the failure is resolved → 1 attempt, 0 leads.
    resolved = book.score_at("carol", 2.0 + 300.0 + 1.0)
    assert resolved.attempts == 1 and resolved.leads == 0


def test_low_evidence_wallet_shrinks_to_base() -> None:
    """One lucky trial should NOT produce a huge lift — shrinkage toward the base rate."""
    cfg = AttributionConfig(runup_pct=1.0, runup_window_s=300.0, min_attempts=1, prior_strength=50.0)
    pools = [_runup_pool("P", "lucky", runup=True)]
    pools += [_runup_pool(f"bg{i}", f"bg{i}", runup=(i % 10 == 0)) for i in range(40)]
    book = WalletScoreBook.build(pools, cfg)
    lucky = book.score_at("lucky", 1e9)
    assert lucky.attempts == 1 and lucky.leads == 1
    assert lucky.posterior < 0.5  # strong prior keeps a 1/1 wallet near the population rate


# ── attribution decision signal ────────────────────────────────────────────────
def test_attribution_signal_ignores_future_and_unscored() -> None:
    cfg = AttributionConfig(runup_pct=1.0, runup_window_s=300.0, min_attempts=2, prior_strength=2.0)
    # Build a book where 'alice' is a proven leader, 'noob' has no track record.
    hist = [_runup_pool(f"H{i}", "alice", runup=True) for i in range(4)]
    book = WalletScoreBook.build(hist, cfg)
    scfg = AttributionSignalConfig(min_attempts=2, attribution=cfg)

    now = 1e9  # well after all history resolved, so alice is fully scored
    visible = [
        _swap(now - 30, "buy", 1.0, 100.0, "alice"),  # scored leader buying now
        _swap(now - 20, "buy", 1.0, 100.0, "noob"),  # no track record → ignored in weight
    ]
    res = compute_attribution(visible, now, book, scfg)
    assert res.defined and res.n_scored_buyers == 1
    assert res.score > 0  # weighted lift driven by the proven leader

    # A FUTURE buy must not change the signal (knowable_at > now).
    future = [*visible, _swap(now + 100, "buy", 1.0, 1e6, "alice")]
    res2 = compute_attribution(future, now, book, scfg)
    assert res2.score == res.score


def test_attribution_undefined_without_scored_buyers() -> None:
    cfg = AttributionConfig(min_attempts=2)
    book = WalletScoreBook.build([], cfg)  # empty book → nobody is scored
    scfg = AttributionSignalConfig(min_attempts=2, attribution=cfg)
    visible = [_swap(100.0, "buy", 1.0, 50.0, "whoever")]
    assert not compute_attribution(visible, 102.0, book, scfg).defined
