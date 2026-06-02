"""Tests for the Dune adapter — pure mappers + the key-gate. No network.

These pin three things: (1) a Dune `dex_solana.trades` row maps to the SAME canonical
Swap as the other provider paths (the swap-in contract), (2) the directional buy/sell
convention is correct (bought base = buy, sold base = sell), and (3) no network call can
fire without a (free) API key.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from autocrypt.providers.dune import (
    SOL,
    USDC,
    Dune,
    DuneKeyNotConfiguredError,
)
from autocrypt.schema import Source, TradeSide

# A representative dex_solana.trades row: trader SOLD USDC, BOUGHT a low-cap mint → BUY of
# base. Keys are UPPER-cased on purpose to prove the lower-casing normalization works.
BUY_ROW = {
    "BLOCK_TIME": "2026-05-20 12:00:00.000",  # space-separated, naive → assumed UTC
    "BLOCK_SLOT": 1234567,
    "TX_ID": "sig_abc",
    "TRADER_ID": "wallet_xyz",
    "TOKEN_SOLD_MINT_ADDRESS": USDC,
    "TOKEN_SOLD_AMOUNT": "500.0",
    "TOKEN_BOUGHT_MINT_ADDRESS": "LOWCAPmint",
    "TOKEN_BOUGHT_AMOUNT": "1000.0",
    "AMOUNT_USD": "500.0",
    "PROJECT": "raydium",
    "PROJECT_PROGRAM_ID": "prog123",
}

# The mirror: trader BOUGHT SOL, SOLD the low-cap mint → SELL of base.
SELL_ROW = {
    "block_time": "2026-05-20T12:05:00Z",
    "block_slot": 1234600,
    "tx_id": "sig_def",
    "trader_id": "wallet_2",
    "token_bought_mint_address": SOL,
    "token_bought_amount": "4.5",
    "token_sold_mint_address": "LOWCAPmint",
    "token_sold_amount": "2000.0",
    "amount_usd": "900.0",
    "project": "orca",
    "project_program_id": "prog456",
}


def test_to_swap_buy_maps_canonical_fields() -> None:
    d = Dune()  # no key — mappers still work offline
    swap = d.to_swap(BUY_ROW, run_id="t")
    assert swap is not None
    assert swap.source == Source.dune
    assert swap.base_mint == "LOWCAPmint"
    assert swap.quote_mint == USDC
    assert swap.signer == "wallet_xyz"
    assert swap.side == TradeSide.buy  # bought base → buy
    assert swap.base_amount == 1000
    assert swap.quote_amount == 500
    assert swap.amount_usd == 500
    assert swap.price_usd == pytest.approx(0.5)  # 500 USD / 1000 base
    assert swap.usd_price_source == "dune"
    assert swap.block_slot == 1234567
    assert swap.pool_address == f"dune:raydium:LOWCAPmint/{USDC}"  # surrogate market key
    assert swap.knowable_at >= swap.event_time  # no look-ahead


def test_to_swap_sell_direction() -> None:
    d = Dune()
    swap = d.to_swap(SELL_ROW, run_id="t")
    assert swap is not None
    assert swap.base_mint == "LOWCAPmint"
    assert swap.quote_mint == SOL
    assert swap.side == TradeSide.sell  # sold base → sell
    assert swap.base_amount == 2000
    assert swap.quote_amount == pytest.approx(4.5)


def test_quote_to_quote_swap_is_skipped() -> None:
    """A SOL↔USDC swap is not a low-cap launch trade and must be dropped."""
    d = Dune()
    row = {
        "block_time": "2026-05-20T12:00:00Z",
        "tx_id": "sig_q",
        "trader_id": "w",
        "token_bought_mint_address": USDC,
        "token_sold_mint_address": SOL,
        "token_bought_amount": "150",
        "token_sold_amount": "1",
    }
    assert d.to_swap(row, run_id="t") is None


def test_real_pool_address_field_is_preferred() -> None:
    """If the schema exposes a pool address, it wins over the surrogate."""
    d = Dune()
    row = {**BUY_ROW, "pool_address": "RealPool111"}
    swap = d.to_swap(row, run_id="t")
    assert swap is not None
    assert swap.pool_address == "RealPool111"


def test_wallet_event_links_to_swap() -> None:
    d = Dune()
    swap = d.to_swap(BUY_ROW, run_id="t")
    assert swap is not None
    we = d.swap_to_wallet_event(swap)
    assert we.wallet == "wallet_xyz"
    assert we.linked_event_id == swap.event_id()


def test_pool_created_proxy_from_first_trade() -> None:
    d = Dune()
    pc = d.to_pool_created(BUY_ROW, run_id="t")
    assert pc is not None
    assert pc.base_mint == "LOWCAPmint"
    assert pc.quote_mint == USDC
    assert pc.pool_address == f"dune:raydium:LOWCAPmint/{USDC}"
    assert pc.dex == "raydium"
    assert pc.program_id == "prog123"


def test_key_gate_blocks_network_without_key() -> None:
    """A fetch must raise unless a (free) API key is present."""
    d = Dune()  # no key

    async def _go() -> None:
        async for _ in d.iter_trade_rows(
            query_id=123,
            since=datetime(2026, 5, 1, tzinfo=UTC),
            till=datetime(2026, 5, 2, tzinfo=UTC),
        ):
            pass

    with pytest.raises(DuneKeyNotConfiguredError):
        asyncio.run(_go())


def test_key_gate_guard_direct() -> None:
    Dune(api_key="free_key")._guard_key()  # no raise with a key
    with pytest.raises(DuneKeyNotConfiguredError):
        Dune()._guard_key()
