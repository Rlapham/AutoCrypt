"""Tests for the Flipside adapter — pure mappers + the key-gate. No network.

These pin three things: (1) a Flipside `ez_dex_swaps` row maps to the SAME canonical
Swap as the DexPaprika/Bitquery paths (the swap-in contract), (2) the directional
buy/sell convention is correct (received base = buy, gave base = sell), and (3) no
network call can fire without a (free) API key.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from autocrypt.providers.flipside import (
    SOL,
    USDC,
    Flipside,
    FlipsideKeyNotConfiguredError,
)
from autocrypt.schema import Source, TradeSide

# A representative ez_dex_swaps row: swapper PAID USDC, RECEIVED a low-cap mint → BUY of
# base. Keys are UPPER-cased on purpose to prove the lower-casing normalization works.
BUY_ROW = {
    "BLOCK_TIMESTAMP": "2026-05-20 12:00:00.000",
    "BLOCK_ID": 1234567,
    "TX_ID": "sig_abc",
    "SWAPPER": "wallet_xyz",
    "SWAP_FROM_MINT": USDC,
    "SWAP_FROM_AMOUNT": "500.0",
    "SWAP_FROM_AMOUNT_USD": "500.0",
    "SWAP_TO_MINT": "LOWCAPmint",
    "SWAP_TO_AMOUNT": "1000.0",
    "SWAP_TO_AMOUNT_USD": "500.0",
    "SWAP_PROGRAM": "raydium v4",
    "PROGRAM_ID": "prog123",
}

# The mirror: swapper GAVE the low-cap mint, RECEIVED SOL → SELL of base.
SELL_ROW = {
    "block_timestamp": "2026-05-20T12:05:00Z",
    "block_id": 1234600,
    "tx_id": "sig_def",
    "swapper": "wallet_2",
    "swap_from_mint": "LOWCAPmint",
    "swap_from_amount": "2000.0",
    "swap_from_amount_usd": "900.0",
    "swap_to_mint": SOL,
    "swap_to_amount": "4.5",
    "swap_to_amount_usd": "900.0",
    "swap_program": "orca whirlpool",
    "program_id": "prog456",
}


def test_to_swap_buy_maps_canonical_fields() -> None:
    fs = Flipside()  # no key — mappers still work offline
    swap = fs.to_swap(BUY_ROW, run_id="t")
    assert swap is not None
    assert swap.source == Source.flipside
    assert swap.base_mint == "LOWCAPmint"
    assert swap.quote_mint == USDC
    assert swap.signer == "wallet_xyz"
    assert swap.side == TradeSide.buy  # received base → buy
    assert swap.base_amount == 1000
    assert swap.quote_amount == 500
    assert swap.amount_usd == 500
    assert swap.price_usd == pytest.approx(0.5)  # 500 USD / 1000 base
    assert swap.usd_price_source == "flipside"
    assert swap.block_slot == 1234567
    # surrogate pool key (no native pool address in ez_dex_swaps)
    assert swap.pool_address == f"flipside:raydium v4:LOWCAPmint/{USDC}"
    # knowable_at must be >= event_time (no look-ahead, latency added)
    assert swap.knowable_at >= swap.event_time


def test_to_swap_sell_direction() -> None:
    fs = Flipside()
    swap = fs.to_swap(SELL_ROW, run_id="t")
    assert swap is not None
    assert swap.base_mint == "LOWCAPmint"
    assert swap.quote_mint == SOL
    assert swap.side == TradeSide.sell  # gave base → sell
    assert swap.base_amount == 2000
    assert swap.quote_amount == pytest.approx(4.5)


def test_quote_to_quote_swap_is_skipped() -> None:
    """A SOL↔USDC swap is not a low-cap launch trade and must be dropped."""
    fs = Flipside()
    row = {
        "block_timestamp": "2026-05-20T12:00:00Z",
        "tx_id": "sig_q",
        "swapper": "w",
        "swap_from_mint": SOL,
        "swap_to_mint": USDC,
        "swap_from_amount": "1",
        "swap_to_amount": "150",
    }
    assert fs.to_swap(row, run_id="t") is None


def test_real_pool_address_field_is_preferred() -> None:
    """If the live schema ever exposes a pool address, it wins over the surrogate."""
    fs = Flipside()
    row = {**BUY_ROW, "pool_address": "RealPool111"}
    swap = fs.to_swap(row, run_id="t")
    assert swap is not None
    assert swap.pool_address == "RealPool111"


def test_wallet_event_links_to_swap() -> None:
    fs = Flipside()
    swap = fs.to_swap(BUY_ROW, run_id="t")
    assert swap is not None
    we = fs.swap_to_wallet_event(swap)
    assert we.wallet == "wallet_xyz"
    assert we.linked_event_id == swap.event_id()


def test_pool_created_proxy_from_first_swap() -> None:
    fs = Flipside()
    pc = fs.to_pool_created(BUY_ROW, run_id="t")
    assert pc is not None
    assert pc.base_mint == "LOWCAPmint"
    assert pc.quote_mint == USDC
    assert pc.pool_address == f"flipside:raydium v4:LOWCAPmint/{USDC}"
    assert pc.dex == "raydium v4"


def test_key_gate_blocks_network_without_key() -> None:
    """A fetch must raise unless a (free) API key is present."""
    fs = Flipside()  # no key

    async def _go() -> None:
        async for _ in fs.iter_swap_rows(
            since=datetime(2026, 5, 1, tzinfo=UTC),
            till=datetime(2026, 5, 2, tzinfo=UTC),
        ):
            pass

    with pytest.raises(FlipsideKeyNotConfiguredError):
        asyncio.run(_go())


def test_key_gate_guard_direct() -> None:
    Flipside(api_key="free_key")._guard_key()  # no raise with a key
    with pytest.raises(FlipsideKeyNotConfiguredError):
        Flipside()._guard_key()
