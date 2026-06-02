# Provider Evaluation — Phase 1 (read-only Solana data)

*Verified June 2026. Pricing/limits move — re-verify at build time. This doc records the
free-tier evaluation that satisfies the Phase 1 "evaluate free tiers first" requirement and
the conclusion on whether a paid tier (YELLOW) is needed.*

## TL;DR

**Free tiers are sufficient for Phase 1.** No paid signup is requested this session. The
data layer is built provider-agnostic (a thin adapter per provider behind one canonical
schema), so we can start on free tiers and swap in a paid archive later without touching the
rest of the pipeline.

**Likely future YELLOW (Phase 2, not now):** a complete, swap-level, deep-historical backfill
across *thousands* of tokens (including rugs) for the kill-gate backtest will probably exceed
free-tier point/CU budgets. The most likely paid need is **Bitquery** (deep historical archive
+ gRPC streaming). I will quantify that and propose it *when Phase 2 defines the exact backfill
scope* — not before.

## Modes × providers

| Mode | Primary (free) | Cross-check (free) | Notes |
|------|----------------|--------------------|-------|
| **Stream (live)** | DexPaprika SSE | Bitquery gRPC CoreCast (free streams, limited) | New pools + trades as they happen |
| **Poll (periodic state)** | GeckoTerminal (30 req/min) | DexPaprika | New-pools list, pool OHLCV, liquidity, holders-ish |
| **Backfill (historical)** | GeckoTerminal OHLCV + DexPaprika historical | Bitquery (trial only on free) | Enumerate pools by *creation*, then pull history |

## Per-provider notes

### DexPaprika — *free, no key, the breadth workhorse*
- Public API, **no API key or registration required**; 29+ chains incl. Solana; ~15M tokens.
- Free **real-time streaming (SSE)** and historical endpoints (tokens, pools, DEX trades, liquidity).
- Free-tier rate limits not published as a hard number; "contact us for higher limits."
- **Role:** primary free stream + cheap breadth for the token universe and liquidity.
- Risk: undocumented limits; treat as best-effort and rate-limit ourselves politely.

### GeckoTerminal — *free, the polling + OHLCV workhorse*
- Free public API, **30 calls/min**, currently in Beta. Multichain incl. Solana.
- Endpoints we need: **new/trending pools**, **pool OHLCV** (candles, unix-second timestamps),
  pool/token metadata, top pools per token. OHLCV historical depth is limited (fine for the
  recent low-cap launches we care about).
- **Role:** enumerate new pools (survivorship-safe — by creation, not survival) + OHLCV backfill.
- Note: same data family as CoinGecko's on-chain API; CoinGecko Demo key raises limits if needed.

### Bitquery — *deep archive + streaming, but free is trial-only*
- Free **Developer plan**: ~1k–10k points *trial* (first month), **10 requests/min**,
  **2 simultaneous streams** for testing. Point-based pricing (queries cost points by complexity).
- **2026:** Solana **gRPC CoreCast streaming is free** for eligible use (good for live).
- Deepest **historical archive** + raw DEX trades (Raydium, Orca, Meteora, Jupiter, Pumpfun).
- **Role now:** evaluation/cross-check + free gRPC stream. **Role later (Phase 2):** the likely
  paid archive for deep survivorship-proof backfill. Commercial plan is custom-quoted (contact sales).

### Birdeye — *real-time terminal, free tier too small for backfill*
- Free (Standard): **30,000 CU/month**, **1 request/sec**, "limited" data access, no extra-CU purchase.
- Paid: Lite $39 (1.5M CU), Starter $99 (5M), Premium $199 (15M, +websockets), Business $499 (60M).
- **Role:** occasional live cross-check on a specific token; not a backfill source on free tier.

### Solana RPC (Helius/Triton/QuickNode) — *raw ground truth, optional*
- Free public/dev RPC endpoints exist (rate-limited). Raw `getSignaturesForAddress` /
  transaction parsing is the ultimate point-in-time truth but heavy to parse at scale.
- **Role:** reserved for targeted verification / filling gaps; not the Phase 1 primary.

## Decision

