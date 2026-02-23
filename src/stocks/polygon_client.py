from __future__ import annotations

import re
from urllib.parse import quote
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import httpx

from src.core.logger import get_logger

logger = get_logger("polygon_client")
_OPTION_SYMBOL_RE = re.compile(r"^(?:O:)?[A-Z]{1,6}\d{6}[CP]\d{8}$")


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
        ticker = self._polygon_ticker(symbol)
        url = (
            f"{self.base_url}/v2/aggs/ticker/{ticker}/range/{mult}/{span}/"
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

    async def get_all_snapshots(self) -> List[Dict[str, Any]]:
        """
        Fetch all US stock snapshots in a single bulk call.

        Returns list of snapshot dicts with keys: ticker, day, prevDay,
        lastTrade, min, etc.  Empty list on error or if endpoint is
        unavailable (e.g. free-tier restriction).
        """
        if not self.enabled:
            return []
        if self._client is None:
            await self.initialize()
        url = f"{self.base_url}/v2/snapshot/locale/us/markets/stocks/tickers"
        params = {"apiKey": self.api_key}
        try:
            resp = await self._client.get(url, params=params, timeout=60.0)
            resp.raise_for_status()
            data = resp.json()
            return data.get("tickers", []) or []
        except Exception as e:
            logger.warning("Polygon bulk snapshot fetch failed", error=repr(e))
            return []

    async def get_reference_tickers(
        self,
        *,
        market: str = "stocks",
        ticker_type: str = "CS",
        active: bool = True,
        limit: int = 1000,
        cursor: str = "",
    ) -> tuple[List[Dict[str, Any]], str]:
        """
        Fetch tickers from /v3/reference/tickers with cursor pagination.

        Returns (tickers_list, next_cursor).  next_cursor is empty when
        there are no more pages.
        """
        if not self.enabled:
            return [], ""
        if self._client is None:
            await self.initialize()
        url = f"{self.base_url}/v3/reference/tickers"
        params: Dict[str, Any] = {
            "market": market,
            "type": ticker_type,
            "active": str(active).lower(),
            "order": "asc",
            "limit": min(limit, 1000),
            "sort": "ticker",
            "apiKey": self.api_key,
        }
        if cursor:
            params["cursor"] = cursor
        try:
            resp = await self._client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            tickers = data.get("results", []) or []
            next_cursor = data.get("next_url", "") or ""
            # Extract cursor param from next_url if present
            if next_cursor and "cursor=" in next_cursor:
                next_cursor = next_cursor.split("cursor=", 1)[1].split("&", 1)[0]
            elif next_cursor:
                next_cursor = ""
            return tickers, next_cursor
        except Exception as e:
            logger.warning("Polygon reference tickers fetch failed", error=repr(e))
            return [], ""

    async def get_gainers_losers(
        self, direction: str = "gainers"
    ) -> List[Dict[str, Any]]:
        """
        Fetch top gainers or losers snapshot.

        direction: "gainers" or "losers"
        Returns list of snapshot dicts.
        """
        if not self.enabled:
            return []
        if self._client is None:
            await self.initialize()
        direction = direction if direction in ("gainers", "losers") else "gainers"
        url = (
            f"{self.base_url}/v2/snapshot/locale/us/markets/stocks/{direction}"
        )
        params = {"apiKey": self.api_key}
        try:
            resp = await self._client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            return data.get("tickers", []) or []
        except Exception as e:
            logger.warning(
                "Polygon gainers/losers fetch failed",
                direction=direction,
                error=repr(e),
            )
            return []

    async def get_grouped_daily_bars(
        self, date: str = "",
    ) -> Dict[str, Dict[str, Any]]:
        """
        Fetch grouped daily OHLCV for ALL US stocks in a single call.

        Uses /v2/aggs/grouped/locale/us/market/stocks/{date}.
        Returns dict keyed by ticker with keys: o, h, l, c, v, t.
        Available on free tier.
        """
        if not self.enabled:
            return {}
        if self._client is None:
            await self.initialize()
        if not date:
            from datetime import datetime, timezone, timedelta
            # Use previous trading day: Mon→Fri(3), Sun→Fri(2), Sat→Fri(1), else→yesterday(1)
            today = datetime.now(timezone.utc).date()
            wd = today.weekday()
            offset = 3 if wd == 0 else 2 if wd == 6 else 1 if wd == 5 else 1
            date = (today - timedelta(days=offset)).isoformat()
        url = f"{self.base_url}/v2/aggs/grouped/locale/us/market/stocks/{date}"
        params = {"adjusted": "true", "apiKey": self.api_key}
        try:
            resp = await self._client.get(url, params=params, timeout=60.0)
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", []) or []
            out: Dict[str, Dict[str, Any]] = {}
            for row in results:
                ticker = (row.get("T") or "").strip().upper()
                if ticker:
                    out[ticker] = row
            return out
        except Exception as e:
            logger.warning("Polygon grouped daily fetch failed", error=repr(e))
            return {}

    @staticmethod
    def _polygon_ticker(symbol: str) -> str:
        raw = str(symbol or "").strip().upper()
        if _OPTION_SYMBOL_RE.match(raw) and not raw.startswith("O:"):
            raw = f"O:{raw}"
        return quote(raw, safe="")
