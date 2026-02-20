"""
Ichimoku Cloud Strategy — Complete trading system in one indicator.

Ichimoku Kinko Hyo provides trend, momentum, and support/resistance all in
one framework.  We require MULTIPLE conditions to align before entering,
which filters out most 1-min noise.

LONG entry:
  1. Price above the cloud (Senkou Span A > Senkou Span B for bullish cloud)
  2. Tenkan-Sen crosses above Kijun-Sen (TK bullish cross)
  3. Chikou Span is above the close from 26 bars ago

SHORT entry:
  1. Price below the cloud
  2. Tenkan-Sen crosses below Kijun-Sen
  3. Chikou Span is below the close from 26 bars ago

SL: Opposite cloud edge (natural support/resistance)
TP: 3.0x ATR or Kijun-Sen, whichever is further
"""

from __future__ import annotations

import numpy as np

from src.strategies.base import BaseStrategy, SignalDirection, StrategySignal
from src.utils.indicators import atr, compute_sl_tp, ichimoku


class IchimokuStrategy(BaseStrategy):

    def __init__(
        self,
        tenkan_period: int = 9,
        kijun_period: int = 26,
        senkou_b_period: int = 52,
        atr_period: int = 14,
        weight: float = 0.15,
        enabled: bool = True,
    ):
        super().__init__(name="ichimoku", weight=weight, enabled=enabled)
        self.tenkan_period = tenkan_period
        self.kijun_period = kijun_period
        self.senkou_b_period = senkou_b_period
        self.atr_period = atr_period

    def min_bars_required(self) -> int:
        return self.senkou_b_period + self.kijun_period + 10

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
            tenkan_sen, kijun_sen, senkou_a, senkou_b, chikou = cache.ichimoku(
                self.tenkan_period, self.kijun_period, self.senkou_b_period,
            )
            atr_vals = cache.atr(self.atr_period)
        else:
            tenkan_sen, kijun_sen, senkou_a, senkou_b, chikou = ichimoku(
                highs, lows, closes,
                self.tenkan_period, self.kijun_period, self.senkou_b_period,
            )
            atr_vals = atr(highs, lows, closes, self.atr_period)

        fee_pct = kwargs.get("round_trip_fee_pct")

        # Current values
        price = closes[-1]
        curr_tenkan = tenkan_sen[-1]
        curr_kijun = kijun_sen[-1]
        prev_tenkan = tenkan_sen[-2]
        prev_kijun = kijun_sen[-2]
        curr_senkou_a = senkou_a[-1]
        curr_senkou_b = senkou_b[-1]
        curr_atr = atr_vals[-1]

        # Validate indicators converged
        for v in [curr_tenkan, curr_kijun, curr_senkou_a, curr_senkou_b]:
            if np.isnan(v):
                return self._neutral_signal(pair, "Indicators not converged")
        if curr_atr <= 0:
            return self._neutral_signal(pair, "ATR is zero")

        # Cloud boundaries
        cloud_top = max(curr_senkou_a, curr_senkou_b)
        cloud_bottom = min(curr_senkou_a, curr_senkou_b)

        # TK cross detection
        tk_bullish_cross = prev_tenkan <= prev_kijun and curr_tenkan > curr_kijun
        tk_bearish_cross = prev_tenkan >= prev_kijun and curr_tenkan < curr_kijun

        # Chikou span confirmation: chikou is close shifted back by kijun periods
        # At index i, chikou[i] = closes[i + kijun] — so chikou[-1] is only valid
        # if we look at chikou at position (n - 1 - kijun) which equals closes[-1]
        # compared against closes at that earlier position.
        chikou_idx = len(closes) - 1 - self.kijun_period
        chikou_bullish = False
        chikou_bearish = False
        if 0 <= chikou_idx < len(chikou) and not np.isnan(chikou[chikou_idx]):
            chikou_bullish = chikou[chikou_idx] > closes[chikou_idx]
            chikou_bearish = chikou[chikou_idx] < closes[chikou_idx]

        direction = SignalDirection.NEUTRAL
        strength = 0.0
        confidence = 0.0

        # ---- LONG ----
        if price > cloud_top and tk_bullish_cross:
            direction = SignalDirection.LONG
            strength = 0.50
            confidence = 0.45

            # Cloud thickness bonus (thicker = stronger S/R)
            cloud_width_pct = (cloud_top - cloud_bottom) / price if price > 0 else 0
            if cloud_width_pct > 0.005:
                strength += 0.1
                confidence += 0.05

            # Chikou confirmation
            if chikou_bullish:
                strength += 0.15
                confidence += 0.15

            # Price well above cloud
            dist_above = (price - cloud_top) / price if price > 0 else 0
            if dist_above < 0.01:
                confidence += 0.05  # Close to cloud = better entry

            # Tenkan > Kijun strength
            if curr_tenkan > curr_kijun:
                confidence += 0.05

        # ---- SHORT ----
        elif price < cloud_bottom and tk_bearish_cross:
            direction = SignalDirection.SHORT
            strength = 0.50
            confidence = 0.45

            cloud_width_pct = (cloud_top - cloud_bottom) / price if price > 0 else 0
            if cloud_width_pct > 0.005:
                strength += 0.1
                confidence += 0.05

            if chikou_bearish:
                strength += 0.15
                confidence += 0.15

            dist_below = (cloud_bottom - price) / price if price > 0 else 0
            if dist_below < 0.01:
                confidence += 0.05

            if curr_tenkan < curr_kijun:
                confidence += 0.05

        # ---- SL/TP ----
        stop_loss = 0.0
        take_profit = 0.0
        if direction == SignalDirection.LONG:
            # SL at opposite cloud edge (cloud_bottom = support)
            sl_at_cloud = price - cloud_bottom
            sl_dist = max(sl_at_cloud, curr_atr * 2.0)
            stop_loss = price - sl_dist
            # TP: 3.0x ATR or Kijun, whichever is further
            tp_base = price + curr_atr * 3.0
            _, tp_floor = compute_sl_tp(price, curr_atr, "long", 2.0, 3.0, round_trip_fee_pct=fee_pct)
            take_profit = max(tp_base, tp_floor)
            # Enforce SL floor
            sl_floor, _ = compute_sl_tp(price, curr_atr, "long", 2.0, 3.0, round_trip_fee_pct=fee_pct)
            stop_loss = min(stop_loss, sl_floor)
        elif direction == SignalDirection.SHORT:
            sl_at_cloud = cloud_top - price
            sl_dist = max(sl_at_cloud, curr_atr * 2.0)
            stop_loss = price + sl_dist
            tp_base = price - curr_atr * 3.0
            _, tp_floor = compute_sl_tp(price, curr_atr, "short", 2.0, 3.0, round_trip_fee_pct=fee_pct)
            take_profit = min(tp_base, tp_floor)
            sl_floor, _ = compute_sl_tp(price, curr_atr, "short", 2.0, 3.0, round_trip_fee_pct=fee_pct)
            stop_loss = max(stop_loss, sl_floor)

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
                "tenkan": round(float(curr_tenkan), 4),
                "kijun": round(float(curr_kijun), 4),
                "senkou_a": round(float(curr_senkou_a), 4),
                "senkou_b": round(float(curr_senkou_b), 4),
                "cloud_top": round(float(cloud_top), 4),
                "cloud_bottom": round(float(cloud_bottom), 4),
                "tk_bullish_cross": bool(tk_bullish_cross),
                "tk_bearish_cross": bool(tk_bearish_cross),
                "chikou_bullish": bool(chikou_bullish),
                "chikou_bearish": bool(chikou_bearish),
                "atr": round(float(curr_atr), 6),
            },
        )
