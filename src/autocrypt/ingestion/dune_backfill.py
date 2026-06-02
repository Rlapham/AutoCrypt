"""Dune backfill + validation — turn the FREE `dex_solana.trades` archive into events.

This is the ingestion glue the kill-gate needs. It drives the (key-gated, $0) Dune
Execution API through `providers.dune.Dune` and writes Swap / WalletEvent / PoolCreated
records into the same DuckDB store the profiler reads. Two entry points:

- `validate_dune()` — ONE small-window execution that confirms FIELD PATHS against a real
  pull, measures row volume + execution metadata (the free-tier-cost proxy), and reports
  SURVIVORSHIP breadth (distinct base mints / dead-token presence). Run this FIRST: the
  whole Phase-2c/2d plan gates the bulk backfill on it (see docs/provider-evaluation.md).
- `run_dune_backfill()` — the full windowed pull. Streams time-ordered trade rows, emits a
  PoolCreated *creation-proxy* the first time each surrogate market appears, plus a
  Swap + WalletEvent per trade. Idempotent (the store dedups on `event_id`).

Both reconstruct `knowable_at = block_time + latency` (NEVER fetch time), identical to the
forward-collector, so Dune-backfilled rows and live-collected rows stay directly comparable
(Project_spec §4.2, the no-look-ahead rule). Nothing here drops a token for dying: the
universe is every market that traded in the window, rugs and duds included by construction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from autocrypt.providers.dune import _POOL_FIELDS, DEFAULT_TX_LATENCY, Dune
from autocrypt.schema import BaseEvent
from autocrypt.storage.store import EventStore

# The columns DEX_TRADES_SQL selects. The validation step diffs these against what Dune
# actually returns — a missing column means the mappers will silently yield None, so we
# surface it loudly rather than discover it as an empty backfill.
EXPECTED_COLUMNS = (
    "block_time",
    "block_slot",
    "tx_id",
    "trader_id",
    "token_bought_mint_address",
    "token_bought_amount",
    "token_sold_mint_address",
    "token_sold_amount",
    "amount_usd",
    "project",
    "project_program_id",
)


def parse_window(s: str) -> datetime:
    """Parse a CLI window bound ('YYYY-MM-DD HH:MM:SS' or ISO-8601) into tz-aware UTC.

    A naive (offset-less) value is treated as UTC — the whole store is UTC and the Dune
    table's `block_time` is UTC, so attaching UTC is correct, not a guess."""
    s = s.strip().replace("Z", "+00:00")
    if " " in s and "T" not in s:
        s = s.replace(" ", "T", 1)
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


@dataclass
class DuneValidationReport:
    """What ONE free validation execution tells us before trusting a bulk backfill."""

    query_id: int
    since: datetime
    till: datetime
    total_row_count: int | None  # from Dune metadata (the free-window cost proxy)
    sampled_rows: int
    columns_returned: list[str]
    missing_expected: list[str]  # selected columns Dune did NOT return → mapper breakage
    extra_columns: list[str]  # columns present beyond what we select (informational)
    pool_field_present: bool  # did a real pool-address column appear? (surrogate retired)
    mapped_swaps: int  # sampled rows that mapped to a canonical Swap
    skipped_non_quote: int  # sampled rows dropped (no SOL/USDC leg — not a launch trade)
    rows_with_usd: int  # sampled rows carrying amount_usd (price/impact model input)
    distinct_base_mints: int  # survivorship breadth proxy (many tokens incl. rugs)
    distinct_markets: int  # distinct surrogate (base,quote,project) markets sampled
    metadata: dict[str, Any]  # raw Dune execution metadata, passed through for the record
    sample_swap: dict[str, Any] | None
    notes: list[str] = field(default_factory=list)

    @property
    def field_paths_ok(self) -> bool:
        return not self.missing_expected and self.mapped_swaps > 0