1. **No paid tier this session.** Build on DexPaprika (stream/breadth) + GeckoTerminal
   (poll/OHLCV backfill), with Bitquery free gRPC as a streaming option and Birdeye as a
   spot cross-check.
2. **Provider-agnostic adapters.** Each provider implements a small interface that emits the
   canonical schema. Swapping to a paid archive later is a config change, not a rewrite.
3. **Flag for Phase 2:** quantify deep-backfill point/CU cost against the exact backtest universe
   and bring a concrete Bitquery-paid proposal (price + scope) as a YELLOW item then.

## Phase 2c addendum — cheaper-than-Bitquery archive (verified June 2026)

*Context: the Phase 2b Bitquery estimate (~$2–6k effective, custom-quoted) was judged too high
for a one-time ~14d backfill. Operator asked to scout cheaper sources. Decision below
**supersedes** the "Bitquery is the likely paid need" flag in the TL;DR above.*

**Reframe:** our need — survivorship-complete, **decoded**, swap-level Solana DEX history
**including the rugs/duds** — is best served by **decoded-DEX-trade data warehouses**, not by
per-call price APIs. Warehouses index *all* on-chain swaps, so dead/rugged tokens are present
**by construction** — *better* survivorship than DexPaprika's currently-listed-pools view.

| Provider | What it gives | Cost (one-time ~14d pull) | Fit |
|---|---|---|---|
| **Flipside** ⭐ | SQL over `solana.defi.ez_dex_swaps` — decoded, Raydium/Orca/Meteora/PumpSwap/Jupiter, all tokens, deep history | **Free** Data API (Community; Pro custom) | **Chosen primary** — decoded + survivorship-complete at $0 |
| **Dune** | `dex_solana.trades` decoded table | Free = 2,500 credits/mo + API; bulk pull burns credits → overage $5/100 or ~$399/mo Plus | **Cross-check / fallback** |
| **CoinGecko onchain** (= paid GeckoTerminal) | OHLCV + trades, 37M+ DEX tokens, long-tail | $35/mo (6mo) / **$129/mo** Analyst (full from 2021) | Cheap turnkey insurance if free caps too tight |
| **Helius** | Solana-native raw/enhanced tx, streaming | credit-based; ~$49–99/mo dev tiers | Earmarked for the **live feed (Phase 4)**, not historical backfill (decode burden) |
| **Bitquery** | Deep archive | **$2–6k**, custom-quoted | **Shelved** — unnecessary given the above |
| ~~Polygon.io~~ | CEX/listed-crypto aggregates | — | **Not a fit** — no brand-new low-cap Solana launches |

**Decision (operator-approved):** pivot from Bitquery to **Flipside-free as the primary archive,
Dune as the SQL cross-check.** Build a provider-agnostic Flipside adapter (same pattern as the
spend-gated Bitquery scaffold) emitting the canonical schema.

**Open validation items (next session, all $0/GREEN):**
1. Free-tier credit/row caps unverified against a *full* 14d universe pull — large extractions
   paginate and may hit per-query row limits or monthly credit caps. Test with one real query.
2. `ez_dex_swaps` is a **swap** table — enumerate pool *creation* by deriving each token's
   **first swap** as a creation proxy (or join a token/pool-creation table), not a native feed.
3. Signups are $0 but need an account + API key in `.env` (never committed).

## Phase 2d addendum — Flipside access closed → Dune is now PRIMARY (verified June 2026)

*Context: 2c chose Flipside-free as the primary archive on the strength of its data. 2d
verified the **access model** before building a backfill on it — and the door is closed.
This **supersedes** the "Flipside ⭐ chosen primary" row above.*

**Finding — Flipside free self-signup is effectively closed.** As of June 2026 Flipside
repositioned to an enterprise / "Agents as a Service" model. Authoritative live pages
(homepage, `/api-keys`) funnel only to **"Get a personalized demo"** and **"Log In"** —
no public free-signup CTA. The "free API key" self-serve story survives only in **stale
secondary sources**: the GitHub SDK README (*formerly ShroomDK*), QuickNode's writeup, and
the docs pages (which 403 automated fetches, so they could not be read directly). The API
surface also appears to have **moved** to a REST `api.flipsidecrypto.xyz/public/v3`
endpoint (the adapter targets the older `api-v2…/json-rpc`). *Caveat:* a user with a legacy
account may still be able to generate a key via `app.flipsidecrypto.xyz` — the operator's
own login attempt is the tiebreaker — but a NEW user is funneled to sales.

