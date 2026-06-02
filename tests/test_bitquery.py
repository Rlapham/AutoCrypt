"""Tests for the Bitquery scaffold — pure mappers + the YELLOW spend-guard. No network.

These pin two things: (1) a Bitquery DEXTrade node maps to the SAME canonical Swap as
the DexPaprika path (the swap-in contract), and (2) no network call can fire without
explicit paid authorization.
"""

from __future__ import annotations

import asyncio

import pytest

from autocrypt.providers.bitquery import (
    USDC,
    Bitquery,
    PaidSpendNotAuthorizedError,
)
from autocrypt.schema import Source, TradeSide

# A representative archive DEXTrade node (base = a low-cap mint, quote = USDC).
TRADE_NODE = {
    "Block": {"Time": "2026-05-20T12:00:00Z", "Slot": 1234567},
    "Transaction": {"Signature": "sig_abc", "Signer": "wallet_xyz"},
    "Trade": {
        "Dex": {"ProtocolName": "raydium", "ProgramAddress": "prog123"},
        "Market": {"MarketAddress": "pool_market_1"},
        "Buy": {
            "Amount": "1000.0",
            "AmountInUSD": "500.0",
            "PriceInUSD": "0.5",
            "Currency": {"MintAddress": "LOWCAPmint", "Decimals": 6, "Symbol": "LOW"},
        },
        "Sell": {
            "Amount": "500.0",
            "AmountInUSD": "500.0",
            "PriceInUSD": "1.0",
            "Currency": {"MintAddress": USDC, "Decimals": 6, "Symbol": "USDC"},
        },
    },
}


def test_to_swap_maps_canonical_fields() -> None:
    bq = Bitquery()  # no key, no paid — mappers still work offline
    swap = bq.to_swap(TRADE_NODE, run_id="t")
    assert swap is not None
    assert swap.source == Source.bitquery
    assert swap.pool_address == "pool_market_1"
    assert swap.base_mint == "LOWCAPmint"
    assert swap.quote_mint == USDC
    assert swap.signer == "wallet_xyz"
    assert swap.side == TradeSide.buy  # base was on the Buy leg
    assert swap.usd_price_source == "bitquery"
    # knowable_at must be >= event_time (no look-ahead, latency added)
    assert swap.knowable_at >= swap.event_time


def test_wallet_event_links_to_swap() -> None:
    bq = Bitquery()
    swap = bq.to_swap(TRADE_NODE, run_id="t")
    assert swap is not None
    we = bq.swap_to_wallet_event(swap)
    assert we.wallet == "wallet_xyz"
    assert we.linked_event_id == swap.event_id()


def test_pool_created_proxy_from_trade() -> None:
    bq = Bitquery()
    pc = bq.to_pool_created(TRADE_NODE, run_id="t")
    assert pc is not None
    assert pc.pool_address == "pool_market_1"
    assert pc.base_mint == "LOWCAPmint"
    assert pc.quote_mint == USDC


def test_spend_guard_blocks_network_without_authorization() -> None:
    """A fetch must raise unless enable_paid=True AND a key is present (YELLOW gate)."""
    bq = Bitquery(api_key="fake")  # key present but paid NOT enabled
    with pytest.raises(PaidSpendNotAuthorizedError):

        async def _go() -> None:
            async for _ in bq.iter_dex_trades(
                since=__import__("datetime").datetime(2026, 5, 1, tzinfo=__import__("datetime").UTC),
                till=__import__("datetime").datetime(2026, 5, 2, tzinfo=__import__("datetime").UTC),
            ):
                pass

        asyncio.run(_go())


def test_spend_guard_blocks_when_enabled_but_no_key() -> None:
    bq = Bitquery(enable_paid=True)  # paid enabled but no key
    with pytest.raises(PaidSpendNotAuthorizedError):
        bq._guard_spend()
