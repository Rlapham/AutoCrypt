"""Tests for G0 graduation-event detection (no network).

These pin the load-bearing properties of the detector:
- venue→phase taxonomy (BC / AMM / OTHER), incl. an unknown venue staying OTHER;
- a genuine BC→AMM transition is detected with the milestone stamped at the AMM pool's
  knowable_at (no look-ahead onto the bonding-curve time);
- the co-launch artifact (tiny BC→AMM lag) is flagged, not counted as genuine;
- survivorship: never-graduated and direct-AMM mints are classified, not dropped;
- post-graduation swap coverage is counted point-in-time (knowable_at >= graduation).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from autocrypt.grad.graduation import detect_graduations, render_markdown, venue_phase
from autocrypt.schema import (
    PoolCreated,
    Source,
    Swap,
    TradeSide,
    knowable_at_for_tx,
)
from autocrypt.storage.store import EventStore

T0 = datetime(2026, 6, 3, 12, 0, 0, tzinfo=UTC)
LAT = timedelta(seconds=2)


def _pc(mint: str, dex: str, pool: str, minute: float) -> PoolCreated:
    t = T0 + timedelta(minutes=minute)
    return PoolCreated(
        source=Source.synthetic,
        event_time=t,
        knowable_at=knowable_at_for_tx(t, LAT),
        pool_address=pool,
        dex=dex,
        base_mint=mint,
        quote_mint="So11111111111111111111111111111111111111112",
    )


def _swap(pool: str, mint: str, minute: float, sig: str) -> Swap:
    t = T0 + timedelta(minutes=minute)
    return Swap(
        source=Source.synthetic,
        event_time=t,
        knowable_at=knowable_at_for_tx(t, LAT),
        pool_address=pool,
        base_mint=mint,
        quote_mint="So11111111111111111111111111111111111111112",
        signer="W",
        side=TradeSide.buy,
        base_amount=Decimal("1"),
        tx_signature=sig,
        instruction_index=0,
    )


def _store(tmp_path, events) -> EventStore:
    s = EventStore(tmp_path / "g.duckdb")
    s.write_events(events)
    return s


def test_venue_phase_taxonomy():
    assert venue_phase("pumpfun") == "BC"
    assert venue_phase("meteora_dbc") == "BC"
    assert venue_phase("pumpswap") == "AMM"
    assert venue_phase("raydium") == "AMM"
    assert venue_phase("meteora_daam_v2") == "AMM"
    assert venue_phase("some_new_launchpad") == "OTHER"  # unknown ≠ graduation target
    assert venue_phase(None) == "OTHER"


def test_genuine_graduation_detected_point_in_time(tmp_path):
    # Bonding-curve pool, then an AMM pool 10 min later = a genuine graduation.
    events = [
        _pc("MINT_A", "pumpfun", "BC_A", 0.0),
        _pc("MINT_A", "pumpswap", "AMM_A", 10.0),
    ]
    store = _store(tmp_path, events)
    census = detect_graduations(store, min_lag_s=120.0)
    store.close()

    assert census.n_bc_origin == 1
    assert census.n_genuine == 1
    assert census.n_suspect_colaunch == 0
    assert census.n_never_graduated == 0
    e = census.events[0]
    assert e.transition == "pumpfun->pumpswap"
    assert e.lag_s == 600.0
    # The milestone is the AMM pool's knowable_at — NOT the bonding-curve creation time.
    assert e.grad_knowable_at == knowable_at_for_tx(T0 + timedelta(minutes=10), LAT)
    assert e.grad_knowable_at > e.bc_event_time


def test_colaunch_artifact_flagged_not_counted_genuine(tmp_path):
    # AMM pool created 30s after the bonding-curve pool = co-launch config artifact.
    events = [
        _pc("MINT_B", "meteora_dbc", "BC_B", 0.0),
        _pc("MINT_B", "meteora_daam_v2", "AMM_B", 0.5),  # 30s lag < 120s
    ]
    store = _store(tmp_path, events)
    census = detect_graduations(store, min_lag_s=120.0)
    store.close()

    assert census.n_graduated == 1
    assert census.n_genuine == 0
    assert census.n_suspect_colaunch == 1
    assert census.events[0].suspect_colaunch is True
    assert census.graduation_rate == 0.0  # rate counts genuine only


def test_never_graduated_kept_in_denominator(tmp_path):
    # A mint that only ever lives on the bonding curve is a retained failure (survivorship).
    events = [_pc("MINT_C", "pumpfun", "BC_C", 0.0)]
    store = _store(tmp_path, events)
    census = detect_graduations(store)
    store.close()

    assert census.n_bc_origin == 1
    assert census.n_never_graduated == 1
    assert census.n_graduated == 0


def test_direct_amm_launch_not_a_graduation(tmp_path):
    # First/only pool is already an AMM → deep from birth, not a BC→AMM transition.
    events = [_pc("MINT_D", "raydium", "AMM_D", 0.0)]
    store = _store(tmp_path, events)
    census = detect_graduations(store)
    store.close()

    assert census.n_direct_amm == 1
    assert census.n_bc_origin == 0
    assert census.n_graduated == 0


def test_amm_before_bc_does_not_match_as_graduation(tmp_path):
    # An AMM pool created BEFORE the bonding-curve pool is not a forward graduation;
    # there is no AMM pool at/after the BC pool, so the mint never graduates in-window.
    events = [
        _pc("MINT_E", "raydium", "AMM_E", 0.0),
        _pc("MINT_E", "pumpfun", "BC_E", 5.0),
    ]
    store = _store(tmp_path, events)
    census = detect_graduations(store)
    store.close()

    # It has a BC pool, so it's BC-origin; but its only AMM pool predates the BC pool.
    assert census.n_bc_origin == 1
    assert census.n_never_graduated == 1
    assert census.n_graduated == 0


def test_post_grad_swap_coverage_is_point_in_time(tmp_path):
    grad_min = 10.0
    events = [
        _pc("MINT_F", "pumpfun", "BC_F", 0.0),
        _pc("MINT_F", "pumpswap", "AMM_F", grad_min),
        # a swap on the AMM pool BEFORE graduation became knowable → must NOT count
        _swap("AMM_F", "MINT_F", grad_min - 1.0, "early"),
        # two swaps after graduation → count
        _swap("AMM_F", "MINT_F", grad_min + 1.0, "late1"),
        _swap("AMM_F", "MINT_F", grad_min + 2.0, "late2"),
    ]
    store = _store(tmp_path, events)
    census = detect_graduations(store)
    store.close()

    e = census.events[0]
    assert e.post_grad_swaps == 2  # only the two post-graduation swaps
    assert census.n_with_post_grad_swaps == 1


def test_mixed_universe_census_and_render(tmp_path):
    events = [
        # genuine graduation
        _pc("G", "pumpfun", "BC_G", 0.0),
        _pc("G", "pumpswap", "AMM_G", 30.0),
        # suspect co-launch
        _pc("S", "meteora_dbc", "BC_S", 0.0),
        _pc("S", "meteora_daam_v2", "AMM_S", 0.3),
        # never graduated
        _pc("N", "pumpfun", "BC_N", 1.0),
        # direct amm
        _pc("D", "orca", "AMM_D", 2.0),
    ]
    store = _store(tmp_path, events)
    census = detect_graduations(store, min_lag_s=120.0)
    store.close()

    assert census.n_bc_origin == 3  # G, S, N
    assert census.n_genuine == 1  # G
    assert census.n_suspect_colaunch == 1  # S
    assert census.n_never_graduated == 1  # N
    assert census.n_direct_amm == 1  # D
    assert census.by_transition["pumpfun->pumpswap"] == 1
    # render must not throw and should surface the genuine rate
    md = render_markdown(census)
    assert "Graduation-event detection" in md
    assert "genuine" in md.lower()