async def validate_dune(
    dune: Dune,
    *,
    query_id: int,
    since: datetime,
    till: datetime,
    run_id: str = "dune-validate",
    sample_size: int = 5000,
) -> DuneValidationReport:
    """Execute the saved query for a SMALL window and report field-path / cost / survivorship.

    This is deliberately ONE execution over ONE page: enough to confirm the column names,
    that rows map to canonical Swaps, and to read Dune's row-count/cost metadata — without
    burning credits on a full pull. Keep `till - since` to minutes/hours for the first run.
    """
    notes: list[str] = []
    execution_id = await dune.execute_query(
        query_id, parameters={
            "since": since.strftime("%Y-%m-%d %H:%M:%S"),
            "till": till.strftime("%Y-%m-%d %H:%M:%S"),
        }
    )
    await dune.wait_for_execution(execution_id)

    status = await dune.get_execution_status(execution_id)
    page = await dune.fetch_results_page(execution_id, limit=sample_size, offset=0)
    result = page.get("result") or {}
    rows: list[dict[str, Any]] = [r for r in (result.get("rows") or []) if isinstance(r, dict)]

    # Dune surfaces total_row_count in either the status or the results metadata.
    meta: dict[str, Any] = {**(status.get("result_metadata") or {}), **(result.get("metadata") or {})}
    total_row_count = meta.get("total_row_count")
    if total_row_count is None and rows:
        total_row_count = len(rows)
        notes.append("Dune returned no total_row_count metadata; using sampled-page count.")

    # Field-path validation: union of the actual (lower-cased) column names across the sample.
    seen_cols: set[str] = set()
    for r in rows:
        seen_cols.update(k.lower() for k in r)
    columns = sorted(seen_cols)
    missing = [c for c in EXPECTED_COLUMNS if c not in seen_cols]
    extra = [c for c in columns if c not in EXPECTED_COLUMNS]
    pool_field_present = any(f in seen_cols for f in _POOL_FIELDS)

    # Map the sample through the REAL adapter mappers — the swap-in contract under test.
    mapped = skipped = with_usd = 0
    base_mints: set[str] = set()
    markets: set[str] = set()
    sample_swap: dict[str, Any] | None = None
    for r in rows:
        swap = dune.to_swap(r, run_id=run_id)
        if swap is None:
            skipped += 1
            continue
        mapped += 1
        base_mints.add(swap.base_mint or "")
        markets.add(swap.pool_address or "")
        if swap.amount_usd is not None:
            with_usd += 1
        if sample_swap is None:
            sample_swap = swap.model_dump(mode="json")

    if rows and mapped == 0:
        notes.append("0 rows mapped to a Swap — check field paths and the SOL/USDC quote filter.")
    if not pool_field_present:
        notes.append("No native pool-address column — using the (base,quote,project) surrogate key.")
    notes.append(
        "Credits consumed per execution are NOT returned by the API — read the exact "
        "deduction from dune.com → Settings → Billing after this run."
    )

    return DuneValidationReport(
        query_id=query_id,
        since=since,
        till=till,
        total_row_count=total_row_count,
        sampled_rows=len(rows),
        columns_returned=columns,
        missing_expected=missing,
        extra_columns=extra,
        pool_field_present=pool_field_present,
        mapped_swaps=mapped,
        skipped_non_quote=skipped,
        rows_with_usd=with_usd,
        distinct_base_mints=len(base_mints),
        distinct_markets=len(markets),
        metadata=meta,
        sample_swap=sample_swap,
        notes=notes,
    )


@dataclass
class DuneBackfillReport:
    """Outcome of a full windowed Dune backfill into the store."""

    query_id: int
    since: datetime
    till: datetime
    raw_rows: int  # trade rows streamed from Dune
    swaps_mapped: int  # rows that became a canonical Swap (+ WalletEvent each)
    pools_created: int  # surrogate markets first-seen → PoolCreated creation-proxy
    skipped_non_quote: int  # rows with no SOL/USDC leg (dropped, not a launch trade)
    net_new_rows: int  # store delta (post event_id dedup) across all three types
    hit_max_rows: bool  # True if the client-side safety ceiling capped the pull
    notes: list[str] = field(default_factory=list)


async def run_dune_backfill(
    store: EventStore,
    dune: Dune,
    *,
    run_id: str,
    query_id: int,
    since: datetime,
    till: datetime,
    latency: timedelta = DEFAULT_TX_LATENCY,
    page_size: int = 5000,
    max_rows: int = 10**7,
    write_batch: int = 2000,
) -> DuneBackfillReport:
    """Stream the window's trades from Dune and write Swap/WalletEvent/PoolCreated rows.

    Rows arrive time-ordered (the saved query is `ORDER BY block_time ASC`), so the FIRST
    appearance of each surrogate market is its earliest trade → the PoolCreated creation
    proxy. Writes are batched and idempotent (INSERT OR REPLACE on `event_id`), so a
    re-run over an overlapping window adds no duplicates.
    """
    seen_markets: set[str] = set()
    batch: list[BaseEvent] = []
    raw = mapped = skipped = pools = 0
    before = store.count()
    hit_max = False

    async for row in dune.iter_trade_rows(
        query_id, since, till, page_size=page_size, max_rows=max_rows
    ):
        raw += 1
        if raw >= max_rows:
            hit_max = True
        swap = dune.to_swap(row, run_id=run_id, latency=latency)
        if swap is None:
            skipped += 1
            continue
        mapped += 1
        market = swap.pool_address or ""
        if market not in seen_markets:
            seen_markets.add(market)
            pc = dune.to_pool_created(row, run_id=run_id, latency=latency)
            if pc is not None:
                batch.append(pc)
                pools += 1
        batch.append(swap)
        batch.append(dune.swap_to_wallet_event(swap))
        if len(batch) >= write_batch:
            store.write_events(batch)
            batch.clear()
    if batch:
        store.write_events(batch)

    notes: list[str] = []
    if hit_max:
        notes.append(
            f"Hit the client-side max_rows ceiling ({max_rows}) — this is a CAP to report, "
            "not a complete window. Raise --max-rows or split the window and re-run."
        )
    if mapped == 0 and raw > 0:
        notes.append("Streamed rows but mapped 0 swaps — validate field paths first.")

    return DuneBackfillReport(
        query_id=query_id,
        since=since,
        till=till,
        raw_rows=raw,
        swaps_mapped=mapped,
        pools_created=pools,
        skipped_non_quote=skipped,
        net_new_rows=store.count() - before,
        hit_max_rows=hit_max,
        notes=notes,
    )
