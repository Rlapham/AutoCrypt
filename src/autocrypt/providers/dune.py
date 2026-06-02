"""Dune adapter — the FREE, survivorship-complete historical archive (Phase 2c PRIMARY).

Promoted from "cross-check" to PRIMARY in this session: Flipside's free self-serve
signup is effectively closed (enterprise/demo model as of June 2026), whereas Dune's
free tier is open self-signup and publicly committed for 2026. See
docs/provider-evaluation.md → "Phase 2c addendum (revised)".

Status: built; pure mappers complete and tested offline. The network layer drives the
Dune **Execution API** (execute saved query → poll status → page results) and is
**key-gated** — it refuses to fire without a Dune API key. Dune is FREE (Community
tier), so the guard is a missing-key guard, NOT a spend gate.

Why Dune: `dex_solana.trades` (Spellbook curated) is a DECODED, USD-enriched swap table
covering Raydium/Orca/Meteora/Jupiter/etc across **all** tokens and deep history. Because
it indexes every on-chain swap, dead/rugged tokens are present **by construction** —
exactly the Project_spec §4.1 survivorship requirement, at $0.

Design contract: a Dune row maps to the SAME canonical schema records (Swap /
PoolCreated / WalletEvent) as DexPaprika / Bitquery / Flipside — switching the backfill
source is a swap-in, not a rewrite. The three-time discipline is identical: `event_time`
= on-chain `block_time`, `knowable_at = block_time + latency` (NEVER fetch time).

FREE-TIER ACCESS MODEL (important): Dune's free tier executes **saved queries by ID**
(ad-hoc SQL creation via API is a paid feature). So the workflow is:
  1. Operator pastes `DEX_TRADES_SQL` (below) into a new Dune query, with `{{since}}`,
     `{{till}}` as Dune **parameters**, and saves it → gets a numeric `query_id`.
  2. We call `iter_trade_rows(query_id, since, till, ...)` which executes that saved
     query with those parameters, polls, and pages the results.

⚠️ TWO things MUST be validated against ONE real free execution before a bulk backfill
is trusted (the Phase 2c validation step, now against Dune):
  1. **Field paths.** Column names below reflect the documented Solana `dex_solana.trades`
     schema (June 2026): block_time, block_slot, tx_id, trader_id,
     token_bought_mint_address / token_bought_amount, token_sold_mint_address /
     token_sold_amount, amount_usd, project, project_program_id. The live result is the
     source of truth (Dune returns lower-cased keys; we normalize regardless).
  2. **No native pool address.** `dex_solana.trades` carries no single pool/market
     address; we derive a deterministic **surrogate market key** per
     (base_mint, quote_mint, project) and take each market's FIRST trade as the
     PoolCreated creation proxy. `_pool_key()` prefers a real pool column if one exists.
  3. **Credit cap.** Dune free is credit-metered (~2,500 credits/mo); a full 14d pull may
     exceed it. The validation execution measures actual cost/row-count to report honestly.
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

log = get_logger("dune")

# Dune REST API base (Execution API). Auth via the X-Dune-Api-Key header.
DUNE_API_BASE = "https://api.dune.com/api/v1"

# Well-known Solana quote mints (same set as the other adapters).
SOL = "So11111111111111111111111111111111111111112"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
DEFAULT_QUOTES = (SOL, USDC)

DEFAULT_TX_LATENCY = timedelta(seconds=2)  # assumed time-to-know (backfill reconstruction)

# Candidate field names for a real pool/market address, if the schema exposes one.
# `dex_solana.trades` documents none today; checked first so the adapter upgrades for free.
_POOL_FIELDS = ("pool_address", "pool_id", "amm", "pool")

# ── SQL to SAVE as a Dune query (free tier executes saved queries by ID) ──────────────
#
# Paste this into a new Dune query, declare `since`/`till` as TIMESTAMP parameters
# (Dune `{{since}}` / `{{till}}`), save, and pass the resulting query_id to
# iter_trade_rows(). Survivorship-complete by CREATION: take each market's FIRST trade as
# the creation proxy; we keep every trade whose bought/sold mint is a known quote
# (SOL/USDC) — the SOL+USDC-quoted universe (Project_spec §3), rugs/duds included.
DEX_TRADES_SQL = """
SELECT
  block_time,
  block_slot,
  tx_id,
  trader_id,
  token_bought_mint_address,
  token_bought_amount,
  token_sold_mint_address,
  token_sold_amount,
  amount_usd,
  project,
  project_program_id
FROM dex_solana.trades
WHERE block_time >= TRY_CAST('{{since}}' AS TIMESTAMP)
  AND block_time <  TRY_CAST('{{till}}'  AS TIMESTAMP)
  AND (
        token_bought_mint_address IN ('So11111111111111111111111111111111111111112',
                                      'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v')
     OR token_sold_mint_address   IN ('So11111111111111111111111111111111111111112',
                                      'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v')
      )
