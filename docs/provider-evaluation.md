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
