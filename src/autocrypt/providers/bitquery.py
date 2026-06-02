"""Bitquery adapter — SCAFFOLD (paid, key-gated). The deep-historical truth layer.

Status: built but DELIBERATELY NOT WIRED TO SPEND. As of this session the human is
HOLDING on the Bitquery purchase pending a real sales quote (pricing is custom-quoted,
not public). This module therefore ships as a provider-agnostic swap-in whose pure
mappers are complete and tested, but whose network fetchers are guarded: they refuse
to run unless the operator passes BOTH a real API key AND `enable_paid=True`, so no
paid query can fire by accident merely because a key landed in `.env`.

Design contract (Phase 1 decision): a Bitquery row maps to the SAME canonical schema
records (PoolCreated / Swap / WalletEvent) as DexPaprika — so switching the backfill
source is a swap-in, not a rewrite. The three-time discipline is identical: we stamp
`event_time` = on-chain block time and reconstruct `knowable_at = block_time + latency`
(never fetch time), exactly as backfill does for the free provider.

⚠️ Before trusting a real backfill, the GraphQL field paths below MUST be validated
against a live trial response — they reflect Bitquery's documented Solana DEXTrades
(EAP) schema (June 2026) but the trial is the source of truth, and a one-query trial
on the free tier is the right first step once spend is authorized.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from autocrypt.logging import get_logger
from autocrypt.providers.base import HTTPProvider, RetryableHTTPError
from autocrypt.schema import (
    Commitment,
    PoolCreated,
    Source,
    Swap,
    TradeSide,
    WalletAction,
    WalletEvent,
    knowable_at_for_tx,
)

log = get_logger("bitquery")

# Bitquery's Early-Access-Protocol GraphQL endpoint (Solana real-time + archive).
BITQUERY_EAP_ENDPOINT = "https://streaming.bitquery.io/eap"

# Well-known Solana quote mints (same set as the DexPaprika adapter).
SOL = "So11111111111111111111111111111111111111112"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
DEFAULT_QUOTES = (SOL, USDC)

DEFAULT_TX_LATENCY = timedelta(seconds=2)

# ── Drafted GraphQL (parameterized; validate against a live trial before bulk use) ──
#
# Survivorship-complete universe by CREATION: Bitquery exposes pool/pair creation via
# the Instructions/DEXPools feeds. The pragmatic, well-documented path is to take the
# FIRST DEXTrade per market in the window as the creation proxy (every tradeable pool
# has a first trade); a dedicated pool-creation feed can replace this once validated.
DEX_TRADES_QUERY = """
query SolanaDexTrades($since: DateTime!, $till: DateTime!, $quotes: [String!], $limit: Int!, $offset: Int!) {
  Solana(dataset: archive) {
    DEXTrades(
      where: {
        Block: { Time: { since: $since, till: $till } }
        Trade: { Side: { Currency: { MintAddress: { in: $quotes } } } }
      }
      orderBy: { ascending: Block_Time }
      limit: { count: $limit, offset: $offset }
    ) {
      Block { Time Slot }
      Transaction { Signature Signer }
      Trade {
        Dex { ProtocolName ProgramAddress }
        Market { MarketAddress }
        Buy  { Amount AmountInUSD PriceInUSD Currency { MintAddress Decimals Symbol } }
        Sell { Amount AmountInUSD PriceInUSD Currency { MintAddress Decimals Symbol } }
      }
    }
  }
}
""".strip()


def _parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _dec(v: Any) -> Decimal | None:
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None


class PaidSpendNotAuthorizedError(RuntimeError):
    """Raised when a Bitquery network call is attempted without explicit authorization.

    This is the code-level enforcement of the YELLOW spend gate: a Bitquery query costs
    money, so it may only fire when the operator has consciously enabled paid use.
    """


class Bitquery(HTTPProvider):
    """Bitquery GraphQL adapter (paid). Network fetchers are spend-gated; mappers are pure.

    Construct with `enable_paid=True` ONLY after a specific spend has been authorized
    (see Project_spec §8 / CLAUDE.md §3 YELLOW). Without it, any fetch raises
    `PaidSpendNotAuthorizedError` — the mappers below still work offline for tests.
    """

    base_url = BITQUERY_EAP_ENDPOINT
    per_minute = 10.0  # free Developer tier ceiling; raise once on a paid plan
    source = Source.bitquery

    def __init__(
        self,
        api_key: str | None = None,
        *,
        enable_paid: bool = False,
        **kwargs: Any,
    ) -> None:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        super().__init__(headers=headers, **kwargs)
        self._api_key = api_key
        self._enable_paid = enable_paid

    def _guard_spend(self) -> None:
        if not self._enable_paid:
            raise PaidSpendNotAuthorizedError(
                "Bitquery is a PAID source. Network calls are disabled until a specific "
                "spend is authorized: construct Bitquery(api_key=..., enable_paid=True) "
                "only after the YELLOW spend gate is cleared (Project_spec §8)."
            )
        if not self._api_key:
            raise PaidSpendNotAuthorizedError("BITQUERY_API_KEY is required for paid calls.")

    async def _graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        """POST a GraphQL query (spend-gated, rate-limited, retried on 429/5xx)."""
        self._guard_spend()
        await self.limiter.acquire()
        resp = await self._client.post(
            self.base_url,
            json={"query": query, "variables": variables},
            headers=self._headers,
        )
        if resp.status_code == 429 or resp.status_code >= 500:
            log.warning("bitquery_retryable", status=resp.status_code)
            raise RetryableHTTPError(f"{resp.status_code} for bitquery")
        resp.raise_for_status()
        body = resp.json()
        if body.get("errors"):
            raise RuntimeError(f"Bitquery GraphQL errors: {body['errors']}")
        return body.get("data", {})

    async def iter_dex_trades(
        self,
        since: datetime,
        till: datetime,
        *,
        quotes: tuple[str, ...] = DEFAULT_QUOTES,
        page_limit: int = 10000,
        max_pages: int = 10**6,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield raw DEXTrade nodes across the window, paged by offset. SPEND-GATED."""
        offset = 0
        for _ in range(max_pages):
            data = await self._graphql(
                DEX_TRADES_QUERY,
                {
                    "since": since.isoformat(),
                    "till": till.isoformat(),
                    "quotes": list(quotes),
                    "limit": page_limit,
                    "offset": offset,
                },
            )
            trades = (data.get("Solana") or {}).get("DEXTrades") or []
            if not trades:
                return
            for t in trades:
                yield t
            if len(trades) < page_limit:
                return
            offset += page_limit

    # ── pure mappers (no network — unit-testable offline) ───────────────────────
    @staticmethod
    def _base_quote_sides(trade: dict[str, Any], quotes: tuple[str, ...]) -> tuple[dict, dict]:
        """Return (base_side, quote_side) dicts, where the quote side's currency is a
        known quote mint. Bitquery splits each trade into Buy/Sell legs."""
        buy = trade.get("Buy") or {}
        sell = trade.get("Sell") or {}
        buy_mint = ((buy.get("Currency") or {}).get("MintAddress"))
        if buy_mint in quotes:
            # buy leg is the quote token → base is the sell leg
            return sell, buy
        return buy, sell

    def to_swap(
        self,
        trade_node: dict[str, Any],
        *,
        run_id: str,
        quotes: tuple[str, ...] = DEFAULT_QUOTES,
        latency: timedelta = DEFAULT_TX_LATENCY,
    ) -> Swap | None:
        """Map a Bitquery DEXTrade node to a canonical Swap (identical shape to DexPaprika)."""
        block = trade_node.get("Block") or {}
        txn = trade_node.get("Transaction") or {}
        trade = trade_node.get("Trade") or {}
        time_s, sig, signer = block.get("Time"), txn.get("Signature"), txn.get("Signer")
        if not (time_s and sig and signer):
            return None

        base_side, quote_side = self._base_quote_sides(trade, quotes)
        base_cur = base_side.get("Currency") or {}
        quote_cur = quote_side.get("Currency") or {}
        base_mint, quote_mint = base_cur.get("MintAddress"), quote_cur.get("MintAddress")
        if not base_mint or not quote_mint:
            return None

        # Buy/Sell legs are signed from the trade's perspective; a positive base "Buy"
        # amount means base was acquired = BUY (same convention as the DexPaprika adapter).
        is_buy = (trade.get("Buy") or {}).get("Currency", {}).get("MintAddress") == base_mint
        side = TradeSide.buy if is_buy else TradeSide.sell

        base_amt = _dec(base_side.get("Amount"))
        quote_amt = _dec(quote_side.get("Amount"))
        price_usd = _dec(base_side.get("PriceInUSD"))
        amount_usd = _dec(base_side.get("AmountInUSD"))

        event_time = _parse_dt(time_s)
        market = (trade.get("Market") or {}).get("MarketAddress")
        dex = (trade.get("Dex") or {}).get("ProtocolName")
        return Swap(
            source=self.source,
            event_time=event_time,
            knowable_at=knowable_at_for_tx(event_time, latency),
            block_slot=block.get("Slot"),
            source_ref=sig,
            ingest_run_id=run_id,
            commitment=Commitment.backfill,
            pool_address=market,
            dex=dex,
            base_mint=base_mint,
            quote_mint=quote_mint,
            signer=signer,
            side=side,
            base_amount=abs(base_amt) if base_amt is not None else None,
            quote_amount=abs(quote_amt) if quote_amt is not None else None,
            price_usd=price_usd,
            usd_price_source="bitquery",
            amount_usd=abs(amount_usd) if amount_usd is not None else None,
            tx_signature=sig,
            instruction_index=None,
        )

    def to_pool_created(
        self,
        trade_node: dict[str, Any],
        *,
        run_id: str,
        quotes: tuple[str, ...] = DEFAULT_QUOTES,
        latency: timedelta = DEFAULT_TX_LATENCY,
    ) -> PoolCreated | None:
        """Map a (first-trade-as-creation-proxy) node to a canonical PoolCreated.

        Bitquery has no single 'pool created' row for every AMM; using the first
        observed trade per market in the window is the survivorship-safe creation proxy.
        The caller is responsible for taking the EARLIEST trade per market.
        """
        block = trade_node.get("Block") or {}
        trade = trade_node.get("Trade") or {}
        time_s = block.get("Time")
        market = (trade.get("Market") or {}).get("MarketAddress")
        if not (time_s and market):
            return None
        base_side, quote_side = self._base_quote_sides(trade, quotes)
        base_cur = base_side.get("Currency") or {}
        quote_cur = quote_side.get("Currency") or {}
        if not base_cur.get("MintAddress") or not quote_cur.get("MintAddress"):
            return None
        event_time = _parse_dt(time_s)
        return PoolCreated(
            source=self.source,
            event_time=event_time,
            knowable_at=knowable_at_for_tx(event_time, latency),
            block_slot=block.get("Slot"),
            source_ref=market,
            ingest_run_id=run_id,
            commitment=Commitment.backfill,
            pool_address=market,
            dex=(trade.get("Dex") or {}).get("ProtocolName") or "unknown",
            program_id=(trade.get("Dex") or {}).get("ProgramAddress"),
            base_mint=base_cur.get("MintAddress"),
            quote_mint=quote_cur.get("MintAddress"),
            base_decimals=base_cur.get("Decimals"),
            quote_decimals=quote_cur.get("Decimals"),
        )

    @staticmethod
    def swap_to_wallet_event(swap: Swap) -> WalletEvent:
        """Project a Swap into a WalletEvent (provider-agnostic; label added in Phase 3)."""
        return WalletEvent(
            source=swap.source,
            event_time=swap.event_time,
            knowable_at=swap.knowable_at,
            block_slot=swap.block_slot,
            source_ref=swap.source_ref,
            ingest_run_id=swap.ingest_run_id,
            commitment=swap.commitment,
            wallet=swap.signer,
            action=WalletAction.buy if swap.side == TradeSide.buy else WalletAction.sell,
            base_mint=swap.base_mint,
            quote_mint=swap.quote_mint,
            pool_address=swap.pool_address,
            base_amount=swap.base_amount,
            quote_amount=swap.quote_amount,
            amount_usd=swap.amount_usd,
            tx_signature=swap.tx_signature,
            instruction_index=swap.instruction_index,
            linked_event_id=swap.event_id(),
        )
