"""DexPaprika adapter (free, no key) — the breadth + swap-level workhorse.

Used for: enumerating the pool universe by CREATION time (survivorship-safe), and
pulling per-pool swap history. Emits canonical-schema records.

LOOK-AHEAD GUARD: pool *listing/detail* fields like `last_price_usd`, `volume_usd`,
`token_reserves`, and the `24h/6h/1h` stat blocks are CURRENT (as-of-now) aggregates.
They must NOT be stored as point-in-time facts. This adapter reads only creation-time
facts (address, created_at, block number, token mints/decimals) from listings, and
otherwise relies on per-event timestamps (transactions carry their own block time).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from autocrypt.providers.base import HTTPProvider
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

# Well-known quote mints on Solana. The "base" is whatever token is NOT one of these.
SOL = "So11111111111111111111111111111111111111112"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
KNOWN_QUOTES = {SOL, USDC, USDT}

DEFAULT_TX_LATENCY = timedelta(seconds=2)  # assumed time-to-know for a stream consumer


def _parse_dt(s: str) -> datetime:
    """Parse an ISO-8601 'Z' timestamp into a tz-aware UTC datetime."""
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _dec(v: Any) -> Decimal | None:
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None


def _scaled(raw: int | None, decimals: int | None) -> Decimal | None:
    """Convert a raw integer base-unit amount to a ui Decimal using token decimals."""
    if raw is None or decimals is None:
        return None
    return Decimal(raw) / (Decimal(10) ** decimals)


class DexPaprika(HTTPProvider):
    base_url = "https://api.dexpaprika.com"
    per_minute = 120.0  # undocumented free limit; stay polite (2/sec)
    source = Source.dexpaprika
    network = "solana"

    # ── raw fetchers ──────────────────────────────────────────────────────────
    async def iter_pools_by_creation(
        self, max_pools: int, page_limit: int = 100, max_pages: int = 5000
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield Solana pools newest-first by created_at. Selection is by CREATION,
        independent of survival → includes rugged/dead pools (survivorship-safe)."""
        yielded = 0
        for page in range(1, max_pages + 1):
            data = await self.get_json(
                f"/networks/{self.network}/pools",
                params={
                    "limit": page_limit,
                    "page": page,
                    "sort": "desc",
                    "order_by": "created_at",
                },
            )
            pools = data.get("pools", []) if isinstance(data, dict) else data
            if not pools:
                return
            for p in pools:
                yield p
                yielded += 1
                if yielded >= max_pools:
                    return

    async def get_pool(self, pool_id: str) -> dict[str, Any]:
        return await self.get_json(f"/networks/{self.network}/pools/{pool_id}")

    async def iter_pool_transactions(
        self, pool_id: str, page_limit: int = 100, max_pages: int = 200
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield all swap transactions for a pool (paginated, oldest-or-newest as the
        API returns them — we stamp each by its own block time, so order is irrelevant
        for correctness)."""
        for page in range(1, max_pages + 1):
            data = await self.get_json(
                f"/networks/{self.network}/pools/{pool_id}/transactions",
                params={"limit": page_limit, "page": page},
            )
            txs = data.get("transactions", []) if isinstance(data, dict) else data
            if not txs:
                return
            for t in txs:
                yield t
            page_info = data.get("page_info", {}) if isinstance(data, dict) else {}
            if page >= page_info.get("total_pages", page):
                return

    # ── identity helpers ────────────────────────────────────────────────────────
    @staticmethod
    def _split_base_quote(token_ids: list[str]) -> tuple[str, str]:
        """Return (base_mint, quote_mint). Quote = a known quote mint; base = other."""
        quotes = [t for t in token_ids if t in KNOWN_QUOTES]
        if quotes:
            quote = quotes[0]
            base = next((t for t in token_ids if t != quote), token_ids[0])
            return base, quote
        # neither is a known quote → assume the 2nd listed is base (best effort)
        return token_ids[-1], token_ids[0]

    # ── mappers to canonical schema ──────────────────────────────────────────────
    def to_pool_created(
        self, pool: dict[str, Any], run_id: str, latency: timedelta = DEFAULT_TX_LATENCY
    ) -> PoolCreated | None:
        created = pool.get("created_at")
        if not created:
            return None
        tokens = pool.get("tokens", [])
        by_id = {t["id"]: t for t in tokens if "id" in t}
        token_ids = list(by_id.keys())
        if len(token_ids) < 2:
            return None
        base_mint, quote_mint = self._split_base_quote(token_ids)
        event_time = _parse_dt(created)
        return PoolCreated(
            source=self.source,
            event_time=event_time,
            knowable_at=knowable_at_for_tx(event_time, latency),
            block_slot=pool.get("created_at_block_number"),
            source_ref=pool.get("id"),
            ingest_run_id=run_id,
            commitment=Commitment.backfill,
            pool_address=pool["id"],
            dex=pool.get("dex_id") or pool.get("dex_name") or "unknown",
            program_id=pool.get("factory_id"),
            base_mint=base_mint,
            quote_mint=quote_mint,
            base_decimals=by_id.get(base_mint, {}).get("decimals"),
            quote_decimals=by_id.get(quote_mint, {}).get("decimals"),
        )

    def to_swap(
        self,
        tx: dict[str, Any],
        *,
        pool_address: str,
        base_mint: str,
        quote_mint: str,
        base_decimals: int | None,
        quote_decimals: int | None,
        dex: str | None,
        run_id: str,
        latency: timedelta = DEFAULT_TX_LATENCY,
    ) -> Swap | None:
        created = tx.get("created_at")
        sig = tx.get("id")
        signer = tx.get("sender")
        if not (created and sig and signer):
            return None

        # Identify which token slot is the base.
        t0 = tx.get("token_0")
        if base_mint == t0:
            base_amt_raw, quote_amt_raw = tx.get("amount_0"), tx.get("amount_1")
            base_price_usd = tx.get("price_0_usd")
        else:
            base_amt_raw, quote_amt_raw = tx.get("amount_1"), tx.get("amount_0")
            base_price_usd = tx.get("price_1_usd")

        base_amt_raw = int(base_amt_raw) if base_amt_raw is not None else None
        quote_amt_raw = int(quote_amt_raw) if quote_amt_raw is not None else None

        # Sign convention (TRADER-perspective delta, verified empirically against price
        # direction on live data: positive base delta coincides with price UP → buy).
        # A positive base amount means the trader's base balance increased = BOUGHT.
        side = TradeSide.sell
        if base_amt_raw is not None:
            side = TradeSide.buy if base_amt_raw > 0 else TradeSide.sell

        base_ui = _scaled(abs(base_amt_raw) if base_amt_raw is not None else None, base_decimals)
        quote_ui = _scaled(
            abs(quote_amt_raw) if quote_amt_raw is not None else None, quote_decimals
        )
        price_usd = _dec(base_price_usd)
        amount_usd = (base_ui * price_usd) if (base_ui is not None and price_usd) else None

        event_time = _parse_dt(created)
        return Swap(
            source=self.source,
            event_time=event_time,
            knowable_at=knowable_at_for_tx(event_time, latency),
            block_slot=tx.get("created_at_block_number"),
            source_ref=sig,
            ingest_run_id=run_id,
            commitment=Commitment.backfill,
            pool_address=pool_address,
            dex=dex,
            base_mint=base_mint,
            quote_mint=quote_mint,
            signer=signer,
            side=side,
            base_amount_raw=abs(base_amt_raw) if base_amt_raw is not None else None,
            quote_amount_raw=abs(quote_amt_raw) if quote_amt_raw is not None else None,
            base_amount=base_ui,
            quote_amount=quote_ui,
            price_usd=price_usd,
            usd_price_source="dexpaprika",
            amount_usd=amount_usd,
            tx_signature=sig,
            instruction_index=tx.get("log_index"),
        )

    @staticmethod
    def swap_to_wallet_event(swap: Swap) -> WalletEvent:
        """Project a Swap into a per-wallet activity record (attribution input).
        The 'is this a leading wallet' LABEL is added later (Phase 3), as-of knowable_at."""
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
