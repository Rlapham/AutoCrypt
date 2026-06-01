"""Tests for the DuckDB event store — replay gate + idempotency (no network)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from autocrypt.schema import Source, Swap, TradeSide, knowable_at_for_tx
from autocrypt.storage.store import EventStore

T0 = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
LAT = timedelta(seconds=2)


def _swap(sig: str, minute: int) -> Swap:
    t = T0 + timedelta(minutes=minute)
    return Swap(
        source=Source.synthetic,
        event_time=t,
        knowable_at=knowable_at_for_tx(t, LAT),
        block_slot=1000 + minute,
        pool_address="POOL",
        base_mint="BASE",
        quote_mint="QUOTE",
        signer="W",
        side=TradeSide.buy,
        base_amount=Decimal("1"),
        tx_signature=sig,
        instruction_index=0,
    )


def test_write_and_count(tmp_path) -> None:
    store = EventStore(tmp_path / "t.duckdb")
    n = store.write_events([_swap("A", 0), _swap("B", 1)])
    assert n == 2
    assert store.count() == 2
    store.close()


def test_idempotent_reingest(tmp_path) -> None:
    store = EventStore(tmp_path / "t.duckdb")
    store.write_events([_swap("A", 0)])
    store.write_events([_swap("A", 0)])  # same event_id → no duplicate row
    assert store.count() == 1
    store.close()


def test_replay_gate_excludes_future(tmp_path) -> None:
    store = EventStore(tmp_path / "t.duckdb")
    store.write_events([_swap("A", 0), _swap("B", 5), _swap("C", 10)])
    # Decision time between the 1st and 2nd swap's knowable_at: only the 1st is visible.
    cut = T0 + timedelta(minutes=1)
    visible = store.replay(cut)
    assert len(visible) == 1
    assert visible[0]["tx_signature"] == "A"
    store.close()


def test_export_parquet_writes_files(tmp_path) -> None:
    # Regression: DuckDB writes nothing if a bind param is in both WHERE and TO target.
    store = EventStore(tmp_path / "t.duckdb")
    store.write_events([_swap("A", 0), _swap("B", 1)])
    out = tmp_path / "pq"
    paths = store.export_parquet(out)
    store.close()
    assert paths, "expected at least one parquet file"
    for p in paths:
        assert p.exists() and p.stat().st_size > 0
