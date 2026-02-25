"""Tests for Feature 9: Ensemble ML Model with LightGBM."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.ai.ensemble_model import EnsembleModel
from src.core.config import AIConfig, BotConfig, EnsembleMLConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_model(**kwargs) -> EnsembleModel:
    defaults = {
        "lgbm_weight": 0.4,
        "tflite_weight": 0.6,
        "min_training_samples": 10,
        "retrain_interval_hours": 24.0,
        "feature_names": ["f1", "f2", "f3"],
    }
    defaults.update(kwargs)
    return EnsembleModel(**defaults)


def _make_features(n: int, seed: int = 42) -> list:
    """Generate n random feature dicts."""
    rng = np.random.RandomState(seed)
    return [
        {"f1": float(rng.randn()), "f2": float(rng.randn()), "f3": float(rng.randn())}
        for _ in range(n)
    ]


def _make_labels(n: int, seed: int = 42) -> list:
    """Generate n binary labels."""
    rng = np.random.RandomState(seed)
    return [float(x) for x in rng.randint(0, 2, size=n)]


# ---------------------------------------------------------------------------
# Tests that do NOT require lightgbm (fallback behavior)
# ---------------------------------------------------------------------------


class TestEnsembleNoLightGBM:
    """Tests that work even if lightgbm is NOT installed."""

    def test_predict_untrained_returns_none(self):
        model = _make_model()
        result = model.predict({"f1": 1.0, "f2": 0.5, "f3": -0.3})
        assert result is None

    def test_ensemble_with_only_tflite(self):
        """When LightGBM is untrained, returns TFLite score directly."""
        model = _make_model()
        result = model.ensemble_predict({"f1": 1.0}, tflite_score=0.75)
        assert result == 0.75

    def test_ensemble_no_models(self):
        """When neither model is available, returns 0.5."""
        model = _make_model()
        result = model.ensemble_predict({"f1": 1.0}, tflite_score=None)
        assert result == 0.5

    def test_needs_retrain_initially(self):
        model = _make_model()
        assert model.needs_retrain() is True

    def test_is_trained_initially_false(self):
        model = _make_model()
        assert model.is_trained is False

    def test_feature_extraction(self):
        model = _make_model(feature_names=["a", "b", "c"])
        features = [{"a": 1.0, "b": 2.0, "c": 3.0}]
        X = model._extract_features(features)
        assert X.shape == (1, 3)
        np.testing.assert_array_almost_equal(X[0], [1.0, 2.0, 3.0])

    def test_feature_extraction_missing_keys(self):
        model = _make_model(feature_names=["a", "b", "c"])
        features = [{"a": 1.0}]  # b and c missing -> default to 0.0
        X = model._extract_features(features)
        np.testing.assert_array_almost_equal(X[0], [1.0, 0.0, 0.0])

    def test_feature_extraction_none_value(self):
        model = _make_model(feature_names=["a", "b"])
        features = [{"a": None, "b": 2.0}]
        X = model._extract_features(features)
        np.testing.assert_array_almost_equal(X[0], [0.0, 2.0])

    def test_feature_extraction_empty(self):
        model = _make_model(feature_names=["a", "b"])
        X = model._extract_features([])
        assert X.shape == (0, 2)

    def test_get_status(self):
        model = _make_model()
        status = model.get_status()
        assert "trained" in status
        assert "last_train_time" in status
        assert "lgbm_weight" in status
        assert "tflite_weight" in status
        assert "feature_importance" in status
        assert "needs_retrain" in status
        assert status["trained"] is False
        assert status["needs_retrain"] is True

    def test_feature_importance_empty_before_training(self):
        model = _make_model()
        assert model.feature_importance == {}

    @pytest.mark.asyncio
    async def test_train_insufficient_samples(self):
        model = _make_model(min_training_samples=50)
        features = _make_features(10)
        labels = _make_labels(10)
        result = await model.train(features, labels)
        assert result is False

    @pytest.mark.asyncio
    async def test_train_without_lightgbm_installed(self):
        """When lightgbm is not importable, training returns False gracefully."""
        model = _make_model(min_training_samples=5)
        features = _make_features(20)
        labels = _make_labels(20)
        with patch.dict("sys.modules", {"lightgbm": None}):
            result = await model.train(features, labels)
        assert result is False


# ---------------------------------------------------------------------------
# Config integration tests
# ---------------------------------------------------------------------------


class TestEnsembleConfig:

    def test_ensemble_ml_config_defaults(self):
        cfg = EnsembleMLConfig()
        assert cfg.enabled is False
        assert cfg.lgbm_weight == 0.4
        assert cfg.tflite_weight == 0.6
        assert cfg.min_training_samples == 100
        assert cfg.retrain_interval_hours == 24.0
        assert len(cfg.feature_names) == 10

    def test_ensemble_ml_in_ai_config(self):
        ai_cfg = AIConfig()
        assert hasattr(ai_cfg, "ensemble_ml")
        assert isinstance(ai_cfg.ensemble_ml, EnsembleMLConfig)
        assert ai_cfg.ensemble_ml.enabled is False

    def test_ensemble_disabled_no_effect(self):
        """When disabled, ensemble_ml exists but is disabled."""
        bot_cfg = BotConfig()
        assert bot_cfg.ai.ensemble_ml.enabled is False

    def test_ensemble_config_custom_values(self):
        cfg = EnsembleMLConfig(
            enabled=True,
            lgbm_weight=0.7,
            tflite_weight=0.3,
            min_training_samples=200,
            retrain_interval_hours=12.0,
        )
        assert cfg.enabled is True
        assert cfg.lgbm_weight == 0.7
        assert cfg.tflite_weight == 0.3
        assert cfg.min_training_samples == 200
        assert cfg.retrain_interval_hours == 12.0


# ---------------------------------------------------------------------------
# Tests that REQUIRE lightgbm
# ---------------------------------------------------------------------------


class TestEnsembleWithLightGBM:

    @pytest.fixture(autouse=True)
    def _require_lgbm(self):
        pytest.importorskip("lightgbm")

    @pytest.mark.asyncio
    async def test_train_and_predict(self):
        """Train on mock data, verify predict returns value in [0, 1]."""
        model = _make_model(min_training_samples=10)
        features = _make_features(100)
        labels = _make_labels(100)

        result = await model.train(features, labels)
        assert result is True
        assert model.is_trained is True

        pred = model.predict({"f1": 0.5, "f2": -0.2, "f3": 1.0})
        assert pred is not None
        assert 0.0 <= pred <= 1.0

    @pytest.mark.asyncio
    async def test_feature_importance_populated(self):
        """After training, feature importance dict is populated."""
        model = _make_model(min_training_samples=10)
        features = _make_features(100)
        labels = _make_labels(100)

        await model.train(features, labels)
        fi = model.feature_importance
        assert len(fi) > 0
        assert all(isinstance(v, float) for v in fi.values())

    @pytest.mark.asyncio
    async def test_ensemble_weighted_average(self):
        """Both models available -> weighted average."""
        model = _make_model(
            lgbm_weight=0.5,
            tflite_weight=0.5,
            min_training_samples=10,
        )
        features = _make_features(100)
        labels = _make_labels(100)

        await model.train(features, labels)
        assert model.is_trained

        tflite_score = 0.8
        result = model.ensemble_predict(
            {"f1": 0.5, "f2": -0.2, "f3": 1.0},
            tflite_score=tflite_score,
        )
        assert 0.0 <= result <= 1.0
        # Should be between lgbm prediction and tflite_score
        lgbm_only = model.predict({"f1": 0.5, "f2": -0.2, "f3": 1.0})
        low = min(lgbm_only, tflite_score)
        high = max(lgbm_only, tflite_score)
        assert low - 0.01 <= result <= high + 0.01

    @pytest.mark.asyncio
    async def test_ensemble_with_only_lgbm(self):
        """Only LightGBM trained, no TFLite -> returns LightGBM prediction."""
        model = _make_model(min_training_samples=10)
        features = _make_features(100)
        labels = _make_labels(100)

        await model.train(features, labels)
        result = model.ensemble_predict(
            {"f1": 0.5, "f2": -0.2, "f3": 1.0},
            tflite_score=None,
        )
        lgbm_only = model.predict({"f1": 0.5, "f2": -0.2, "f3": 1.0})
        assert result == lgbm_only

    @pytest.mark.asyncio
    async def test_needs_retrain_after_training(self):
        """After training, needs_retrain should be False."""
        model = _make_model(min_training_samples=10, retrain_interval_hours=24.0)
        features = _make_features(100)
        labels = _make_labels(100)

        await model.train(features, labels)
        assert model.needs_retrain() is False

    @pytest.mark.asyncio
    async def test_needs_retrain_after_interval(self):
        """After retrain interval elapses, needs_retrain should be True."""
        model = _make_model(min_training_samples=10, retrain_interval_hours=0.0001)
        features = _make_features(100)
        labels = _make_labels(100)

        await model.train(features, labels)
        # Force time to elapse past the very short interval
        model._last_train_time = time.time() - 10
        assert model.needs_retrain() is True

    @pytest.mark.asyncio
    async def test_get_status_after_training(self):
        model = _make_model(min_training_samples=10)
        features = _make_features(100)
        labels = _make_labels(100)

        await model.train(features, labels)
        status = model.get_status()
        assert status["trained"] is True
        assert status["last_train_time"] > 0
        assert status["needs_retrain"] is False
        assert len(status["feature_importance"]) > 0

    @pytest.mark.asyncio
    async def test_weight_clamping(self):
        """Weights outside [0, 1] should be clamped."""
        model = _make_model(lgbm_weight=2.0, tflite_weight=-0.5, min_training_samples=10)
        assert model._lgbm_weight == 1.0
        assert model._tflite_weight == 0.0

        features = _make_features(100)
        labels = _make_labels(100)
        await model.train(features, labels)

        # Only LightGBM weight matters
        result = model.ensemble_predict(
            {"f1": 0.5, "f2": -0.2, "f3": 1.0},
            tflite_score=0.9,
        )
        lgbm_only = model.predict({"f1": 0.5, "f2": -0.2, "f3": 1.0})
        assert abs(result - lgbm_only) < 0.01

    @pytest.mark.asyncio
    async def test_predict_with_extra_features(self):
        """Extra keys in feature dict are ignored."""
        model = _make_model(min_training_samples=10)
        features = _make_features(100)
        labels = _make_labels(100)

        await model.train(features, labels)
        pred = model.predict({"f1": 0.5, "f2": -0.2, "f3": 1.0, "extra": 99.0})
        assert pred is not None
        assert 0.0 <= pred <= 1.0
