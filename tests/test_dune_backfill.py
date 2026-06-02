"""Tests for the Dune backfill/validation ingestion glue — offline, no network.

A `FakeDune` subclasses the real adapter and overrides ONLY the four network methods
(`execute_query`, `wait_for_execution`, `get_execution_status`, `fetch_results_page`,
`iter_trade_rows`) to replay canned `dex_solana.trades` rows. The REAL mappers
(`to_swap`, `to_pool_created`, `swap_to_wallet_event`) run unchanged — so these pin the
ingestion logic (field-path validation, the first-trade-as-creation-proxy rule, idempotent
writes) against the same code paths a live pull would exercise.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from autocrypt.ingestion.dune_backfill import (
    parse_window,
    run_dune_backfill,
    validate_dune,
)
from autocrypt.providers.dune import SOL, USDC, Dune
from autocrypt.storage.store import EventStore

# Two markets. Market A (TOKA/USDC, raydium) has 2 trades; the EARLIER one (12:00) must
# become the PoolCreated proxy. Market B (TOKB/SOL, orca) has 1 trade. One SOL↔USDC row is
# a non-launch trade that must be skipped by the mappers.
ROWS: list[dict[str, Any]] = [
    {
        "block_time": "2026-05-20 12:00:00.000",
        "block_slot": 100,
        "tx_id": "a1",
        "trader_id": "w1",
        "token_sold_mint_address": USDC,
        "token_sold_amount": "500",
        "token_bought_mint_address": "TOKA",
        "token_bought_amount": "1000",
        "amount_usd": "500",
        "project": "raydium",
        "project_program_id": "progA",
    },
    {
        "block_time": "2026-05-20 12:01:00.000",
        "block_slot": 101,
        "tx_id": "a2",
        "trader_id": "w2",
        "token_sold_mint_address": USDC,
        "token_sold_amount": "250",
        "token_bought_mint_address": "TOKA",
        "token_bought_amount": "400",
        "amount_usd": "250",
        "project": "raydium",
        "project_program_id": "progA",
    },
    {  # SOL↔USDC — not a low-cap launch trade → skipped
        "block_time": "2026-05-20 12:02:00.000",
        "block_slot": 102,
        "tx_id": "q",
        "trader_id": "w3",
        "token_sold_mint_address": SOL,
        "token_sold_amount": "1",
        "token_bought_mint_address": USDC,
        "token_bought_amount": "150",
    },
    {
        "block_time": "2026-05-20 12:03:00.000",
        "block_slot": 103,
        "tx_id": "b1",
        "trader_id": "w4",
        "token_bought_mint_address": SOL,
        "token_bought_amount": "2.5",
        "token_sold_mint_address": "TOKB",
        "token_sold_amount": "900",
        "amount_usd": "450",
        "project": "orca",
        "project_program_id": "progB",
    },
]


class FakeDune(Dune):
    """Real mappers, fake network: replays ROWS without a key or HTTP."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        super().__init__(api_key="fake")  # satisfies the key-gate; no real call is made
        self._rows = rows

    async def execute_query(self, query_id: int, **_: Any) -> str:  # type: ignore[override]
        return "exec-1"

    async def wait_for_execution(self, execution_id: str, **_: Any) -> None:  # type: ignore[override]
        return None

    async def get_execution_status(self, execution_id: str) -> dict[str, Any]:  # type: ignore[override]
        return {"result_metadata": {"total_row_count": len(self._rows)}}

    async def fetch_results_page(  # type: ignore[override]
        self, execution_id: str, *, limit: int, offset: int = 0
    ) -> dict[str, Any]:
        return {"result": {"rows": self._rows[offset : offset + limit], "metadata": {}}}

    async def iter_trade_rows(  # type: ignore[override]
        self, query_id: int, since: datetime, till: datetime, **_: Any
    ) -> AsyncIterator[dict[str, Any]]:
        for r in self._rows:
            yield {k.lower(): v for k, v in r.items()}


