"""
Volatility Squeeze Strategy — TTM Squeeze concept.

Trades the physics of volatility compression -> expansion.  A "squeeze" occurs
when Bollinger Bands contract inside Keltner Channels, indicating low volatility.
When the squeeze releases (BB expand past KC), a directional move is imminent.

Squeeze detection:
  BB upper < KC upper AND BB lower > KC lower

LONG entry:  Squeeze just released + momentum > 0 and rising
SHORT entry: Squeeze just released + momentum < 0 and falling

SL: 2.5x ATR, TP: 4.0x ATR (wider R:R for momentum after squeeze)
"""

from __future__ import annotations

import numpy as np

from src.strategies.base import BaseStrategy, SignalDirection, StrategySignal
from src.utils.indicators import (
    atr,
    bollinger_bands,
    compute_sl_tp,
    keltner_channels,
    momentum,
)


class VolatilitySqueezeStrategy(BaseStrategy):

    def __init__(
        self,
        bb_period: int = 20,
        bb_std: float = 2.0,
        kc_ema_period: int = 20,
        kc_atr_period: int = 14,
        kc_multiplier: float = 1.5,
        momentum_period: int = 12,
        atr_period: int = 14,
        min_squeeze_bars: int = 3,
        weight: float = 0.12,
        enabled: bool = True,
    ):
        super().__init__(name="volatility_squeeze", weight=weight, enabled=enabled)
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.kc_ema_period = kc_ema_period
        self.kc_atr_period = kc_atr_period
        self.kc_multiplier = kc_multiplier
        self.momentum_period = momentum_period
        self.atr_period = atr_period
        self.min_squeeze_bars = min_squeeze_bars

    def min_bars_required(self) -> int:
        return max(self.bb_period, self.kc_ema_period) + self.momentum_period + 20

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
            bb_upper, bb_mid, bb_lower = cache.bollinger_bands(self.bb_period, self.bb_std)
            kc_upper, kc_mid, kc_lower = cache.keltner_channels(
                self.kc_ema_period, self.kc_atr_period, self.kc_multiplier,
            )
            mom_vals = cache.momentum(self.momentum_period)
            atr_vals = cache.atr(self.atr_period)
        else:
            bb_upper, bb_mid, bb_lower = bollinger_bands(closes, self.bb_period, self.bb_std)
            kc_upper, kc_mid, kc_lower = keltner_channels(
                highs, lows, closes, self.kc_ema_period, self.kc_atr_period, self.kc_multiplier,
            )
            mom_vals = momentum(closes, self.momentum_period)
            atr_vals = atr(highs, lows, closes, self.atr_period)

        fee_pct = kwargs.get("round_trip_fee_pct")

        price = closes[-1]
        curr_atr = atr_vals[-1]

        # Validate convergence
        for v in [bb_upper[-1], kc_upper[-1], mom_vals[-1]]:
            if np.isnan(v):
                return self._neutral_signal(pair, "Indicators not converged")
        if curr_atr <= 0:
            return self._neutral_signal(pair, "ATR is zero")

        # Detect squeeze: BB inside KC
        squeeze = (bb_upper < kc_upper) & (bb_lower > kc_lower)

        # Count consecutive squeeze bars ending before current bar
        # Current bar should NOT be in squeeze (= squeeze just released)
        curr_in_squeeze = bool(squeeze[-1])
        prev_squeeze_count = 0
        for i in range(len(squeeze) - 2, -1, -1):
            if squeeze[i]:
                prev_squeeze_count += 1
            else:
                break

        squeeze_just_released = not curr_in_squeeze and prev_squeeze_count >= self.min_squeeze_bars

        if not squeeze_just_released:
            return self._neutral_signal(pair, "No squeeze release")

        # Momentum direction and acceleration
        curr_mom = mom_vals[-1]
        prev_mom = mom_vals[-2] if len(mom_vals) > 1 else 0
        prev_mom2 = mom_vals[-3] if len(mom_vals) > 2 else 0
        mom_rising = curr_mom > prev_mom
        mom_falling = curr_mom < prev_mom
        mom_accelerating = (curr_mom - prev_mom) > (prev_mom - prev_mom2)

        direction = SignalDirection.NEUTRAL
        strength = 0.0
        confidence = 0.0

        # ---- LONG: squeeze released + positive rising momentum ----
        if curr_mom > 0 and mom_rising:
            long_price_break = price > max(bb_upper[-1], kc_upper[-1])
            long_momentum_persist = prev_mom > 0
            if not (long_price_break or long_momentum_persist):
                return self._neutral_signal(pair, "Weak long squeeze release")

            direction = SignalDirection.LONG
            strength = 0.50
            confidence = 0.45

            # Longer squeeze = bigger move expected
            if prev_squeeze_count >= 8:
                strength += 0.15
                confidence += 0.10
            elif prev_squeeze_count >= 5:
                strength += 0.08
                confidence += 0.05

            # Momentum acceleration
            if mom_accelerating:
                strength += 0.10
                confidence += 0.08

            # Price above BB middle (confirming upward bias)
            if price > bb_mid[-1]:
                confidence += 0.05

        # ---- SHORT: squeeze released + negative falling momentum ----
        elif curr_mom < 0 and mom_falling:
            short_price_break = price < min(bb_lower[-1], kc_lower[-1])
            short_momentum_persist = prev_mom < 0
            if not (short_price_break or short_momentum_persist):
                return self._neutral_signal(pair, "Weak short squeeze release")

            direction = SignalDirection.SHORT
            strength = 0.50
            confidence = 0.45

            if prev_squeeze_count >= 8:
                strength += 0.15
                confidence += 0.10
            elif prev_squeeze_count >= 5:
                strength += 0.08
                confidence += 0.05

            if not mom_accelerating:  # Momentum accelerating to downside
                strength += 0.10
                confidence += 0.08

            if price < bb_mid[-1]:
                confidence += 0.05

        # ---- SL/TP ----
        stop_loss = 0.0
        take_profit = 0.0
        if direction != SignalDirection.NEUTRAL:
            side = "long" if direction == SignalDirection.LONG else "short"
            stop_loss, take_profit = compute_sl_tp(
                price, curr_atr, side, sl_mult=2.5, tp_mult=4.0,
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
                "squeeze_bars": prev_squeeze_count,
                "squeeze_released": bool(squeeze_just_released),
                "momentum": round(float(curr_mom), 6),
                "momentum_rising": bool(mom_rising),
                "momentum_falling": bool(mom_falling),
                "bb_upper": round(float(bb_upper[-1]), 4),
                "bb_lower": round(float(bb_lower[-1]), 4),
                "kc_upper": round(float(kc_upper[-1]), 4),
                "kc_lower": round(float(kc_lower[-1]), 4),
                "atr": round(float(curr_atr), 6),
            },
        )
