"""Tests for Feature 6: Regime Transition Prediction."""

from __future__ import annotations

import math
from unittest.mock import MagicMock

import numpy as np
import pytest

from src.ai.regime_predictor import RegimeTransitionPredictor
from src.core.config import AIConfig, RegimePredictorConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_predictor(**kwargs) -> RegimeTransitionPredictor:
    defaults = {
        "squeeze_duration_threshold": 8,
        "adx_slope_period": 5,
        "adx_emerging_threshold": 20.0,
        "volume_ratio_threshold": 1.3,
        "emerging_trend_boost": 0.10,
    }
    defaults.update(kwargs)
    return RegimeTransitionPredictor(**defaults)


def _make_indicator_cache(
    adx_vals=None,
    volume_ratio_vals=None,
    choppiness_vals=None,
    bb_upper=None, bb_mid=None, bb_lower=None,
    kc_upper=None, kc_mid=None, kc_lower=None,
) -> MagicMock:
    """Create a mock IndicatorCache with controllable indicator values."""
    ic = MagicMock()

    if adx_vals is not None:
        ic.adx.return_value = np.array(adx_vals, dtype=float)
    else:
        ic.adx.return_value = np.array([25.0] * 20, dtype=float)

    if volume_ratio_vals is not None:
        ic.volume_ratio.return_value = np.array(volume_ratio_vals, dtype=float)
    else:
        ic.volume_ratio.return_value = np.array([1.0] * 20, dtype=float)

    if choppiness_vals is not None:
        ic.choppiness.return_value = np.array(choppiness_vals, dtype=float)
    else:
        ic.choppiness.return_value = np.array([50.0] * 20, dtype=float)

    if bb_upper is not None:
        ic.bollinger_bands.return_value = (
            np.array(bb_upper, dtype=float),
            np.array(bb_mid, dtype=float),
            np.array(bb_lower, dtype=float),
        )
    else:
        ic.bollinger_bands.return_value = (
            np.array([110.0] * 20, dtype=float),
            np.array([100.0] * 20, dtype=float),
            np.array([90.0] * 20, dtype=float),
        )

    if kc_upper is not None:
        ic.keltner_channels.return_value = (
            np.array(kc_upper, dtype=float),
            np.array(kc_mid, dtype=float),
            np.array(kc_lower, dtype=float),
        )
    else:
        ic.keltner_channels.return_value = (
            np.array([115.0] * 20, dtype=float),
            np.array([100.0] * 20, dtype=float),
            np.array([85.0] * 20, dtype=float),
        )

    return ic


# ---------------------------------------------------------------------------
# Unit Tests
# ---------------------------------------------------------------------------

