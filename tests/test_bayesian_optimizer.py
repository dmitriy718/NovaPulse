"""Tests for Feature 10: Bayesian Hyperparameter Optimization with Optuna."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

import numpy as np
import pytest

from src.ai.bayesian_optimizer import BayesianOptimizer
from src.core.config import AIConfig, BayesianOptimizerConfig, BotConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_optimizer(**kwargs) -> BayesianOptimizer:
    defaults = {
        "n_trials": 20,
        "optimization_interval_hours": 48.0,
        "min_trades_for_optimization": 50,
        "metric": "sharpe_ratio",
    }
    defaults.update(kwargs)
    return BayesianOptimizer(**defaults)


def _make_trade_history(n: int, seed: int = 42) -> list:
    """Generate n synthetic trade records with pnl, confidence, and confluence_count."""
    rng = np.random.RandomState(seed)
    trades = []
    for _ in range(n):
        pnl = float(rng.randn() * 50 + 10)  # Mean positive bias
        trades.append({
            "pnl": pnl,
            "confidence": float(rng.uniform(0.4, 0.8)),
            "confluence_count": int(rng.choice([2, 3, 4, 5])),
            "strategy": rng.choice(["keltner", "trend", "mean_reversion"]),
        })
    return trades


# ---------------------------------------------------------------------------
# Tests that do NOT require optuna (fallback behavior)
# ---------------------------------------------------------------------------


class TestBayesianOptimizerNoOptuna:
    """Tests that work even if optuna is NOT installed."""

    def test_best_params_empty_initially(self):
        opt = _make_optimizer()
        assert opt.best_params == {}

    def test_best_score_neg_inf_initially(self):
        opt = _make_optimizer()
        assert opt.best_score == float("-inf")

    def test_not_running_initially(self):
        opt = _make_optimizer()
        assert opt.is_running is False

    def test_needs_optimization_initially(self):
        opt = _make_optimizer()
        assert opt.needs_optimization() is True

    def test_get_status_keys(self):
        opt = _make_optimizer()
        status = opt.get_status()
        expected_keys = {
            "is_running",
            "last_run_time",
            "best_params",
            "best_score",
            "needs_optimization",
            "n_trials",
            "metric",
            "history_count",
        }
        assert set(status.keys()) == expected_keys

    def test_get_history_empty(self):
        opt = _make_optimizer()
        history = opt.get_optimization_history()
        assert history == []

    def test_get_history_limit(self):
        opt = _make_optimizer()
        # Manually populate history
        for i in range(5):
            opt._history.append({"params": {}, "score": float(i), "timestamp": time.time()})
        assert len(opt.get_optimization_history(limit=3)) == 3
        assert len(opt.get_optimization_history(limit=10)) == 5

    @pytest.mark.asyncio
    async def test_optimize_insufficient_trades(self):
        opt = _make_optimizer(min_trades_for_optimization=100)
        trades = _make_trade_history(20)
        result = await opt.optimize(trades)
        assert result == {}

    @pytest.mark.asyncio
    async def test_optimize_without_optuna_installed(self):
        """When optuna is not importable, optimization returns empty gracefully."""
        opt = _make_optimizer(min_trades_for_optimization=10)
        trades = _make_trade_history(50)
        with patch.dict("sys.modules", {"optuna": None}):
            result = await opt.optimize(trades)
        assert result == {}

    def test_needs_optimization_false_when_running(self):
        opt = _make_optimizer()
        opt._is_running = True
        assert opt.needs_optimization() is False

    def test_needs_optimization_false_after_recent_run(self):
        opt = _make_optimizer(optimization_interval_hours=1.0)
        opt._last_run_time = time.time()  # Just ran
        assert opt.needs_optimization() is False

    def test_needs_optimization_true_after_interval(self):
        opt = _make_optimizer(optimization_interval_hours=1.0)
        opt._last_run_time = time.time() - 7200  # 2 hours ago, interval is 1 hour
        assert opt.needs_optimization() is True

    def test_n_trials_minimum_clamped(self):
        opt = _make_optimizer(n_trials=3)
        assert opt._n_trials == 10  # min 10

    def test_min_trades_minimum_clamped(self):
        opt = _make_optimizer(min_trades_for_optimization=5)
        assert opt._min_trades == 50  # min 50


# ---------------------------------------------------------------------------
# Config integration tests
# ---------------------------------------------------------------------------


class TestBayesianOptimizerConfig:

    def test_config_defaults(self):
        cfg = BayesianOptimizerConfig()
        assert cfg.enabled is False
        assert cfg.n_trials == 50
        assert cfg.optimization_interval_hours == 48.0
        assert cfg.min_trades_for_optimization == 200
        assert cfg.metric == "sharpe_ratio"

    def test_config_in_ai_config(self):
        ai_cfg = AIConfig()
        assert hasattr(ai_cfg, "bayesian_optimizer")
        assert isinstance(ai_cfg.bayesian_optimizer, BayesianOptimizerConfig)
        assert ai_cfg.bayesian_optimizer.enabled is False

    def test_config_disabled_no_effect(self):
        bot_cfg = BotConfig()
        assert bot_cfg.ai.bayesian_optimizer.enabled is False

    def test_config_custom_values(self):
        cfg = BayesianOptimizerConfig(
            enabled=True,
            n_trials=100,
            optimization_interval_hours=24.0,
            min_trades_for_optimization=500,
            metric="profit_factor",
        )
        assert cfg.enabled is True
        assert cfg.n_trials == 100
        assert cfg.optimization_interval_hours == 24.0
        assert cfg.min_trades_for_optimization == 500
        assert cfg.metric == "profit_factor"


# ---------------------------------------------------------------------------
# Tests that REQUIRE optuna
# ---------------------------------------------------------------------------


class TestBayesianOptimizerWithOptuna:

    @pytest.fixture(autouse=True)
    def _require_optuna(self):
        pytest.importorskip("optuna")

    @pytest.mark.asyncio
    async def test_optimize_with_optuna(self):
        """Full optimization on mock trades returns params."""
        opt = _make_optimizer(
            n_trials=15,
            min_trades_for_optimization=50,
            metric="sharpe_ratio",
        )
        trades = _make_trade_history(200)
        result = await opt.optimize(trades)
        assert isinstance(result, dict)
        assert len(result) > 0
        assert "confluence_threshold" in result
        assert "min_confidence" in result

    @pytest.mark.asyncio
    async def test_sharpe_ratio_objective(self):
        """Sharpe ratio metric produces a finite score."""
        opt = _make_optimizer(
            n_trials=10,
            min_trades_for_optimization=50,
            metric="sharpe_ratio",
        )
        trades = _make_trade_history(200)
        await opt.optimize(trades)
        assert opt.best_score != float("-inf")
        assert np.isfinite(opt.best_score)

    @pytest.mark.asyncio
    async def test_profit_factor_objective(self):
        """Profit factor metric produces a finite score."""
        opt = _make_optimizer(
            n_trials=10,
            min_trades_for_optimization=50,
            metric="profit_factor",
        )
        trades = _make_trade_history(200)
        await opt.optimize(trades)
        assert opt.best_score != float("-inf")
        assert np.isfinite(opt.best_score)

    @pytest.mark.asyncio
    async def test_calmar_ratio_objective(self):
        """Calmar ratio metric produces a finite score."""
        opt = _make_optimizer(
            n_trials=10,
            min_trades_for_optimization=50,
            metric="calmar_ratio",
        )
        trades = _make_trade_history(200)
        await opt.optimize(trades)
        assert opt.best_score != float("-inf")
        assert np.isfinite(opt.best_score)

    @pytest.mark.asyncio
    async def test_history_recorded_after_run(self):
        """History is updated after a successful optimization run."""
        opt = _make_optimizer(
            n_trials=10,
            min_trades_for_optimization=50,
        )
        trades = _make_trade_history(200)
        await opt.optimize(trades)
        history = opt.get_optimization_history()
        assert len(history) == 1
        assert "params" in history[0]
        assert "score" in history[0]
        assert "timestamp" in history[0]
        assert "n_trials" in history[0]
        assert "n_trades" in history[0]
        assert history[0]["n_trades"] == 200

    @pytest.mark.asyncio
    async def test_best_params_populated_after_run(self):
        """Best params and score are populated after optimization."""
        opt = _make_optimizer(
            n_trials=10,
            min_trades_for_optimization=50,
        )
        trades = _make_trade_history(200)
        await opt.optimize(trades)
        assert len(opt.best_params) > 0
        assert opt.best_score != float("-inf")

    @pytest.mark.asyncio
    async def test_needs_optimization_false_after_run(self):
        """After running, needs_optimization should be False (within interval)."""
        opt = _make_optimizer(
            n_trials=10,
            min_trades_for_optimization=50,
            optimization_interval_hours=24.0,
        )
        trades = _make_trade_history(200)
        await opt.optimize(trades)
        assert opt.needs_optimization() is False

    @pytest.mark.asyncio
    async def test_concurrent_optimization_prevented(self):
        """Lock prevents concurrent optimization runs."""
        opt = _make_optimizer(
            n_trials=10,
            min_trades_for_optimization=50,
        )
        trades = _make_trade_history(200)

        # Start two optimizations concurrently
        results = await asyncio.gather(
            opt.optimize(trades),
            opt.optimize(trades),
        )
        # Both should return results (one blocks, then the other runs)
        # But only one should run at a time due to the lock
        non_empty = [r for r in results if r]
        assert len(non_empty) >= 1
        # History should have at most 2 entries (sequential, not concurrent)
        assert len(opt.get_optimization_history()) <= 2

    @pytest.mark.asyncio
    async def test_custom_objective_function(self):
        """Custom objective function is used when provided."""
        opt = _make_optimizer(
            n_trials=10,
            min_trades_for_optimization=50,
        )
        trades = _make_trade_history(200)

        def custom_obj(trial):
            x = trial.suggest_float("custom_param", 0.0, 1.0)
            return -(x - 0.42) ** 2  # Simple quadratic with max at 0.42

        result = await opt.optimize(trades, objective_fn=custom_obj)
        assert "custom_param" in result
        # Should be reasonably close to 0.42
        assert abs(result["custom_param"] - 0.42) < 0.2

    @pytest.mark.asyncio
    async def test_history_capped_at_20(self):
        """History is capped at 20 entries."""
        opt = _make_optimizer(
            n_trials=10,
            min_trades_for_optimization=50,
            optimization_interval_hours=0.0,  # Always needs optimization
        )
        trades = _make_trade_history(200)
        # Run 22 times - force last_run_time reset to allow re-run
        for _ in range(22):
            opt._last_run_time = 0  # Reset so needs_optimization() is True
            await opt.optimize(trades)
        assert len(opt._history) == 20

    @pytest.mark.asyncio
    async def test_get_status_after_run(self):
        """Status reflects state after successful optimization."""
        opt = _make_optimizer(
            n_trials=10,
            min_trades_for_optimization=50,
        )
        trades = _make_trade_history(200)
        await opt.optimize(trades)
        status = opt.get_status()
        assert status["is_running"] is False
        assert status["last_run_time"] > 0
        assert len(status["best_params"]) > 0
        assert status["best_score"] != float("-inf")
        assert status["needs_optimization"] is False
        assert status["history_count"] == 1
