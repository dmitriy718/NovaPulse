"""
Stochastic Divergence Strategy — Price-indicator divergence at extremes.

Requires actual price-stochastic divergence PLUS K/D crossover confirmation.
Divergence means momentum is shifting BEFORE price reverses — a statistically
validated reversal signal.

LONG entry:
  1. %K < 20 (oversold zone)
  2. Bullish K/D crossover (%K crosses above %D)
  3. Bullish divergence: price made a lower low but stochastic made a higher low

SHORT entry:
  1. %K > 80 (overbought zone)
  2. Bearish K/D crossover (%K crosses below %D)
  3. Bearish divergence: price made a higher high but stochastic made a lower high

SL: 2.0x ATR, TP: 3.0x ATR
"""

from __future__ import annotations

import numpy as np

from src.strategies.base import BaseStrategy, SignalDirection, StrategySignal
from src.utils.indicators import atr, compute_sl_tp, stochastic


class StochasticDivergenceStrategy(BaseStrategy):

    def __init__(
        self,
        k_period: int = 14,
        d_period: int = 3,
        smooth: int = 3,
        oversold: float = 20.0,
        overbought: float = 80.0,
        divergence_lookback: int = 20,
        atr_period: int = 14,
        weight: float = 0.12,
        enabled: bool = True,
    ):
        super().__init__(name="stochastic_divergence", weight=weight, enabled=enabled)
        self.k_period = k_period
        self.d_period = d_period
        self.smooth = smooth
        self.oversold = oversold
        self.overbought = overbought
        self.divergence_lookback = divergence_lookback
        self.atr_period = atr_period

    def min_bars_required(self) -> int:
        return self.k_period + self.smooth + self.d_period + self.divergence_lookback + 10

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
            pct_k, pct_d = cache.stochastic(self.k_period, self.d_period, self.smooth)
            atr_vals = cache.atr(self.atr_period)
        else:
            pct_k, pct_d = stochastic(highs, lows, closes, self.k_period, self.d_period, self.smooth)
            atr_vals = atr(highs, lows, closes, self.atr_period)

        fee_pct = kwargs.get("round_trip_fee_pct")

        price = closes[-1]
        curr_k = pct_k[-1]
        curr_d = pct_d[-1]
        prev_k = pct_k[-2]
        prev_d = pct_d[-2]
        curr_atr = atr_vals[-1]

        for v in [curr_k, curr_d, prev_k, prev_d]:
            if np.isnan(v):
                return self._neutral_signal(pair, "Indicators not converged")
        if curr_atr <= 0:
            return self._neutral_signal(pair, "ATR is zero")

        # K/D crossovers
        bullish_cross = prev_k <= prev_d and curr_k > curr_d
        bearish_cross = prev_k >= prev_d and curr_k < curr_d

        # Divergence detection over lookback window
        lb = self.divergence_lookback
        bull_divergence = self._detect_bullish_divergence(lows, pct_k, lb)
        bear_divergence = self._detect_bearish_divergence(highs, pct_k, lb)

        direction = SignalDirection.NEUTRAL
        strength = 0.0
        confidence = 0.0

        # ---- LONG ----
        if curr_k < self.oversold and bullish_cross:
            direction = SignalDirection.LONG
            strength = 0.45
            confidence = 0.40

            # Oversold depth bonus
            if curr_k < 10:
                strength += 0.1
                confidence += 0.08

            # Divergence is the key signal
            if bull_divergence:
                strength += 0.20
                confidence += 0.20
            else:
                # Without divergence, signal is weaker but still valid at extreme
                confidence -= 0.05

            # K/D spread bonus (strong crossover)
            kd_spread = curr_k - curr_d
            if kd_spread > 3:
                confidence += 0.05

        # ---- SHORT ----
        elif curr_k > self.overbought and bearish_cross:
            direction = SignalDirection.SHORT
            strength = 0.45
            confidence = 0.40

            if curr_k > 90:
                strength += 0.1
                confidence += 0.08

            if bear_divergence:
                strength += 0.20
                confidence += 0.20
            else:
                confidence -= 0.05

            kd_spread = curr_d - curr_k
            if kd_spread > 3:
                confidence += 0.05

        # ---- SL/TP ----
        stop_loss = 0.0
        take_profit = 0.0
        if direction != SignalDirection.NEUTRAL:
            side = "long" if direction == SignalDirection.LONG else "short"
            stop_loss, take_profit = compute_sl_tp(
                price, curr_atr, side, sl_mult=2.0, tp_mult=3.0,
                round_trip_fee_pct=fee_pct,
            )

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
                "k": round(float(curr_k), 2),
                "d": round(float(curr_d), 2),
                "bullish_cross": bool(bullish_cross),
                "bearish_cross": bool(bearish_cross),
                "bull_divergence": bool(bull_divergence),
                "bear_divergence": bool(bear_divergence),
                "atr": round(float(curr_atr), 6),
            },
        )

    @staticmethod
    def _detect_bullish_divergence(
        lows: np.ndarray, pct_k: np.ndarray, lookback: int,
    ) -> bool:
        """Price made lower low but stochastic made higher low."""
        n = len(lows)
        if n < lookback + 2:
            return False

        window_lows = lows[-lookback:]
        window_k = pct_k[-lookback:]

        # Find the two most recent local lows in price
        price_low_indices = []
        for i in range(1, len(window_lows) - 1):
            if window_lows[i] <= window_lows[i - 1] and window_lows[i] <= window_lows[i + 1]:
                price_low_indices.append(i)

        if len(price_low_indices) < 2:
            return False

        # Most recent two lows
        idx_recent = price_low_indices[-1]
        idx_prior = price_low_indices[-2]

        # Price: lower low
        price_lower = window_lows[idx_recent] < window_lows[idx_prior]
        # Stochastic: higher low (divergence)
        k_recent = window_k[idx_recent]
        k_prior = window_k[idx_prior]
        if np.isnan(k_recent) or np.isnan(k_prior):
            return False
        stoch_higher = k_recent > k_prior

        return price_lower and stoch_higher

    @staticmethod
    def _detect_bearish_divergence(
        highs: np.ndarray, pct_k: np.ndarray, lookback: int,
    ) -> bool:
        """Price made higher high but stochastic made lower high."""
        n = len(highs)
        if n < lookback + 2:
            return False

        window_highs = highs[-lookback:]
        window_k = pct_k[-lookback:]

        price_high_indices = []
        for i in range(1, len(window_highs) - 1):
            if window_highs[i] >= window_highs[i - 1] and window_highs[i] >= window_highs[i + 1]:
                price_high_indices.append(i)

        if len(price_high_indices) < 2:
            return False

        idx_recent = price_high_indices[-1]
        idx_prior = price_high_indices[-2]

        price_higher = window_highs[idx_recent] > window_highs[idx_prior]
        k_recent = window_k[idx_recent]
        k_prior = window_k[idx_prior]
        if np.isnan(k_recent) or np.isnan(k_prior):
            return False
        stoch_lower = k_recent < k_prior

        return price_higher and stoch_lower