def test_parse_window_attaches_utc() -> None:
    assert parse_window("2026-05-20 12:00:00") == datetime(2026, 5, 20, 12, 0, tzinfo=UTC)
    assert parse_window("2026-05-20T12:00:00Z") == datetime(2026, 5, 20, 12, 0, tzinfo=UTC)


def test_validate_reports_field_paths_and_survivorship() -> None:
    dune = FakeDune(ROWS)
    rep = asyncio.run(
        validate_dune(
            dune,
            query_id=1,
            since=datetime(2026, 5, 20, tzinfo=UTC),
            till=datetime(2026, 5, 21, tzinfo=UTC),
        )
    )
    assert rep.total_row_count == 4
    assert rep.sampled_rows == 4
    assert rep.mapped_swaps == 3  # the SOL↔USDC row is skipped
    assert rep.skipped_non_quote == 1
    assert rep.missing_expected == []  # all selected columns present in the sample
    assert rep.field_paths_ok is True
    assert rep.distinct_base_mints == 2  # TOKA + TOKB — survivorship breadth
    assert rep.distinct_markets == 2
    assert rep.rows_with_usd == 3
    assert rep.pool_field_present is False  # surrogate key in use
    assert rep.sample_swap is not None


def test_validate_flags_missing_column() -> None:
    """Drop a selected column from every row → validation must surface it, not hide it."""
    rows = [{k: v for k, v in r.items() if k != "amount_usd"} for r in ROWS]
    dune = FakeDune(rows)
    rep = asyncio.run(
        validate_dune(
            dune, query_id=1,
            since=datetime(2026, 5, 20, tzinfo=UTC),
            till=datetime(2026, 5, 21, tzinfo=UTC),
        )
    )
    assert "amount_usd" in rep.missing_expected
    assert rep.field_paths_ok is False
    assert rep.rows_with_usd == 0


def test_backfill_writes_first_trade_as_pool_proxy(tmp_path: Any) -> None:
    store = EventStore(tmp_path / "t.duckdb")
    dune = FakeDune(ROWS)
    rep = asyncio.run(
        run_dune_backfill(
            store, dune,
            run_id="t",
            query_id=1,
            since=datetime(2026, 5, 20, tzinfo=UTC),
            till=datetime(2026, 5, 21, tzinfo=UTC),
        )
    )
    assert rep.raw_rows == 4
    assert rep.swaps_mapped == 3
    assert rep.skipped_non_quote == 1
    # Two surrogate markets → exactly two PoolCreated creation-proxies.
    assert rep.pools_created == 2

    counts = store.counts_by_type()
    assert counts.get("swap") == 3
    assert counts.get("wallet_event") == 3
    assert counts.get("pool_created") == 2

    # The PoolCreated proxy for market A must be its EARLIEST trade (12:00, slot 100).
    pc = store.replay(datetime(2026, 5, 21, tzinfo=UTC), types=None)
    a_pools = [
        r for r in pc
        if r["event_type"] == "pool_created" and r["base_mint"] == "TOKA"
    ]
    assert len(a_pools) == 1
    assert a_pools[0]["block_slot"] == 100  # first trade, not the 12:01 one
    store.close()


def test_backfill_is_idempotent(tmp_path: Any) -> None:
    store = EventStore(tmp_path / "t.duckdb")
    first = asyncio.run(
        run_dune_backfill(
            store, FakeDune(ROWS), run_id="t1", query_id=1,
            since=datetime(2026, 5, 20, tzinfo=UTC),
            till=datetime(2026, 5, 21, tzinfo=UTC),
        )
    )
    assert first.net_new_rows == 8  # 3 swaps + 3 wallet + 2 pools
    second = asyncio.run(
        run_dune_backfill(
            store, FakeDune(ROWS), run_id="t2", query_id=1,
            since=datetime(2026, 5, 20, tzinfo=UTC),
            till=datetime(2026, 5, 21, tzinfo=UTC),
        )
    )
    assert second.net_new_rows == 0  # event_id dedup → re-run adds nothing
    store.close()
