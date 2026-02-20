"""
Session-Aware Trading — confidence multiplier based on hour-of-day performance.

Computes a per-hour multiplier (0.70–1.15) from historical trade win rates.
Strong hours get a modest confidence boost, weak hours get a penalty.
Hours with insufficient data default to neutral (1.0).
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from src.core.database import DatabaseManager
from src.core.logger import get_logger

logger = get_logger("session_analyzer")


class SessionAnalyzer:
    """Cached per-hour confidence multiplier, refreshed from DB hourly."""

    def __init__(
        self,
        db: DatabaseManager,
        min_trades_per_hour: int = 5,
        max_boost: float = 1.15,
        max_penalty: float = 0.70,
        tenant_id: str = "default",
    ):
        self.db = db
        self.min_trades = min_trades_per_hour
        self.max_boost = max_boost
        self.max_penalty = max_penalty
        self.tenant_id = tenant_id

        self._cache: Dict[int, float] = {}  # hour → multiplier
        self._last_refresh: float = 0.0
        self._refresh_interval: float = 3600.0  # 1 hour

    async def refresh(self) -> None:
        """Refresh hourly stats from DB and recompute multipliers."""
        try:
            stats = await self.db.get_hourly_stats(tenant_id=self.tenant_id)
        except Exception as e:
            logger.warning("Session stats refresh failed", error=repr(e))
            return

        new_cache: Dict[int, float] = {}
        for hour in range(24):
            entry = stats.get(hour)
            if not entry or entry["total"] < self.min_trades:
                new_cache[hour] = 1.0
                continue

            win_rate = entry["wins"] / entry["total"]
            # Linear interpolation:
            # win_rate 0.50 → 1.0 (neutral)
            # win_rate 0.80+ → max_boost (1.15)
            # win_rate 0.25- → max_penalty (0.70)
            if win_rate >= 0.50:
                # Scale from 1.0 to max_boost over win_rate 0.50–0.80
                t = min((win_rate - 0.50) / 0.30, 1.0)
                mult = 1.0 + t * (self.max_boost - 1.0)
            else:
                # Scale from 1.0 to max_penalty over win_rate 0.50–0.25
                t = min((0.50 - win_rate) / 0.25, 1.0)
                mult = 1.0 - t * (1.0 - self.max_penalty)

            new_cache[hour] = round(mult, 3)

        self._cache = new_cache
        self._last_refresh = time.time()

        non_neutral = {h: m for h, m in new_cache.items() if m != 1.0}
        if non_neutral:
            logger.info("Session multipliers refreshed", non_neutral=non_neutral)

    def get_multiplier(self, hour: int) -> float:
        """Get confidence multiplier for given UTC hour (synchronous, cached)."""
        return self._cache.get(hour % 24, 1.0)

    async def maybe_refresh(self) -> None:
        """Refresh if stale. Call this from the main scan loop."""
        if time.time() - self._last_refresh > self._refresh_interval:
            await self.refresh()
