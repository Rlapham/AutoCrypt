"""Tests for the forward-collector cohort logic — admit/retire/hold. No network.

The collector's value over `poll` is that it HOLDS an admitted pool and tails its
swaps for hours (capturing a run-up), evicting only by age — not by recency. These
tests pin that contract on the pure cohort functions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from autocrypt.ingestion.collect import _admit_candidates, _age_out


def _entry(age_s: float) -> dict:
    return {"ctx": {}, "created_at": datetime.now(UTC) - timedelta(seconds=age_s)}


@dataclass
class _FakePC:
    """Minimal stand-in for PoolCreated for the pure admission test (no network)."""

    pool_address: str
    dex: str
    base_mint: str = "M"
    quote_mint: str = "Q"
    base_decimals: int | None = None
    quote_decimals: int | None = None
    event_time: datetime = datetime(2026, 6, 3, tzinfo=UTC)


def test_age_out_retires_only_old_pools() -> None:
    """Pools younger than max_pool_age stay; older ones retire and free their slot."""
    watch = {"young": _entry(10), "old": _entry(10_000)}
    retired: set[str] = set()
    n = _age_out(watch, retired, max_pool_age_s=3600.0)
    assert n == 1
    assert "young" in watch and "old" not in watch
    assert "old" in retired


def test_retired_pool_not_readmitted() -> None:
    """A pool retired by age must not climb back into the cohort on a later tick.

    (Enumeration checks `addr in retired`; here we assert age-out populates that set
    so the readmission guard has something to check.)
    """
    watch = {"old": _entry(10_000)}
    retired: set[str] = set()
    _age_out(watch, retired, max_pool_age_s=3600.0)
    assert "old" in retired


def test_fresh_cohort_held_not_evicted_by_newer() -> None:
    """Nothing retires while every pool is within the age window — the cohort is held,
    so newer launches cannot evict a still-young pool (the bug the redesign fixed)."""
    watch = {f"p{i}": _entry(60 * i) for i in range(5)}  # all < 1h old
    retired: set[str] = set()
    n = _age_out(watch, retired, max_pool_age_s=3600.0)
    assert n == 0
    assert len(watch) == 5


def test_admission_reserves_slots_for_amm_pools() -> None:
    """Bonding-curve pools must NOT fill the whole watchlist — `amm_reserved` slots stay
    open so a later graduation (AMM pool) can be tailed. This is the Track-G fix: without
    it, the ~99% bonding-curve creation stream starves post-graduation collection."""
    watch: dict[str, dict] = {}
    bc = [_FakePC(f"bc{i}", "pumpfun") for i in range(20)]
    admitted = _admit_candidates(watch, bc, watch_max=10, amm_reserved=4)
    # only watch_max - amm_reserved = 6 bonding-curve pools admitted; 4 slots held for AMM
    assert admitted == 6
    assert len(watch) == 6
    assert all(e["phase"] == "BC" for e in watch.values())


def test_admission_prioritizes_amm_then_fills_rest() -> None:
    """AMM (graduation-target) pools are admitted first and may use full capacity; the
    reserve only caps non-AMM, so a mixed tick tails every AMM pool plus some BC pools."""
    watch: dict[str, dict] = {}
    cands = [_FakePC("amm0", "pumpswap"), _FakePC("amm1", "raydium")]
    cands += [_FakePC(f"bc{i}", "pumpfun") for i in range(20)]
    admitted = _admit_candidates(watch, cands, watch_max=10, amm_reserved=4)
    phases = [e["phase"] for e in watch.values()]
    assert phases.count("AMM") == 2  # both AMM pools admitted
    assert phases.count("BC") == 6  # non-AMM capped at watch_max - amm_reserved
    assert admitted == 8


def test_admission_never_overshoots_watch_max() -> None:
    """The total watchlist must never exceed watch_max, even when AMM pools fill most of
    it and non-AMM candidates remain (the rate-limiter guard the runtime caught)."""
    watch: dict[str, dict] = {}
    cands = [_FakePC(f"amm{i}", "pumpswap") for i in range(8)]  # 8 AMM
    cands += [_FakePC(f"bc{i}", "pumpfun") for i in range(10)]  # plenty of BC
    admitted = _admit_candidates(watch, cands, watch_max=10, amm_reserved=3)
    assert len(watch) == 10  # NOT 8 + 7; capped at watch_max
    assert admitted == 10
    phases = [e["phase"] for e in watch.values()]
    assert phases.count("AMM") == 8 and phases.count("BC") == 2


def test_admission_amm_can_consume_reserved_capacity() -> None:
    """When many AMM pools arrive, they may use the FULL watch_max (the reserve is a floor
    for AMM, not a ceiling) — graduation tailing is never throttled by the reserve."""
    watch: dict[str, dict] = {}
    amm = [_FakePC(f"amm{i}", "pumpswap") for i in range(15)]
    admitted = _admit_candidates(watch, amm, watch_max=10, amm_reserved=4)
    assert admitted == 10
    assert len(watch) == 10
