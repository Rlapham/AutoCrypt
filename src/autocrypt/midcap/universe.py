"""Mid-cap deep-pool universe: parse → filter to band → snapshot / ingest OHLCV.

The band is load-bearing (later phases hard-depend on it) and was signed off in M1:
liquidity (reserve_in_usd) >= $500k AND FDV in [$1M, $250M]. The load-bearing parameter
is POOL DEPTH (reserve) — the whole point of Track M is to escape Iteration-1's Law 1
(the cost wall), which requires pools deep enough that our own price impact is small.
FDV bounds keep it genuinely *mid*-cap: above micro-cap dust, below stables/SOL majors.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from autocrypt.logging import get_logger
from autocrypt.providers.geckoterminal import GeckoTerminal
from autocrypt.storage.store import EventStore

log = get_logger("midcap")

# GeckoTerminal token relationship ids are namespaced "solana_<mint>".
_NETWORK_PREFIX = "solana_"


@dataclass(frozen=True)
class UniverseBand:
    """The mid-cap deep-pool selection band (M1, operator-signed-off)."""

    min_reserve_usd: float = 500_000.0
    fdv_min_usd: float = 1_000_000.0
    fdv_max_usd: float = 250_000_000.0

    def contains(self, pool: PoolRow) -> bool:
        if pool.reserve_usd is None or pool.fdv_usd is None:
            return False
        return (
            pool.reserve_usd >= self.min_reserve_usd
            and self.fdv_min_usd <= pool.fdv_usd <= self.fdv_max_usd
        )


@dataclass(frozen=True)
class PoolRow:
    """A parsed GeckoTerminal pool listing row (the fields the band needs)."""

    pool_address: str
    name: str
    base_mint: str | None
    quote_mint: str | None
    reserve_usd: float | None
    fdv_usd: float | None
    mcap_usd: float | None
    pool_created_at: datetime | None
    h24_volume_usd: float | None


def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _mint_from_rel(rel: dict[str, Any], key: str) -> str | None:
    """Extract a bare mint address from a GeckoTerminal relationship block."""
    data = (rel or {}).get(key, {}).get("data") or {}
    rid = data.get("id")
    if not isinstance(rid, str):
        return None
    return rid[len(_NETWORK_PREFIX) :] if rid.startswith(_NETWORK_PREFIX) else rid


def _parse_dt(v: Any) -> datetime | None:
    if not isinstance(v, str) or not v:
        return None
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_pool(item: dict[str, Any]) -> PoolRow | None:
    """Map one raw GeckoTerminal `/pools` item to a PoolRow (None if unusable)."""
    if not isinstance(item, dict):
        return None
    attrs = item.get("attributes") or {}
    addr = attrs.get("address")
    if not addr:
        return None
    vol = attrs.get("volume_usd") or {}
    rels = item.get("relationships") or {}
    return PoolRow(
        pool_address=addr,
        name=attrs.get("name") or "",
        base_mint=_mint_from_rel(rels, "base_token"),
        quote_mint=_mint_from_rel(rels, "quote_token"),
        reserve_usd=_to_float(attrs.get("reserve_in_usd")),
        fdv_usd=_to_float(attrs.get("fdv_usd")),
        mcap_usd=_to_float(attrs.get("market_cap_usd")),
        pool_created_at=_parse_dt(attrs.get("pool_created_at")),
        h24_volume_usd=_to_float(vol.get("h24") if isinstance(vol, dict) else None),
    )


async def enumerate_pools(gt: GeckoTerminal, *, max_pages: int = 10) -> list[PoolRow]:
    """Enumerate the current top pools (deduped by address). CURRENT snapshot only."""
    rows: dict[str, PoolRow] = {}
    for page in range(1, max_pages + 1):
        raw = await gt.top_pools_raw(page=page)
        if not raw:
            break  # endpoint exhausted (caps ~10 pages / 200 pools)
        for item in raw:
            row = parse_pool(item)
            if row is not None:
                rows.setdefault(row.pool_address, row)
    return list(rows.values())


# ── Forward snapshot storage (survivorship-safe over wall-clock) ──────────────

_SNAPSHOT_DDL = """
CREATE TABLE IF NOT EXISTS universe_snapshots (
    snapshot_at      TIMESTAMPTZ NOT NULL,
    pool_address     VARCHAR NOT NULL,
    name             VARCHAR,
    base_mint        VARCHAR,
    quote_mint       VARCHAR,
    reserve_usd      DOUBLE,
    fdv_usd          DOUBLE,
    mcap_usd         DOUBLE,
    h24_volume_usd   DOUBLE,
    pool_created_at  TIMESTAMPTZ,
    in_band          BOOLEAN NOT NULL,
    source           VARCHAR NOT NULL DEFAULT 'geckoterminal',
    PRIMARY KEY (snapshot_at, pool_address)
);
"""


def write_snapshot(
    store: EventStore, rows: list[PoolRow], band: UniverseBand, *, snapshot_at: datetime
) -> int:
    """Append one universe snapshot to the midcap store.

    ALL enumerated pools are recorded (with `in_band` flagged), not just in-band ones —
    that is what makes the forward series survivorship-safe: a pool captured here while
    alive remains in this snapshot even after it later dies/delists.
    """
    con = store.con  # reuse the store's single DuckDB connection
    con.execute(_SNAPSHOT_DDL)
    payload = [
        (
            snapshot_at,
            r.pool_address,
            r.name,
            r.base_mint,
            r.quote_mint,
            r.reserve_usd,
            r.fdv_usd,
            r.mcap_usd,
            r.h24_volume_usd,
            r.pool_created_at,
            band.contains(r),
        )
        for r in rows
    ]
    con.executemany(
        "INSERT OR REPLACE INTO universe_snapshots "
        "(snapshot_at, pool_address, name, base_mint, quote_mint, reserve_usd, fdv_usd, "
        " mcap_usd, h24_volume_usd, pool_created_at, in_band) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        payload,
    )
    return len(payload)


async def snapshot_universe(
    store: EventStore, band: UniverseBand, *, max_pages: int = 10
) -> tuple[int, int]:
    """Take one forward universe snapshot. Returns (n_enumerated, n_in_band)."""
    gt = GeckoTerminal()
    try:
        rows = await enumerate_pools(gt, max_pages=max_pages)
    finally:
        await gt.aclose()
    now = datetime.now(UTC)
    n_band = sum(1 for r in rows if band.contains(r))
    write_snapshot(store, rows, band, snapshot_at=now)
    log.info("universe_snapshot", enumerated=len(rows), in_band=n_band, at=now.isoformat())
    return len(rows), n_band


# ── Biased control dataset (immediate, explicitly survivorship-biased) ────────


async def build_control_dataset(
    store: EventStore,
    band: UniverseBand,
    *,
    run_id: str,
    interval: str = "1d",
    max_pages: int = 10,
    ohlcv_limit: int = 1000,
    latency: timedelta = timedelta(seconds=2),
) -> tuple[int, int]:
    """Ingest today's in-band pools' OHLCV — an EXPLICITLY survivorship-BIASED control.

    Returns (n_in_band_pools, n_bars_written). This is an upper bound, never a GO: the
    universe is today's survivors, so any positive expectancy could be pure survivorship.
    A NEGATIVE result here is the trustworthy one (bias only inflates returns).
    """
    gt = GeckoTerminal()
    bars_written = 0
    try:
        rows = await enumerate_pools(gt, max_pages=max_pages)
        in_band = [r for r in rows if band.contains(r)]
        # record the membership snapshot alongside the OHLCV so the control is auditable
        write_snapshot(store, rows, band, snapshot_at=datetime.now(UTC))
        log.info("control_universe", enumerated=len(rows), in_band=len(in_band))
        for r in in_band:
            batch = []
            async for bar in gt.iter_pool_ohlcv(
                r.pool_address,
                base_mint=r.base_mint,
                quote_mint=r.quote_mint,
                interval=interval,
                run_id=run_id,
                limit=ohlcv_limit,
                latency=latency,
            ):
                batch.append(bar)
            if batch:
                store.write_events(batch)
                bars_written += len(batch)
            log.info("control_ohlcv", pool=r.name[:24], bars=len(batch))
    finally:
        await gt.aclose()
    return len(in_band), bars_written
