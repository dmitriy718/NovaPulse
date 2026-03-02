"""Dynamic stock universe scanner.

Fetches tradeable tickers from Polygon, applies volume/price filters,
optionally overlays top movers, merges with pinned symbols, and caches
the result.  Refreshes periodically during market hours.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from src.core.logger import get_logger

logger = get_logger("universe_scanner")


class UniverseScanner:
    """Build and cache a dynamic stock universe from Polygon market data."""

    def __init__(self, polygon: Any, config: Any) -> None:
        self._polygon = polygon
        self._cfg = config.universe
        # Pinned symbols: explicit list, or fall back to static stocks.symbols
        pinned_raw = self._cfg.pinned_symbols or list(config.symbols or [])
        self._pinned: List[str] = [
            s.strip().upper() for s in pinned_raw if s and s.strip()
        ]
        self._cached_symbols: List[str] = list(self._pinned)
        self._cached_snapshots: Dict[str, Dict[str, Any]] = {}
        self._last_refresh_ts: float = 0.0
        self._last_request_ts: float = 0.0
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def symbols(self) -> List[str]:
        """Current universe.  Returns pinned symbols if never refreshed."""
        return list(self._cached_symbols)

    @property
    def cached_snapshots(self) -> Dict[str, Dict[str, Any]]:
        """Snapshot data keyed by ticker, for Tier-1 pre-filtering."""
        return self._cached_snapshots

    async def refresh(self) -> List[str]:
        """Full universe rebuild: fetch -> filter -> rank -> merge pinned -> cache."""
        async with self._lock:
            return await self._do_refresh()

    def is_market_hours(self) -> bool:
        """Check if current time is within US stock market hours.

        Market: 9:30 AM - 4:00 PM Eastern.
        pre_market_minutes extends the window before open.
        """
        # US Eastern = UTC-5 (EST) or UTC-4 (EDT)
        try:
            import zoneinfo
            et = zoneinfo.ZoneInfo("America/New_York")
        except Exception:
            # Fallback: approximate ET as UTC-5
            et = timezone(timedelta(hours=-5))
        now_et = datetime.now(et)
        # Skip weekends
        if now_et.weekday() >= 5:
            return False
        pre = max(0, self._cfg.pre_market_minutes)
        open_minutes = 9 * 60 + 30 - pre  # 9:30 AM minus pre-market
        close_minutes = 16 * 60            # 4:00 PM
        current_minutes = now_et.hour * 60 + now_et.minute
        return open_minutes <= current_minutes <= close_minutes

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _do_refresh(self) -> List[str]:
        logger.info("Universe refresh starting")
        t0 = time.monotonic()

        # --- Step 1: try bulk snapshots (single API call) -------------
        await self._rate_limit_delay()
        snapshots_list = await self._polygon.get_all_snapshots()
        snap_by_ticker: Dict[str, Dict[str, Any]] = {}

        if snapshots_list:
            for snap in snapshots_list:
                ticker = (snap.get("ticker") or "").strip().upper()
                if ticker:
                    snap_by_ticker[ticker] = snap
            logger.info(
                "Bulk snapshots fetched",
                count=len(snap_by_ticker),
            )
        else:
            # Fallback: grouped daily bars (free tier — single call, has OHLCV)
            logger.info("Bulk snapshots unavailable, falling back to grouped daily bars")
            snap_by_ticker = await self._fetch_grouped_fallback()

        if not snap_by_ticker:
            logger.warning("No ticker data obtained, keeping previous universe")
            return self._cached_symbols

        # --- Step 2: filter and rank ----------------------------------
        filtered = self._apply_filters(snap_by_ticker)

        # --- Step 3: optionally add top movers ------------------------
        movers: List[str] = []
        if self._cfg.include_movers:
            movers = await self._fetch_movers()
            # If Polygon snapshot endpoints returned nothing (free tier 403),
            # compute movers from the grouped daily bars we already have.
            if not movers and snap_by_ticker:
                movers = self._compute_movers_from_bars(snap_by_ticker)

        # --- Step 4: merge with pinned --------------------------------
        universe = self._merge(filtered, movers)

        # --- Step 5: cache --------------------------------------------
        self._cached_symbols = universe
        self._cached_snapshots = snap_by_ticker
        self._last_refresh_ts = time.time()

        elapsed = time.monotonic() - t0
        logger.info(
            "Universe refresh complete",
            total=len(universe),
            dynamic=len(universe) - len([s for s in self._pinned if s in universe]),
            pinned=len([s for s in self._pinned if s in universe]),
            movers_added=len([m for m in movers if m in universe]),
            elapsed_s=round(elapsed, 1),
        )
        return universe

    async def _fetch_grouped_fallback(self) -> Dict[str, Dict[str, Any]]:
        """Fetch grouped daily bars as fallback when bulk snapshots are unavailable.

        Uses /v2/aggs/grouped which returns OHLCV for ALL tickers in one call.
        Available on Polygon free tier.
        """
        await self._rate_limit_delay()
        grouped = await self._polygon.get_grouped_daily_bars()
        if not grouped:
            logger.warning("Grouped daily bars also unavailable")
            return {}

        # Convert grouped bar format to snapshot-compatible format
        snap_by_ticker: Dict[str, Dict[str, Any]] = {}
        for ticker, row in grouped.items():
            snap_by_ticker[ticker] = {
                "ticker": ticker,
                "day": {
                    "c": row.get("c", 0),
                    "v": row.get("v", 0),
                    "o": row.get("o", 0),
                    "h": row.get("h", 0),
                    "l": row.get("l", 0),
                },
                "prevDay": {
                    "c": row.get("o", 0),  # Approximate prev close with open
                },
            }

        logger.info("Grouped daily bars fetched", count=len(snap_by_ticker))
        return snap_by_ticker

    def _apply_filters(self, snap_by_ticker: Dict[str, Dict[str, Any]]) -> List[str]:
        """Filter by price/volume, rank by volume descending."""
        candidates: List[tuple[str, float]] = []
        min_vol = self._cfg.min_avg_volume
        min_price = self._cfg.min_price
        max_price = self._cfg.max_price

        for ticker, snap in snap_by_ticker.items():
            try:
                day = snap.get("day") or {}
                price = float(day.get("c", 0) or 0)
                volume = float(day.get("v", 0) or 0)

                if price < min_price or price > max_price:
                    continue
                if volume < min_vol:
                    continue

                candidates.append((ticker, volume))
            except (ValueError, TypeError):
                continue

        # Sort by volume descending (most liquid first)
        candidates.sort(key=lambda x: x[1], reverse=True)

        # Reserve slots for pinned symbols
        max_dynamic = max(0, self._cfg.max_universe_size - len(self._pinned))
        return [sym for sym, _ in candidates[:max_dynamic]]

    async def _fetch_movers(self) -> List[str]:
        """Fetch top gainers AND losers as bonus candidates."""
        movers: List[str] = []
        half = max(1, self._cfg.movers_count // 2)

        # Top gainers
        await self._rate_limit_delay()
        gainers = await self._polygon.get_gainers_losers("gainers")
        for snap in gainers[:half]:
            ticker = (snap.get("ticker") or "").strip().upper()
            if ticker:
                movers.append(ticker)

        # Top losers (big drops = reversal / momentum plays)
        await self._rate_limit_delay()
        losers = await self._polygon.get_gainers_losers("losers")
        for snap in losers[:half]:
            ticker = (snap.get("ticker") or "").strip().upper()
            if ticker and ticker not in movers:
                movers.append(ticker)

        if movers:
            logger.info(
                "Top movers fetched",
                gainers=min(half, len(gainers)),
                losers=min(half, len(losers)),
                total=len(movers),
            )
        return movers

    def _compute_movers_from_bars(
        self, snap_by_ticker: Dict[str, Dict[str, Any]]
    ) -> List[str]:
        """Derive top gainers and losers from grouped daily bar data.

        Uses open vs close to estimate daily change percentage.
        Returns a mix of top gainers and top losers.
        """
        half = max(1, self._cfg.movers_count // 2)
        min_vol = self._cfg.min_avg_volume
        min_price = self._cfg.min_price

        scored: List[tuple[str, float]] = []
        for ticker, snap in snap_by_ticker.items():
            try:
                day = snap.get("day") or {}
                close = float(day.get("c", 0) or 0)
                open_price = float(day.get("o", 0) or 0)
                volume = float(day.get("v", 0) or 0)
                if close <= 0 or open_price <= 0 or close < min_price or volume < min_vol:
                    continue
                change_pct = (close - open_price) / open_price
                scored.append((ticker, change_pct))
            except (ValueError, TypeError):
                continue

        if not scored:
            return []

        # Sort by change_pct: top gainers first, then top losers
        scored.sort(key=lambda x: x[1], reverse=True)
        gainers = [s for s, _ in scored[:half]]
        losers = [s for s, _ in scored[-half:]]
        movers = gainers + [s for s in losers if s not in gainers]

        logger.info(
            "Movers computed from daily bars",
            gainers=len(gainers),
            losers=len([s for s in losers if s not in gainers]),
            total=len(movers),
        )
        return movers

    def _merge(self, dynamic: List[str], movers: List[str]) -> List[str]:
        """Merge pinned + movers + dynamic, deduplicated, capped."""
        seen: set[str] = set()
        result: List[str] = []

        # Pinned first
        for sym in self._pinned:
            if sym not in seen:
                seen.add(sym)
                result.append(sym)

        # Movers next (high-interest bonus)
        for sym in movers:
            if sym not in seen:
                seen.add(sym)
                result.append(sym)

        # Dynamic remainder
        for sym in dynamic:
            if len(result) >= self._cfg.max_universe_size:
                break
            if sym not in seen:
                seen.add(sym)
                result.append(sym)

        return result

    async def _rate_limit_delay(self) -> None:
        """Enforce minimum inter-request delay for Polygon API."""
        rate = max(1, self._cfg.polygon_rate_limit_per_min)
        min_interval = 60.0 / rate
        elapsed = time.time() - self._last_request_ts
        if elapsed < min_interval:
            await asyncio.sleep(min_interval - elapsed)
        self._last_request_ts = time.time()