ORDER BY block_time ASC
""".strip()


def _parse_dt(s: str) -> datetime:
    """Parse an ISO-8601 / space-separated timestamp into tz-aware UTC.

    Dune returns UTC; a naive (offset-less) string is UTC by convention, so we attach
    UTC rather than let a naive timestamp through (the schema rejects naive, and a wrong
    tz would corrupt the knowable_at gate)."""
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
    return {k.lower(): v for k, v in row.items()}


class DuneKeyNotConfiguredError(RuntimeError):
    """Raised when a Dune network call is attempted without an API key.

    Dune is FREE (Community tier), so this is NOT a spend gate — it enforces that a (free)
    key has been provisioned into `.env` before any network call. The pure mappers below
    work offline without a key (for tests)."""


class Dune(HTTPProvider):
    """Dune Execution API adapter (FREE). Network layer is key-gated; mappers are pure.

    Construct with `api_key=...` (free Community key from dune.com → Settings → API,
    stored in `.env` as DUNE_API_KEY). Without a key, any network call raises
    `DuneKeyNotConfiguredError`; the mappers still run offline.
    """

    base_url = DUNE_API_BASE
    per_minute = 40.0  # polite default; Dune free allows a few req/sec — re-tune after validation
    source = Source.dune

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        headers = {"X-Dune-Api-Key": api_key} if api_key else {}
        super().__init__(headers=headers, **kwargs)
        self._api_key = api_key

    def _guard_key(self) -> None:
        if not self._api_key:
            raise DuneKeyNotConfiguredError(
                "DUNE_API_KEY is required. Dune is FREE (Community tier) — create a key at "
                "dune.com → Settings → API and put it in .env (never commit). Then construct "
                "Dune(api_key=settings...). Mappers work offline without a key."
            )

    # ── network: execute saved query → poll → page (validate against a live run) ──────
    async def _post(self, path: str, json_body: dict[str, Any]) -> dict[str, Any]:
        self._guard_key()
        await self.limiter.acquire()
        resp = await self._client.post(
            f"{self.base_url}{path}", json=json_body, headers=self._headers
        )
        if resp.status_code == 429 or resp.status_code >= 500:
            log.warning("dune_retryable", status=resp.status_code, path=path)
            raise RetryableHTTPError(f"{resp.status_code} for dune {path}")
        resp.raise_for_status()
        return resp.json()

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._guard_key()
        await self.limiter.acquire()
        resp = await self._client.get(
            f"{self.base_url}{path}", params=params, headers=self._headers
        )
        if resp.status_code == 429 or resp.status_code >= 500:
            log.warning("dune_retryable", status=resp.status_code, path=path)
            raise RetryableHTTPError(f"{resp.status_code} for dune {path}")
        resp.raise_for_status()
        return resp.json()

    async def execute_query(
        self, query_id: int, *, parameters: dict[str, str], performance: str = "medium"
    ) -> str:
        """Execute a saved Dune query with parameters; return the execution_id. SPEND = $0."""
        body = {"query_parameters": parameters, "performance": performance}
        result = await self._post(f"/query/{query_id}/execute", body)
        execution_id = result.get("execution_id")
        if not execution_id:
            raise RuntimeError(f"Dune execute returned no execution_id: {result}")
        return execution_id

    async def wait_for_execution(
        self, execution_id: str, *, poll_interval_s: float = 2.0, max_polls: int = 900
    ) -> None:
        """Poll an execution until terminal; raise on failure/timeout."""
        for _ in range(max_polls):
            result = await self._get(f"/execution/{execution_id}/status")
            state = result.get("state")
            if state == "QUERY_STATE_COMPLETED":
                return
            if state in ("QUERY_STATE_FAILED", "QUERY_STATE_CANCELLED", "QUERY_STATE_EXPIRED"):
                raise RuntimeError(f"Dune execution {execution_id} ended in state {state}")
            await asyncio.sleep(poll_interval_s)
        raise RuntimeError(f"Dune execution {execution_id} did not finish in time")

    async def iter_trade_rows(
        self,
        query_id: int,
        since: datetime,
        till: datetime,
        *,
        page_size: int = 5000,
        max_rows: int = 10**7,
    ) -> AsyncIterator[dict[str, Any]]:
        """Execute the saved DEX-trades query for the window and yield each row.

        KEY-GATED. Drives the full lifecycle: execute → poll → paginate (limit/offset). The
        client-side `max_rows` is a safety ceiling, NOT a survivorship filter — hitting it
        means a free-tier cap to report honestly, not a result to trust.
        """
        params = {
            "since": since.strftime("%Y-%m-%d %H:%M:%S"),
            "till": till.strftime("%Y-%m-%d %H:%M:%S"),
        }
        execution_id = await self.execute_query(query_id, parameters=params)
        await self.wait_for_execution(execution_id)

        yielded, offset = 0, 0
        while yielded < max_rows:
            result = await self._get(
                f"/execution/{execution_id}/results",
                params={"limit": page_size, "offset": offset},
            )
            rows = (result.get("result") or {}).get("rows") or []
            if not rows:
                return
            for row in rows:
                yield _lower_keys(row) if isinstance(row, dict) else row
                yielded += 1
                if yielded >= max_rows:
                    log.warning("dune_max_rows_hit", max_rows=max_rows)
                    return
            if len(rows) < page_size or result.get("next_offset") is None:
                return
            offset = result["next_offset"]

    # ── identity helpers ─────────────────────────────────────────────────────────────
    @staticmethod
    def _split_base_quote(
        bought_mint: str, sold_mint: str, quotes: tuple[str, ...]
    ) -> tuple[str, str, bool] | None:
        """Return (base_mint, quote_mint, base_is_bought) or None if no quote present.

        `base_is_bought` is True when the trader RECEIVED the base token (a BUY of base).
        """
        if sold_mint in quotes and bought_mint not in quotes:
            # paid a quote → bought base; base is the BOUGHT side
            return bought_mint, sold_mint, True
        if bought_mint in quotes and sold_mint not in quotes:
            # received a quote → sold base; base is the SOLD side
            return sold_mint, bought_mint, False
        # quote↔quote (or non-quote↔non-quote): not a low-cap launch trade — skip
        return None

    @staticmethod
    def _pool_key(row: dict[str, Any], base_mint: str, quote_mint: str) -> str:
        """Real pool address if the schema exposes one; else a deterministic surrogate
        market key per (base, quote, project). Documented limitation: see module docstring."""
        for f in _POOL_FIELDS:
            v = row.get(f)
            if v:
                return str(v)
        project = row.get("project") or "unknown"
        return f"dune:{project}:{base_mint}/{quote_mint}"

    # ── pure mappers to canonical schema (no network — unit-testable offline) ─────────
    def to_swap(
        self,
        row: dict[str, Any],
        *,
        run_id: str,
        quotes: tuple[str, ...] = DEFAULT_QUOTES,
        latency: timedelta = DEFAULT_TX_LATENCY,
    ) -> Swap | None:
        """Map a Dune dex_solana.trades row to a canonical Swap (same shape as DexPaprika)."""
        row = _lower_keys(row)
        ts = row.get("block_time")
        sig = row.get("tx_id")
        signer = row.get("trader_id")
        bought_mint = row.get("token_bought_mint_address")
        sold_mint = row.get("token_sold_mint_address")
        if not (ts and sig and signer and bought_mint and sold_mint):
            return None

        split = self._split_base_quote(bought_mint, sold_mint, quotes)
        if split is None:
            return None
        base_mint, quote_mint, base_is_bought = split

        side = TradeSide.buy if base_is_bought else TradeSide.sell
        if base_is_bought:
            base_amt = _dec(row.get("token_bought_amount"))
            quote_amt = _dec(row.get("token_sold_amount"))
        else:
            base_amt = _dec(row.get("token_sold_amount"))
            quote_amt = _dec(row.get("token_bought_amount"))
        amount_usd = _dec(row.get("amount_usd"))
        price_usd = (amount_usd / base_amt) if (amount_usd and base_amt and base_amt != 0) else None

        event_time = _parse_dt(ts)
        return Swap(
            source=self.source,
            event_time=event_time,
            knowable_at=knowable_at_for_tx(event_time, latency),
            block_slot=row.get("block_slot"),
            source_ref=sig,
            ingest_run_id=run_id,
            commitment=Commitment.backfill,
            pool_address=self._pool_key(row, base_mint, quote_mint),
            dex=row.get("project"),
            base_mint=base_mint,
            quote_mint=quote_mint,
            signer=signer,
            side=side,
            base_amount=abs(base_amt) if base_amt is not None else None,
            quote_amount=abs(quote_amt) if quote_amt is not None else None,
            price_usd=price_usd,
            usd_price_source="dune",
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
        """Map a (first-trade-as-creation-proxy) row to a canonical PoolCreated.

        `dex_solana.trades` has no pool-creation row, so the caller must pass the EARLIEST
        trade per (surrogate) market; this stamps that as the pool's creation."""
        row = _lower_keys(row)
        ts = row.get("block_time")
        bought_mint = row.get("token_bought_mint_address")
        sold_mint = row.get("token_sold_mint_address")
        if not (ts and bought_mint and sold_mint):
            return None
        split = self._split_base_quote(bought_mint, sold_mint, quotes)
        if split is None:
            return None
        base_mint, quote_mint, _ = split
        event_time = _parse_dt(ts)
        return PoolCreated(
            source=self.source,
            event_time=event_time,
            knowable_at=knowable_at_for_tx(event_time, latency),
            block_slot=row.get("block_slot"),
            source_ref=self._pool_key(row, base_mint, quote_mint),
            ingest_run_id=run_id,
            commitment=Commitment.backfill,
            pool_address=self._pool_key(row, base_mint, quote_mint),
            dex=row.get("project") or "unknown",
            program_id=row.get("project_program_id") or row.get("program_id"),
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
