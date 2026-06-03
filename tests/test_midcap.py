"""Tests for the Track-M mid-cap universe — pure parse + band filter + snapshot. No network.

These pin: (1) a raw GeckoTerminal `/pools` item maps to the right PoolRow (incl. bare
mint extraction from the `solana_<mint>` relationship id), (2) the signed-off band
(reserve >= $500k AND FDV in [$1M, $250M]) includes/excludes correctly at the edges, and
(3) a forward snapshot records ALL enumerated pools with `in_band` flagged (the property
that makes the forward series survivorship-safe).
"""

from __future__ import annotations

from datetime import UTC, datetime

from autocrypt.midcap.universe import (
    PoolRow,
    UniverseBand,
    parse_pool,
    write_snapshot,
)
from autocrypt.storage.store import EventStore


def _raw(addr="POOL1", name="MID / SOL", reserve="750000", fdv="50000000", mcap=None,
         base="solana_BASEMINT", quote="solana_So11111111111111111111111111111111111111112"):
    return {
        "id": f"solana_{addr}",
        "attributes": {
            "address": addr,
            "name": name,
            "reserve_in_usd": reserve,
            "fdv_usd": fdv,
            "market_cap_usd": mcap,
            "pool_created_at": "2026-01-15T10:00:00Z",
            "volume_usd": {"h24": "123456.7"},
        },
        "relationships": {
            "base_token": {"data": {"id": base, "type": "token"}},
            "quote_token": {"data": {"id": quote, "type": "token"}},
        },
    }


def test_parse_pool_extracts_bare_mints_and_floats():
    row = parse_pool(_raw())
    assert row is not None
    assert row.pool_address == "POOL1"
    assert row.base_mint == "BASEMINT"  # "solana_" prefix stripped
    assert row.quote_mint == "So11111111111111111111111111111111111111112"
    assert row.reserve_usd == 750_000.0
    assert row.fdv_usd == 50_000_000.0
    assert row.h24_volume_usd == 123456.7
    assert row.pool_created_at == datetime(2026, 1, 15, 10, 0, tzinfo=UTC)


def test_parse_pool_rejects_missing_address():
    bad = _raw()
    del bad["attributes"]["address"]
    assert parse_pool(bad) is None


def _row(reserve, fdv):
    return PoolRow("P", "N", "b", "q", reserve, fdv, None, None, None)


def test_band_edges():
    band = UniverseBand()  # defaults: reserve>=500k, FDV in [1M, 250M]
    assert band.contains(_row(500_000, 1_000_000))      # both at lower edge → in
    assert band.contains(_row(750_000, 250_000_000))    # FDV at upper edge → in
    assert not band.contains(_row(499_999, 50_000_000)) # too shallow → out
    assert not band.contains(_row(1_000_000, 999_999))  # FDV too small → out
    assert not band.contains(_row(1_000_000, 250_000_001))  # FDV too big (major) → out
    assert not band.contains(_row(None, 50_000_000))    # missing liquidity → out
    assert not band.contains(_row(750_000, None))       # missing FDV → out


def test_write_snapshot_records_all_with_in_band_flag(tmp_path):
    store = EventStore(tmp_path / "midcap.duckdb")
    band = UniverseBand()
    rows = [
        parse_pool(_raw(addr="IN", reserve="750000", fdv="50000000")),
        parse_pool(_raw(addr="OUT", reserve="100", fdv="50000000")),
    ]
    at = datetime(2026, 6, 3, 12, 0, tzinfo=UTC)
    n = write_snapshot(store, [r for r in rows if r], band, snapshot_at=at)
    assert n == 2  # ALL enumerated pools recorded, not just in-band (survivorship-safe)
    got = dict(
        store.con.execute(
            "SELECT pool_address, in_band FROM universe_snapshots WHERE snapshot_at = ?", [at]
        ).fetchall()
    )
    assert got == {"IN": True, "OUT": False}
    store.close()
