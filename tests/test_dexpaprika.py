"""Tests for the DexPaprika adapter mappers (no network — synthetic fixtures).

Pins the empirically-verified side convention: a POSITIVE base-token delta (trader's
base balance increased) is a BUY. This was validated against live price direction
(buys coincide with price up); the test guards against a silent regression.
"""

from __future__ import annotations

from decimal import Decimal

from autocrypt.providers.dexpaprika import SOL, DexPaprika
from autocrypt.schema import TradeSide, WalletAction

BASE = "BASEmint11111111111111111111111111111111111"

POOL = {
    "id": "POOL1",
    "dex_id": "pumpfun",
    "factory_id": "FACTORY",
    "created_at": "2026-05-20T00:00:00Z",
    "created_at_block_number": 1000,
    "tokens": [
        {"id": SOL, "symbol": "SOL", "decimals": 9},
        {"id": BASE, "symbol": "DOGE2", "decimals": 6},
    ],
}


def _tx(base_amount: int) -> dict:
    return {
        "id": "SIG",
        "sender": "WALLET1",
        "created_at": "2026-05-20T00:01:00Z",
        "created_at_block_number": 1001,
        "token_0": SOL,
        "token_1": BASE,
        "amount_0": -base_amount // 2,  # opposite sign to base (trader perspective)
        "amount_1": base_amount,
        "price_1_usd": "0.5",
        "log_index": 7,
    }


def test_pool_created_splits_base_quote() -> None:
    dp = DexPaprika()
    pc = dp.to_pool_created(POOL, run_id="t")
    assert pc is not None
    assert pc.base_mint == BASE
    assert pc.quote_mint == SOL
    assert pc.base_decimals == 6
    assert pc.dex == "pumpfun"
    assert pc.knowable_at > pc.event_time  # latency applied


def test_positive_base_delta_is_buy() -> None:
    dp = DexPaprika()
    swap = dp.to_swap(
        _tx(5000),
        pool_address="POOL1",
        base_mint=BASE,
        quote_mint=SOL,
        base_decimals=6,
        quote_decimals=9,
        dex="pumpfun",
        run_id="t",
    )
    assert swap is not None
    assert swap.side == TradeSide.buy
    assert swap.base_amount_raw == 5000  # stored as magnitude
    assert swap.base_amount == Decimal(5000) / Decimal(10**6)
    assert swap.signer == "WALLET1"
    assert swap.instruction_index == 7


def test_negative_base_delta_is_sell() -> None:
    dp = DexPaprika()
    swap = dp.to_swap(
        _tx(-5000),
        pool_address="POOL1",
        base_mint=BASE,
        quote_mint=SOL,
        base_decimals=6,
        quote_decimals=9,
        dex="pumpfun",
        run_id="t",
    )
    assert swap is not None
    assert swap.side == TradeSide.sell


def test_swap_to_wallet_event_links_and_labels() -> None:
    dp = DexPaprika()
    swap = dp.to_swap(
        _tx(5000),
        pool_address="POOL1",
        base_mint=BASE,
        quote_mint=SOL,
        base_decimals=6,
        quote_decimals=9,
        dex="pumpfun",
        run_id="t",
    )
    assert swap is not None
    we = dp.swap_to_wallet_event(swap)
    assert we.action == WalletAction.buy
    assert we.wallet == "WALLET1"
    assert we.linked_event_id == swap.event_id()
    assert we.knowable_at == swap.knowable_at