**Decision (operator-approved): pivot to Dune as the PRIMARY free archive.** Dune's free
tier is **open self-signup** and was **publicly recommitted in Jan 2026** (CEO: "we will
keep having a generous free plan to serve the broader Dune community"). `dex_solana.trades`
is decoded + survivorship-complete — the same property that made Flipside attractive.

| Provider | Access (June 2026) | Cost | Role now |
|---|---|---|---|
| **Dune** ⭐ | **Open self-signup**, free plan publicly committed | Free (credit-metered, ~2,500/mo) | **PRIMARY archive** (`dex_solana.trades`) |
| Flipside | **Effectively closed** to free self-signup (enterprise/demo) | n/a to us | **Swap-in only** if access reopens (adapter built) |
| CoinGecko Analyst | Open | $129/mo | Paid fallback if Dune free credits too tight — YELLOW |

**Free-tier mechanics that shaped the Dune adapter:**
- Dune free executes **saved queries by ID** (ad-hoc SQL creation via API is paid). So the
  adapter ships `DEX_TRADES_SQL` to paste into a Dune query with `{{since}}`/`{{till}}`
  params; `iter_trade_rows(query_id, …)` executes it via the Execution API
  (`/query/{id}/execute` → poll `/execution/{id}/status` → page `/execution/{id}/results`),
  auth header `X-Dune-Api-Key`.
- Free is **credit-metered** → a full 14d pull may exceed the monthly credit cap. The ONE
  validation execution must measure real cost/row-count; scope or paginate accordingly.

**Both warehouse adapters share two honest limits (validate against ONE live pull):**
1. **Field paths documented-but-unvalidated** — no live response has yet confirmed
   `dex_solana.trades` / `ez_dex_swaps` column names. Mappers are defensive (lower-case
   normalization, candidate pool fields); the validation query is the source of truth.
2. **No native pool address** in either table → a deterministic **surrogate market key**
   per (base, quote, project/program) groups a launch's swaps; first trade = creation proxy.

Code: `src/autocrypt/providers/dune.py` (primary), `src/autocrypt/providers/flipside.py`
(swap-in), tests `tests/test_dune.py` + `tests/test_flipside.py`. See
`docs/phase-2d-synthesis.md`.

### Flipside / Dune / Helius sources
- Flipside `ez_dex_swaps` docs — https://docs.flipsidecrypto.com/blockchain-data/solana/defi/ez-dex-swaps
- Flipside Data API / rate limits — https://docs.flipsidecrypto.xyz/flipside-api/get-started/rate-limits
- Flipside Python SDK — https://pypi.org/project/flipside/
- Dune `dex_solana.trades` — https://docs.dune.com/data-catalog/curated/trading/solana/solana-dex-trades
- Dune pricing (free = 2,500 credits/mo + API) — https://dune.com/pricing
- CoinGecko onchain DEX APIs comparison — https://www.coingecko.com/learn/top-5-best-onchain-dex-data-apis
- Helius historical data / pricing — https://www.helius.dev/historical-data ; https://www.helius.dev/pricing

## Sources
- Bitquery Solana docs — https://docs.bitquery.io/docs/blockchain/Solana/
- Bitquery pricing — https://bitquery.io/pricing ; points — https://docs.bitquery.io/docs/ide/points/
- Bitquery April 2026 release (free gRPC) — https://bitquery.io/blog/bitquery-april-2026-release
- Birdeye pricing — https://docs.birdeye.so/docs/pricing ; rate limits — https://docs.birdeye.so/docs/rate-limiting
- GeckoTerminal API docs — https://api.geckoterminal.com/docs/index.html ; guide — https://apiguide.geckoterminal.com/
- DexPaprika API — https://docs.dexpaprika.com/api-reference/introduction
