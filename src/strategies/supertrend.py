"""
Supertrend Strategy — ATR-based adaptive trend following with volume confirmation.

Supertrend has a built-in adaptive stop that moves with volatility (unlike fixed
EMA crossovers).  Only trades FLIPS (direction changes), making it highly selective.
The Supertrend level itself serves as a natural stop-loss.

LONG entry:  Supertrend flips bearish -> bullish + volume > 1.2x average
SHORT entry: Supertrend flips bullish -> bearish + volume > 1.2x average

SL: At Supertrend level (natural stop), TP: 3.5x ATR
"""

from __future__ import annotations

import numpy as np

from src.strategies.base import BaseStrategy, SignalDirection, StrategySignal
from src.utils.indicators import atr, compute_sl_tp, supertrend, volume_ratio


class SupertrendStrategy(BaseStrategy):

    def __init__(
        self,
        st_period: int = 10,
        st_multiplier: float = 3.0,
        volume_period: int = 20,
        volume_threshold: float = 1.2,
        atr_period: int = 14,
        weight: float = 0.10,
        enabled: bool = True,
    ):
        super().__init__(name="supertrend", weight=weight, enabled=enabled)
        self.st_period = st_period
        self.st_multiplier = st_multiplier
        self.volume_period = volume_period
        self.volume_threshold = volume_threshold
        self.atr_period = atr_period

    def min_bars_required(self) -> int:
        return max(self.st_period, self.volume_period) + 20

    async def analyze(
        self,
        pair: str,
        closes: np.ndarray,
        highs: np.ndarray,
        lows: np.ndarray,
        volumes: np.ndarray,
        **kwargs,
    ) -> StrategySignal:
        if len(closes) < self.min_bars_required():
            return self._neutral_signal(pair, "Insufficient data")

        cache = kwargs.get("indicator_cache")
        if cache:
            st_line, st_dir = cache.supertrend(self.st_period, self.st_multiplier)
            vol_ratio = cache.volume_ratio(self.volume_period)
            atr_vals = cache.atr(self.atr_period)
        else:
            st_line, st_dir = supertrend(highs, lows, closes, self.st_period, self.st_multiplier)
            vol_ratio = volume_ratio(volumes, self.volume_period)
            atr_vals = atr(highs, lows, closes, self.atr_period)

        fee_pct = kwargs.get("round_trip_fee_pct")

        price = closes[-1]
        curr_st = st_line[-1]
        curr_dir = st_dir[-1]
        prev_dir = st_dir[-2] if len(st_dir) > 1 else 0
        curr_vol_ratio = vol_ratio[-1]
        curr_atr = atr_vals[-1]

        if np.isnan(curr_st) or curr_dir == 0 or prev_dir == 0:
            return self._neutral_signal(pair, "Indicators not converged")
        if curr_atr <= 0:
            return self._neutral_signal(pair, "ATR is zero")

        # Flip detection
        bullish_flip = prev_dir < 0 and curr_dir > 0
        bearish_flip = prev_dir > 0 and curr_dir < 0
        volume_confirmed = curr_vol_ratio >= self.volume_threshold

        direction = SignalDirection.NEUTRAL
        strength = 0.0
        confidence = 0.0

        # ---- LONG: bearish -> bullish flip ----
        if bullish_flip:
            direction = SignalDirection.LONG
            strength = 0.50
            confidence = 0.40

            if volume_confirmed:
                strength += 0.15
                confidence += 0.15
            else:
                # Weak signal without volume
                confidence -= 0.05

            # Supertrend distance from price (closer = tighter stop = better R:R)
            st_dist_pct = abs(price - curr_st) / price if price > 0 else 0
            if st_dist_pct < 0.02:
                confidence += 0.08  # Tight natural stop

            # Strong volume surge
            if curr_vol_ratio > 2.0:
                strength += 0.10
                confidence += 0.05

        # ---- SHORT: bullish -> bearish flip ----
        elif bearish_flip:
            direction = SignalDirection.SHORT
            strength = 0.50
            confidence = 0.40

            if volume_confirmed:
                strength += 0.15
                confidence += 0.15
            else:
                confidence -= 0.05

            st_dist_pct = abs(price - curr_st) / price if price > 0 else 0
            if st_dist_pct < 0.02:
                confidence += 0.08

            if curr_vol_ratio > 2.0:
                strength += 0.10
                confidence += 0.05

        # ---- SL/TP ----
        stop_loss = 0.0
        take_profit = 0.0
        if direction != SignalDirection.NEUTRAL:
            # SL at supertrend level (natural stop)
            st_sl = curr_st
            # Ensure minimum SL distance using compute_sl_tp floor
            side = "long" if direction == SignalDirection.LONG else "short"
            floor_sl, take_profit = compute_sl_tp(
                price, curr_atr, side, sl_mult=2.0, tp_mult=3.5,
                round_trip_fee_pct=fee_pct,
            )
            if direction == SignalDirection.LONG:
                # SL = min of supertrend and floor (wider stop survives better)
                stop_loss = min(st_sl, floor_sl)
            else:
                stop_loss = max(st_sl, floor_sl)

        return StrategySignal(
            strategy_name=self.name,
            pair=pair,
            direction=direction,
            strength=min(strength, 1.0),
            confidence=min(confidence, 1.0),
            entry_price=price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            metadata={
                "supertrend": round(float(curr_st), 4),
                "direction_val": float(curr_dir),
                "prev_direction": float(prev_dir),
                "bullish_flip": bool(bullish_flip),
                "bearish_flip": bool(bearish_flip),
                "volume_ratio": round(float(curr_vol_ratio), 4),
                "volume_confirmed": bool(volume_confirmed),
                "atr": round(float(curr_atr), 6),
            },
        )
