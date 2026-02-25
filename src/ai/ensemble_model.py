"""
Ensemble ML Model -- Combines LightGBM with existing TFLite predictor.

Uses a configurable weighted average of predictions from multiple models.
LightGBM trains on historical ml_features from the database.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional

import numpy as np

from src.core.logger import get_logger

logger = get_logger("ensemble_model")


class EnsembleModel:
    """Ensemble model combining LightGBM + TFLite predictions."""

    def __init__(
        self,
        lgbm_weight: float = 0.4,
        tflite_weight: float = 0.6,
        min_training_samples: int = 100,
        retrain_interval_hours: float = 24.0,
        feature_names: Optional[List[str]] = None,
    ):
        self._lgbm_weight = max(0.0, min(1.0, lgbm_weight))
        self._tflite_weight = max(0.0, min(1.0, tflite_weight))
        self._min_training_samples = max(10, min_training_samples)
        self._retrain_interval = retrain_interval_hours * 3600
        self._feature_names = feature_names or [
            "rsi_14",
            "atr_pct",
            "bb_position",
            "volume_ratio",
            "momentum_5",
            "adx",
            "obv_slope",
            "spread_pct",
            "confidence",
            "confluence_count",
        ]
        self._model = None  # LightGBM Booster
        self._last_train_time: float = 0
        self._is_trained: bool = False
        self._training_lock = asyncio.Lock()
        self._feature_importance: Dict[str, float] = {}

    @property
    def is_trained(self) -> bool:
        return self._is_trained

    @property
    def feature_importance(self) -> Dict[str, float]:
        return dict(self._feature_importance)

    async def train(
        self, features: List[Dict[str, Any]], labels: List[float]
    ) -> bool:
        """Train the LightGBM model on historical features.

        Args:
            features: List of feature dicts from ml_features table
            labels: List of outcomes (1=profitable, 0=not)

        Returns:
            True if training succeeded
        """
        if len(features) < self._min_training_samples:
            logger.debug(
                "Not enough samples for training",
                count=len(features),
                needed=self._min_training_samples,
            )
            return False

        async with self._training_lock:
            try:
                import lightgbm as lgb
            except ImportError:
                logger.warning(
                    "lightgbm not installed, ensemble training skipped"
                )
                return False

            try:
                # Extract feature matrix
                X = self._extract_features(features)
                y = np.array(labels, dtype=float)

                if len(X) == 0 or len(y) == 0:
                    return False

                # Train with LightGBM
                train_data = lgb.Dataset(
                    X,
                    label=y,
                    feature_name=self._feature_names[: X.shape[1]],
                )
                params = {
                    "objective": "binary",
                    "metric": "binary_logloss",
                    "num_leaves": 31,
                    "learning_rate": 0.05,
                    "feature_fraction": 0.8,
                    "bagging_fraction": 0.8,
                    "bagging_freq": 5,
                    "verbose": -1,
                }

                self._model = lgb.train(
                    params,
                    train_data,
                    num_boost_round=100,
                    valid_sets=[train_data],
                    callbacks=[
                        lgb.early_stopping(10, verbose=False),
                        lgb.log_evaluation(0),
                    ],
                )

                # Store feature importance
                importance = self._model.feature_importance(
                    importance_type="gain"
                )
                names = self._model.feature_name()
                self._feature_importance = {
                    name: float(imp)
                    for name, imp in zip(names, importance)
                }

                self._is_trained = True
                self._last_train_time = time.time()
                logger.info(
                    "LightGBM model trained",
                    samples=len(y),
                    features=X.shape[1],
                )
                return True

            except Exception as e:
                logger.warning("LightGBM training failed", error=repr(e))
                return False

    def predict(self, features: Dict[str, Any]) -> Optional[float]:
        """Get LightGBM prediction for a single observation.

        Returns probability of profitable trade (0-1), or None if not trained.
        """
        if not self._is_trained or self._model is None:
            return None

        try:
            X = self._extract_features([features])
            if X.shape[0] == 0:
                return None
            pred = self._model.predict(X)[0]
            return float(np.clip(pred, 0.0, 1.0))
        except Exception as e:
            logger.debug("LightGBM prediction failed", error=repr(e))
            return None

    def ensemble_predict(
        self,
        features: Dict[str, Any],
        tflite_score: Optional[float] = None,
    ) -> float:
        """Combine LightGBM + TFLite predictions using weighted average.

        If LightGBM is not trained, returns tflite_score directly.
        If tflite_score is None, returns LightGBM prediction directly.

        Returns combined score in [0, 1].
        """
        lgbm_pred = self.predict(features)

        if lgbm_pred is None and tflite_score is None:
            return 0.5  # No models available

        if lgbm_pred is None:
            return float(tflite_score)

        if tflite_score is None:
            return lgbm_pred

        # Weighted average
        total_weight = self._lgbm_weight + self._tflite_weight
        if total_weight <= 0:
            return 0.5

        combined = (
            lgbm_pred * self._lgbm_weight
            + tflite_score * self._tflite_weight
        ) / total_weight
        return float(np.clip(combined, 0.0, 1.0))

    def needs_retrain(self) -> bool:
        """Check if model needs retraining based on time interval."""
        if not self._is_trained:
            return True
        return (time.time() - self._last_train_time) > self._retrain_interval

    def _extract_features(
        self, features: List[Dict[str, Any]]
    ) -> np.ndarray:
        """Extract feature matrix from list of feature dicts."""
        rows = []
        for f in features:
            row = []
            for name in self._feature_names:
                val = f.get(name, 0.0)
                try:
                    row.append(float(val) if val is not None else 0.0)
                except (TypeError, ValueError):
                    row.append(0.0)
            rows.append(row)
        return (
            np.array(rows, dtype=float)
            if rows
            else np.empty((0, len(self._feature_names)))
        )

    def get_status(self) -> Dict[str, Any]:
        """Return model status for dashboard."""
        return {
            "trained": self._is_trained,
            "last_train_time": self._last_train_time,
            "lgbm_weight": self._lgbm_weight,
            "tflite_weight": self._tflite_weight,
            "feature_importance": dict(self._feature_importance),
            "needs_retrain": self.needs_retrain(),
        }
