"""Tests for the forward-collector cohort logic — admit/retire/hold. No network.

The collector's value over `poll` is that it HOLDS an admitted pool and tails its swaps,
evicting only by age. For Track G the binding requirement is sharper: a GRADUATION pool
(an AMM pool for a mint already seen on a bonding curve) must be PINNED — admitted even
when the watchlist is full and held for its full multi-day arc — while non-graduation
discovery pools churn out fast so the watchlist never freezes. These tests pin that
contract on the pure cohort functions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from autocrypt.ingestion.collect import _admit_candidates, _age_out, _is_graduation


def _entry(age_s: float, tier: str = "disc") -> dict:
    return {"ctx": {}, "created_at": datetime.now(UTC) - timedelta(seconds=age_s), "tier": tier}


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


# --- graduation classification ------------------------------------------------------


def test_is_graduation_only_amm_with_known_bc_mint() -> None:
    """A graduation = AMM-venue pool whose mint was already seen on a bonding curve.
    A direct-AMM pool (mint never on a curve) and a bonding-curve pool are NOT graduations."""
    bc_mints = {"Mg"}
    assert _is_graduation(_FakePC("amm", "pumpswap", base_mint="Mg"), bc_mints) is True
    assert _is_graduation(_FakePC("amm", "pumpswap", base_mint="Md"), bc_mints) is False  # direct-AMM
    assert _is_graduation(_FakePC("bc", "pumpfun", base_mint="Mg"), bc_mints) is False  # BC pool


# --- age-out: tier-based retention --------------------------------------------------


def test_age_out_holds_grad_long_retires_discovery_short() -> None:
    """A graduation pool is held for the long arc; a same-age discovery pool ages out."""
    watch = {"grad": _entry(10_000, "grad"), "disc": _entry(10_000, "disc")}
    retired: set[str] = set()
    n = _age_out(watch, retired, max_pool_age_s=604800.0, discovery_age_s=3600.0)
    assert n == 1
    assert "grad" in watch and "disc" not in watch
    assert "disc" in retired


def test_age_out_retires_only_old_pools() -> None:
    """Discovery pools younger than discovery_age stay; older ones retire and free a slot."""
    watch = {"young": _entry(10), "old": _entry(10_000)}
    retired: set[str] = set()
    n = _age_out(watch, retired, max_pool_age_s=604800.0, discovery_age_s=3600.0)
    assert n == 1
    assert "young" in watch and "old" not in watch and "old" in retired


def test_fresh_cohort_held_not_evicted_by_newer() -> None:
    """Nothing retires while every pool is within its age window — the cohort is held,
    so newer launches cannot evict a still-young pool."""
    watch = {f"p{i}": _entry(60 * i) for i in range(5)}  # all < 1h old
    retired: set[str] = set()
    n = _age_out(watch, retired, max_pool_age_s=604800.0, discovery_age_s=3600.0)
    assert n == 0 and len(watch) == 5


# --- admission: graduation pinned above discovery -----------------------------------


def test_admission_reserves_slots_for_graduations() -> None:
    """Discovery (here bonding-curve) pools must NOT fill the whole watchlist —
    `grad_reserved` slots stay open so an incoming graduation can be tailed."""
    watch: dict[str, dict] = {}
    bc = [_FakePC(f"bc{i}", "pumpfun", base_mint=f"M{i}") for i in range(20)]
    admitted = _admit_candidates(watch, bc, set(), set(), watch_max=10, grad_reserved=4)
    # only watch_max - grad_reserved = 6 discovery pools admitted; 4 slots held for graduations
    assert admitted == 6 and len(watch) == 6
    assert all(e["tier"] == "disc" for e in watch.values())


def test_admission_graduation_uses_reserved_headroom() -> None:
    """A graduation (AMM pool for a mint already on a curve) is admitted into the reserved
    headroom even after discovery has filled its unreserved portion."""
    watch: dict[str, dict] = {}
    bc_mints = {"Mg"}
    cands = [_FakePC("grad0", "pumpswap", base_mint="Mg")]  # the graduation
    cands += [_FakePC(f"bc{i}", "pumpfun", base_mint=f"M{i}") for i in range(20)]
    admitted = _admit_candidates(watch, cands, set(), bc_mints, watch_max=10, grad_reserved=4)
    tiers = [e["tier"] for e in watch.values()]
    assert tiers.count("grad") == 1  # graduation admitted
    assert tiers.count("disc") == 6  # discovery still capped at watch_max - grad_reserved
    assert admitted == 7


def test_admission_graduation_never_locked_out_evicts_oldest_discovery() -> None:
    """When the watchlist is FULL, a graduation evicts the OLDEST discovery pool (and retires
    it) rather than being dropped — the bug the redesign fixes (saturated watchlist froze and
    graduations, which arrive minutes-to-hours later, never won a slot)."""
    # full watchlist of discovery pools, oldest = "old"
    watch = {"old": _entry(9_000, "disc"), "mid": _entry(5_000, "disc"), "new": _entry(100, "disc")}
    retired: set[str] = set()
    bc_mints = {"Mg"}
    grad = [_FakePC("grad0", "pumpswap", base_mint="Mg")]
    admitted = _admit_candidates(watch, grad, retired, bc_mints, watch_max=3, grad_reserved=1)
    assert admitted == 1
    assert len(watch) == 3  # still capped
    assert "grad0" in watch and watch["grad0"]["tier"] == "grad"
    assert "old" not in watch and "old" in retired  # oldest discovery evicted + retired
    assert "mid" in watch and "new" in watch


def test_admission_direct_amm_is_discovery_not_pinned() -> None:
    """A direct-AMM pool (deep from birth, mint never on a curve) is treated as discovery,
    NOT a graduation — it must not consume graduation headroom or get long retention."""
    watch: dict[str, dict] = {}
    cands = [_FakePC("amm0", "pumpswap", base_mint="Mx")]  # mint NOT in bc_mints
    admitted = _admit_candidates(watch, cands, set(), set(), watch_max=10, grad_reserved=4)
    assert admitted == 1 and watch["amm0"]["tier"] == "disc"


def test_admission_never_overshoots_watch_max() -> None:
    """The total watchlist must never exceed watch_max, even when many graduations arrive
    into a full watchlist (each evicts one discovery pool, never growing the total)."""
    watch = {f"d{i}": _entry(1000 + i, "disc") for i in range(8)}  # 8 discovery, watch_max 10
    retired: set[str] = set()
    bc_mints = {f"Mg{i}" for i in range(5)}
    grads = [_FakePC(f"grad{i}", "pumpswap", base_mint=f"Mg{i}") for i in range(5)]
    admitted = _admit_candidates(watch, grads, retired, bc_mints, watch_max=10, grad_reserved=4)
    assert len(watch) <= 10
    assert admitted == 5  # all 5 graduations admitted (2 into free slots, 3 by eviction)
    assert sum(1 for e in watch.values() if e["tier"] == "grad") == 5


def test_admission_all_graduation_watchlist_cannot_make_room() -> None:
    """Safety valve: if the watchlist is full of graduations (no discovery to evict), a new
    graduation is not admitted rather than overshooting watch_max."""
    watch = {f"g{i}": _entry(100, "grad") for i in range(3)}  # full, all grad
    retired: set[str] = set()
    bc_mints = {"Mg"}
    admitted = _admit_candidates(
        watch, [_FakePC("grad_new", "pumpswap", base_mint="Mg")],
        retired, bc_mints, watch_max=3, grad_reserved=1,
    )
    assert admitted == 0 and len(watch) == 3 and "grad_new" not in watch
