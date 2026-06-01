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

## Sources
- Bitquery Solana docs — https://docs.bitquery.io/docs/blockchain/Solana/
- Bitquery pricing — https://bitquery.io/pricing ; points — https://docs.bitquery.io/docs/ide/points/
- Bitquery April 2026 release (free gRPC) — https://bitquery.io/blog/bitquery-april-2026-release
- Birdeye pricing — https://docs.birdeye.so/docs/pricing ; rate limits — https://docs.birdeye.so/docs/rate-limiting
- GeckoTerminal API docs — https://api.geckoterminal.com/docs/index.html ; guide — https://apiguide.geckoterminal.com/
- DexPaprika API — https://docs.dexpaprika.com/api-reference/introduction