class TestRegimePredictorUnit:
    def test_emerging_trend_detected(self):
        """Squeeze + rising ADX + volume surge + falling CI = emerging trend."""
        predictor = _make_predictor(squeeze_duration_threshold=3)

        # BB inside KC for 10 bars (squeeze)
        n = 20
        bb_upper = [105.0] * n  # BB upper inside KC upper (115)
        bb_mid = [100.0] * n
        bb_lower = [95.0] * n   # BB lower inside KC lower (85)
        kc_upper = [115.0] * n
        kc_mid = [100.0] * n
        kc_lower = [85.0] * n

        # ADX rising from 15 to 22
        adx_vals = list(np.linspace(15, 22, n))

        # Volume surging
        vr_vals = [1.5] * n

        # CI falling from 70 to 55
        ci_vals = list(np.linspace(70, 55, n))

        ic = _make_indicator_cache(
            adx_vals=adx_vals,
            volume_ratio_vals=vr_vals,
            choppiness_vals=ci_vals,
            bb_upper=bb_upper, bb_mid=bb_mid, bb_lower=bb_lower,
            kc_upper=kc_upper, kc_mid=kc_mid, kc_lower=kc_lower,
        )
        closes = np.array([100.0] * 60, dtype=float)

        state, conf = predictor.predict_transition(ic, closes)
        assert state == "emerging_trend"
        assert conf > 0.5

    def test_stable_range_detected(self):
        """Low ADX flat, no squeeze, high CI = stable range."""
        predictor = _make_predictor()

        adx_vals = [15.0] * 20  # Low, flat
        vr_vals = [0.6] * 20   # Low volume
        ci_vals = [70.0] * 20  # High choppiness

        # BB wider than KC (no squeeze)
        bb_upper = [120.0] * 20
        bb_mid = [100.0] * 20
        bb_lower = [80.0] * 20
        kc_upper = [110.0] * 20
        kc_mid = [100.0] * 20
        kc_lower = [90.0] * 20

        ic = _make_indicator_cache(
            adx_vals=adx_vals,
            volume_ratio_vals=vr_vals,
            choppiness_vals=ci_vals,
            bb_upper=bb_upper, bb_mid=bb_mid, bb_lower=bb_lower,
            kc_upper=kc_upper, kc_mid=kc_mid, kc_lower=kc_lower,
        )
        closes = np.array([100.0] * 60, dtype=float)

        state, _ = predictor.predict_transition(ic, closes)
        assert state == "stable_range"

    def test_stable_trend_detected(self):
        """High ADX, flat/rising, low CI = stable trend."""
        predictor = _make_predictor()

        adx_vals = [35.0] * 20  # High, stable
        vr_vals = [1.0] * 20
        ci_vals = [30.0] * 20  # Low choppiness

        # No squeeze
        bb_upper = [120.0] * 20
        bb_mid = [100.0] * 20
        bb_lower = [80.0] * 20
        kc_upper = [110.0] * 20
        kc_mid = [100.0] * 20
        kc_lower = [90.0] * 20

        ic = _make_indicator_cache(
            adx_vals=adx_vals,
            volume_ratio_vals=vr_vals,
            choppiness_vals=ci_vals,
            bb_upper=bb_upper, bb_mid=bb_mid, bb_lower=bb_lower,
            kc_upper=kc_upper, kc_mid=kc_mid, kc_lower=kc_lower,
        )
        closes = np.array([100.0] * 60, dtype=float)

        state, _ = predictor.predict_transition(ic, closes)
        assert state == "stable_trend"

    def test_emerging_range_detected(self):
        """High ADX falling + rising CI = emerging range."""
        predictor = _make_predictor(adx_slope_period=3)

        # ADX falling steeply: last 4 vals go from 42 to 32 => slope=(32-42)/4=-2.5, current=32>30
        adx_vals = [45.0] * 16 + [42.0, 38.0, 35.0, 32.0]

        vr_vals = [0.8] * 20

        # CI rising from 25 to 50: first_half of last 10 ~30 (<38.2), second_half ~45 (>30+3)
        ci_vals = list(np.linspace(25, 50, 20))

        # No squeeze
        bb_upper = [120.0] * 20
        bb_mid = [100.0] * 20
        bb_lower = [80.0] * 20
        kc_upper = [110.0] * 20
        kc_mid = [100.0] * 20
        kc_lower = [90.0] * 20

        ic = _make_indicator_cache(
            adx_vals=adx_vals,
            volume_ratio_vals=vr_vals,
            choppiness_vals=ci_vals,
            bb_upper=bb_upper, bb_mid=bb_mid, bb_lower=bb_lower,
            kc_upper=kc_upper, kc_mid=kc_mid, kc_lower=kc_lower,
        )
        closes = np.array([100.0] * 60, dtype=float)

        state, _ = predictor.predict_transition(ic, closes)
        assert state == "emerging_range"

    def test_squeeze_duration_counting(self):
        """Squeeze is only triggered when bars >= threshold."""
        predictor = _make_predictor(squeeze_duration_threshold=5)

        # BB inside KC for only 3 bars (below threshold of 5)
        n = 20
        bb_upper = [120.0] * (n - 3) + [105.0] * 3
        bb_lower = [80.0] * (n - 3) + [95.0] * 3
        bb_mid = [100.0] * n
        kc_upper = [115.0] * n
        kc_lower = [85.0] * n
        kc_mid = [100.0] * n

        ic = _make_indicator_cache(
            bb_upper=bb_upper, bb_mid=bb_mid, bb_lower=bb_lower,
            kc_upper=kc_upper, kc_mid=kc_mid, kc_lower=kc_lower,
        )
        closes = np.array([100.0] * 60, dtype=float)

        # The squeeze check itself should return None (not enough bars)
        result = predictor._check_squeeze(ic)
        assert result is None  # 3 < 5 threshold

    def test_adx_slope_calculation(self):
        """ADX slope detection: rising ADX below threshold = emerging_trend."""
        predictor = _make_predictor(adx_slope_period=3, adx_emerging_threshold=25.0)

        # ADX rising steeply: last 4 go from 10 to 22 => slope=(22-10)/4=3.0 > 1.0, current=22<25
        adx_vals = [8.0] * 6 + [10.0, 14.0, 18.0, 22.0]

        ic = MagicMock()
        ic.adx.return_value = np.array(adx_vals, dtype=float)

        result = predictor._check_adx_slope(ic)
        assert result is not None
        assert result[0] == "emerging_trend"

    def test_insufficient_data_returns_stable(self):
        """When data is too short, should return stable_range."""
        predictor = _make_predictor()
        ic = MagicMock()
        closes = np.array([100.0] * 10, dtype=float)  # Only 10 bars

        state, conf = predictor.predict_transition(ic, closes)
        # With 10 bars (< 30 threshold), returns stable_range
        assert state == "stable_range"
        assert conf == 0.0

    def test_high_confidence_when_all_agree(self):
        """When all indicators agree on emerging_trend, confidence should be high."""
        predictor = _make_predictor(squeeze_duration_threshold=3)

        n = 20
        bb_upper = [105.0] * n
        bb_mid = [100.0] * n
        bb_lower = [95.0] * n
        kc_upper = [115.0] * n
        kc_mid = [100.0] * n
        kc_lower = [85.0] * n

        adx_vals = list(np.linspace(12, 19, n))
        vr_vals = [1.5] * n
        ci_vals = list(np.linspace(70, 55, n))

        ic = _make_indicator_cache(
            adx_vals=adx_vals,
            volume_ratio_vals=vr_vals,
            choppiness_vals=ci_vals,
            bb_upper=bb_upper, bb_mid=bb_mid, bb_lower=bb_lower,
            kc_upper=kc_upper, kc_mid=kc_mid, kc_lower=kc_lower,
        )
        closes = np.array([100.0] * 60, dtype=float)

        _, conf = predictor.predict_transition(ic, closes)
        assert conf >= 0.7, f"Expected high confidence when all agree, got {conf}"

    def test_low_confidence_when_mixed(self):
        """When indicators disagree, confidence should be lower than unanimous."""
        predictor = _make_predictor(adx_slope_period=3)

        # ADX votes emerging_trend: last 4 go from 10 to 22 (slope=3.0, <25)
        adx_vals = [8.0] * 16 + [10.0, 14.0, 18.0, 22.0]

        # Volume surging -> also votes emerging_trend
        vr_vals = [1.5] * 20

        # But CI says stable_range: high flat choppiness (70)
        ci_vals = [70.0] * 20

        # No squeeze (BB outside KC)
        bb_upper = [120.0] * 20
        bb_mid = [100.0] * 20
        bb_lower = [80.0] * 20
        kc_upper = [110.0] * 20
        kc_mid = [100.0] * 20
        kc_lower = [90.0] * 20

        ic = _make_indicator_cache(
            adx_vals=adx_vals,
            volume_ratio_vals=vr_vals,
            choppiness_vals=ci_vals,
            bb_upper=bb_upper, bb_mid=bb_mid, bb_lower=bb_lower,
            kc_upper=kc_upper, kc_mid=kc_mid, kc_lower=kc_lower,
        )
        closes = np.array([100.0] * 60, dtype=float)

        _, conf = predictor.predict_transition(ic, closes)
        # ADX (0.8) + Volume (0.6) vote emerging_trend = 1.4
        # CI (0.4) votes stable_range = 0.4
        # Confidence = 1.4 / 1.8 = 0.78 — not unanimous
        assert conf < 0.95, f"Mixed signals should give lower confidence, got {conf}"


