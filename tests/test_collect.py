"""Tests for the forward-collector cohort logic — admit/retire/hold. No network.

The collector's value over `poll` is that it HOLDS an admitted pool and tails its
swaps for hours (capturing a run-up), evicting only by age — not by recency. These
tests pin that contract on the pure cohort functions.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from autocrypt.ingestion.collect import _age_out


def _entry(age_s: float) -> dict:
    return {"ctx": {}, "created_at": datetime.now(UTC) - timedelta(seconds=age_s)}


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
