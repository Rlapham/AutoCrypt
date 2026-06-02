"""Flipside adapter — the FREE, survivorship-complete historical archive (Phase 2c).

Status: built; pure mappers are complete and tested offline. The network layer drives
the Flipside **Data API** (JSON-RPC: create-run → poll → page results) and is
**key-gated** — it refuses to fire without a Flipside API key. Unlike Bitquery this
source is **FREE** (Community tier), so the guard is a missing-key guard, NOT a spend
gate; there is no `enable_paid` flag because no money is at stake.

Why Flipside (see docs/provider-evaluation.md → "Phase 2c addendum"): `solana.defi.
ez_dex_swaps` is a DECODED, USD-enriched swap table covering Raydium/Orca/Meteora/
PumpSwap/Jupiter across **all** tokens and deep history. Because it indexes every
on-chain swap, dead/rugged tokens are present **by construction** — exactly the
Project_spec §4.1 survivorship requirement, at $0. It is *better* survivorship than our
DexPaprika "currently-listed pools" view.

Design contract (Phase 1/2c decision): a Flipside row maps to the SAME canonical schema
records (Swap / PoolCreated / WalletEvent) as DexPaprika & Bitquery — so switching the
backfill source is a swap-in, not a rewrite. The three-time discipline is identical: we
stamp `event_time` = on-chain `block_timestamp` and reconstruct
`knowable_at = block_time + latency` (NEVER fetch time), exactly as backfill must.

⚠️ TWO things MUST be validated against ONE real free query before a bulk backfill is
trusted (this is the explicit Phase 2c validation step):
  1. **Field paths.** Column names below reflect the documented `ez_dex_swaps` schema
     (June 2026): BLOCK_TIMESTAMP, BLOCK_ID, TX_ID, SWAPPER, SWAP_FROM_MINT/AMOUNT(_USD),
     SWAP_TO_MINT/AMOUNT(_USD), SWAP_PROGRAM, PROGRAM_ID. The live response is the source
     of truth (column casing arrives lower-cased from the API).
  2. **No native pool address.** `ez_dex_swaps` carries NO pool/market address. We
     therefore derive a deterministic **surrogate market key** per
     (base_mint, quote_mint, swap_program) so swaps of one launch group into one "pool",
     and take each market's FIRST swap as the PoolCreated creation proxy. If the live
     schema turns out to expose a real pool column, `_pool_key()` picks it up first.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
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

log = get_logger("flipside")

# Flipside Data API JSON-RPC endpoint (Community/free tier authenticates with an api key).
FLIPSIDE_RPC_ENDPOINT = "https://api-v2.flipsidecrypto.xyz/json-rpc"

# Well-known Solana quote mints (same set as the other adapters).
SOL = "So11111111111111111111111111111111111111112"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
DEFAULT_QUOTES = (SOL, USDC)

DEFAULT_TX_LATENCY = timedelta(seconds=2)  # assumed time-to-know (backfill reconstruction)

# Candidate field names for a real pool/market address, if the live schema exposes one.
# `ez_dex_swaps` documents NONE of these today; checked first so the adapter upgrades for
# free if a future column appears, otherwise we fall back to a surrogate key.
_POOL_FIELDS = ("pool_address", "pool_id", "market_address", "pool")

# ── Parameterized SQL (validate against ONE free run before bulk use) ────────────────
#
# Survivorship-complete universe by CREATION: take the FIRST swap per market in the
# window as the creation proxy (every tradeable launch has a first swap). We pull every
# swap whose FROM- or TO-mint is a known quote (SOL/USDC) — that is the SOL+USDC-quoted
# universe from Project_spec §3, dead/rugged tokens included by construction.
#
# {since}/{till}/{quote_list} are substituted by the caller. We intentionally do NOT
# LIMIT here so survivorship is complete; the free-tier ROW CAP is what the validation
# query measures (and `max_rows` enforces a safety ceiling on the client side).
DEX_SWAPS_SQL = """
SELECT
  block_timestamp,
  block_id,
  tx_id,
  swapper,
  swap_from_mint,
  swap_from_amount,
  swap_from_amount_usd,
  swap_to_mint,
  swap_to_amount,
  swap_to_amount_usd,
  swap_program,
  program_id
