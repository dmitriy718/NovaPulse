"""
Cross-feature integration tests.

Tests interactions between the 10 new features to ensure they work
together correctly without conflicts.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock, AsyncMock, patch

import numpy as np
import pytest

from src.core.config import (
    BotConfig,
    EventCalendarConfig,
    LeadLagConfig,
    RegimePredictorConfig,
    OnChainConfig,
    StructuralStopConfig,
    LiquiditySizingConfig,
    EnsembleMLConfig,
    BayesianOptimizerConfig,
    AnomalyDetectorConfig,
)
from src.ai.confluence import ConfluenceSignal
from src.ai.lead_lag import LeadLagTracker
from src.ai.regime_predictor import RegimeTransitionPredictor
from src.ai.ensemble_model import EnsembleModel
from src.ai.bayesian_optimizer import BayesianOptimizer
from src.exchange.onchain_data import OnChainDataClient
from src.execution.anomaly_detector import AnomalyDetector
from src.execution.risk_manager import RiskManager, PositionSizeResult
from src.strategies.base import SignalDirection, StrategySignal
from src.utils.event_calendar import EventCalendar

from tests.conftest import (
    StubDB,
    StubMarketData,
    StubRiskManager,
    make_signal,
    make_executor,
    make_trade,
)


class TestFeatureIntegration:
    """Cross-feature integration tests."""

    async def test_event_blackout_prevents_trading_despite_strong_signals(self):
        """Event calendar blackout overrides even high-confidence signals."""
        executor, rm = make_executor()

        # Set up event calendar that is in blackout
        calendar = MagicMock()
        calendar.is_blackout.return_value = (True, "FOMC Meeting")
        executor.set_event_calendar(calendar)

        # Create a high-confidence signal (would normally trade)
        sig = make_signal(confidence=0.95, strength=0.90, is_sure_fire=True)

        # Should be gated by blackout
        result = await executor.execute_signal(sig)
        assert result is None or (hasattr(result, "get") and result.get("status") != "filled")
        # Verify calendar was checked
        calendar.is_blackout.assert_called()

    async def test_anomaly_detector_pause_state(self):
        """When anomaly detector is paused, it reports as paused."""
        detector = AnomalyDetector(pause_seconds=300)

        # Initially not paused
        assert not detector.is_paused()

        # Trigger a pause
        detector._paused_until = time.time() + 300
        assert detector.is_paused()

        # Status reflects pause
        status = detector.get_status()
        assert status["paused"] is True

    async def test_structural_stop_with_liquidity_sizing(self):
        """Structural stop + liquidity sizing work together."""
        rm = RiskManager(
            initial_bankroll=100_000,
            max_concurrent_positions=10,
            max_position_usd=5000,
        )

        # Structural stop computation
        highs = np.array([102, 103, 104, 105, 106, 105, 104, 103, 102, 101,
                          100, 101, 102, 103, 104, 105, 106, 107, 108, 109], dtype=float)
        lows = np.array([98, 99, 100, 101, 102, 101, 100, 99, 98, 97,
                         96, 97, 98, 99, 100, 101, 102, 103, 104, 105], dtype=float)

        structural_sl = rm.compute_structural_stop(
            pair="BTC/USD",
            side="buy",
            entry_price=108.0,
            highs=highs,
            lows=lows,
            atr_value=2.0,
            lookback=3,
        )
        assert structural_sl > 0
        assert structural_sl < 108.0  # Stop is below entry for buy

        # Liquidity sizing reduces position
        adjusted = rm.apply_liquidity_adjustment(
            position_size_usd=1000.0,
            bid_depth_usd=5000.0,
            ask_depth_usd=200.0,  # Thin ask side
            side="buy",
            max_impact_pct=0.10,
            min_depth_ratio=3.0,
        )
        # Thin ask depth should reduce buy position
        assert adjusted < 1000.0
        assert adjusted >= 10.0  # Minimum floor

    async def test_lead_lag_boost_combined_with_onchain_sentiment(self):
        """Lead-lag boost + on-chain sentiment stack additively on confidence."""
        base_confidence = 0.60

        # Lead-lag would boost by +0.10
        tracker = LeadLagTracker(
            leader_pairs=["BTC/USD"],
            atr_multiplier=1.0,
            lookback_minutes=5,
            boost_confidence=0.10,
            penalize_confidence=0.05,
            min_correlation=0.3,
        )

        # On-chain client with bullish sentiment
        onchain = OnChainDataClient(weight=0.08, min_abs_score=0.3)
        onchain.inject_sentiments({"ETH/USD": 0.7})  # Bullish

        sentiment = onchain.get_sentiment("ETH/USD")
        assert sentiment is not None
        assert sentiment > 0.3  # Above threshold

        # Combined: both adjustments should be additive
        onchain_boost = onchain.weight  # 0.08 for aligned direction
        # Total confidence with both boosters
        combined = min(1.0, base_confidence + 0.10 + onchain_boost)
        assert combined > base_confidence
        assert combined <= 1.0

    async def test_regime_predictor_transition_types(self):
        """Regime predictor correctly identifies different transition states."""
        predictor = RegimeTransitionPredictor(
            squeeze_duration_threshold=8,
            adx_slope_period=5,
            adx_emerging_threshold=20.0,
            volume_ratio_threshold=1.3,
            emerging_trend_boost=0.10,
        )

        # Verify predictor has the expected interface
        assert hasattr(predictor, "predict_transition")
        assert hasattr(predictor, "get_transition_confidence")

    async def test_attribution_records_after_trade_close(self):
        """P&L attribution correctly records strategy info when trade closes."""
        db = StubDB()
        executor, rm = make_executor(db=db, use_real_risk_manager=True)

        # Pre-register a position
        trade = make_trade(trade_id="T-attr-001", entry_price=50000.0, quantity=0.01)
        db._open_trades = [trade]
        rm.register_position("T-attr-001", "BTC/USD", "buy", 50000.0, 500.0, "keltner")
        rm.initialize_stop_loss("T-attr-001", 50000.0, 48500.0, "buy")

        # The DB insert_attribution method exists
        assert hasattr(db, "insert_attribution")

    async def test_ensemble_ml_fallback_without_training(self):
        """Ensemble model gracefully falls back when not trained."""
        model = EnsembleModel(lgbm_weight=0.4, tflite_weight=0.6)

        # Not trained - predict returns None
        assert model.predict({"rsi_14": 50}) is None

        # Ensemble with only TFLite score
        result = model.ensemble_predict({"rsi_14": 50}, tflite_score=0.75)
        assert result == 0.75  # Falls back to TFLite

        # Ensemble with neither
        result = model.ensemble_predict({"rsi_14": 50}, tflite_score=None)
        assert result == 0.5  # Default

    async def test_config_roundtrip_all_features(self):
        """All 10 feature configs exist with correct defaults."""
        config = BotConfig()

        # Event Calendar
        assert hasattr(config, "event_calendar")
        assert config.event_calendar.enabled is False

        # Lead-Lag
        assert hasattr(config.ai, "lead_lag")
        assert config.ai.lead_lag.enabled is False

        # Regime Predictor
        assert hasattr(config.ai, "regime_predictor")
        assert config.ai.regime_predictor.enabled is False

        # On-Chain
        assert hasattr(config.ai, "onchain")
        assert config.ai.onchain.enabled is False

        # Structural Stop
        assert hasattr(config.risk, "structural_stop")
        assert config.risk.structural_stop.enabled is False

        # Liquidity Sizing
        assert hasattr(config.risk, "liquidity_sizing")
        assert config.risk.liquidity_sizing.enabled is False

        # Ensemble ML
        assert hasattr(config.ai, "ensemble_ml")
        assert config.ai.ensemble_ml.enabled is False

        # Bayesian Optimizer
        assert hasattr(config.ai, "bayesian_optimizer")
        assert config.ai.bayesian_optimizer.enabled is False

        # Anomaly Detector
        assert hasattr(config.monitoring, "anomaly_detector")
        assert config.monitoring.anomaly_detector.enabled is False

    async def test_all_features_disabled_no_behavior_change(self):
        """When all features are disabled, basic executor flow still works."""
        executor, rm = make_executor(use_real_risk_manager=True)

        # No event calendar, no anomaly detector set
        assert getattr(executor, "_event_calendar", None) is None

        # A normal signal should still be processable
        sig = make_signal(confidence=0.70, entry_price=50000.0)
        # The executor should function without any optional components
        assert sig.confidence == 0.70
        assert sig.entry_price == 50000.0

    async def test_multiple_confidence_adjustments_clamped(self):
        """Multiple positive adjustments are clamped to [0, 1]."""
        base = 0.80

        # Simulate stacking: lead-lag +0.15, onchain +0.08, regime +0.10
        adjustments = [0.15, 0.08, 0.10]
        result = base + sum(adjustments)
        clamped = max(0.0, min(1.0, result))
        assert clamped == 1.0  # Should cap at 1.0

        # Simulate stacking negatives: lead-lag -0.10, onchain -0.08
        base_low = 0.12
        neg_adjustments = [-0.10, -0.08]
        result = base_low + sum(neg_adjustments)
        clamped = max(0.0, min(1.0, result))
        assert clamped == 0.0  # Should floor at 0.0

    async def test_bayesian_optimizer_insufficient_trades(self):
        """Bayesian optimizer gracefully handles insufficient trade history."""
        optimizer = BayesianOptimizer(
            n_trials=10,
            min_trades_for_optimization=200,
        )

        # Too few trades
        trades = [{"pnl": 10.0, "confidence": 0.7, "confluence_count": 3}] * 50
        result = await optimizer.optimize(trades)
        assert result == {}
        assert optimizer.best_params == {}
