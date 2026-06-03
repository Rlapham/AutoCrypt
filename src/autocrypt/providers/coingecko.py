"""CoinGecko adapter (free public / demo tier) — market-cap-ranked enumeration.

Track M's M1 finding: GeckoTerminal's volume-ranked top-pools endpoint is the WRONG
enumeration source for mid-caps (Solana liquidity is barbelled → n=1 in-band). CoinGecko
inverts the funnel: enumerate tokens by *market-cap rank* (authoritative token-level FDV,
not the pool-quote-confused FDV GeckoTerminal reports for SOL-quoted pools), then hand the
mints to GeckoTerminal to find the deepest pool. This adapter supplies the mcap-rank side.

READ-ONLY. Free public tier is ~10-30 req/min and aggressively throttled; we stay low and
honour 429 backoff via the shared base. A demo key (env COINGECKO_API_KEY) lifts the limit
and is sent as the `x-cg-demo-api-key` header when present.

SURVIVORSHIP NOTE: `/coins/markets` and `/coins/list` are CURRENT snapshots — there is no
"as-of" param on the free tier. The mid-cap universe built from this is therefore a
survivorship-BIASED control universe (today's survivors), exactly as M1 signed off. It can
only ever yield a NO-GO / "unproven", never a false GO.
"""

from __future__ import annotations

from typing import Any

from autocrypt.providers.base import HTTPProvider
from autocrypt.schema import Source

# CoinGecko's curated category slug for Solana-ecosystem tokens. Filtering server-side
# here is far cheaper than paging all ~17k coins and intersecting with the platform map.
SOLANA_CATEGORY = "solana-ecosystem"


class CoinGecko(HTTPProvider):
    """Market-cap-ranked token enumeration + id→Solana-mint mapping (free tier)."""

    base_url = "https://api.coingecko.com/api/v3"
    per_minute = 5.0  # keyless public tier 429s aggressively; stay very low (key bumps it)
    source = Source.coingecko

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        headers = {"x-cg-demo-api-key": api_key} if api_key else {}
        # a demo key lifts the public limit to ~30/min; still stay under it
        if api_key and "per_minute" not in kwargs:
            kwargs["per_minute"] = 25.0
        super().__init__(headers=headers, **kwargs)
        self._api_key = api_key

    async def coins_markets(
        self,
        *,
        category: str | None = SOLANA_CATEGORY,
        page: int = 1,
        per_page: int = 250,
        order: str = "market_cap_desc",
        vs_currency: str = "usd",
    ) -> list[dict[str, Any]]:
        """One page of `/coins/markets` (mcap-ranked). Returns [] when exhausted.

        Each row carries `id`, `symbol`, `name`, `market_cap`, and
        `fully_diluted_valuation` — the fields the FDV band needs.
        """
        params: dict[str, Any] = {
            "vs_currency": vs_currency,
            "order": order,
            "per_page": per_page,
            "page": page,
        }
        if category:
            params["category"] = category
        data = await self.get_json("/coins/markets", params=params)
        return data if isinstance(data, list) else []

    async def solana_mint_map(self) -> dict[str, str]:
        """Map CoinGecko coin-id → Solana mint, for every coin with a Solana address.

        One call to `/coins/list?include_platform=true` (the whole coin list, ~17k rows)
        avoids a rate-limited per-coin `/coins/{id}` lookup.
        """
        data = await self.get_json("/coins/list", params={"include_platform": "true"})
        out: dict[str, str] = {}
        if not isinstance(data, list):
            return out
        for c in data:
            if not isinstance(c, dict):
                continue
            plats = c.get("platforms")
            mint = plats.get("solana") if isinstance(plats, dict) else None
            cid = c.get("id")
            if isinstance(cid, str) and isinstance(mint, str) and mint:
                out[cid] = mint
        return out
