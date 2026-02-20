"""
Order Flow Strategy — Microstructure-based trading from order book imbalances.

The ONLY strategy using order book microstructure data.  Order book imbalance
is a leading indicator — it shows where size is positioned BEFORE price moves.

LONG entry:
  1. book_score > 0.3 (strong bid-side imbalance)
  2. Spread compression (tight spread = about to move)
  3. Price making higher lows (bid absorption pattern)

SHORT entry:
  1. book_score < -0.3 (strong ask-side imbalance)
  2. Spread compression
  3. Price making lower highs

Graceful degradation: returns neutral if order book data is stale (>5s old).

SL: 2.0x ATR, TP: 3.0x ATR
"""

from __future__ import annotations

import time

import numpy as np

from src.strategies.base import BaseStrategy, SignalDirection, StrategySignal
from src.utils.indicators import atr, compute_sl_tp


class OrderFlowStrategy(BaseStrategy):

    def __init__(
        self,
        book_score_threshold: float = 0.3,
        spread_tight_pct: float = 0.0010,
        hl_lookback: int = 5,
        max_book_age_seconds: int = 5,
        atr_period: int = 14,
        weight: float = 0.15,
        enabled: bool = True,
    ):
        super().__init__(name="order_flow", weight=weight, enabled=enabled)
        self.book_score_threshold = book_score_threshold
        self.spread_tight_pct = spread_tight_pct
        self.hl_lookback = hl_lookback
        self.max_book_age_seconds = max_book_age_seconds
        self.atr_period = atr_period

    def min_bars_required(self) -> int:
        return max(self.hl_lookback + 5, 30)

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

        # Get order book analysis data from kwargs (passed through by engine)
        market_data = kwargs.get("market_data")
        if market_data is None:
            return self._neutral_signal(pair, "No market_data reference")

        book_analysis = market_data.get_order_book_analysis(pair)
        if not book_analysis:
            return self._neutral_signal(pair, "No order book analysis")

        # Check freshness
        try:
            updated_at = float(book_analysis.get("updated_at", 0))
            age = time.time() - updated_at
            if age > self.max_book_age_seconds:
                return self._neutral_signal(pair, f"Book data stale ({age:.0f}s)")
        except (TypeError, ValueError):
            return self._neutral_signal(pair, "Bad book timestamp")

        book_score = float(book_analysis.get("book_score", 0.0))
        spread_pct = float(book_analysis.get("spread_pct", 999.0))
        obi = float(book_analysis.get("obi", 0.0))
        whale_bias = float(book_analysis.get("whale_bias", 0.0))

        cache = kwargs.get("indicator_cache")
        if cache:
            atr_vals = cache.atr(self.atr_period)
        else:
            atr_vals = atr(highs, lows, closes, self.atr_period)

        fee_pct = kwargs.get("round_trip_fee_pct")
        price = closes[-1]
        curr_atr = atr_vals[-1]
        if curr_atr <= 0:
            return self._neutral_signal(pair, "ATR is zero")

        # Price action: higher lows (bullish) or lower highs (bearish)
        lb = self.hl_lookback
        recent_lows = lows[-lb:]
        recent_highs = highs[-lb:]
        higher_lows = all(recent_lows[i] >= recent_lows[i - 1] for i in range(1, len(recent_lows)))
        lower_highs = all(recent_highs[i] <= recent_highs[i - 1] for i in range(1, len(recent_highs)))

        # Spread compression
        spread_tight = spread_pct < self.spread_tight_pct

        direction = SignalDirection.NEUTRAL
        strength = 0.0
        confidence = 0.0

        # ---- LONG: strong bid imbalance + price absorption ----
        if book_score > self.book_score_threshold:
            direction = SignalDirection.LONG
            strength = 0.40
            confidence = 0.35

            # Book score strength (0.3 baseline, scales up)
            score_excess = book_score - self.book_score_threshold
            strength += min(score_excess * 0.5, 0.25)
            confidence += min(score_excess * 0.4, 0.20)

            # Spread compression — move is imminent
            if spread_tight:
                strength += 0.10
                confidence += 0.08

            # Higher lows — bids being absorbed
            if higher_lows:
                strength += 0.10
                confidence += 0.10

            # Whale bias confirmation
            if whale_bias > 0.1:
                confidence += 0.08

            # OBI agreement
            if obi > 0.15:
                confidence += 0.05

        # ---- SHORT: strong ask imbalance + distribution ----
        elif book_score < -self.book_score_threshold:
            direction = SignalDirection.SHORT
            strength = 0.40
            confidence = 0.35

            score_excess = abs(book_score) - self.book_score_threshold
            strength += min(score_excess * 0.5, 0.25)
            confidence += min(score_excess * 0.4, 0.20)

            if spread_tight:
                strength += 0.10
                confidence += 0.08

            if lower_highs:
                strength += 0.10
                confidence += 0.10

            if whale_bias < -0.1:
                confidence += 0.08

            if obi < -0.15:
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
                "book_score": round(float(book_score), 4),
                "obi": round(float(obi), 4),
                "whale_bias": round(float(whale_bias), 4),
                "spread_pct": round(float(spread_pct), 6),
                "spread_tight": bool(spread_tight),
                "higher_lows": bool(higher_lows),
                "lower_highs": bool(lower_highs),
                "book_age_s": round(float(age), 1),
                "atr": round(float(curr_atr), 6),
            },
        )
