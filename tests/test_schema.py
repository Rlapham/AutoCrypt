"""Tests for the canonical event schema — focused on the no-look-ahead invariants."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import TypeAdapter, ValidationError

from autocrypt.schema import (
    AnyEvent,
    OHLCVBar,
    Source,
    Swap,
    TradeSide,
    knowable_at_for_bar,
    knowable_at_for_tx,
)

T0 = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
LAT = timedelta(seconds=2)


def _swap(**over) -> Swap:
    base = {
        "source": Source.bitquery,
        "event_time": T0,
        "knowable_at": knowable_at_for_tx(T0, LAT),
        "block_slot": 1000,
        "pool_address": "POOL",
        "base_mint": "BASE",
        "quote_mint": "So11111111111111111111111111111111111111112",
        "signer": "WALLET",
        "side": TradeSide.buy,
        "base_amount": Decimal("1000"),
        "quote_amount": Decimal("1.5"),
        "tx_signature": "SIG",
        "instruction_index": 0,
    }
    base.update(over)
    return Swap(**base)


def test_knowable_at_after_event_time() -> None:
    s = _swap()
    assert s.knowable_at == T0 + LAT
    assert s.ingest_latency_ms == pytest.approx(2000.0)


def test_lookahead_rejected() -> None:
    # knowable_at BEFORE event_time is a look-ahead violation and must not construct.
    with pytest.raises(ValidationError):
        _swap(knowable_at=T0 - timedelta(seconds=1))


def test_naive_datetime_rejected() -> None:
    with pytest.raises(ValidationError):
        _swap(event_time=datetime(2026, 5, 1, 12, 0, 0))


def test_ohlcv_event_time_must_equal_close() -> None:
    open_t = T0
    close_t = T0 + timedelta(minutes=1)
    # correct: event_time == close_time, knowable_at >= close_time
    bar = OHLCVBar(
        source=Source.geckoterminal,
        event_time=close_t,
        knowable_at=knowable_at_for_bar(close_t, LAT),
        pool_address="POOL",
        interval="1m",
        open_time=open_t,
        close_time=close_t,
        open=Decimal("1"),
        high=Decimal("2"),
        low=Decimal("0.5"),
        close=Decimal("1.5"),
    )
    assert bar.event_time == close_t
    # stamping a bar at its OPEN time is the classic look-ahead trap → rejected
    with pytest.raises(ValidationError):
        OHLCVBar(
            source=Source.geckoterminal,
            event_time=open_t,  # wrong
            knowable_at=knowable_at_for_bar(close_t, LAT),
            pool_address="POOL",
            interval="1m",
            open_time=open_t,
            close_time=close_t,
            open=Decimal("1"),
            high=Decimal("2"),
            low=Decimal("0.5"),
            close=Decimal("1.5"),
        )


def test_deterministic_event_id_dedup() -> None:
    # Same natural key from two different providers → same id (cross-provider dedup).
    a = _swap(source=Source.bitquery)
    b = _swap(source=Source.dexpaprika)
    assert a.event_id() == b.event_id()


def test_discriminated_union_roundtrip() -> None:
    s = _swap()
    adapter = TypeAdapter(AnyEvent)
    dumped = s.model_dump()
    parsed = adapter.validate_python(dumped)
    assert isinstance(parsed, Swap)
    assert parsed.event_id() == s.event_id()
