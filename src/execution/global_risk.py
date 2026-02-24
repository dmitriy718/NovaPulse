"""
Global Risk Aggregator — Cross-engine exposure tracking.

Singleton that aggregates exposure across all running engines (crypto Kraken,
crypto Coinbase, stocks Alpaca) to enforce a global maximum total exposure cap.

Thread-safe via asyncio Lock (all engines share a single event loop via
MultiEngineHub, or each engine has its own loop — the Lock is per-process).
"""

from __future__ import annotations

import asyncio
from typing import Dict, Optional

from src.core.logger import get_logger

logger = get_logger("global_risk")


class GlobalRiskAggregator:
    """Singleton cross-engine risk aggregator."""

    _instance: Optional[GlobalRiskAggregator] = None

    def __new__(cls) -> GlobalRiskAggregator:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, max_total_exposure_usd: float = 0.0):
        if self._initialized:
            return
        self._initialized = True
        self._exposures: Dict[str, float] = {}
        self._lock = asyncio.Lock()
        self.max_total_exposure_usd = max(0.0, float(max_total_exposure_usd))

    def configure(self, max_total_exposure_usd: float) -> None:
        """Update the global exposure cap (called during engine init)."""
        self.max_total_exposure_usd = max(0.0, float(max_total_exposure_usd))

    async def register_exposure(self, engine_id: str, exposure_usd: float) -> None:
        """Register or update the current exposure for an engine."""
        async with self._lock:
            self._exposures[engine_id] = max(0.0, float(exposure_usd))

    async def get_total_exposure(self) -> float:
        """Get the combined exposure across all engines."""
        async with self._lock:
            return sum(self._exposures.values())

    async def get_remaining_capacity(self) -> float:
        """Get remaining capacity in USD before hitting the global cap.

        Returns float('inf') if no cap is configured (max_total_exposure_usd == 0).
        """
        if self.max_total_exposure_usd <= 0:
            return float("inf")
        total = await self.get_total_exposure()
        return max(0.0, self.max_total_exposure_usd - total)

    async def unregister_engine(self, engine_id: str) -> None:
        """Remove an engine from tracking (on shutdown)."""
        async with self._lock:
            self._exposures.pop(engine_id, None)

    def get_snapshot(self) -> Dict[str, float]:
        """Non-async snapshot for reporting (may be slightly stale)."""
        return {
            "total_exposure_usd": sum(self._exposures.values()),
            "max_total_exposure_usd": self.max_total_exposure_usd,
            "engines": dict(self._exposures),
        }