FROM solana.defi.ez_dex_swaps
WHERE block_timestamp >= '{since}'
  AND block_timestamp <  '{till}'
  AND succeeded = TRUE
  AND (swap_from_mint IN ({quote_list}) OR swap_to_mint IN ({quote_list}))
ORDER BY block_timestamp ASC
""".strip()


def _parse_dt(s: str) -> datetime:
    """Parse an ISO-8601 timestamp into a tz-aware UTC datetime.

    Flipside returns either ISO-8601 with 'Z' or a space-separated naive string; the
    latter is UTC by convention, so we attach UTC when no offset is present (never let a
    naive timestamp through — the schema rejects it, and a wrong tz would corrupt the gate).
    """
    s = s.strip()
    s = s.replace(" ", "T", 1) if " " in s and "T" not in s else s
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _dec(v: Any) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None


def _lower_keys(row: dict[str, Any]) -> dict[str, Any]:
    """Flipside returns column names in varying case; normalize to lower-case keys."""
    return {k.lower(): v for k, v in row.items()}


class FlipsideKeyNotConfiguredError(RuntimeError):
    """Raised when a Flipside network call is attempted without an API key.

    Flipside is FREE (Community tier), so this is NOT a spend gate — it just enforces
    that a (free) key has been provisioned into `.env` before any network call. The
    pure mappers below work offline without a key (for tests).
    """


class Flipside(HTTPProvider):
    """Flipside Data API adapter (FREE). Network layer is key-gated; mappers are pure.

    Construct with `api_key=...` (free Community key from app.flipsidecrypto.com →
    Settings → API Keys, stored in `.env` as FLIPSIDE_API_KEY). Without a key, any
    network call raises `FlipsideKeyNotConfiguredError`; the mappers still run offline.
    """

    base_url = FLIPSIDE_RPC_ENDPOINT
    per_minute = 30.0  # polite default for the Community tier; re-tune after validation
    source = Source.flipside

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        # Flipside authenticates the JSON-RPC endpoint with an `x-api-key` header.
        headers = {"x-api-key": api_key, "Content-Type": "application/json"} if api_key else {}
        super().__init__(headers=headers, **kwargs)
        self._api_key = api_key
        self._rpc_id = 0

    def _guard_key(self) -> None:
        if not self._api_key:
            raise FlipsideKeyNotConfiguredError(
                "FLIPSIDE_API_KEY is required. Flipside is FREE (Community tier) — create "
                "a key at app.flipsidecrypto.com → Settings → API Keys and put it in .env "
                "(never commit). Then construct Flipside(api_key=settings...). Mappers work "
                "offline without a key."
            )

    # ── network: JSON-RPC create-run → poll → page (validate against a live run) ──────
    async def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """POST a single JSON-RPC call (key-gated, rate-limited, retried on 429/5xx)."""
        self._guard_key()
        await self.limiter.acquire()
        self._rpc_id += 1
        resp = await self._client.post(
            self.base_url,
            json={"jsonrpc": "2.0", "method": method, "params": [params], "id": self._rpc_id},
            headers=self._headers,
        )
        if resp.status_code == 429 or resp.status_code >= 500:
            log.warning("flipside_retryable", status=resp.status_code, method=method)
            raise RetryableHTTPError(f"{resp.status_code} for flipside {method}")
        resp.raise_for_status()
        body = resp.json()
        if body.get("error"):
            raise RuntimeError(f"Flipside JSON-RPC error ({method}): {body['error']}")
        return body.get("result", {})

    async def create_query_run(self, sql: str, *, ttl_minutes: int = 60) -> str:
        """Submit a SQL query; return its queryRunId. Free Community tier. SPEND = $0."""
        result = await self._rpc(
            "createQueryRun",
            {
                "resultTTLHours": 1,
                "maxAgeMinutes": ttl_minutes,
                "sql": sql,
                "tags": {"source": "autocrypt", "phase": "2c"},
                "dataSource": "snowflake-default",
                "dataProvider": "flipside",
            },
        )
        run = result.get("queryRun") or {}
        run_id = run.get("id")
        if not run_id:
            raise RuntimeError(f"Flipside createQueryRun returned no id: {result}")
        return run_id

    async def wait_for_query(
        self, query_run_id: str, *, poll_interval_s: float = 2.0, max_polls: int = 600
    ) -> None:
        """Poll a query run until it reaches a terminal state; raise on failure/timeout."""
        for _ in range(max_polls):
            result = await self._rpc("getQueryRun", {"queryRunId": query_run_id})
            state = (result.get("queryRun") or {}).get("state")
            if state == "QUERY_STATE_SUCCESS":
                return
            if state in ("QUERY_STATE_FAILED", "QUERY_STATE_CANCELED"):
                raise RuntimeError(f"Flipside query {query_run_id} ended in state {state}")
            await asyncio.sleep(poll_interval_s)
        raise RuntimeError(f"Flipside query {query_run_id} did not finish in time")

    async def iter_swap_rows(
        self,
        since: datetime,
        till: datetime,
        *,
        quotes: tuple[str, ...] = DEFAULT_QUOTES,
        page_size: int = 10000,
        max_rows: int = 10**7,
    ) -> AsyncIterator[dict[str, Any]]:
        """Run the DEX-swaps query for the window and yield each row (lower-cased keys).

        KEY-GATED. Drives the full Data API lifecycle: create → poll → paginate. The
        client-side `max_rows` is a safety ceiling, NOT a survivorship filter — if a real
        pull hits it, that is a free-tier cap to report honestly, not a result to trust.
        """
        quote_list = ", ".join(f"'{q}'" for q in quotes)
        sql = DEX_SWAPS_SQL.format(
            since=since.strftime("%Y-%m-%d %H:%M:%S"),
            till=till.strftime("%Y-%m-%d %H:%M:%S"),
            quote_list=quote_list,
        )
        run_id = await self.create_query_run(sql)
        await self.wait_for_query(run_id)

        yielded, page = 0, 1
        while yielded < max_rows:
            result = await self._rpc(
                "getQueryRunResults",
                {"queryRunId": run_id, "format": "json", "page": {"number": page, "size": page_size}},
            )
            rows = result.get("rows") or []
            if not rows:
                return
            for row in rows:
                yield _lower_keys(row) if isinstance(row, dict) else row
                yielded += 1
                if yielded >= max_rows:
                    log.warning("flipside_max_rows_hit", max_rows=max_rows)
                    return
            if len(rows) < page_size:
                return
            page += 1

    # ── identity helpers ─────────────────────────────────────────────────────────────
    @staticmethod
    def _split_base_quote(
        from_mint: str, to_mint: str, quotes: tuple[str, ...]
    ) -> tuple[str, str, bool] | None:
        """Return (base_mint, quote_mint, base_is_to_side) or None if no quote present.

        `base_is_to_side` is True when the swapper RECEIVED the base token (a BUY of base).
        """
        if to_mint in quotes and from_mint not in quotes:
            # received a quote → sold base; base is the FROM side
            return from_mint, to_mint, False
        if from_mint in quotes and to_mint not in quotes:
            # paid a quote → bought base; base is the TO side
            return to_mint, from_mint, True
        if from_mint in quotes and to_mint in quotes:
            # quote↔quote swap (e.g. SOL→USDC): not a low-cap launch trade — skip
            return None
        return None

    @staticmethod
    def _pool_key(row: dict[str, Any], base_mint: str, quote_mint: str) -> str:
        """Real pool address if the live schema exposes one; else a deterministic
        surrogate market key per (base, quote, program). Documented limitation: see module
        docstring — `ez_dex_swaps` has no native pool address."""
        for f in _POOL_FIELDS:
            v = row.get(f)
            if v:
                return str(v)
        program = row.get("swap_program") or "unknown"
        return f"flipside:{program}:{base_mint}/{quote_mint}"

    # ── pure mappers to canonical schema (no network — unit-testable offline) ─────────
    def to_swap(
        self,
        row: dict[str, Any],
        *,
        run_id: str,
        quotes: tuple[str, ...] = DEFAULT_QUOTES,
        latency: timedelta = DEFAULT_TX_LATENCY,
    ) -> Swap | None:
        """Map a Flipside ez_dex_swaps row to a canonical Swap (same shape as DexPaprika)."""
        row = _lower_keys(row)
        ts = row.get("block_timestamp")
        sig = row.get("tx_id")
        signer = row.get("swapper")
        from_mint = row.get("swap_from_mint")
        to_mint = row.get("swap_to_mint")
        if not (ts and sig and signer and from_mint and to_mint):
            return None

        split = self._split_base_quote(from_mint, to_mint, quotes)
        if split is None:
            return None
        base_mint, quote_mint, base_is_to_side = split

        # Direction = trader perspective: received base → BUY, gave base → SELL.
        side = TradeSide.buy if base_is_to_side else TradeSide.sell
        if base_is_to_side:
            base_amt = _dec(row.get("swap_to_amount"))
            quote_amt = _dec(row.get("swap_from_amount"))
            amount_usd = _dec(row.get("swap_to_amount_usd")) or _dec(row.get("swap_from_amount_usd"))
        else:
            base_amt = _dec(row.get("swap_from_amount"))
            quote_amt = _dec(row.get("swap_to_amount"))
            amount_usd = _dec(row.get("swap_from_amount_usd")) or _dec(row.get("swap_to_amount_usd"))

        price_usd = (amount_usd / base_amt) if (amount_usd and base_amt and base_amt != 0) else None

        event_time = _parse_dt(ts)
        return Swap(
            source=self.source,
            event_time=event_time,
            knowable_at=knowable_at_for_tx(event_time, latency),
            block_slot=row.get("block_id"),
            source_ref=sig,
            ingest_run_id=run_id,
            commitment=Commitment.backfill,
            pool_address=self._pool_key(row, base_mint, quote_mint),
            dex=row.get("swap_program"),
            base_mint=base_mint,
            quote_mint=quote_mint,
            signer=signer,
            side=side,
            base_amount=abs(base_amt) if base_amt is not None else None,
            quote_amount=abs(quote_amt) if quote_amt is not None else None,
            price_usd=price_usd,
            usd_price_source="flipside",
            amount_usd=abs(amount_usd) if amount_usd is not None else None,
            tx_signature=sig,
            instruction_index=None,
        )

    def to_pool_created(
        self,
        row: dict[str, Any],
        *,
        run_id: str,
        quotes: tuple[str, ...] = DEFAULT_QUOTES,
        latency: timedelta = DEFAULT_TX_LATENCY,
    ) -> PoolCreated | None:
        """Map a (first-swap-as-creation-proxy) row to a canonical PoolCreated.

        Flipside `ez_dex_swaps` has no pool-creation row, so the caller must pass the
        EARLIEST swap per (surrogate) market; this stamps that as the pool's creation.
        """
        row = _lower_keys(row)
        ts = row.get("block_timestamp")
        from_mint = row.get("swap_from_mint")
        to_mint = row.get("swap_to_mint")
        if not (ts and from_mint and to_mint):
            return None
        split = self._split_base_quote(from_mint, to_mint, quotes)
        if split is None:
            return None
        base_mint, quote_mint, _ = split
        event_time = _parse_dt(ts)
        return PoolCreated(
            source=self.source,
            event_time=event_time,
            knowable_at=knowable_at_for_tx(event_time, latency),
            block_slot=row.get("block_id"),
            source_ref=self._pool_key(row, base_mint, quote_mint),
            ingest_run_id=run_id,
            commitment=Commitment.backfill,
            pool_address=self._pool_key(row, base_mint, quote_mint),
            dex=row.get("swap_program") or "unknown",
            program_id=row.get("program_id"),
            base_mint=base_mint,
            quote_mint=quote_mint,
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
