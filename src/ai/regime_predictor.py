"""
Regime Transition Predictor — Anticipates market regime shifts.

Analyzes multiple indicators (squeeze duration, ADX slope, volume trend,
choppiness trend) to predict whether the market is transitioning from
range to trend or vice versa.  Provides a transition state and a
confidence level that confluence uses to pre-adjust strategy weights.
"""

from __future__ import annotations

import math
from typing import Any, Optional, Tuple

import numpy as np

from src.core.logger import get_logger

logger = get_logger("regime_predictor")


class RegimeTransitionPredictor:
    """Predicts upcoming regime transitions from indicator state."""

    def __init__(
        self,
        squeeze_duration_threshold: int = 8,
        adx_slope_period: int = 5,
        adx_emerging_threshold: float = 20.0,
        volume_ratio_threshold: float = 1.3,
        emerging_trend_boost: float = 0.10,
    ):
        self._squeeze_threshold = max(1, int(squeeze_duration_threshold))
        self._adx_slope_period = max(2, int(adx_slope_period))
        self._adx_emerging = float(adx_emerging_threshold)
        self._volume_ratio_threshold = max(1.0, float(volume_ratio_threshold))
        self._emerging_trend_boost = max(0.0, min(0.30, float(emerging_trend_boost)))

        # State from the last prediction
        self._last_state: str = "stable_range"
        self._last_confidence: float = 0.0

    def predict_transition(
        self,
        indicator_cache: Any,
        closes: np.ndarray,
    ) -> Tuple[str, float]:
        """Predict the current regime transition state.

        Returns a tuple of (state, confidence) where state is one of:
        - "stable_range"   — market staying range-bound
        - "stable_trend"   — market staying in established trend
        - "emerging_trend" — range about to break into trend
        - "emerging_range" — trend about to collapse into range

        Parameters
        ----------
        indicator_cache : IndicatorCache
            The per-scan indicator cache.
        closes : np.ndarray
            Close prices for the current timeframe.
        """
        if closes is None or len(closes) < 30:
            state, conf = "stable_range", 0.0
            self._last_state = state
            self._last_confidence = conf
            return state, conf

        signals = []  # Each item: (state, weight)

        # 1. Squeeze duration analysis
        squeeze_signal = self._check_squeeze(indicator_cache)
        if squeeze_signal is not None:
            signals.append(squeeze_signal)

        # 2. ADX slope analysis
        adx_signal = self._check_adx_slope(indicator_cache)
        if adx_signal is not None:
            signals.append(adx_signal)

        # 3. Volume trend analysis
        vol_signal = self._check_volume_trend(indicator_cache)
        if vol_signal is not None:
            signals.append(vol_signal)

        # 4. Choppiness trend analysis
        chop_signal = self._check_choppiness_trend(indicator_cache)
        if chop_signal is not None:
            signals.append(chop_signal)

        if not signals:
            state, conf = "stable_range", 0.0
            self._last_state = state
            self._last_confidence = conf
            return state, conf

        # Tally votes
        state_votes: dict = {}
        for state, weight in signals:
            state_votes[state] = state_votes.get(state, 0.0) + weight

        # Winner is the state with most weighted votes
        best_state = max(state_votes, key=state_votes.get)
        total_weight = sum(state_votes.values())
        if total_weight > 0:
            agreement = state_votes[best_state] / total_weight
        else:
            agreement = 0.0

        state = best_state
        conf = min(1.0, agreement)
        self._last_state = state
        self._last_confidence = conf
        return state, conf

    def get_transition_confidence(self) -> float:
        """Return 0-1 confidence based on how many indicators agree."""
        return self._last_confidence

    def get_status(self) -> dict:
        """Return a status dict for the dashboard API."""
        return {
            "state": self._last_state,
            "confidence": round(self._last_confidence, 4),
            "emerging_trend_boost": self._emerging_trend_boost,
        }

    @property
    def emerging_trend_boost(self) -> float:
        """The configured confidence boost for emerging trends."""
        return self._emerging_trend_boost

    def _check_squeeze(self, ic: Any) -> Optional[Tuple[str, float]]:
        """Check if BB has been inside KC for multiple bars (squeeze).

        A prolonged squeeze suggests an imminent breakout (emerging trend).
        """
        try:
            bb = ic.bollinger_bands(20, 2.0)
            kc = ic.keltner_channels(20, 14, 1.5)
            if bb is None or kc is None:
                return None

            bb_upper, bb_mid, bb_lower = bb
            kc_upper, kc_mid, kc_lower = kc

            if len(bb_upper) < self._squeeze_threshold or len(kc_upper) < self._squeeze_threshold:
                return None

            # Count consecutive bars where BB is inside KC
            n = min(len(bb_upper), len(kc_upper))
            squeeze_count = 0
            for i in range(n - 1, max(n - 30, -1), -1):
                bu = float(bb_upper[i])
                bl = float(bb_lower[i])
                ku = float(kc_upper[i])
                kl = float(kc_lower[i])
                if not (math.isfinite(bu) and math.isfinite(ku)):
                    break
                if bu < ku and bl > kl:
                    squeeze_count += 1
                else:
                    break

            if squeeze_count >= self._squeeze_threshold:
                return ("emerging_trend", 1.0)
            return None
        except Exception:
            return None

    def _check_adx_slope(self, ic: Any) -> Optional[Tuple[str, float]]:
        """Check ADX slope to predict trend emergence or collapse."""
        try:
            adx_vals = ic.adx(14)
            if adx_vals is None or len(adx_vals) < self._adx_slope_period + 1:
                return None

            recent = adx_vals[-(self._adx_slope_period + 1):]
            valid = [float(v) for v in recent if math.isfinite(float(v))]
            if len(valid) < 2:
                return None

            # Linear slope of ADX
            slope = (valid[-1] - valid[0]) / len(valid)
            current_adx = valid[-1]

            if current_adx < self._adx_emerging and slope > 1.0:
                # ADX below threshold but rising fast -> emerging trend
                return ("emerging_trend", 0.8)
            elif current_adx > 30 and slope < -1.0:
                # ADX high but falling -> emerging range
                return ("emerging_range", 0.8)
            elif current_adx >= self._adx_emerging and slope >= 0:
                return ("stable_trend", 0.5)
            elif current_adx < self._adx_emerging and slope <= 0:
                return ("stable_range", 0.5)

            return None
        except Exception:
            return None

    def _check_volume_trend(self, ic: Any) -> Optional[Tuple[str, float]]:
        """Rising volume can precede breakouts (emerging trend)."""
        try:
            vr = ic.volume_ratio(20)
            if vr is None or len(vr) < 5:
                return None

            recent_vr = [float(v) for v in vr[-5:] if math.isfinite(float(v))]
            if not recent_vr:
                return None

            avg_vr = sum(recent_vr) / len(recent_vr)
            if avg_vr >= self._volume_ratio_threshold:
                return ("emerging_trend", 0.6)
            elif avg_vr < 0.7:
                return ("stable_range", 0.4)

            return None
        except Exception:
            return None

    def _check_choppiness_trend(self, ic: Any) -> Optional[Tuple[str, float]]:
        """Falling choppiness suggests transition from range to trend."""
        try:
            ci = ic.choppiness(14)
            if ci is None or len(ci) < 10:
                return None

            recent = [float(v) for v in ci[-10:] if math.isfinite(float(v))]
            if len(recent) < 5:
                return None

            # Check trend of CI: falling CI = emerging trend, rising CI = emerging range
            first_half = sum(recent[: len(recent) // 2]) / (len(recent) // 2)
            second_half = sum(recent[len(recent) // 2:]) / (len(recent) - len(recent) // 2)

            if first_half > 61.8 and second_half < first_half - 3:
                # CI was high and is falling -> emerging trend
                return ("emerging_trend", 0.7)
            elif first_half < 38.2 and second_half > first_half + 3:
                # CI was low and is rising -> emerging range
                return ("emerging_range", 0.7)
            elif second_half > 61.8:
                return ("stable_range", 0.4)
            elif second_half < 38.2:
                return ("stable_trend", 0.4)

            return None
        except Exception:
            return None
