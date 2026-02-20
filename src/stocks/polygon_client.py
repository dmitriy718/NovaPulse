from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import httpx

from src.core.logger import get_logger

logger = get_logger("polygon_client")


class PolygonClient:
    """Minimal async Polygon client for daily OHLCV bars."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.polygon.io",
        timeout_seconds: float = 20.0,
    ):
        self.api_key = (api_key or "").strip()
        self.base_url = (base_url or "https://api.polygon.io").rstrip("/")
        self.timeout_seconds = float(timeout_seconds)
        self._client: httpx.AsyncClient | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    async def initialize(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout_seconds)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def get_daily_bars(self, symbol: str, limit: int = 120) -> List[Dict[str, Any]]:
        """
        Return daily bars in ascending order.

        Items:
        - time: epoch seconds
        - open, high, low, close, volume
        """
        return await self.get_aggregate_bars(
            symbol=symbol,
            multiplier=1,
            timespan="day",
            limit=limit,
        )

    async def get_aggregate_bars(
        self,
        symbol: str,
        *,
        multiplier: int,
        timespan: str,
        limit: int = 300,
    ) -> List[Dict[str, Any]]:
        """
        Return Polygon aggregate bars in ascending order.

        Items:
        - time: epoch seconds
        - open, high, low, close, volume
        """
        if not self.enabled:
            return []
        if self._client is None:
            await self.initialize()

        mult = max(1, int(multiplier))
        span = (timespan or "day").strip().lower()
        lim = max(20, int(limit))

        if span == "minute":
            days_back = max(10, int((lim * mult) / (60 * 24) * 4) + 2)
        elif span == "hour":
            days_back = max(30, int((lim * mult) / 24 * 4) + 2)
        else:
            span = "day"
            days_back = max(30, int(lim * mult * 3))

        now = datetime.now(timezone.utc).date()
        start = now - timedelta(days=days_back)
        end = now
        url = (
            f"{self.base_url}/v2/aggs/ticker/{symbol.upper()}/range/{mult}/{span}/"
            f"{start.isoformat()}/{end.isoformat()}"
        )
        params = {
            "adjusted": "true",
            "sort": "asc",
            "limit": lim,
            "apiKey": self.api_key,
        }

        try:
            resp = await self._client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", []) or []
            bars: List[Dict[str, Any]] = []
            for row in results[-lim:]:
                ts_ms = float(row.get("t", 0) or 0)
                bars.append(
                    {
                        "time": ts_ms / 1000.0,
                        "open": float(row.get("o", 0) or 0),
                        "high": float(row.get("h", 0) or 0),
                        "low": float(row.get("l", 0) or 0),
                        "close": float(row.get("c", 0) or 0),
                        "volume": float(row.get("v", 0) or 0),
                    }
                )
            return bars
        except Exception as e:
            logger.warning(
                "Polygon aggregate fetch failed",
                symbol=symbol,
                multiplier=mult,
                timespan=span,
                error=repr(e),
            )
            return []
