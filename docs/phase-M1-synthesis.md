# Phase M1 Synthesis — Track M mid-cap universe + free OHLCV (Iteration 2)

*Session date: 2026-06-03. Track M (mid-cap deep-pool) Phase M1, plus fire-and-forget G0.*

## Goal

Resolve Track M's **#1 validity risk first**: can the free GeckoTerminal/CoinGecko tiers
give a **survivorship-safe, point-in-time mid-cap universe** (tokens meeting a
liquidity/mcap threshold *as of each historical date*, including ones that later died)?
Verify provider access **before** building. Then define the universe band, ingest
point-in-time OHLCV, run `qc`. In parallel, stand up a **durable G0 collector** so Track
G's multi-day data ripens.

## Headline findings

### 1. A survivorship-safe point-in-time mid-cap universe is NOT available for free (verified live)

I probed the live APIs rather than trusting docs:

| Capability | Free reality | Verdict |
|---|---|---|
| Universe enumeration (GeckoTerminal `/pools`) | **Today's top ~200 pools** (10 pages × 20, hard stop). No date / "as-of" param. | ❌ current snapshot only |
| Universe enumeration (CoinGecko `/coins/markets`) | Current snapshot; rich mcap/fdv/rank fields; no historical date param. | ❌ current only |
| Per-pool OHLCV | Daily capped **~182 bars (~6mo)**; hourly **1000 bars (~41d)** even at `limit=1000`. | ⚠️ history only for *surviving* pools |
| `pool_created_at` | ✅ present | useful filter, doesn't solve enumeration |

**The problem is enumeration, not prices.** Free gives rich history *for survivors you can
still see today*. Backtesting "today's top-N liquid tokens" over their 6-month OHLCV is the
**survivorship-biased trap** the kickoff forbids — a backtest run only on winners.
DexPaprika (currently-listed view) and the on-disk Dune cohort (1h fresh-launch window)
don't fix it.

**Operator decision (YELLOW, resolved this session):** proceed with **free
survivorship-BIASED control + start free forward snapshots**, *not* a paid pull. Rationale
= **asymmetry**: bias only inflates returns, so a biased backtest can only yield a decisive
NO-GO or "unproven" — never a false GO. That is exactly the strategy-doc role for Track M
("a control on whether our machine finds *any* survivable edge"), extracted at $0 today.
Pay only if the free control hints at edge worth confirming.

### 2. The signed-off band yields a STRUCTURALLY THIN universe from free top-pools (n=1) — Solana liquidity is barbelled

Operator signed off the band: **reserve_in_usd ≥ $500k AND FDV ∈ [$1M, $250M]** (depth is
load-bearing — the point is escaping Iteration-1 Law 1, the cost wall). Applied to the live
top-200 (snapshot in `data/autocrypt_midcap.duckdb`):

```
total enumerated:           200
reserve ≥ $500k:              9   ← of which 8 are SOL/USDC·USDT majors (FDV ~$1.6B, excluded)
fdv ∈ [$1M, $250M]:          20
reserve ≥ $500k & in-band:    1   ← cbBTC/USDC (FDV $204M; basically wrapped BTC)
reserve ≥ $250k & in-band:    3
reserve ≥ $100k & in-band:    6
```

**Interpretation:** Solana liquidity is **barbelled** — majors (SOL/stables, BTC) are deep;
almost everything else is thin fresh-launch pumpfun. The "mid-cap *token* with a *deep*
pool" middle barely exists in the free top-200. This is itself an early, honest read on the
thesis: the niche Track M targets is **sparse**, and the **volume-ranked top-pools endpoint
is the wrong enumeration source** for it. *(Note: for SOL-quoted pools GeckoTerminal reports
the SOL FDV (~$1.6B), so the FDV>250M cut correctly removes SOL-major pairs; Verse/SOL at
FDV $21.7M / reserve $457k shows the band logic works — it's the supply that's thin.)*

