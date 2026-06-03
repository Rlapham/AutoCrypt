# Phase M1b Synthesis — usable mid-cap universe via mcap-ranked enumeration

*Session date: 2026-06-03. Track M (mid-cap deep-pool), Iteration 2. Ran autonomously.*

## Goal

M1 resolved Track M's #1 validity risk (a survivorship-safe point-in-time mid-cap universe
is **not** free) and chose the free survivorship-**biased** control path — but the signed-off
band (reserve ≥ $500k ∧ FDV ∈ [$1M, $250M]) yielded **n=1** from GeckoTerminal's volume-ranked
top-pools endpoint, because Solana liquidity is barbelled and top-pools is the *wrong*
enumeration source for mid-caps. **M1b goal:** get a USABLE universe by inverting the funnel
(enumerate by market-cap rank, then find depth), so the biased control + M2/M3 can actually run.

## Headline result — n=1 → n=113 (blocker resolved, no paid pull)

The mcap-ranked funnel works decisively:

```
786 FDV-in-band candidates  →  627 with a GeckoTerminal pool  →  113 in-band
```

In-band = reserve_in_usd ≥ $500k AND FDV ∈ [$1M, $250M]. Depth distribution of the 113:

```
reserve ≥ $5M : 16     ≥ $2M : 45     ≥ $1M : 72     ≥ $500k : 113
```

Recognizable liquid Solana mid-caps surfaced (top by reserve): uniBTC, SLD, TRX, SLERF, CASH,
smole, MELANIA, BOME, MEW, Fartcoin, WIF, jellyjelly, HYPE, arc, PUNDU, … This is exactly the
deep-pool mid-cap arena Track M targets. **The free funnel produced a usable universe at the
signed-off band — so the YELLOW depth-vs-paid fork (loosen to $100k, or pay Dune Plus $399 /
CoinGecko Analyst $129) is moot.** No money spent, no key required.

## The inverted funnel (what made it work)

M1's funnel started from deep pools (volume-ranked top-200) and hoped they were mid-cap → n=1.
M1b starts from mid-caps and finds their depth:

1. **CoinGecko `/coins/markets?category=solana-ecosystem&order=market_cap_desc`** — page the
   Solana-ecosystem list by market-cap rank; keep coins whose **FDV** (token-level, authoritative)
   falls in [$1M, $250M]. FDV preferred, market_cap as fallback.
2. **`/coins/list?include_platform=true`** (one call) → map coin-id → **Solana mint**. Drops
   FDV-in-band coins with no resolvable Solana mint (5,717 of 17,387 coins carry a Solana addr).
3. **GeckoTerminal `/networks/solana/tokens/{mint}/pools`** → take the **deepest** pool by
   reserve, **substitute CoinGecko's FDV** into the row (fixes M1's SOL-quoted-pool FDV
   confusion, where GeckoTerminal reported the SOL FDV ~$1.6B for SOL-quoted pairs).
4. Apply the reserve ≥ $500k depth filter (via the unchanged `UniverseBand.contains`).

This is still **survivorship-BIASED** (CoinGecko exposes only a current snapshot, no as-of param)
→ by asymmetry it can only ever yield a NO-GO / "unproven", never a false GO. Snapshot rows are
tagged `source='coingecko_mcap_ranked'` to keep them distinct from the forward top-pools series.

## Biased-control OHLCV dataset (ready for M2/M3)

Ingested daily OHLCV for all 113 in-band pools (reusing the persisted universe, not re-enumerating):

- **16,177 `ohlcv_bar` events, 113 pools**, interval 1d, range 2024-05-17 → 2026-06-02.
- Per-pool depth: median **181 bars**, avg 143; **79 pools have ≥180 bars** (full ~6mo daily),
  91 ≥ 90 bars, only 18 with < 30 bars (younger pools). Free daily cap is ~182 bars (~6mo).
- **`qc` clean:** no look-ahead, no future timestamps, no logical dupes, ingest latency 2s as
  stamped. One benign WARN (`ohlcv_gaps` > 2× interval) — expected for thin mid-caps that skip
  trading days. The close-stamped no-look-ahead discipline (`event_time = close_time`,
  `knowable_at = close_time + latency`) holds for every bar.

## What was built

