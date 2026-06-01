# Data Dictionary — AutoCrypt event store (Phase 1)

The canonical store is a single DuckDB table `events` (file: `data/autocrypt.duckdb`),
append-only, idempotent on `event_id`. Type-specific fields live losslessly in the
`payload` JSON column; the most-queried fields are also promoted to typed columns.
Schema source of truth: `src/autocrypt/schema/events.py` (`SCHEMA_VERSION = 1.0`).

See `docs/event-schema.md` for the design rationale and the three-time discipline.

## The three timestamps (read this first)

| Field | Meaning | May gate decisions? |
|-------|---------|----------------------|
| `event_time` | when the fact became true **on-chain** (tx block time / bar **close** / snapshot as-of) | no |
| `knowable_at` | earliest wall-clock we **could** have known it; always ≥ `event_time` | **YES — the only gate** |
| `observed_at` | when we actually fetched it (≈now for backfill) | **NEVER** |

Point-in-time replay: `SELECT * FROM events WHERE knowable_at <= :T ORDER BY knowable_at, block_slot`.

## Table `events` — promoted (typed) columns

| Column | Type | Notes |
|--------|------|-------|
| `event_id` | VARCHAR PK | deterministic hash of the record's natural key; cross-provider dedup |
| `schema_version` | VARCHAR | `"1.0"` |
| `event_type` | VARCHAR | `pool_created` \| `swap` \| `liquidity_change` \| `ohlcv_bar` \| `holder_snapshot` \| `token_meta` \| `wallet_event` |
| `chain` | VARCHAR | `solana` (|`base` future) |
| `source` | VARCHAR | `dexpaprika` \| `geckoterminal` \| `bitquery` \| `birdeye` \| `solana_rpc` \| `synthetic` |
| `event_time` | TIMESTAMPTZ | valid time (UTC) |
| `knowable_at` | TIMESTAMPTZ | known time (UTC) — replay gate |
| `observed_at` | TIMESTAMPTZ | audit only (nullable) |
| `block_slot` | BIGINT | Solana slot / block number; monotonic order key |
| `commitment` | VARCHAR | `processed` \| `confirmed` \| `finalized` \| `backfill` |
| `revision` | INTEGER | append-only correction counter (0 = original) |
| `pool_address` | VARCHAR | promoted from payload |
| `base_mint` | VARCHAR | the low-cap token of interest |
| `quote_mint` | VARCHAR | SOL / USDC / USDT |
| `actor` | VARCHAR | principal wallet (signer/wallet/creator) |
| `tx_signature` | VARCHAR | Solana tx signature |
| `amount_usd` | DOUBLE | promoted USD magnitude (convenience) |
| `payload` | VARCHAR(JSON) | full lossless record (all fields below) |
| `ingested_at` | TIMESTAMPTZ | row write time (audit) |

## Per-type `payload` fields

### `pool_created` — a new pool/launch (universe entry point)
`pool_address, dex, program_id, base_mint, quote_mint, base_decimals, quote_decimals,
creator, tx_signature, init_base_reserve, init_quote_reserve, init_liquidity_usd,
init_price_usd`. `event_time` = pool creation block time.

### `swap` — a DEX trade (core attribution + buy-pressure signal)
`pool_address, dex, base_mint, quote_mint, signer, side, base_amount_raw,
quote_amount_raw, base_amount, quote_amount, price_quote_per_base, price_usd,
usd_price_source, amount_usd, tx_signature, instruction_index`.
- **`side`**: `buy` / `sell` **w.r.t. the base token**. Convention (verified against live
  price direction): a positive trader base-delta = `buy`. Stored amounts are magnitudes.
- `*_raw` = exact integer base units (on-chain truth); `base_amount`/`quote_amount` = ui Decimals.

### `liquidity_change` — LP add/remove (rug / liquidity-pull signal)
`pool_address, base_mint, quote_mint, wallet, side (add/remove), base_amount,
quote_amount, lp_token_delta, base_reserve_after, quote_reserve_after, liquidity_usd_after,
tx_signature, instruction_index`.

### `ohlcv_bar` — candle (backfill unit). `event_time == close_time` (look-ahead-guarded)
`pool_address, base_mint, quote_mint, interval, open_time, close_time, open, high, low,
close, volume_base, volume_quote, volume_usd, trade_count, currency`.

### `holder_snapshot` — polled distribution (a SAMPLE; step, never interpolate)
`base_mint, pool_address, as_of_slot, holder_count, total_supply, circulating_supply,
top10_pct, top50_pct, creator_pct, lp_pct`.

### `token_meta` — rug-filter raw inputs as a time-stamped snapshot
`base_mint, symbol, name, decimals, total_supply, mint_authority, freeze_authority,
lp_locked, lp_burned, lp_lock_until, is_honeypot`. Authorities: `present`/`revoked`/`unknown`.

### `wallet_event` — per-wallet activity projection (attribution input)
`wallet, action (buy/sell/add_liquidity/remove_liquidity/create_pool/transfer), base_mint,
quote_mint, pool_address, base_amount, quote_amount, amount_usd, tx_signature,
instruction_index, linked_event_id`. The "leading/smart wallet" **label is NOT here** —
it is produced in Phase 3 and joined as-of `knowable_at`.

## Provenance & survivorship

- **Universe** is enumerated by pool **creation time** (DexPaprika `order_by=created_at`),
  independent of survival, so rugged/dead pools are included by construction.
- A `min_transactions` filter skips never-traded dust (an "ever-tradeable" filter, not a
  survivorship filter — rugs that traded are kept).
- Current/aggregate provider fields (`last_price_usd`, current reserves, 24h stats) are
  **not** stored as point-in-time facts — they would be look-ahead.

## Data-quality checks (`autocrypt qc`)

`row_count`, `lookahead_knowable_before_event` (fail), `future_timestamps` (fail),
`logical_duplicates` (keyed on tx+instruction+type), `orphan_swaps`, `negative_amount_usd`
(fail), `swap_missing_keys` (fail), `ingest_latency` (sanity), `ohlcv_gaps`.
