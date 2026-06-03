"""M1b — market-cap-ranked mid-cap enumeration (the inverted funnel).

M1 proved the volume-ranked top-pools endpoint is the wrong source for a mid-cap universe
(Solana liquidity is barbelled → n=1 in-band). This module inverts the funnel:

    CoinGecko mcap-rank (FDV band, authoritative)  →  map id→Solana mint
        →  GeckoTerminal deepest pool per mint  →  reserve depth filter

so we START from mid-caps and FIND their depth, instead of starting from deep pools and
hoping they are mid-cap. FDV is taken from CoinGecko (token-level, correct) and substituted
into the resolved PoolRow, fixing M1's SOL-quoted-pool FDV confusion.

Still survivorship-BIASED (CoinGecko exposes only a current snapshot) → it can only ever
yield a NO-GO / "unproven", never a false GO. See `docs/phase-M1-synthesis.md`.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from autocrypt.logging import get_logger
from autocrypt.midcap.universe import PoolRow, UniverseBand, parse_pool, write_snapshot
from autocrypt.providers.base import RetryableHTTPError
from autocrypt.providers.coingecko import SOLANA_CATEGORY, CoinGecko
from autocrypt.providers.geckoterminal import GeckoTerminal
from autocrypt.storage.store import EventStore

log = get_logger("midcap.mcap_rank")


@dataclass(frozen=True)
class MidcapCandidate:
    """A CoinGecko mcap-ranked Solana token whose FDV falls in the band."""

    coin_id: str
    symbol: str
    name: str
    mint: str
    mcap_usd: float | None
    fdv_usd: float | None  # authoritative token-level FDV (preferred), else mcap


def _fdv_ref(coin: dict) -> float | None:
    """FDV for the band test: prefer fully-diluted valuation, fall back to market cap."""
    fdv = coin.get("fully_diluted_valuation")
    mcap = coin.get("market_cap")
    val = fdv if fdv is not None else mcap
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None


async def enumerate_candidates(
    cg: CoinGecko,
    band: UniverseBand,
    *,
    max_pages: int = 12,
    per_page: int = 250,
) -> list[MidcapCandidate]:
    """Page mcap-ranked Solana-ecosystem coins; keep those with FDV in the band + a mint.

    Ordering is market_cap_desc, but FDV ≠ mcap so we do NOT early-stop on the band — the
    top pages (huge majors) fail the FDV<max cut and are skipped, the band sits mid-list.
    """
    mint_map = await cg.solana_mint_map()
    log.info("solana_mint_map", coins_with_mint=len(mint_map))
    out: list[MidcapCandidate] = []
    seen: set[str] = set()
    for page in range(1, max_pages + 1):
        try:
            rows = await cg.coins_markets(category=SOLANA_CATEGORY, page=page, per_page=per_page)
        except RetryableHTTPError as exc:
            # keyless tier rate-limited past our retries — proceed with the pages we got
            # (a partial universe is fine for a survivorship-biased control). Logged, not silent.
            log.warning("coins_markets_ratelimited", page=page, got_candidates=len(out), err=str(exc))
            break
        if not rows:
            break  # category exhausted
        for c in rows:
            cid = c.get("id")
            if not isinstance(cid, str) or cid in seen:
                continue
            ref = _fdv_ref(c)
            if ref is None or not (band.fdv_min_usd <= ref <= band.fdv_max_usd):
                continue
            mint = mint_map.get(cid)
            if not mint:
                continue  # FDV-in-band but no resolvable Solana mint → can't trade it
            seen.add(cid)
            fdv = c.get("fully_diluted_valuation")
            out.append(
                MidcapCandidate(
                    coin_id=cid,
                    symbol=str(c.get("symbol") or "").upper(),
                    name=str(c.get("name") or ""),
                    mint=mint,
                    mcap_usd=_to_float(c.get("market_cap")),
                    fdv_usd=_to_float(fdv) if fdv is not None else _to_float(c.get("market_cap")),
                )
            )
    log.info("mcap_candidates", n=len(out), pages_scanned=page)
    return out


def _to_float(v: object) -> float | None:
    try:
        return float(v) if v is not None else None  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


async def resolve_deepest_pool(
    gt: GeckoTerminal, cand: MidcapCandidate
) -> PoolRow | None:
    """Find the candidate's DEEPEST pool and stamp it with authoritative CoinGecko FDV.

    Returns None if the token has no parseable pool. A 404 means GeckoTerminal indexes no
    pool for this mint (common for CoinGecko-listed tokens that never got a Solana DEX pool,
    or are bridged) — treated as "no pool", not an error. The reserve depth filter is applied
    by the caller (via `band.contains` on the returned row), not here.
    """
    try:
        raw = await gt.token_pools_raw(cand.mint)
    except httpx.HTTPStatusError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            return None  # no GeckoTerminal pool for this mint
        raise
    pools = [p for p in (parse_pool(item) for item in raw) if p is not None]
    pools = [p for p in pools if p.reserve_usd is not None]
    if not pools:
        return None
    deepest = max(pools, key=lambda p: p.reserve_usd or 0.0)
    # substitute CoinGecko's token-level FDV/mcap so the band test is correct even for
    # SOL-quoted pools (whose GeckoTerminal fdv_usd is the SOL FDV, not the token's).
    return dataclasses.replace(deepest, fdv_usd=cand.fdv_usd, mcap_usd=cand.mcap_usd)


async def build_midcap_universe(
    store: EventStore,
    band: UniverseBand,
    *,
    cg_api_key: str | None = None,
    max_pages: int = 12,
    per_page: int = 250,
) -> tuple[int, int, int, list[PoolRow]]:
    """Run the full mcap-ranked funnel and write one labelled universe snapshot.

    Returns (n_candidates, n_with_pool, n_in_band, in_band_rows). The snapshot records
    every FDV-in-band candidate that has a resolvable pool (in_band flags depth-pass), so
    it stays survivorship-honest over wall-clock. Source tag = 'coingecko_mcap_ranked'.
    """
    cg = CoinGecko(api_key=cg_api_key)
    gt = GeckoTerminal()
    try:
        candidates = await enumerate_candidates(cg, band, max_pages=max_pages, per_page=per_page)
        rows: list[PoolRow] = []
        for cand in candidates:
            try:
                pr = await resolve_deepest_pool(gt, cand)
            except (RetryableHTTPError, httpx.HTTPError) as exc:
                # never let one bad token abort a long run — skip it, keep what we have
                log.warning("resolve_pool_failed", symbol=cand.symbol, err=str(exc))
                continue
            if pr is not None:
                rows.append(pr)
                log.info(
                    "resolved_pool",
                    symbol=cand.symbol,
                    reserve=pr.reserve_usd,
                    fdv=cand.fdv_usd,
                    in_band=band.contains(pr),
                )
    finally:
        await cg.aclose()
        await gt.aclose()
    in_band = [r for r in rows if band.contains(r)]
    write_snapshot(
        store, rows, band, snapshot_at=datetime.now(UTC), source="coingecko_mcap_ranked"
    )
    log.info(
        "midcap_universe_built",
        candidates=len(candidates),
        with_pool=len(rows),
        in_band=len(in_band),
    )
    return len(candidates), len(rows), len(in_band), in_band
