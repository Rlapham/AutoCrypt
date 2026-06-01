"""Read-only HTTP provider base: async client + polite rate limiting + retry.

All providers are READ-ONLY (Phase 1). No endpoint here may sign, broadcast, or move
funds. Each provider emits canonical-schema records via its adapter methods.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from autocrypt.logging import get_logger

log = get_logger("providers")


class RateLimiter:
    """Simple async min-interval gate (one shared instance per provider).

    `per_minute` is the provider's documented free-tier ceiling; we stay strictly
    under it by spacing calls at least `60/per_minute` seconds apart.
    """

    def __init__(self, per_minute: float) -> None:
        self.min_interval = 60.0 / per_minute if per_minute > 0 else 0.0
        self._lock = asyncio.Lock()
        self._next_at = 0.0

    async def acquire(self) -> None:
        if self.min_interval <= 0:
            return
        async with self._lock:
            now = time.monotonic()
            wait = self._next_at - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._next_at = max(now, self._next_at) + self.min_interval


class RetryableHTTPError(Exception):
    """Raised for transient HTTP failures (429/5xx) so tenacity retries them."""


class HTTPProvider:
    """Base async HTTP provider with rate limiting + backoff on 429/5xx."""

    base_url: str = ""
    per_minute: float = 60.0  # default polite ceiling; override per provider

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        headers: dict[str, str] | None = None,
        per_minute: float | None = None,
    ) -> None:
        self._own_client = client is None
        self._client = client or httpx.AsyncClient(timeout=30.0)
        self._headers = {
            "Accept": "application/json",
            "User-Agent": "autocrypt/0.1 (+research, read-only)",
            **(headers or {}),
        }
        self.limiter = RateLimiter(per_minute if per_minute is not None else self.per_minute)

    async def aclose(self) -> None:
        if self._own_client:
            await self._client.aclose()

    async def __aenter__(self) -> HTTPProvider:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    @retry(
        retry=retry_if_exception_type(RetryableHTTPError),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    async def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET an endpoint and return parsed JSON, honoring rate limits + retries."""
        await self.limiter.acquire()
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        resp = await self._client.get(url, params=params, headers=self._headers)
        if resp.status_code == 429 or resp.status_code >= 500:
            log.warning("http_retryable", url=url, status=resp.status_code)
            raise RetryableHTTPError(f"{resp.status_code} for {url}")
        resp.raise_for_status()
        return resp.json()