- **`src/autocrypt/providers/coingecko.py`** — new read-only CoinGecko adapter: `coins_markets`
  (mcap-ranked, Solana-ecosystem category) + `solana_mint_map` (id→mint in one call). Demo-key
  header support (`x-cg-demo-api-key`); polite 5/min keyless default (the public tier 429s hard).
- **`GeckoTerminal.token_pools_raw(mint)`** — pools-for-a-token endpoint (the depth-resolution
  step). GeckoTerminal rate lowered 18→12/min (token-pools 429s well under 18).
- **`src/autocrypt/midcap/mcap_rank.py`** — the funnel: `enumerate_candidates`,
  `resolve_deepest_pool` (FDV substitution + 404→no-pool), `build_midcap_universe`. Graceful
  degradation: CoinGecko rate-limit past retries → use the pages we got; any per-token httpx
  error → skip that token, keep the run.
- **`midcap/universe.py`** — `write_snapshot` gained a `source` tag; new `load_in_band_pools`
  (read latest in-band pools of a source as PoolRows) + `build_control_from_pools` (ingest OHLCV
  for a pre-resolved list — avoids re-running the expensive funnel).
- **CLI:** `midcap-enumerate` (build universe; `--control` to also ingest) and
  `midcap-control-snapshot` (ingest control OHLCV from the latest stored snapshot).
- **`Source.coingecko`** added to the schema enum.
- **Tests:** `tests/test_midcap_mcap_rank.py` (6: fdv-ref, band+mint filter, deepest-pool +
  FDV override, no-pool, **404-is-no-pool regression**, build counts+write) + a
  `load_in_band_pools` test in `test_midcap.py`. **74/74 green, ruff clean.**

## What broke and how it was fixed (the autonomous-run lessons)

1. **CoinGecko keyless 429 mid-enumeration** aborted run #1. Fix: lower rate to 5/min + catch
   the exhausted-retry error and proceed with the pages already fetched (partial universe is fine
   for a biased control). Logged, not silent.
2. **A 404 from GeckoTerminal token-pools crashed run #2 at ~101 resolved** — a token CoinGecko
   lists but GeckoTerminal indexes no pool for. `raise_for_status()` raised `HTTPStatusError`,
   which the `RetryableHTTPError`-only guard didn't catch, and since the snapshot is written only
   at the END of the funnel, all 101 resolved pools were lost. Fix: treat 404 as "no pool"
   (return None) and broaden the per-candidate catch to all `httpx.HTTPError`. Added a regression
   test. Run #3 completed: 627 resolved, 0 crashes.

## Open items / follow-ups (next session)

1. **M2 — deep-pool cost recalibration (the immediate next step).** Confirm empirically that
   cost drag on these deep pools is **low single digits** (Iteration-1 Law 1 escaped) *before*
   trusting any expectancy. NOTE: the profiler's cost model was built for swap-level fresh-launch
   data; adapting it to mid-cap **OHLCV + reserve depth** is the first M2 task (own-impact from the
   constant-product model using `reserve_usd`; fees + spread should dominate). If cost drag is
   still large, stop and re-scope (pools not deep enough).
2. **Funnel efficiency (worth fixing before re-running).** Run #3 took ~2.5h because it grinds all
   786 candidates — including hundreds of sub-band dust tokens in the low-mcap tail — and writes
   the snapshot only at the end (so a crash loses everything). Improvements: (a) **incremental
   snapshot writes** (per batch), (b) **early-stop / page cap** once candidates fall consistently
   out-of-band (in-band names cluster in the higher-mcap pages; ~max_pages 3–4 likely captures all
   113), (c) GeckoTerminal 429s on nearly every call — its effective free limit is ~10/min.
3. **Universe noise.** A few "deepest pools" are stablecoin or wrapped-asset pairs (uniBTC/xBTC,
   SLD/JupUSD, PSTUSDC/USDC, TRX bridged) that aren't really speculative mid-caps. Consider
   restricting the quote leg (SOL/USDC/USDT) or excluding stable-stable / wrapped pairs in M2/M3.
4. **Forward snapshots still accruing** (the clean, unbiased series) — `midcap_snapshot_loop.sh`
   nohup, daily, top-pools source. Reboot kills it; durable launchd still blocked by macOS TCC.
5. **Track G / G0 collector** healthy this session (graduation cohort accruing to
   `autocrypt_graduation.duckdb`). Same reboot caveat.

