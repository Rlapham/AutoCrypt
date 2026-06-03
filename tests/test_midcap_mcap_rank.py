"""Tests for the M1b mcap-ranked enumeration funnel — pure logic, fake providers, no net.

These pin the inverted funnel's three contracts:
  (1) the FDV-band filter prefers fully_diluted_valuation, falls back to market_cap, and
      drops candidates with no resolvable Solana mint;
  (2) `resolve_deepest_pool` picks the DEEPEST pool and substitutes CoinGecko's
      authoritative FDV (fixing M1's SOL-quoted-pool FDV confusion);
  (3) `build_midcap_universe` records every candidate-with-a-pool and counts in-band by the
      substituted FDV + reserve depth.
"""

from __future__ import annotations

import pytest

from autocrypt.midcap.mcap_rank import (
    MidcapCandidate,
    _fdv_ref,
    build_midcap_universe,
    enumerate_candidates,
    resolve_deepest_pool,
)
from autocrypt.midcap.universe import UniverseBand
from autocrypt.storage.store import EventStore


def _coin(cid, fdv=50_000_000, mcap=40_000_000, sym="mid", name="MidCoin"):
    return {
        "id": cid,
        "symbol": sym,
        "name": name,
        "market_cap": mcap,
        "fully_diluted_valuation": fdv,
    }


def _pool(addr, reserve, base="solana_MINTX", quote="solana_SOL", fdv="999999999"):
    # GeckoTerminal pool item: fdv here is the (possibly SOL-quote-confused) pool FDV,
    # which the funnel must OVERRIDE with CoinGecko's token-level FDV.
    return {
        "id": f"solana_{addr}",
        "attributes": {
            "address": addr,
            "name": "MID / SOL",
            "reserve_in_usd": reserve,
            "fdv_usd": fdv,
            "market_cap_usd": None,
            "pool_created_at": "2026-01-15T10:00:00Z",
            "volume_usd": {"h24": "1000"},
        },
        "relationships": {
            "base_token": {"data": {"id": base}},
            "quote_token": {"data": {"id": quote}},
        },
    }


class _FakeCG:
    """Stand-in CoinGecko: one page of markets + a fixed mint map."""

    def __init__(self, rows, mint_map):
        self._rows = rows
        self._mint_map = mint_map

    async def coins_markets(self, *, category=None, page=1, per_page=250, **_):
        return self._rows if page == 1 else []

    async def solana_mint_map(self):
        return self._mint_map

    async def aclose(self):  # pragma: no cover - trivial
        pass


class _FakeGT:
    """Stand-in GeckoTerminal: maps mint → list of raw pool items."""

    def __init__(self, by_mint):
        self._by_mint = by_mint

    async def token_pools_raw(self, mint, page=1):
        return self._by_mint.get(mint, []) if page == 1 else []

    async def aclose(self):  # pragma: no cover - trivial
        pass


def test_fdv_ref_prefers_fdv_falls_back_to_mcap():
    assert _fdv_ref(_coin("a", fdv=7, mcap=3)) == 7.0
    assert _fdv_ref({"market_cap": 5, "fully_diluted_valuation": None}) == 5.0
    assert _fdv_ref({"market_cap": None, "fully_diluted_valuation": None}) is None


@pytest.mark.asyncio
async def test_enumerate_candidates_filters_band_and_requires_mint():
    band = UniverseBand()  # FDV in [1M, 250M]
    rows = [
        _coin("inband", fdv=50_000_000),       # in band, has mint → kept
        _coin("major", fdv=300_000_000),       # FDV too big → dropped
        _coin("dust", fdv=500_000),            # FDV too small → dropped
        _coin("nomint", fdv=20_000_000),       # in band but no Solana mint → dropped
    ]
    cg = _FakeCG(rows, mint_map={"inband": "MINTX", "major": "M2", "dust": "M3"})
    cands = await enumerate_candidates(cg, band, max_pages=3)
    assert [c.coin_id for c in cands] == ["inband"]
    assert cands[0].mint == "MINTX"
    assert cands[0].fdv_usd == 50_000_000.0


@pytest.mark.asyncio
async def test_resolve_deepest_pool_picks_max_reserve_and_overrides_fdv():
    cand = MidcapCandidate("c", "MID", "MidCoin", "MINTX", mcap_usd=40e6, fdv_usd=50e6)
    gt = _FakeGT(
        {"MINTX": [_pool("SHALLOW", "100000"), _pool("DEEP", "900000"), _pool("MID", "400000")]}
    )
    row = await resolve_deepest_pool(gt, cand)
    assert row is not None
    assert row.pool_address == "DEEP"  # deepest by reserve
    assert row.reserve_usd == 900_000.0
    assert row.fdv_usd == 50_000_000.0  # OVERRIDDEN with CoinGecko FDV (not pool's 999999999)


@pytest.mark.asyncio
async def test_resolve_deepest_pool_none_when_no_pool():
    cand = MidcapCandidate("c", "MID", "MidCoin", "MINTX", mcap_usd=None, fdv_usd=50e6)
    assert await resolve_deepest_pool(_FakeGT({}), cand) is None


@pytest.mark.asyncio
async def test_resolve_deepest_pool_404_is_no_pool_not_crash():
    """A token GeckoTerminal doesn't index returns 404 → treat as no pool, never crash."""
    import httpx

    class _GT404:
        async def token_pools_raw(self, mint, page=1):
            req = httpx.Request("GET", "https://x/pools")
            raise httpx.HTTPStatusError(
                "404", request=req, response=httpx.Response(404, request=req)
            )

    cand = MidcapCandidate("c", "MID", "MidCoin", "MINTX", mcap_usd=None, fdv_usd=50e6)
    assert await resolve_deepest_pool(_GT404(), cand) is None


@pytest.mark.asyncio
async def test_build_midcap_universe_counts_and_writes(tmp_path, monkeypatch):
    band = UniverseBand()
    rows = [_coin("deep", fdv=50e6), _coin("thin", fdv=60e6)]
    cg = _FakeCG(rows, mint_map={"deep": "DMINT", "thin": "TMINT"})
    gt = _FakeGT(
        {
            "DMINT": [_pool("DEEP", "900000")],   # depth pass → in band
            "TMINT": [_pool("THIN", "100000")],   # has a pool but too shallow → out of band
        }
    )
    import autocrypt.midcap.mcap_rank as mr

    monkeypatch.setattr(mr, "CoinGecko", lambda *a, **k: cg)
    monkeypatch.setattr(mr, "GeckoTerminal", lambda *a, **k: gt)

    store = EventStore(tmp_path / "midcap.duckdb")
    n_cand, n_pool, n_band, in_band = await build_midcap_universe(store, band, max_pages=1)
    assert (n_cand, n_pool, n_band) == (2, 2, 1)
    assert [r.pool_address for r in in_band] == ["DEEP"]
    # snapshot records BOTH candidates-with-pools (survivorship-honest), tagged by source
    got = dict(
        store.con.execute(
            "SELECT pool_address, in_band FROM universe_snapshots "
            "WHERE source = 'coingecko_mcap_ranked'"
        ).fetchall()
    )
    assert got == {"DEEP": True, "THIN": False}
    store.close()
