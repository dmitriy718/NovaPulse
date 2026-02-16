"""
ContinuousLearner - online, incremental model that improves as trades close.

Design goals:
- Never block trading (best-effort; bounded work; async lock).
- Persist to disk so it keeps improving across restarts.
- Fail-safe: if anything breaks, return None and the system falls back to
  TFLite/heuristics.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from src.ai.predictor import TradePredictorFeatures
from src.core.logger import get_logger

logger = get_logger("continuous_learner")


@dataclass
class ContinuousStats:
    seen: int = 0
    updates: int = 0
    last_saved_ts: float = 0.0
    last_update_ts: float = 0.0


class ContinuousLearner:
    """
    Incremental classifier (SGD log-loss) trained from (features, label).

    Notes:
    - This is not RL and does not directly optimize portfolio objectives.
    - It is a lightweight online learner intended to steadily improve the
      probability gate as labeled examples accumulate.
    """

    def __init__(
        self,
        model_path: str = "models/continuous_sgd.joblib",
        feature_names: Optional[List[str]] = None,
        save_every_updates: int = 25,
        min_updates_before_predict: int = 50,
    ):
        self.model_path = Path(model_path)
        self.model_path.parent.mkdir(parents=True, exist_ok=True)
        self.feature_names = [str(n) for n in (feature_names or TradePredictorFeatures.FEATURE_NAMES)]
        self.save_every_updates = max(1, int(save_every_updates))
        self.min_updates_before_predict = max(1, int(min_updates_before_predict))

        self._lock = asyncio.Lock()
        self._scaler = None
        self._model = None
        self.stats = ContinuousStats()

        self._load_best_effort()

    def _load_best_effort(self) -> None:
        if not self.model_path.exists():
            return
        try:
            import joblib

            payload = joblib.load(self.model_path)
            self._scaler = payload.get("scaler")
            self._model = payload.get("model")
            self.stats = payload.get("stats") or self.stats
            if not isinstance(self.stats, ContinuousStats):
                try:
                    from dataclasses import asdict, fields as dc_fields
                    if hasattr(self.stats, '__dataclass_fields__'):
                        raw = asdict(self.stats)
                    else:
                        raw = dict(self.stats)
                    valid_keys = {f.name for f in dc_fields(ContinuousStats)}
                    self.stats = ContinuousStats(**{k: v for k, v in raw.items() if k in valid_keys})
                except Exception:
                    self.stats = ContinuousStats()
            logger.info("Continuous model loaded", path=str(self.model_path), seen=self.stats.seen)
        except Exception as e:
            logger.warning("Continuous model load failed (non-fatal)", error=repr(e))

    def _vectorize(self, features: Dict[str, Any]) -> np.ndarray:
        x = np.zeros((1, len(self.feature_names)), dtype=np.float32)
        for i, name in enumerate(self.feature_names):
            v = features.get(name, 0.0)
            try:
                fv = float(v)
                if not np.isfinite(fv):
                    fv = 0.0
            except Exception:
                fv = 0.0
            x[0, i] = fv
        return x

    async def predict_proba(self, features: Dict[str, Any]) -> Optional[float]:
        async with self._lock:
            if self._model is None or self._scaler is None:
                return None
            if self.stats.updates < self.min_updates_before_predict:
                return None
            try:
                x = self._vectorize(features)
                xs = self._scaler.transform(x)
                # predict_proba returns [P(class0), P(class1)]
                p = float(self._model.predict_proba(xs)[0, 1])
                if not np.isfinite(p):
                    return None
                return max(0.0, min(1.0, p))
            except Exception:
                return None

    async def update(self, features: Dict[str, Any], label: float) -> None:
        y = 1 if float(label) > 0 else 0
        async with self._lock:
            try:
                from sklearn.linear_model import SGDClassifier
                from sklearn.preprocessing import StandardScaler

                if self._scaler is None:
                    self._scaler = StandardScaler(with_mean=True, with_std=True)
                if self._model is None:
                    self._model = SGDClassifier(
                        loss="log_loss",
                        alpha=0.0005,
                        penalty="l2",
                        learning_rate="optimal",
                        random_state=42,
                    )

                x = self._vectorize(features)
                # Freeze scaler after enough samples to avoid distribution drift
                if self.stats.seen < 200:
                    self._scaler.partial_fit(x)
                xs = self._scaler.transform(x)

                # partial_fit needs classes on first call
                if self.stats.updates == 0:
                    self._model.partial_fit(xs, np.array([y], dtype=np.int64), classes=np.array([0, 1], dtype=np.int64))
                else:
                    self._model.partial_fit(xs, np.array([y], dtype=np.int64))

                self.stats.seen += 1
                self.stats.updates += 1
                self.stats.last_update_ts = time.time()

                if (self.stats.updates % self.save_every_updates) == 0:
                    self._save_locked()
            except Exception as e:
                logger.debug("Continuous update failed (non-fatal)", error=repr(e))

    def _save_locked(self) -> None:
        try:
            import joblib

            tmp = self.model_path.with_suffix(self.model_path.suffix + ".tmp")
            payload = {"scaler": self._scaler, "model": self._model, "stats": self.stats}
            joblib.dump(payload, tmp)
            os.replace(tmp, self.model_path)
            self.stats.last_saved_ts = time.time()
            logger.info("Continuous model saved", path=str(self.model_path), updates=self.stats.updates)
        except Exception as e:
            logger.warning("Continuous model save failed (non-fatal)", error=repr(e))

    async def force_save(self) -> None:
        async with self._lock:
            self._save_locked()