## State of the code

`src/autocrypt/midcap/` (universe + mcap_rank), `providers/coingecko.py`, and the new CLI
commands are tested; 74/74 green, ruff clean. No paid spend, no keys, no funds, no trading.
Track M store: `data/autocrypt_midcap.duckdb` (113-pool in-band universe + 16,177 1d bars +
forward snapshots). Iteration-1 stores untouched.

## Background processes (neither survives reboot — re-launch after any restart)

| Process | Writes to | Purpose |
|---|---|---|
| `autocrypt collect` (nohup) | `data/autocrypt_graduation.duckdb` | G0 graduation cohort, 7-day hold |
| `midcap_snapshot_loop.sh` (nohup) | `data/autocrypt_midcap.duckdb` | daily clean (top-pools) universe snapshot |

⚠️ Single-writer rule: DuckDB is one writer per file. The snapshot loop sleeps 24h between
writes; the M1b enumeration/control ran while it was idle. Don't run two writers on the midcap
file at once.

---

```text
Read CLAUDE.md, then Project_spec.md, then docs/iteration-2-strategy.md, then
docs/phase-M1b-synthesis.md. Confirm in 3-4 sentences where we are and this session's goal
before doing anything else.

CONTEXT: Iteration 2, Track M (mid-cap deep-pool) + Track G (graduation, parallel). M1b
RESOLVED the universe blocker: the mcap-ranked inverted funnel (CoinGecko /coins/markets FDV
band -> Solana mint -> GeckoTerminal deepest pool -> reserve>=$500k) yields n=113 in-band
mid-cap deep-pool names (vs M1's n=1), at the signed-off band, FREE (no paid pull). Biased-
control OHLCV ingested: 16,177 daily bars / 113 pools / ~6mo depth, qc-clean (no look-ahead).
Dataset in data/autocrypt_midcap.duckdb (universe_snapshots source='coingecko_mcap_ranked' +
events ohlcv_bar). 74/74 tests green, ruff clean. Still survivorship-BIASED -> can only NO-GO
/ "unproven", never a GO.

THIS SESSION = M2: deep-pool cost recalibration (confirm Law 1 is escaped) BEFORE any signal.
  1. Adapt the profiler's execution-cost model to mid-cap OHLCV + reserve depth (own price
     impact from the constant-product model using reserve_usd; fees + spread should dominate).
     Confirm empirically that round-trip cost drag is now LOW SINGLE DIGITS on these deep pools
     (Iteration-1 was ~20-28% on thin fresh-launch pools). If cost drag is still large, STOP and
     re-scope -- the universe isn't deep enough and Track M is dead on arrival.
  2. Only if Law 1 is escaped, proceed to M3 (signal battery: TS/XS momentum, mean-reversion,
     breakout) + KILL-GATE per strategy doc §3. (M3 is its own session.)
  Optional cleanups noted in phase-M1b-synthesis.md "Open items": funnel incremental-write +
  early-stop (it took ~2.5h grinding dust), and trimming universe noise (stable/wrapped pairs
  like uniBTC/xBTC, SLD/JupUSD -- consider restricting the quote leg to SOL/USDC/USDT).

CHECK BACKGROUND JOBS FIRST (both DIE on reboot -- re-launch if `ps aux | grep autocrypt`
shows nothing):
  - G0 graduation:  DB_URL=duckdb:///data/autocrypt_graduation.duckdb nohup uv run autocrypt \
      collect --interval 90 --iterations 0 --enum-pages 3 --watch-max 60 --max-pool-age-h 168 \
      --tx-pages 2 > data/g0_collect.interim.log 2>&1 &
  - Track M daily snapshot: nohup bash scripts/midcap_snapshot_loop.sh > data/midcap_snapshot.log 2>&1 &
Durable fix still pending: grant Full Disk Access to /usr/local/bin/uv (then enable
~/Library/LaunchAgents/com.autocrypt.collector.plist), OR relocate repo out of ~/Documents.

Kill-gate bar (strategy §3): profitable after realistic costs AND point-in-time AND
survivorship-complete AND beats blind+random AND robust AND enough fires. Never tune to a
positive; a biased control can only NO-GO, never GO. Autonomy: GREEN code/backtest/free data;
YELLOW paid tiers + universe/label changes + GO/NO-GO; RED unchanged.
```
