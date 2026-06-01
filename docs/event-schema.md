# Canonical Event Schema — Proposal (Phase 1, YELLOW sign-off)

*Status: **awaiting human sign-off.** Later phases hard-depend on this, so it is a YELLOW
checkpoint per CLAUDE.md §3. Implementation: `src/autocrypt/schema/events.py` (pydantic v2),
tests in `tests/test_schema.py`. This doc is the thing to review.*

---

## 0. The one idea that matters: three times per record

The backtest is only valid if the model can never see a fact before it could have known it.
We enforce that by stamping **every** record with three distinct timestamps:

| Field | Meaning | Used to gate decisions? |
|-------|---------|--------------------------|
| `event_time` | **Valid time** — when the fact became true *on-chain* | no (it's the "what/when on chain") |
| `knowable_at` | **Known time** — earliest wall-clock we *could have* known it; always ≥ `event_time` | **YES — the only gate** |
| `observed_at` | **Audit time** — when we actually fetched it (≈now for backfill) | **NEVER** |

**Replay rule:** at decision time `T`, the system may read a record iff `knowable_at <= T`.
`observed_at` exists only for debugging/provenance and is forbidden from any signal path.

What `event_time` means per record type, and how `knowable_at` is derived:

| Record | `event_time` is… | `knowable_at` = … |
|--------|------------------|-------------------|
| Swap / PoolCreated / LiquidityChange | tx **block time** | block time + ingest latency |
| **OHLCVBar** | **bar CLOSE time** (not open!) | close time + ingest latency |
| HolderSnapshot / TokenMeta | chain state **as-of** time | as-of time + poll/compute latency |

The OHLCV rule is the classic trap: a candle's high/low/close are unknown until the interval
ends, so a bar stamped at its *open* time leaks the future. The schema **rejects** an OHLCV bar
whose `event_time != close_time` at construction time. (See `test_ohlcv_event_time_must_equal_close`.)

**Backfill discipline:** when we backfill months-old data, `observed_at` is "now," but we
reconstruct `knowable_at = event_time + assumed_latency` via the `knowable_at_for_*()` helpers —
we never let fetch time stand in for known time. `ingest_latency_ms` is stored on every row so
the assumed latency is auditable and tunable.

**Latency is a tunable assumption, not a guess baked in silently.** Default assumed ingest
latency (proposed): **2 s** for tx/stream events (a realistic time-to-act for a Python consumer
on `confirmed` commitment), **bar-interval-dependent** for OHLCV (close + ~2 s), **poll-period**
for snapshots. Phase 2 can sweep this to test sensitivity. *(Open question Q3.)*

---

## 1. Record types (7)

All inherit a shared **envelope**: `schema_version, event_type, chain, source, event_time,
knowable_at, observed_at, block_slot, source_ref, ingest_run_id, commitment, revision,
superseded_by`. Records are **append-only**; corrections/reorgs arrive as a new row with a higher
`revision` and (optionally) the old row's `superseded_by` set. Each type has a deterministic
`event_id()` from its natural key, so the **same trade seen via two providers dedupes to one id**.

1. **PoolCreated** — a new pool/launch. `pool_address, dex, program_id, base_mint, quote_mint,
   decimals, creator, init reserves/liquidity_usd/price_usd`. *The universe entry point.*
2. **Swap** — a DEX trade. `pool, signer (wallet), side (buy/sell of base), base/quote amounts
   (raw int + ui Decimal), price_quote_per_base, price_usd (+ source), tx_signature,
   instruction_index`. *The core attribution + buy-pressure input.*
3. **LiquidityChange** — LP add/remove. `pool, wallet, side, amounts, reserves_after,
   liquidity_usd_after`. *Rug / liquidity-pull signal.*
4. **OHLCVBar** — candle. `pool, interval, open_time, close_time, OHLC, volume(base/quote/usd),
   trade_count`. *The practical free-tier backfill unit (GeckoTerminal).* Look-ahead-guarded.
5. **HolderSnapshot** — polled distribution. `base_mint, as_of_slot, holder_count, total/circ
   supply, top10_pct, top50_pct, creator_pct, lp_pct`. *A SAMPLE — step, never interpolate.*
6. **TokenMeta** — rug-filter raw inputs as a time-stamped snapshot (authorities can be revoked,
   LP can be locked/burned after launch). `symbol, name, decimals, supply, mint_authority,
   freeze_authority, lp_locked, lp_burned, lp_lock_until, is_honeypot`.
7. **WalletEvent** — a wallet's action linked to its tx (`wallet, action, mints, pool, amounts,
   tx_signature, linked_event_id`). **Note:** the attribution *label* ("is this a leading/smart
   wallet?") is deliberately **not** stored here — it is produced by the Phase 3 model and joined
   **as-of `knowable_at`**, so a future-derived label can never leak into a past decision.

### Numeric precision
Amounts keep **both** the raw integer base units (`*_amount_raw`, on-chain truth, exact) **and**
a `Decimal` ui amount; prices/USD are `Decimal` (never float). USD valuations carry a
`usd_price_source` because a USD price is itself a lagging/derived series with its own
look-ahead risk.

---

## 2. Proposed storage layout

- **Local store: DuckDB** (`data/autocrypt.duckdb`), one table per record type, plus **Parquet**
  exports partitioned by `event_type` and `date(event_time)` for portability/backtest scans.
- Every table indexed on **`knowable_at`** (the replay gate) and on `block_slot`/`event_time`
  (window pruning). Natural-key uniqueness on `event_id` for idempotent re-ingest.
- The point-in-time replay primitive is a single ordered scan:
  `SELECT * FROM events WHERE knowable_at <= :T ORDER BY knowable_at, block_slot`.
- Append-only; no in-place updates. Corrections are new revisions.

*(DuckDB vs. Parquet-only is **Open question Q4**; I lean DuckDB-as-primary + Parquet-export.)*

---

## 3. Proposed backfill window + token universe (survivorship-proof)

This is the other foundational decision; flagging it here so you can approve the whole base at
once. (Building it is post-sign-off work.)

- **Universe by construction = survivorship-safe.** Enumerate **every** Solana pool *created* in
  the window (via GeckoTerminal new-pools + DexPaprika), then pull each one's subsequent
  swaps/OHLCV/liquidity — *including the ones that rugged or died.* Because we select on
  **creation**, not on survival/current-existence, dead and rugged tokens are in by default.
  Survivors-only is exactly the bias Project_spec §4.1 forbids.
- **Proposed window:** a **contiguous 14-day window of recent history** (e.g. roughly the two
  weeks ending a few days before today, so the window is fully "closed" and finalized). Long
  enough for thousands of launches and a meaningful rug base-rate; small enough to fit free-tier
  budgets. *(Open question Q2 — exact dates + length.)*
- **Tradeability filter (recorded, not survivorship):** keep pools that crossed a minimal
  liquidity/quote bar at *any* point (e.g. ≥ a few-hundred-USD pool) so we exclude pure dust that
  was never tradeable — but we record *that they died*, we don't drop them for dying.
- **Quote scope:** SOL- and USDC-quoted pools (the vast majority of low-cap launches).

---

## 4. Open questions for sign-off

- **Q1 — Schema shape.** Do the 7 record types + 3-time envelope cover what Phase 2/3 need? Any
  field you want added now (cheaper than a migration later)? In particular: is modeling
  TokenMeta/HolderSnapshot as time-stamped *snapshots* (not static dimensions) the right call? *(I
  recommend yes — authorities/LP-locks change post-launch and the backtest must respect that.)*
- **Q2 — Backfill window.** OK with a **14-day recent contiguous window**, SOL+USDC quotes,
  enumerate-by-creation? Want it longer/shorter, or anchored to specific dates?
- **Q3 — Default assumed ingest latency.** OK with **2 s** for tx/stream events (and close+2s for
  bars, poll-period for snapshots) as the default, sweepable in Phase 2?
- **Q4 — Store.** DuckDB-as-primary + Parquet-export — good? Or Parquet-only / something else?
- **Q5 — `processed` vs `confirmed`.** Default ingestion commitment = **`confirmed`** (reorg-safe
  enough, low latency). Live HFT later might want `processed` (faster, reorg risk). Default OK?

**Recommended:** approve as proposed (7 types, 3-time envelope, enumerate-by-creation,
14-day window, 2 s latency, DuckDB primary, `confirmed`). It's the most defensible against the
survivorship + look-ahead failure modes that gate the whole project, and every assumption above
is stored/tunable rather than hardcoded silently.

Once you sign off (or amend), I build ingestion + storage + the backfill + data-quality checks +
the data dictionary on top of this.
