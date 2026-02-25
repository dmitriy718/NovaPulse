"""
Market Structure Strategy — Swing-based trend structure with pullback entries.

Identifies market structure (higher highs + higher lows = uptrend, lower highs
+ lower lows = downtrend) and enters on pullbacks to previous swing levels.

LONG entry:
  1. At least 2 swing highs + 2 swing lows forming HH+HL pattern
  2. Price pulls back within pullback_tolerance_pct of previous swing low
  3. RSI > rsi_floor (not oversold)
  4. Volume > average, momentum improving

SHORT entry:
  1. At least 2 swing highs + 2 swing lows forming LH+LL pattern
  2. Price pulls back within pullback_tolerance_pct of previous swing high
  3. RSI < rsi_ceiling (not overbought)
  4. Volume > average, momentum weakening

SL: 2.0x ATR, TP: 3.5x ATR
"""

from __future__ import annotations

import numpy as np

from src.strategies.base import BaseStrategy, SignalDirection, StrategySignal
from src.utils.indicators import compute_sl_tp


class MarketStructureStrategy(BaseStrategy):

    def __init__(
        self,
        swing_lookback: int = 5,
        pullback_tolerance_pct: float = 0.005,
        rsi_floor: int = 35,
        rsi_ceiling: int = 65,
        atr_period: int = 14,
        weight: float = 0.12,
        enabled: bool = True,
    ):
        super().__init__(name="market_structure", weight=weight, enabled=enabled)
        self.swing_lookback = max(2, swing_lookback)
        self.pullback_tolerance_pct = pullback_tolerance_pct
        self.rsi_floor = rsi_floor
        self.rsi_ceiling = rsi_ceiling
        self.atr_period = atr_period

    def min_bars_required(self) -> int:
        return max(self.swing_lookback * 6 + 10, 50)

    # ------------------------------------------------------------------
    # Swing detection
    # ------------------------------------------------------------------

    @staticmethod
    def _find_swings(
        highs: np.ndarray, lows: np.ndarray, lookback: int,
    ) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
        """Return lists of (index, price) for swing highs and swing lows."""
        swing_highs: list[tuple[int, float]] = []
        swing_lows: list[tuple[int, float]] = []
        n = len(highs)
        for i in range(lookback, n - lookback):
            if highs[i] == max(highs[i - lookback : i + lookback + 1]):
                swing_highs.append((i, float(highs[i])))
            if lows[i] == min(lows[i - lookback : i + lookback + 1]):
                swing_lows.append((i, float(lows[i])))
        return swing_highs, swing_lows

    # ------------------------------------------------------------------
    # Analyze
    # ------------------------------------------------------------------

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
            rsi_vals = cache.rsi(14)
            atr_vals = cache.atr(self.atr_period)
            vol_ratio = cache.volume_ratio(20)
            mom_vals = cache.momentum(5)
        else:
            from src.utils.indicators import atr, rsi, momentum, volume_ratio
            rsi_vals = rsi(closes, 14)
            atr_vals = atr(highs, lows, closes, self.atr_period)
            vol_ratio = volume_ratio(volumes, 20)
            mom_vals = momentum(closes, 5)

        fee_pct = kwargs.get("round_trip_fee_pct")
        curr_price = float(closes[-1])
        curr_rsi = float(rsi_vals[-1]) if len(rsi_vals) else 50.0
        curr_atr = float(atr_vals[-1]) if len(atr_vals) else 0.0
        curr_vol_ratio = float(vol_ratio[-1]) if len(vol_ratio) else 1.0
        curr_mom = float(mom_vals[-1]) if len(mom_vals) else 0.0
        prev_mom = float(mom_vals[-2]) if len(mom_vals) > 1 else curr_mom

        if curr_atr <= 0:
            return self._neutral_signal(pair, "ATR is zero")

        swing_highs, swing_lows = self._find_swings(highs, lows, self.swing_lookback)

        if len(swing_highs) < 2 or len(swing_lows) < 2:
            return self._neutral_signal(pair, "Not enough swings")

        # Check for HH+HL (uptrend) or LH+LL (downtrend) using last 2 swings
        sh = swing_highs[-2:]
        sl = swing_lows[-2:]

        higher_highs = sh[1][1] > sh[0][1]
        higher_lows = sl[1][1] > sl[0][1]
        lower_highs = sh[1][1] < sh[0][1]
        lower_lows = sl[1][1] < sl[0][1]

        uptrend = higher_highs and higher_lows
        downtrend = lower_highs and lower_lows

        direction = SignalDirection.NEUTRAL
        strength = 0.0
        confidence = 0.0

        tol = self.pullback_tolerance_pct

        # LONG: uptrend + price near previous swing low + RSI floor
        if uptrend:
            prev_swing_low = sl[-1][1]
            pullback_near = curr_price <= prev_swing_low * (1 + tol)
            if pullback_near and curr_rsi > self.rsi_floor:
                direction = SignalDirection.LONG
                strength = 0.40
                confidence = 0.40

                # Distance bonus: closer to swing low = stronger signal
                dist_pct = abs(curr_price - prev_swing_low) / prev_swing_low if abs(prev_swing_low) > 1e-12 else 0
                if dist_pct < tol * 0.5:
                    strength += 0.10
                    confidence += 0.08

                if curr_vol_ratio > 1.0:
                    strength += 0.10
                    confidence += 0.08

                if curr_mom > prev_mom:
                    strength += 0.10
                    confidence += 0.08

                # Trend strength bonus: wider HH-HL separation
                hh_spread = (sh[1][1] - sh[0][1]) / sh[0][1] if sh[0][1] > 0 else 0
                if hh_spread > 0.01:
                    confidence += 0.10

        # SHORT: downtrend + price near previous swing high + RSI ceiling
        elif downtrend:
            prev_swing_high = sh[-1][1]
            pullback_near = curr_price >= prev_swing_high * (1 - tol)
            if pullback_near and curr_rsi < self.rsi_ceiling:
                direction = SignalDirection.SHORT
                strength = 0.40
                confidence = 0.40

                dist_pct = abs(curr_price - prev_swing_high) / prev_swing_high if prev_swing_high > 0 else 0
                if dist_pct < tol * 0.5:
                    strength += 0.10
                    confidence += 0.08

                if curr_vol_ratio > 1.0:
                    strength += 0.10
                    confidence += 0.08

                if curr_mom < prev_mom:
                    strength += 0.10
                    confidence += 0.08

                lh_spread = (sh[0][1] - sh[1][1]) / sh[0][1] if sh[0][1] > 0 else 0
                if lh_spread > 0.01:
                    confidence += 0.10

        # SL/TP
        stop_loss = 0.0
        take_profit = 0.0
        if direction != SignalDirection.NEUTRAL:
            side = "long" if direction == SignalDirection.LONG else "short"
            stop_loss, take_profit = compute_sl_tp(
                curr_price, curr_atr, side, sl_mult=2.0, tp_mult=3.5,
                round_trip_fee_pct=fee_pct,
            )

        return StrategySignal(
            strategy_name=self.name,
            pair=pair,
            direction=direction,
            strength=min(strength, 1.0),
            confidence=min(confidence, 1.0),
            entry_price=curr_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            metadata={
                "uptrend": bool(uptrend),
                "downtrend": bool(downtrend),
                "swing_highs": len(swing_highs),
                "swing_lows": len(swing_lows),
                "rsi": round(curr_rsi, 2),
                "atr": round(curr_atr, 6),
                "volume_ratio": round(curr_vol_ratio, 2),
                "momentum": round(curr_mom, 6),
            },
        )