**Implication / fix (next step):** to populate a real mid-cap universe, enumerate by
**market-cap rank (CoinGecko `/coins/markets`)** → map each coin to its Solana mint → take
its **deepest** GeckoTerminal pool → apply the depth filter. That inverts the funnel
(start from mid-caps, find depth) instead of starting from deep pools and hoping they're
mid-cap. This needs per-coin address mapping (rate-limited) — a next-session build, or
accept that the deep-pool mid-cap arena is genuinely thin on free Solana data.

## What was built

- **`src/autocrypt/midcap/universe.py`** — pure parse (`parse_pool`, bare-mint extraction
  from `solana_<mint>` ids), the signed-off `UniverseBand` (with `.contains`), forward
  `snapshot_universe` / `write_snapshot` (records ALL enumerated pools with `in_band`
  flagged → survivorship-safe forward series), and `build_control_dataset` (biased OHLCV
  ingest, labelled never-a-GO).
- **`GeckoTerminal.top_pools_raw`** — current top-pools enumeration with an explicit
  survivorship caveat in the docstring.
- **CLI:** `autocrypt midcap-snapshot` (one forward snapshot) and `autocrypt midcap-control`
  (biased control ingest; banner-warns it's an upper bound).
- **`tests/test_midcap.py`** — 4 tests (parse, band edges, snapshot-records-all). **67/67
  green, ruff clean.**

## What was run

- **Forward snapshot #1 taken** → `data/autocrypt_midcap.duckdb::universe_snapshots`
  (200 pools, 1 in-band). The clean survivorship-safe series has started.
- **Biased control NOT meaningfully run** — at n=1 it's analytical theater; the ingest path
  is the Phase-1-validated `iter_pool_ohlcv` + covered by the new unit tests, so it's proven
  by construction. (A live attempt also hit a transient GeckoTerminal 429 from back-to-back
  enumeration — the control re-enumerates; harmless, but it confirms n=1 isn't worth it.)
- `qc` not run on the midcap store — only a universe snapshot + zero OHLCV bars landed
  (nothing for the event-level QC to check yet).

## G0 — Track G durable collection (fire-and-forget)

- **The old `nohup` collector was DEAD** (last write 08:32; log crash). Track G collection
  had silently stopped — exactly the durability gap G0 exists to close.
- Built the durable form: `scripts/g0_collect.sh` + `~/Library/LaunchAgents/com.autocrypt.collector.plist`
  (RunAtLoad + KeepAlive, multi-day hold `--max-pool-age-h 168`, dedicated
  `data/autocrypt_graduation.duckdb`).
- **macOS TCC blocked the LaunchAgent** (repo is under `~/Documents` → "Operation not
  permitted", exit 126). The durable form needs **Full Disk Access** granted to the launch
  process (manual, System Settings) or the repo relocated outside `~/Documents`.
- **Operator decision:** keep the **interim nohup collector** for now (defer the durability
  fix). It is **running and accruing** (~7.6k+ swap/wallet rows, 60 pools watched, healthy
  ticks). Plist + wrapper left dormant on disk, ready for the day FDA is granted.
- **Caveat:** interim nohup survives this session but **NOT reboot** — re-launch after any
  restart (command in the kickoff). Graduation-event *detection* + a graduation-filtered
  cohort are a later G-step, derivable from this raw multi-day store.
- A second nohup loop (`scripts/midcap_snapshot_loop.sh`, pid noted in log) takes a daily
  Track-M forward universe snapshot — same interim-durability caveat.

## Background processes left running (neither survives reboot)

| Process | Writes to | Purpose |
|---|---|---|
| `autocrypt collect` (nohup) | `data/autocrypt_graduation.duckdb` | G0 graduation cohort, 7-day hold |
| `midcap_snapshot_loop.sh` (nohup) | `data/autocrypt_midcap.duckdb` | daily Track-M clean universe snapshot |

⚠️ Single-writer rule: before enabling the launchd collector later, **kill the nohup
collector first** (DuckDB is single-writer per file).

## Open decisions for next session

1. **Enumeration source for the mid-cap universe (the real M1 blocker).** Free top-pools is
   barbelled → n=1 at the signed-off band. **Recommended:** build CoinGecko-mcap-ranked →
   Solana-mint → deepest-pool enumeration. Alternatives: loosen depth to reserve ≥ $100k
   (n=6, shallower, weaker Law-1 escape), or accept paid (Dune Plus ~$399 / CoinGecko
   Analyst $129) for survivorship-complete history. *Until a usable universe exists, the
   biased control can't say anything and M2/M3 can't run.*
2. **Durable collection** — grant Full Disk Access to `uv` (then enable the launchd agent)
   or relocate the repo out of `~/Documents`. Until then, reboot kills both collectors.

## State of the code

`src/autocrypt/midcap/` is new and tested; CLI has `midcap-snapshot` / `midcap-control`;
GeckoTerminal has `top_pools_raw`. 67/67 tests green, ruff clean. No paid spend, no keys,
no funds, no trading. Iteration-1 stores untouched; Track M/G use dedicated DB files.

---

```text
Read CLAUDE.md, then Project_spec.md, then docs/iteration-2-strategy.md, then
docs/phase-M1-synthesis.md. Confirm in 3-4 sentences where we are and this session's goal
before doing anything else.

CONTEXT: Iteration 2, Track M (mid-cap deep-pool) + Track G (graduation, parallel). M1
resolved the #1 validity risk: a survivorship-safe point-in-time mid-cap universe is NOT
free (GeckoTerminal = today's top-200 snapshot only; ~6mo daily / ~41d hourly OHLCV for
survivors only). Operator chose: free survivorship-BIASED control + forward snapshots, no
paid pull. BUT the signed-off band (reserve>=$500k AND FDV $1M-$250M) yields only n=1 from
the free top-pools endpoint — Solana liquidity is barbelled (majors deep, rest thin), and
volume-ranked top-pools is the WRONG enumeration source for mid-caps.

THIS SESSION = M1b: get a USABLE mid-cap universe so the biased control (then M2/M3) can
actually run.
  1. Build mcap-ranked enumeration: CoinGecko /coins/markets (mid-cap band) -> map each
     coin to its Solana mint -> GeckoTerminal token-pools -> take the deepest pool -> apply
     the reserve>=$500k depth filter. This inverts the funnel (start from mid-caps, find
     depth) vs starting from deep pools. Mind CoinGecko free rate limits.
  2. If that still yields too few names, bring the operator the fork: loosen depth to
     reserve>=$100k (n~6, weaker Law-1 escape) vs paid survivorship-complete history (Dune
     Plus ~$399 / CoinGecko Analyst $129) -- YELLOW, quote+cap.
  3. Once a universe with enough pools exists: run `autocrypt midcap-control` (BIASED, label
     it so), then M2 deep-pool cost recalibration (confirm cost drag is low single digits =
     Law 1 escaped) before trusting any expectancy.

CHECK BACKGROUND JOBS FIRST: two nohup collectors should be running (they DIE on reboot --
re-launch if `ps aux | grep autocrypt` shows nothing):
  - G0 graduation:  DB_URL=duckdb:///data/autocrypt_graduation.duckdb nohup uv run autocrypt \
      collect --interval 90 --iterations 0 --enum-pages 3 --watch-max 60 --max-pool-age-h 168 \
      --tx-pages 2 > data/g0_collect.interim.log 2>&1 &
  - Track M daily snapshot: nohup bash scripts/midcap_snapshot_loop.sh > data/midcap_snapshot.log 2>&1 &
Durable fix still pending: grant Full Disk Access to /usr/local/bin/uv (then enable
~/Library/LaunchAgents/com.autocrypt.collector.plist), OR relocate repo out of ~/Documents.

Kill-gate bar (strategy §3): profitable after realistic costs AND point-in-time AND
survivorship-complete AND beats blind+random AND robust AND enough fires. Never tune to a
positive; a biased control can only NO-GO, never GO. Autonomy: GREEN code/backtest/free
data; YELLOW paid tiers + universe/label changes + GO/NO-GO; RED unchanged.
```
