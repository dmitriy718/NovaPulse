"""
Bayesian Hyperparameter Optimizer — Uses Optuna to tune strategy parameters.

Runs as a periodic background task that optimizes strategy weights,
confluence thresholds, and risk parameters based on historical performance.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Dict, List, Optional

from src.core.logger import get_logger

logger = get_logger("bayesian_optimizer")


class BayesianOptimizer:
    """Optuna-based hyperparameter optimizer for trading strategies."""

    def __init__(
        self,
        n_trials: int = 50,
        optimization_interval_hours: float = 48.0,
        min_trades_for_optimization: int = 200,
        metric: str = "sharpe_ratio",
        study_name: str = "novatrader_hpo",
    ):
        self._n_trials = max(10, n_trials)
        self._interval = optimization_interval_hours * 3600
        self._min_trades = max(50, min_trades_for_optimization)
        self._metric = metric  # "sharpe_ratio", "profit_factor", "calmar_ratio"
        self._study_name = study_name
        self._last_run_time: float = 0
        self._best_params: Dict[str, Any] = {}
        self._best_score: float = float("-inf")
        self._is_running: bool = False
        self._optimization_lock = asyncio.Lock()
        self._history: List[Dict[str, Any]] = []  # List of {params, score, timestamp}

    @property
    def best_params(self) -> Dict[str, Any]:
        return dict(self._best_params)

    @property
    def best_score(self) -> float:
        return self._best_score

    @property
    def is_running(self) -> bool:
        return self._is_running

    def needs_optimization(self) -> bool:
        """Check if optimization should run."""
        if self._is_running:
            return False
        return (time.time() - self._last_run_time) > self._interval

    async def optimize(
        self,
        trade_history: List[Dict[str, Any]],
        objective_fn: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        """Run Optuna optimization.

        Args:
            trade_history: List of historical trade dicts with pnl, strategy, etc.
            objective_fn: Optional custom objective. If None, uses built-in.

        Returns:
            Dict of best parameters found.
        """
        if len(trade_history) < self._min_trades:
            logger.debug(
                "Not enough trades for optimization",
                count=len(trade_history),
                needed=self._min_trades,
            )
            return {}

        async with self._optimization_lock:
            self._is_running = True
            try:
                try:
                    import optuna

                    optuna.logging.set_verbosity(optuna.logging.WARNING)
                except ImportError:
                    logger.warning("optuna not installed, optimization skipped")
                    return {}

                # Create study
                study = optuna.create_study(
                    study_name=self._study_name,
                    direction="maximize",
                    sampler=optuna.samplers.TPESampler(seed=42),
                )

                # Define objective
                obj = objective_fn or self._build_objective(trade_history)

                # Run optimization in a thread to avoid blocking the event loop
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None,
                    lambda: study.optimize(
                        obj, n_trials=self._n_trials, show_progress_bar=False
                    ),
                )

                self._best_params = dict(study.best_params)
                self._best_score = study.best_value
                self._last_run_time = time.time()
                self._history.append(
                    {
                        "params": dict(study.best_params),
                        "score": study.best_value,
                        "timestamp": time.time(),
                        "n_trials": self._n_trials,
                        "n_trades": len(trade_history),
                    }
                )
                # Keep last 20 optimization runs
                if len(self._history) > 20:
                    self._history = self._history[-20:]

                logger.info(
                    "Optimization complete",
                    best_score=round(self._best_score, 4),
                    n_trials=self._n_trials,
                    best_params={
                        k: round(v, 4) if isinstance(v, float) else v
                        for k, v in self._best_params.items()
                    },
                )
                return dict(self._best_params)

            except Exception as e:
                logger.warning("Optimization failed", error=repr(e))
                return {}
            finally:
                self._is_running = False

    def _build_objective(self, trade_history: List[Dict[str, Any]]):
        """Build the default objective function."""
        import numpy as np

        def objective(trial):
            # Suggest parameters
            confluence_threshold = trial.suggest_int("confluence_threshold", 2, 5)
            min_confidence = trial.suggest_float(
                "min_confidence", 0.40, 0.75, step=0.05
            )
            trial.suggest_float(
                "trailing_activation_pct", 0.02, 0.08, step=0.005
            )
            trial.suggest_float(
                "max_risk_per_trade", 0.01, 0.04, step=0.005
            )
            trial.suggest_float(
                "atr_multiplier_sl", 1.5, 3.5, step=0.25
            )

            # Simulate trades with these parameters
            filtered_trades = []
            for t in trade_history:
                conf = t.get("confidence", 0.5)
                cc = t.get("confluence_count", 0)
                if cc >= confluence_threshold and conf >= min_confidence:
                    filtered_trades.append(t)

            if len(filtered_trades) < 20:
                return -999  # Not enough filtered trades

            pnls = [t.get("pnl", 0.0) for t in filtered_trades]
            pnl_arr = np.array(pnls)

            if self._metric == "sharpe_ratio":
                mean_ret = np.mean(pnl_arr)
                std_ret = np.std(pnl_arr)
                if std_ret == 0:
                    return 0.0
                return float(mean_ret / std_ret) * np.sqrt(252)  # Annualized

            elif self._metric == "profit_factor":
                wins = pnl_arr[pnl_arr > 0].sum()
                losses = abs(pnl_arr[pnl_arr < 0].sum())
                if losses == 0:
                    return float(wins) if wins > 0 else 0.0
                return float(wins / losses)

            elif self._metric == "calmar_ratio":
                total_pnl = pnl_arr.sum()
                cumsum = np.cumsum(pnl_arr)
                peak = np.maximum.accumulate(cumsum)
                drawdowns = peak - cumsum
                max_dd = drawdowns.max()
                if max_dd == 0:
                    return float(total_pnl) if total_pnl > 0 else 0.0
                return float(total_pnl / max_dd)

            return 0.0

        return objective

    def get_status(self) -> Dict[str, Any]:
        """Return status for dashboard API."""
        return {
            "is_running": self._is_running,
            "last_run_time": self._last_run_time,
            "best_params": dict(self._best_params),
            "best_score": self._best_score,
            "needs_optimization": self.needs_optimization(),
            "n_trials": self._n_trials,
            "metric": self._metric,
            "history_count": len(self._history),
        }

    def get_optimization_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Return recent optimization runs."""
        return list(self._history[-limit:])
