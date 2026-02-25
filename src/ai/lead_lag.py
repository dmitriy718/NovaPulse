"""
Lead-Lag Tracker — Cross-pair signal intelligence.

Monitors leader pairs (BTC, ETH) for large moves, then adjusts confidence
on follower altcoins based on the leader's direction and the historical
correlation between the pairs.

Leader moves > atr_multiplier * ATR that align with the signal direction
get a confidence boost; opposing moves get a penalty.
"""

from __future__ import annotations

import math
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Tuple

import numpy as np

from src.core.logger import get_logger

logger = get_logger("lead_lag")


class LeadLagTracker:
    """Tracks leader pair prices and computes confidence adjustments for followers."""

    def __init__(
        self,
        leader_pairs: Optional[List[str]] = None,
        atr_multiplier: float = 1.0,
        lookback_minutes: int = 5,
        boost_confidence: float = 0.15,
        penalize_confidence: float = 0.10,
        min_correlation: float = 0.5,
    ):
        self._leader_pairs: List[str] = list(leader_pairs or ["BTC/USD", "ETH/USD"])
        self._leader_set: frozenset = frozenset(self._leader_pairs)
        self._atr_multiplier = max(0.1, float(atr_multiplier))
        self._lookback_seconds = max(60, int(lookback_minutes) * 60)
        self._boost = min(0.30, max(0.0, float(boost_confidence)))
        self._penalize = min(0.30, max(0.0, float(penalize_confidence)))
        self._min_correlation = max(0.0, min(1.0, float(min_correlation)))

        # Ring buffers: pair -> deque of (timestamp, price)
        self._price_history: Dict[str, Deque[Tuple[float, float]]] = {}
        for pair in self._leader_pairs:
            self._price_history[pair] = deque(maxlen=100)

    def update_leader_price(self, pair: str, price: float, timestamp: Optional[float] = None) -> None:
        """Record a price observation for a leader pair."""
        if pair not in self._leader_set:
            return
        if price <= 0 or not math.isfinite(price):
            return
        ts = timestamp if timestamp is not None else time.time()
        buf = self._price_history.get(pair)
        if buf is None:
            self._price_history[pair] = deque(maxlen=100)
            buf = self._price_history[pair]
        buf.append((ts, price))

    def get_confidence_adjustment(
        self,
        follower_pair: str,
        direction: str,
        market_data: Any,
    ) -> float:
        """Return a confidence adjustment for a follower pair based on leader moves.

        Parameters
        ----------
        follower_pair : str
            The pair being evaluated (e.g. "SOL/USD").
        direction : str
            Signal direction: "long" or "short".
        market_data : MarketDataCache
            Market data cache for accessing follower closes (used for correlation).

        Returns
        -------
        float
            Adjustment in range [-penalize, +boost].  0.0 if no leader signal.
        """
        # Leaders don't get boosted by themselves
        if follower_pair in self._leader_set:
            return 0.0

        now = time.time()
        best_adjustment = 0.0

        for leader in self._leader_pairs:
            buf = self._price_history.get(leader)
            if not buf or len(buf) < 2:
                continue

            # Get latest leader price and a price from lookback_seconds ago
            latest_ts, latest_price = buf[-1]

            # Skip stale data (older than 2x lookback)
            if (now - latest_ts) > self._lookback_seconds * 2:
                continue

            # Find the price closest to lookback_seconds ago
            cutoff = now - self._lookback_seconds
            old_price = None
            for ts, px in buf:
                if ts <= cutoff:
                    old_price = px
            if old_price is None:
                # No data old enough — use oldest available if at least 30s span
                oldest_ts, oldest_px = buf[0]
                if (latest_ts - oldest_ts) >= 30:
                    old_price = oldest_px
                else:
                    continue

            if old_price <= 0:
                continue

            # Compute leader move as percentage
            leader_move_pct = (latest_price - old_price) / old_price

            # Compute ATR threshold for the leader
            atr_threshold = self._compute_atr_threshold(leader, market_data)
            if atr_threshold <= 0:
                # Fallback: use 0.5% as minimum threshold
                atr_threshold = 0.005

            move_threshold = self._atr_multiplier * atr_threshold
            if abs(leader_move_pct) < move_threshold:
                continue  # Move too small

            # Compute correlation between leader and follower
            correlation = self._compute_correlation(leader, follower_pair, market_data)
            if correlation < self._min_correlation:
                continue

            # Determine if leader move aligns with signal direction
            leader_bullish = leader_move_pct > 0
            signal_long = direction.lower() in ("long", "buy")

            if leader_bullish == signal_long:
                # Aligned — boost
                adjustment = self._boost * min(correlation, 1.0)
            else:
                # Opposing — penalize
                adjustment = -self._penalize * min(correlation, 1.0)

            # Take the strongest signal (largest absolute value)
            if abs(adjustment) > abs(best_adjustment):
                best_adjustment = adjustment

        return best_adjustment

    def _compute_atr_threshold(self, pair: str, market_data: Any) -> float:
        """Compute ATR as percentage of price for the given pair."""
        try:
            closes = market_data.get_closes(pair)
            highs = market_data.get_highs(pair)
            lows = market_data.get_lows(pair)
            if closes is None or len(closes) < 15:
                return 0.005
            from src.utils.indicators import atr as compute_atr
            atr_vals = compute_atr(highs, lows, closes, period=14)
            if len(atr_vals) == 0:
                return 0.005
            atr_val = float(atr_vals[-1])
            price = float(closes[-1])
            if price <= 0 or not math.isfinite(atr_val):
                return 0.005
            return atr_val / price
        except Exception:
            return 0.005

    def _compute_correlation(self, leader: str, follower: str, market_data: Any) -> float:
        """Compute rolling Pearson correlation between leader and follower returns."""
        try:
            leader_closes = market_data.get_closes(leader)
            follower_closes = market_data.get_closes(follower)
            if leader_closes is None or follower_closes is None:
                return 0.0
            min_len = min(len(leader_closes), len(follower_closes))
            if min_len < 20:
                return 0.0
            # Use last 50 bars for correlation
            n = min(min_len, 50)
            lc = leader_closes[-n:]
            fc = follower_closes[-n:]

            # Compute returns
            lr = np.diff(lc) / lc[:-1]
            fr = np.diff(fc) / fc[:-1]

            # Filter out non-finite values
            valid = np.isfinite(lr) & np.isfinite(fr)
            lr = lr[valid]
            fr = fr[valid]

            if len(lr) < 10:
                return 0.0

            corr = float(np.corrcoef(lr, fr)[0, 1])
            if not math.isfinite(corr):
                return 0.0
            return max(0.0, corr)  # Only positive correlations make sense for lead-lag
        except Exception:
            return 0.0

    def get_status(self) -> Dict[str, Any]:
        """Return a status dict for the dashboard API."""
        leaders: Dict[str, Any] = {}
        now = time.time()
        for pair in self._leader_pairs:
            buf = self._price_history.get(pair)
            if buf and len(buf) >= 1:
                latest_ts, latest_px = buf[-1]
                leaders[pair] = {
                    "latest_price": round(latest_px, 4),
                    "observations": len(buf),
                    "stale": (now - latest_ts) > self._lookback_seconds * 2,
                }
            else:
                leaders[pair] = {"latest_price": None, "observations": 0, "stale": True}
        return {
            "leader_pairs": self._leader_pairs,
            "boost": self._boost,
            "penalize": self._penalize,
            "min_correlation": self._min_correlation,
            "leaders": leaders,
        }
