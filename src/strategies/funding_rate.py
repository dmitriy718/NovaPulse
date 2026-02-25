"""
Funding Rate Strategy — Sentiment-based trading from perpetual futures funding rates.

Extreme funding rates indicate crowded positioning. When funding is extremely
positive (longs paying shorts), a mean-reversion SHORT may be forming. When
funding is extremely negative, a LONG setup may develop.

This strategy combines funding rate extremes with momentum confirmation (RSI
crossing key levels, momentum turning) and won't fight strong trends (ADX > 40
in opposing direction).

LONG entry:
  1. Funding rate extremely negative (< -funding_extreme_pct)
  2. RSI crossing above 50 (momentum shifting bullish)
  3. Momentum turning positive
  4. ADX not > 40 in bearish direction

SHORT entry:
  1. Funding rate extremely positive (> funding_extreme_pct)
  2. RSI crossing below 50 (momentum shifting bearish)
  3. Momentum turning negative
  4. ADX not > 40 in bullish direction

SL: 2.0x ATR, TP: 3.0x ATR
"""

from __future__ import annotations

from typing import Dict

import numpy as np

from src.strategies.base import BaseStrategy, SignalDirection, StrategySignal
from src.utils.indicators import compute_sl_tp


class FundingRateStrategy(BaseStrategy):

    def __init__(
        self,
        funding_extreme_pct: float = 0.01,
        weight: float = 0.10,
        enabled: bool = True,
    ):
        super().__init__(name="funding_rate", weight=weight, enabled=enabled)
        self.funding_extreme_pct = abs(funding_extreme_pct)

    def min_bars_required(self) -> int:
        return 50

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

        # Get funding rate from kwargs (injected by engine)
        funding_rates: Dict[str, float] = kwargs.get("funding_rates", {})
        funding_rate = funding_rates.get(pair)
        if funding_rate is None:
            return self._neutral_signal(pair, "No funding rate data")

        cache = kwargs.get("indicator_cache")
        if cache:
            rsi_vals = cache.rsi(14)
            atr_vals = cache.atr(14)
            adx_vals = cache.adx(14)
            mom_vals = cache.momentum(10)
        else:
            from src.utils.indicators import rsi, atr, adx, momentum
            rsi_vals = rsi(closes, 14)
            atr_vals = atr(highs, lows, closes, 14)
            adx_vals = adx(highs, lows, closes, 14)
            mom_vals = momentum(closes, 10)

        fee_pct = kwargs.get("round_trip_fee_pct")
        curr_price = float(closes[-1])
        curr_rsi = float(rsi_vals[-1]) if len(rsi_vals) else 50.0
        prev_rsi = float(rsi_vals[-2]) if len(rsi_vals) > 1 else curr_rsi
        curr_atr = float(atr_vals[-1]) if len(atr_vals) else 0.0
        curr_adx = float(adx_vals[-1]) if len(adx_vals) else 0.0
        curr_mom = float(mom_vals[-1]) if len(mom_vals) else 0.0
        prev_mom = float(mom_vals[-2]) if len(mom_vals) > 1 else curr_mom

        if curr_atr <= 0:
            return self._neutral_signal(pair, "ATR is zero")

        # Determine trend direction for ADX gating
        ema_fast = cache.ema(12) if cache else None
        ema_slow = cache.ema(26) if cache else None
        trend_bullish = False
        trend_bearish = False
        if ema_fast is not None and ema_slow is not None and len(ema_fast) > 0 and len(ema_slow) > 0:
            trend_bullish = float(ema_fast[-1]) > float(ema_slow[-1])
            trend_bearish = float(ema_fast[-1]) < float(ema_slow[-1])

        extreme = self.funding_extreme_pct  # Already a decimal (0.01 = 1%)

        direction = SignalDirection.NEUTRAL
        strength = 0.0
        confidence = 0.0

        # LONG: extreme negative funding + bullish momentum shift
        if funding_rate < -extreme:
            rsi_crossing_up = prev_rsi < 50 and curr_rsi >= 50
            mom_turning_up = curr_mom > prev_mom and curr_mom > 0

            # Don't fight strong bearish trends
            strong_bearish_trend = curr_adx > 40 and trend_bearish

            if (rsi_crossing_up or mom_turning_up) and not strong_bearish_trend:
                direction = SignalDirection.LONG
                strength = 0.40

                # Funding extremity bonus
                funding_excess = abs(funding_rate) - extreme
                strength += min(funding_excess * 50, 0.20)

                confidence = 0.40
                if rsi_crossing_up:
                    confidence += 0.10
                if mom_turning_up:
                    confidence += 0.10
                if curr_adx < 25:
                    confidence += 0.05  # Range regime favors mean reversion

        # SHORT: extreme positive funding + bearish momentum shift
        elif funding_rate > extreme:
            rsi_crossing_down = prev_rsi > 50 and curr_rsi <= 50
            mom_turning_down = curr_mom < prev_mom and curr_mom < 0

            # Don't fight strong bullish trends
            strong_bullish_trend = curr_adx > 40 and trend_bullish

            if (rsi_crossing_down or mom_turning_down) and not strong_bullish_trend:
                direction = SignalDirection.SHORT
                strength = 0.40

                funding_excess = abs(funding_rate) - extreme
                strength += min(funding_excess * 50, 0.20)

                confidence = 0.40
                if rsi_crossing_down:
                    confidence += 0.10
                if mom_turning_down:
                    confidence += 0.10
                if curr_adx < 25:
                    confidence += 0.05

        # SL/TP
        stop_loss = 0.0
        take_profit = 0.0
        if direction != SignalDirection.NEUTRAL:
            side = "long" if direction == SignalDirection.LONG else "short"
            stop_loss, take_profit = compute_sl_tp(
                curr_price, curr_atr, side, sl_mult=2.0, tp_mult=3.0,
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
                "funding_rate": round(float(funding_rate), 6),
                "funding_extreme_pct": self.funding_extreme_pct,
                "rsi": round(curr_rsi, 2),
                "adx": round(curr_adx, 2),
                "momentum": round(curr_mom, 6),
                "atr": round(curr_atr, 6),
            },
        )