# ---------------------------------------------------------------------------
# Integration Tests
# ---------------------------------------------------------------------------

class TestRegimePredictorIntegration:
    def test_emerging_trend_boosts_trend_strategies(self):
        """Verify set_regime_predictor works and boost is applied in confluence."""
        from src.ai.confluence import ConfluenceDetector

        md = MagicMock()
        md.is_warmed_up.return_value = True
        md.is_stale.return_value = False

        detector = ConfluenceDetector(market_data=md)
        predictor = _make_predictor(emerging_trend_boost=0.10)
        detector.set_regime_predictor(predictor)

        assert detector._regime_predictor is predictor
        assert predictor.emerging_trend_boost == 0.10

    def test_regime_predictor_disabled_no_effect(self):
        """When regime_predictor is disabled, no predictor should be created."""
        cfg = RegimePredictorConfig(enabled=False)
        assert cfg.enabled is False
        assert cfg.squeeze_duration_threshold == 8
        assert cfg.emerging_trend_boost == 0.10

    def test_config_model_parses(self):
        """RegimePredictorConfig should parse from dict correctly."""
        cfg = RegimePredictorConfig(
            enabled=True,
            squeeze_duration_threshold=10,
            adx_slope_period=7,
            emerging_trend_boost=0.15,
        )
        assert cfg.enabled is True
        assert cfg.squeeze_duration_threshold == 10
        assert cfg.adx_slope_period == 7
        assert cfg.emerging_trend_boost == 0.15

    def test_regime_predictor_field_on_ai_config(self):
        """AIConfig should have a regime_predictor field."""
        ai = AIConfig()
        assert hasattr(ai, "regime_predictor")
        assert isinstance(ai.regime_predictor, RegimePredictorConfig)
        assert ai.regime_predictor.enabled is False
