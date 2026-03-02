"""
Funding Rate Client — Lightweight async fetcher for Kraken Futures funding rates.

Uses the free public Kraken Futures API (no auth required):
  GET https://futures.kraken.com/derivatives/api/v3/tickers

Provides funding rate data for perpetual contracts, mapped to spot pairs.
5-minute TTL cache to minimize API calls.  Circuit breaker opens after
consecutive failures to avoid hammering a degraded endpoint.
"""

from __future__ import annotations

import asyncio
import random
import time
from typing import Dict, Optional

from src.core.logger import get_logger

logger = get_logger("funding_rates")

# Mapping from Kraken Futures perpetual symbols to spot pair names
_FUTURES_TO_SPOT: Dict[str, str] = {
    "PF_XBTUSD": "BTC/USD",
    "PF_ETHUSD": "ETH/USD",
    "PF_SOLUSD": "SOL/USD",
    "PF_XRPUSD": "XRP/USD",
    "PF_ADAUSD": "ADA/USD",
    "PF_DOTUSD": "DOT/USD",
    "PF_AVAXUSD": "AVAX/USD",
    "PF_LINKUSD": "LINK/USD",
}

_TICKERS_URL = "https://futures.kraken.com/derivatives/api/v3/tickers"
_CACHE_TTL_SECONDS = 300  # 5 minutes
_CIRCUIT_FAILURE_THRESHOLD = 3
_CIRCUIT_OPEN_SECONDS = 300  # 5 minutes


class FundingRateClient:
    """Async client for fetching Kraken Futures funding rates."""

    def __init__(self, cache_ttl: int = _CACHE_TTL_SECONDS):
        self._cache: Dict[str, float] = {}
        self._cache_ts: float = 0.0
        self._cache_ttl = max(60, cache_ttl)
        self._lock = asyncio.Lock()
        # Circuit breaker state
        self._consecutive_failures: int = 0
        self._circuit_open_until: float = 0.0

    async def _fetch_rates(self) -> Dict[str, float]:
        """Fetch all funding rates from Kraken Futures public API with retry."""
        import httpx

        rates: Dict[str, float] = {}
        max_retries = 3

        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(_TICKERS_URL)
                    resp.raise_for_status()
                    data = resp.json()

                tickers = data.get("tickers", [])
                for ticker in tickers:
                    symbol = str(ticker.get("symbol", "")).upper()
                    spot_pair = _FUTURES_TO_SPOT.get(symbol)
                    if spot_pair is None:
                        continue
                    funding_rate = ticker.get("fundingRate")
                    if funding_rate is not None:
                        try:
                            rates[spot_pair] = float(funding_rate)
                        except (TypeError, ValueError):
                            pass

                logger.debug("Funding rates fetched", count=len(rates))
                return rates

            except Exception as e:
                is_server_error = (
                    hasattr(e, "response")
                    and getattr(e.response, "status_code", 0) >= 500
                )
                if is_server_error and attempt < max_retries - 1:
                    delay = (2 ** attempt) + random.uniform(0, 1)
                    logger.debug(
                        "Funding rate retry",
                        attempt=attempt + 1,
                        delay=round(delay, 1),
                    )
                    await asyncio.sleep(delay)
                    continue
                logger.warning("Funding rate fetch failed", error=repr(e))
                break

        return rates

    async def get_all_rates(self) -> Dict[str, float]:
        """Get all funding rates (cached with TTL + circuit breaker)."""
        now = time.time()

        # Cache hit
        if (now - self._cache_ts) < self._cache_ttl and self._cache:
            return dict(self._cache)

        # Circuit breaker — serve stale cache instead of hammering a failing endpoint
        if now < self._circuit_open_until:
            return dict(self._cache)

        async with self._lock:
            # Double-check after acquiring lock
            if (time.time() - self._cache_ts) < self._cache_ttl and self._cache:
                return dict(self._cache)
            if time.time() < self._circuit_open_until:
                return dict(self._cache)

            rates = await self._fetch_rates()
            if rates:
                self._cache = rates
                self._cache_ts = time.time()
                self._consecutive_failures = 0
                self._circuit_open_until = 0.0
            else:
                self._consecutive_failures += 1
                if self._consecutive_failures >= _CIRCUIT_FAILURE_THRESHOLD:
                    self._circuit_open_until = time.time() + _CIRCUIT_OPEN_SECONDS
                    logger.warning(
                        "Funding rate circuit breaker OPEN",
                        failures=self._consecutive_failures,
                        cooldown_seconds=_CIRCUIT_OPEN_SECONDS,
                    )
            return dict(self._cache)

    async def get_funding_rate(self, pair: str) -> Optional[float]:
        """Get funding rate for a specific spot pair."""
        rates = await self.get_all_rates()
        return rates.get(pair)
