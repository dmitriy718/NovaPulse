"""
On-Chain Data Client — Async fetcher for blockchain sentiment signals.

Follows the exact pattern from FundingRateClient: async fetch with httpx,
TTL-cached dict, asyncio.Lock, graceful error handling.

Real implementation would call blockchain.info, DeFiLlama, Glassnode, etc.
Current version uses a deterministic mock that can be swapped for real APIs
once API keys are available.
"""

from __future__ import annotations

import asyncio
import math
import time
from typing import Dict, Optional

from src.core.logger import get_logger

logger = get_logger("onchain_data")


class OnChainDataClient:
    """Async client for fetching on-chain sentiment data."""

    def __init__(
        self,
        cache_ttl_seconds: int = 900,
        weight: float = 0.08,
        min_abs_score: float = 0.3,
    ):
        self._cache: Dict[str, float] = {}
        self._cache_ts: float = 0.0
        self._ttl = max(60, int(cache_ttl_seconds))
        self._weight = max(0.0, min(0.5, float(weight)))
        self._min_abs_score = max(0.0, min(1.0, float(min_abs_score)))
        self._lock = asyncio.Lock()

    @property
    def weight(self) -> float:
        return self._weight

    @property
    def min_abs_score(self) -> float:
        return self._min_abs_score

    async def fetch_sentiments(self) -> Dict[str, float]:
        """Fetch on-chain sentiment scores for supported pairs.

        TTL-cached, async with lock. Returns a dict of pair -> sentiment
        where sentiment is in [-1, +1].

        Currently a stub that returns empty dict (no real API keys).
        Real implementation would call blockchain.info, DeFiLlama, etc.
        """
        now = time.time()
        if (now - self._cache_ts) < self._ttl and self._cache:
            return dict(self._cache)

        async with self._lock:
            # Double-check after acquiring lock
            if (time.time() - self._cache_ts) < self._ttl and self._cache:
                return dict(self._cache)

            try:
                sentiments = await self._fetch_raw()
            except Exception as e:
                logger.warning("On-chain fetch failed, using cached data", error=repr(e))
                sentiments = {}
            if sentiments:
                self._cache = sentiments
                self._cache_ts = time.time()
            return dict(self._cache)

    async def _fetch_raw(self) -> Dict[str, float]:
        """Fetch raw on-chain data from external APIs.

        Gracefully returns empty dict if no external data is available.
        Override this method or extend for real API integration.
        """
        sentiments: Dict[str, float] = {}
        try:
            # Attempt to fetch real data (currently no keys configured)
            # When real APIs are added, use httpx similar to FundingRateClient:
            #
            # import httpx
            # async with httpx.AsyncClient(timeout=10.0) as client:
            #     resp = await client.get(API_URL, headers={"Authorization": ...})
            #     resp.raise_for_status()
            #     data = resp.json()
            #     ... parse into sentiments dict ...
            #
            # For now: return empty (no external data available)
            logger.debug("On-chain fetch: no API configured, returning empty")
        except Exception as e:
            logger.warning("On-chain data fetch failed", error=repr(e))

        return sentiments

    def get_sentiment(self, pair: str) -> Optional[float]:
        """Return cached sentiment for a pair, or None if unavailable.

        Returns a value in [-1, +1] where:
        - Positive = bullish (e.g. exchange outflows, stablecoin minting)
        - Negative = bearish (e.g. exchange inflows, whale selling)
        """
        val = self._cache.get(pair)
        if val is not None and math.isfinite(val):
            return max(-1.0, min(1.0, val))
        return None

    def get_all_sentiments(self) -> Dict[str, float]:
        """Return all cached sentiments."""
        return {
            k: max(-1.0, min(1.0, v))
            for k, v in self._cache.items()
            if math.isfinite(v)
        }

    def inject_sentiments(self, sentiments: Dict[str, float]) -> None:
        """Manually inject sentiment data (useful for testing or external feeds)."""
        self._cache = {
            k: max(-1.0, min(1.0, float(v)))
            for k, v in sentiments.items()
            if isinstance(v, (int, float)) and math.isfinite(float(v))
        }
        self._cache_ts = time.time()
