"""
Anomaly Detection — Protective circuit breaker for unusual market conditions.

Detects spread spikes, volume anomalies, correlation breakdowns, and order book
depth drops. Pauses trading during anomalous periods with configurable cooldown.
"""

from __future__ import annotations

import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional, Tuple

from src.core.logger import get_logger

logger = get_logger("anomaly_detector")


class AnomalyDetector:
    """Detects market anomalies and triggers protective trading pauses."""

    def __init__(
        self,
        spread_threshold_mult: float = 3.0,
        volume_threshold_mult: float = 5.0,
        correlation_threshold: float = 0.60,
        depth_drop_threshold: float = 0.50,
        pause_seconds: int = 300,
        min_history_samples: int = 20,
    ):
        self._spread_threshold_mult = max(1.5, spread_threshold_mult)
        self._volume_threshold_mult = max(2.0, volume_threshold_mult)
        self._correlation_threshold = max(0.3, min(1.0, correlation_threshold))
        self._depth_drop_threshold = max(0.1, min(0.9, depth_drop_threshold))
        self._pause_seconds = max(30, pause_seconds)
        self._min_history = max(5, min_history_samples)

        # Rolling history per pair
        self._spread_history: Dict[str, Deque[float]] = {}
        self._volume_history: Dict[str, Deque[float]] = {}
        self._depth_history: Dict[str, Deque[float]] = {}

        # Cooldown state
        self._paused_until: float = 0.0
        self._last_anomaly_type: str = ""

        # Anomaly event log (capped for memory)
        self._anomaly_log: Deque[Dict] = deque(maxlen=200)

    def update_spread(self, pair: str, spread: float) -> None:
        """Record a spread observation."""
        if pair not in self._spread_history:
            self._spread_history[pair] = deque(maxlen=100)
        self._spread_history[pair].append(spread)

    def update_volume(self, pair: str, volume: float) -> None:
        """Record a volume observation."""
        if pair not in self._volume_history:
            self._volume_history[pair] = deque(maxlen=100)
        self._volume_history[pair].append(volume)

    def update_depth(self, pair: str, depth_usd: float) -> None:
        """Record an order book depth observation."""
        if pair not in self._depth_history:
            self._depth_history[pair] = deque(maxlen=100)
        self._depth_history[pair].append(depth_usd)

    def check_spread_anomaly(self, pair: str, current_spread: float) -> Optional[str]:
        """Detect if spread > threshold x rolling average."""
        history = self._spread_history.get(pair)
        if not history or len(history) < self._min_history:
            return None
        avg = sum(history) / len(history)
        if avg > 0 and current_spread > avg * self._spread_threshold_mult:
            return f"Spread anomaly on {pair}: {current_spread:.6f} > {self._spread_threshold_mult}x avg {avg:.6f}"
        return None

    def check_volume_anomaly(self, pair: str, volume: float, price_change_pct: float = 0.0) -> Optional[str]:
        """Detect volume spike without corresponding price move."""
        history = self._volume_history.get(pair)
        if not history or len(history) < self._min_history:
            return None
        avg = sum(history) / len(history)
        if avg > 0 and volume > avg * self._volume_threshold_mult:
            # Only flag if price didn't move proportionally
            if abs(price_change_pct) < 0.005:  # < 0.5% price move
                return f"Volume anomaly on {pair}: {volume:.0f} > {self._volume_threshold_mult}x avg {avg:.0f} without price move"
        return None

    def check_correlation_anomaly(self, pair_directions: Dict[str, str]) -> Optional[str]:
        """Detect if >threshold of pairs move in the same direction."""
        if len(pair_directions) < 3:
            return None
        directions = list(pair_directions.values())
        long_count = sum(1 for d in directions if d in ("long", "buy", "up"))
        short_count = sum(1 for d in directions if d in ("short", "sell", "down"))
        total = len(directions)
        if total > 0:
            max_ratio = max(long_count, short_count) / total
            if max_ratio > self._correlation_threshold:
                dominant = "long" if long_count > short_count else "short"
                return f"Correlation anomaly: {max_ratio:.0%} of {total} pairs moving {dominant}"
        return None

    def check_depth_anomaly(self, pair: str, current_depth: float) -> Optional[str]:
        """Detect sudden order book depth drop."""
        history = self._depth_history.get(pair)
        if not history or len(history) < self._min_history:
            return None
        # Compare to recent average (last 5 samples)
        recent = list(history)[-5:]
        avg_recent = sum(recent) / len(recent) if recent else 0
        if avg_recent > 0 and current_depth < avg_recent * (1 - self._depth_drop_threshold):
            return f"Depth anomaly on {pair}: {current_depth:.0f} USD dropped >{self._depth_drop_threshold:.0%} from recent avg {avg_recent:.0f}"
        return None

    def run_all_checks(
        self,
        market_data: Any,
        pairs: List[str],
    ) -> List[str]:
        """Run all anomaly checks. Returns list of anomaly descriptions."""
        anomalies: List[str] = []
        for pair in pairs:
            # Spread check
            try:
                spread = market_data.get_spread(pair) if market_data else 0.0
                if spread > 0:
                    self.update_spread(pair, spread)
                    result = self.check_spread_anomaly(pair, spread)
                    if result:
                        anomalies.append(result)
            except Exception:
                pass

            # Depth check
            try:
                book = market_data.get_order_book(pair) if market_data else {}
                if book:
                    bids = book.get("bids", [])
                    asks = book.get("asks", [])
                    bid_depth = sum(float(b[1]) * float(b[0]) for b in bids[:10] if len(b) >= 2) if bids else 0
                    ask_depth = sum(float(a[1]) * float(a[0]) for a in asks[:10] if len(a) >= 2) if asks else 0
                    total_depth = bid_depth + ask_depth
                    if total_depth > 0:
                        self.update_depth(pair, total_depth)
                        result = self.check_depth_anomaly(pair, total_depth)
                        if result:
                            anomalies.append(result)
            except Exception:
                pass

            # Volume check
            try:
                volume = getattr(market_data, "get_volume", lambda _: 0.0)(pair) if market_data else 0.0
                if volume > 0:
                    self.update_volume(pair, volume)
                    result = self.check_volume_anomaly(pair, volume)
                    if result:
                        anomalies.append(result)
            except Exception:
                pass

        if anomalies:
            now = time.time()
            if not self.is_paused():
                self._paused_until = now + self._pause_seconds
                self._last_anomaly_type = anomalies[0].split(":")[0] if anomalies else "unknown"
            for desc in anomalies:
                self._anomaly_log.append({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "description": desc,
                    "pairs_affected": pairs,
                })
            logger.warning("Anomalies detected", count=len(anomalies), pause_seconds=self._pause_seconds)

        return anomalies

    def is_paused(self) -> bool:
        """Check if currently in anomaly cooldown."""
        return time.time() < self._paused_until

    def get_anomaly_log(self, limit: int = 50) -> List[Dict]:
        """Get recent anomaly events."""
        return list(self._anomaly_log)[-limit:]

    def get_status(self) -> Dict[str, Any]:
        """Get current detector status."""
        return {
            "paused": self.is_paused(),
            "paused_until": datetime.fromtimestamp(self._paused_until, tz=timezone.utc).isoformat() if self.is_paused() else None,
            "last_anomaly_type": self._last_anomaly_type,
            "total_anomalies": len(self._anomaly_log),
            "spread_pairs_tracked": len(self._spread_history),
            "volume_pairs_tracked": len(self._volume_history),
            "depth_pairs_tracked": len(self._depth_history),
        }
