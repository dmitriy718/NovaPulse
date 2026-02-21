"""
Core component tests for the AI Trading Bot.

Validates configuration loading, indicator calculations,
strategy signal generation, risk management, and database operations.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.config import BotConfig
from src.core.database import DatabaseManager
from src.exchange.coinbase_rest import CoinbaseRESTClient
from src.exchange.coinbase_ws import CoinbaseWebSocketClient
from src.exchange.market_data import MarketDataCache
from src.execution.executor import TradeExecutor
from src.execution.risk_manager import RiskManager
from src.strategies.base import SignalDirection, StrategySignal
from src.strategies.breakout import BreakoutStrategy
from src.strategies.mean_reversion import MeanReversionStrategy
from src.strategies.momentum import MomentumStrategy
from src.strategies.reversal import ReversalStrategy
from src.strategies.rsi_mean_reversion import RSIMeanReversionStrategy
from src.strategies.trend import TrendStrategy
from src.strategies.vwap_momentum_alpha import VWAPMomentumAlphaStrategy
from src.ai.predictor import TradePredictorFeatures
from src.ml.trainer import ModelTrainer
from src.utils.indicators import (
    adx,
    atr,
    bb_position,
    bollinger_bands,
    ema,
    momentum,
    order_book_imbalance,
    rsi,
    sma,
    trend_strength,
    volume_ratio,
)


# ---- Indicator Tests ----

class TestIndicators:
    """Test technical indicator calculations."""

    def test_ema_basic(self):
        data = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])
        result = ema(data, 3)
        assert len(result) == len(data)
        assert np.isnan(result[0])
        assert not np.isnan(result[2])
        assert result[-1] > result[5]  # Uptrend

    def test_sma_basic(self):
        data = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        result = sma(data, 3)
        assert len(result) == len(data)
        assert np.isnan(result[0])
        assert abs(result[2] - 2.0) < 0.01  # (1+2+3)/3
        assert abs(result[4] - 4.0) < 0.01  # (3+4+5)/3

    def test_rsi_range(self):
        data = np.random.uniform(90, 110, 100)
        result = rsi(data, 14)
        assert len(result) == len(data)
        # RSI should be between 0 and 100
        valid = result[~np.isnan(result)]
        assert all(0 <= v <= 100 for v in valid)

    def test_rsi_extremes(self):
        # All up moves -> RSI should be high
        up_data = np.cumsum(np.ones(50)) + 100
        result = rsi(up_data, 14)
        assert result[-1] > 70

    def test_bollinger_bands(self):
        data = np.random.normal(100, 5, 50)
        upper, middle, lower = bollinger_bands(data, 20, 2.0)
        assert len(upper) == len(data)
        # Upper > middle > lower (for non-NaN values)
        valid_idx = ~np.isnan(upper)
        assert all(upper[valid_idx] >= middle[valid_idx])
        assert all(middle[valid_idx] >= lower[valid_idx])

    def test_bb_position_range(self):
        # M25: bb_position is now unclipped, but should be near [0,1] for normal data
        data = np.random.normal(100, 5, 50)
        result = bb_position(data, 20, 2.0)
        valid = result[~np.isnan(result)]
        assert len(valid) > 0
        # Most values should be between -0.5 and 1.5 for normal distribution
        assert all(-1.0 <= v <= 2.0 for v in valid)

    def test_atr_positive(self):
        highs = np.random.uniform(101, 110, 50)
        lows = np.random.uniform(90, 99, 50)
        closes = (highs + lows) / 2
        result = atr(highs, lows, closes, 14)
        valid = result[result > 0]
        assert len(valid) > 0
        assert all(v >= 0 for v in valid)

    def test_adx_range(self):
        highs = np.cumsum(np.random.uniform(0, 2, 100)) + 100
        lows = highs - np.random.uniform(1, 3, 100)
        closes = (highs + lows) / 2
        result = adx(highs, lows, closes, 14)
        valid = result[~np.isnan(result)]
        assert all(v >= 0 for v in valid)

    def test_order_book_imbalance(self):
        assert order_book_imbalance(100, 50) > 0  # More bids = positive
        assert order_book_imbalance(50, 100) < 0  # More asks = negative
        assert order_book_imbalance(100, 100) == 0  # Equal = neutral
        assert order_book_imbalance(0, 0) == 0  # Empty = neutral

    def test_volume_ratio(self):
        volumes = np.array([100, 100, 100, 100, 100, 200], dtype=float)
        result = volume_ratio(volumes, 5)
        assert result[-1] > 1.0  # Last bar has above-average volume

    def test_momentum_calculation(self):
        data = np.array([100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110], dtype=float)
        result = momentum(data, 5)
        assert result[-1] > 0  # Upward momentum

    def test_trend_strength(self):
        uptrend = np.cumsum(np.ones(50)) + 100
        result = trend_strength(uptrend, 5, 13)
        valid = result[~np.isnan(result)]
        assert len(valid) > 0
        assert valid[-1] > 0  # Positive trend


# ---- Strategy Tests ----

class TestStrategies:
    """Test strategy signal generation."""

    @staticmethod
    def _generate_uptrend(n=200):
        noise = np.random.normal(0, 0.5, n)
        trend = np.cumsum(np.random.uniform(0.1, 0.5, n))
        closes = 100 + trend + noise
        highs = closes + np.random.uniform(0.2, 1.0, n)
        lows = closes - np.random.uniform(0.2, 1.0, n)
        volumes = np.random.uniform(80, 120, n)
        return closes, highs, lows, volumes

    @staticmethod
    def _generate_ranging(n=200):
        closes = 100 + np.sin(np.linspace(0, 10, n)) * 5 + np.random.normal(0, 0.5, n)
        highs = closes + np.random.uniform(0.2, 1.0, n)
        lows = closes - np.random.uniform(0.2, 1.0, n)
        volumes = np.random.uniform(80, 120, n)
        return closes, highs, lows, volumes

    @pytest.mark.asyncio
    async def test_trend_strategy_returns_signal(self):
        strategy = TrendStrategy()
        closes, highs, lows, volumes = self._generate_uptrend()
        signal = await strategy.analyze("BTC/USD", closes, highs, lows, volumes)
        assert isinstance(signal, StrategySignal)
        assert signal.strategy_name == "trend"
        assert signal.pair == "BTC/USD"

    @pytest.mark.asyncio
    async def test_mean_reversion_returns_signal(self):
        strategy = MeanReversionStrategy()
        closes, highs, lows, volumes = self._generate_ranging()
        signal = await strategy.analyze("ETH/USD", closes, highs, lows, volumes)
        assert isinstance(signal, StrategySignal)
        assert signal.strategy_name == "mean_reversion"

    @pytest.mark.asyncio
    async def test_momentum_returns_signal(self):
        strategy = MomentumStrategy()
        closes, highs, lows, volumes = self._generate_uptrend()
        signal = await strategy.analyze("BTC/USD", closes, highs, lows, volumes)
        assert isinstance(signal, StrategySignal)

    @pytest.mark.asyncio
    async def test_breakout_returns_signal(self):
        strategy = BreakoutStrategy()
        closes, highs, lows, volumes = self._generate_uptrend()
        signal = await strategy.analyze("BTC/USD", closes, highs, lows, volumes)
        assert isinstance(signal, StrategySignal)

    @pytest.mark.asyncio
    async def test_reversal_returns_signal(self):
        strategy = ReversalStrategy()
        closes, highs, lows, volumes = self._generate_ranging()
        signal = await strategy.analyze("BTC/USD", closes, highs, lows, volumes)
        assert isinstance(signal, StrategySignal)

    @pytest.mark.asyncio
    async def test_vwap_momentum_alpha_returns_signal(self):
        strategy = VWAPMomentumAlphaStrategy()
        closes, highs, lows, volumes = self._generate_uptrend()
        signal = await strategy.analyze("BTC/USD", closes, highs, lows, volumes)
        assert isinstance(signal, StrategySignal)

    @pytest.mark.asyncio
    async def test_rsi_mean_reversion_returns_signal(self):
        strategy = RSIMeanReversionStrategy()
        closes, highs, lows, volumes = self._generate_ranging()
        signal = await strategy.analyze("ETH/USD", closes, highs, lows, volumes)
        assert isinstance(signal, StrategySignal)

    @pytest.mark.asyncio
    async def test_strategy_insufficient_data(self):
        strategy = TrendStrategy()
        closes = np.array([100.0, 101.0, 102.0])
        highs = closes + 1
        lows = closes - 1
        volumes = np.array([100.0, 100.0, 100.0])
        signal = await strategy.analyze("BTC/USD", closes, highs, lows, volumes)
        assert signal.direction == SignalDirection.NEUTRAL


# ---- Exchange/Data Path Tests ----

class TestExchangeDataPaths:
    """Test exchange helpers and market-data edge cases."""

    @pytest.mark.asyncio
    async def test_coinbase_ws_subscriptions_are_additive(self):
        ws = CoinbaseWebSocketClient(url="wss://example.invalid")
        await ws.subscribe_ticker(["BTC/USD"])
        await ws.subscribe_ticker(["ETH/USD"])

        sub = ws._subscriptions.get("ticker", {})
        product_ids = sub.get("product_ids", [])
        assert "BTC-USD" in product_ids
        assert "ETH-USD" in product_ids
        assert len(product_ids) == 2

    @pytest.mark.asyncio
    async def test_market_data_update_bar_outlier_returns_false(self):
        cache = MarketDataCache(max_bars=64)
        pair = "BTC/USD"
        base_ts = 1_700_000_000

        # Seed enough bars to enable outlier checks.
        for i in range(12):
            wrote = await cache.update_bar(
                pair,
                {
                    "time": float(base_ts + i * 60),
                    "open": 100.0 + i,
                    "high": 101.0 + i,
                    "low": 99.0 + i,
                    "close": 100.0 + i,
                    "volume": 1.0,
                },
            )
            assert isinstance(wrote, bool)

        # >20% jump triggers reject path; should return explicit False.
        result = await cache.update_bar(
            pair,
            {
                "time": float(base_ts + 12 * 60),
                "open": 200.0,
                "high": 205.0,
                "low": 195.0,
                "close": 200.0,
                "volume": 1.0,
            },
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_coinbase_trade_history_falls_back_from_trades_to_ticker(self):
        client = CoinbaseRESTClient()
        calls = []

        async def fake_request(method, path, **kwargs):
            calls.append(path)
            if path.endswith("/trades"):
                raise RuntimeError("trades endpoint unavailable")
            return {"symbol": "BTC-USD", "price": "50000"}

        client._request = fake_request  # type: ignore[method-assign]
        payload = await client.get_trade_history_public("BTC/USD")

        assert calls[0].endswith("/trades")
        assert calls[1].endswith("/ticker")
        assert payload.get("symbol") == "BTC-USD"


# ---- Backtest Parity Smoke Tests ----

class TestBacktesterParity:
    @pytest.mark.asyncio
    async def test_parity_mode_runs_smoke(self):
        import pandas as pd
        from src.core.config import BotConfig
        from src.ml.backtester import Backtester

        n = 200
        base_ts = 1_700_000_000
        df = pd.DataFrame({
            "time": [base_ts + i * 60 for i in range(n)],
            "open": [100.0 + 0.01 * i for i in range(n)],
            "high": [100.2 + 0.01 * i for i in range(n)],
            "low": [99.8 + 0.01 * i for i in range(n)],
            "close": [100.0 + 0.01 * i for i in range(n)],
            "volume": [100.0 for _ in range(n)],
        })

        cfg = BotConfig()
        bt = Backtester(initial_balance=10000.0)
        result = await bt.run(pair="BTC/USD", ohlcv_data=df, mode="parity", config=cfg)
        d = result.to_dict()
        assert d["initial_balance"] == 10000.0
        assert d["total_trades"] >= 0
        assert len(result.equity_curve) > 0


# ---- Risk Manager Tests ----

class TestRiskManager:
    """Test risk management logic."""

    def test_position_sizing_basic(self):
        rm = RiskManager(initial_bankroll=10000)
        result = rm.calculate_position_size(
            pair="BTC/USD",
            entry_price=50000,
            stop_loss=49000,
            take_profit=52000,
            win_rate=0.55,
            avg_win_loss_ratio=2.0,
            confidence=0.7,
        )
        assert result.allowed
        assert result.size_usd > 0
        assert result.size_usd <= 500  # Max position cap
        assert result.risk_reward_ratio >= 1.0

    def test_position_sizing_uses_configurable_rr_threshold(self):
        rm = RiskManager(initial_bankroll=10000, min_risk_reward_ratio=0.9)
        result = rm.calculate_position_size(
            pair="BTC/USD",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=104.6,  # R:R ~= 0.92
            win_rate=0.55,
            avg_win_loss_ratio=1.2,
            confidence=0.7,
        )
        assert result.allowed

    def test_position_sizing_respects_daily_limit(self):
        rm = RiskManager(initial_bankroll=10000, max_daily_loss=0.05)
        # Simulate daily loss exceeding 5% of bankroll
        from datetime import datetime, timezone
        rm._daily_pnl = -600  # Over 5% of 10000
        rm._daily_reset_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        result = rm.calculate_position_size(
            pair="BTC/USD",
            entry_price=50000,
            stop_loss=49000,
            take_profit=52000,
        )
        assert not result.allowed
        assert "Daily loss limit" in result.reason

    def test_stop_loss_tracking(self):
        rm = RiskManager()
        state = rm.initialize_stop_loss("T-123", 50000, 49000, "buy")
        assert state.current_sl == 49000
        assert not state.breakeven_activated

    def test_trailing_stop_activation(self):
        rm = RiskManager(
            breakeven_activation_pct=0.01,
            trailing_activation_pct=0.015,
            trailing_step_pct=0.005,
        )
        rm.initialize_stop_loss("T-123", 50000, 49000, "buy")

        # Price moves up 2% -> should activate trailing
        state = rm.update_stop_loss("T-123", 51000, 50000, "buy")
        assert state.breakeven_activated  # 2% > 1% breakeven threshold
        assert state.current_sl >= 50000  # At least breakeven

    def test_risk_of_ruin_zero_for_no_history(self):
        rm = RiskManager()
        assert rm.calculate_risk_of_ruin() == 0.0

    def test_drawdown_factor_scaling(self):
        rm = RiskManager(initial_bankroll=10000)
        rm._peak_bankroll = 10000

        # No drawdown
        rm.current_bankroll = 10000
        assert rm._get_drawdown_factor() == 1.0

        # 4% drawdown -> 0.80
        rm.current_bankroll = 9600
        assert rm._get_drawdown_factor() == 0.80

        # 8% drawdown -> 0.60
        rm.current_bankroll = 9200
        assert rm._get_drawdown_factor() == 0.60

    def test_partial_reduction_uses_fraction_of_current_exposure(self):
        rm = RiskManager(initial_bankroll=10000)
        rm.register_position("T-partial", "BTC/USD", "buy", 50000, 1000.0)

        rm.reduce_position_size("T-partial", reduction_fraction=0.50)
        assert rm._open_positions["T-partial"]["size_usd"] == pytest.approx(500.0)

        rm.reduce_position_size("T-partial", reduction_fraction=0.60)
        # 60% of remaining 500 leaves 200.
        assert rm._open_positions["T-partial"]["size_usd"] == pytest.approx(200.0)


class TestExecutorHelpers:
    def test_shift_levels_to_fill_preserves_distances(self):
        stop, take = TradeExecutor._shift_levels_to_fill(
            planned_entry=100.0,
            fill_price=102.0,
            stop_loss=95.0,
            take_profit=110.0,
        )
        assert stop == pytest.approx(97.0)
        assert take == pytest.approx(112.0)


# ---- Database Tests ----

class TestDatabase:
    """Test database operations."""

    @pytest.mark.asyncio
    async def test_database_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            db = DatabaseManager(db_path)
            await db.initialize()

            # Insert a trade
            trade_id = await db.insert_trade({
                "trade_id": "T-test-001",
                "pair": "BTC/USD",
                "side": "buy",
                "entry_price": 50000,
                "quantity": 0.001,
                "strategy": "trend",
            })
            assert trade_id > 0

            # Get open trades
            open_trades = await db.get_open_trades()
            assert len(open_trades) == 1
            assert open_trades[0]["trade_id"] == "T-test-001"

            # Close the trade
            await db.close_trade("T-test-001", 51000, 1.0, 0.02)

            # Verify closed
            open_trades = await db.get_open_trades()
            assert len(open_trades) == 0

            history = await db.get_trade_history()
            assert len(history) == 1
            assert history[0]["pnl"] == 1.0

            await db.close()

    @pytest.mark.asyncio
    async def test_thought_log(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            db = DatabaseManager(db_path)
            await db.initialize()

            await db.log_thought("test", "Test thought", "info")
            thoughts = await db.get_thoughts(limit=10)
            assert len(thoughts) == 1
            assert thoughts[0]["message"] == "Test thought"

            await db.close()

    @pytest.mark.asyncio
    async def test_performance_stats(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            db = DatabaseManager(db_path)
            await db.initialize()

            stats = await db.get_performance_stats()
            assert stats["total_trades"] == 0
            assert stats["total_pnl"] == 0.0

            await db.close()

    @pytest.mark.asyncio
    async def test_ml_features_can_be_labeled_for_training(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            db = DatabaseManager(db_path)
            await db.initialize()

            await db.insert_trade({
                "trade_id": "T-test-ml-001",
                "pair": "BTC/USD",
                "side": "buy",
                "entry_price": 50000,
                "quantity": 0.001,
                "strategy": "trend",
            })

            await db.insert_ml_features(
                pair="BTC/USD",
                features={"rsi": 55.0, "ema_ratio": 1.001},
                label=None,
                trade_id="T-test-ml-001",
            )

            assert await db.get_ml_training_data(min_samples=10) == []

            updated = await db.update_ml_label_for_trade("T-test-ml-001", 1.0)
            assert updated == 1

            rows = await db.get_ml_training_data(min_samples=10)
            assert len(rows) == 1
            assert rows[0]["label"] == 1.0
            assert rows[0]["features"]["rsi"] == 55.0

            await db.close()

    @pytest.mark.asyncio
    async def test_order_book_snapshot_insert(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            db = DatabaseManager(db_path)
            await db.initialize()

            await db.insert_order_book_snapshot(
                pair="BTC/USD",
                bid_volume=10.0,
                ask_volume=8.0,
                obi=0.1111,
                spread=0.001,
                whale_detected=0,
                snapshot_data={"bids": [[100.0, 1.0]], "asks": [[101.0, 1.0]]},
                trade_id="T-test-ob-001",
                tenant_id="default",
            )

            # Basic sanity: row exists.
            cur = await db._db.execute("SELECT COUNT(*) FROM order_book_snapshots")
            row = await cur.fetchone()
            assert row[0] == 1

            await db.close()

    @pytest.mark.asyncio
    async def test_count_trades_since(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            db = DatabaseManager(db_path)
            await db.initialize()

            await db.insert_trade(
                {
                    "trade_id": "T-old",
                    "pair": "BTC/USD",
                    "side": "buy",
                    "entry_price": 50000,
                    "quantity": 0.001,
                    "strategy": "trend",
                    "entry_time": "2000-01-01T00:00:00+00:00",
                }
            )
            await db.insert_trade(
                {
                    "trade_id": "T-new",
                    "pair": "BTC/USD",
                    "side": "buy",
                    "entry_price": 50000,
                    "quantity": 0.001,
                    "strategy": "trend",
                    "entry_time": datetime.now(timezone.utc).isoformat(),
                }
            )

            count = await db.count_trades_since(
                since_iso=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
            )
            assert count == 1
            await db.close()

    @pytest.mark.asyncio
    async def test_metrics_are_tenant_scoped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            db = DatabaseManager(db_path)
            await db.initialize()

            await db.insert_metric("scan_cycle_ms", 120.0, tenant_id="tenant_a")
            await db.insert_metric("scan_cycle_ms", 240.0, tenant_id="tenant_b")

            a_rows = await db.get_metrics("scan_cycle_ms", tenant_id="tenant_a")
            b_rows = await db.get_metrics("scan_cycle_ms", tenant_id="tenant_b")

            assert len(a_rows) == 1
            assert len(b_rows) == 1
            assert a_rows[0][1] == pytest.approx(120.0)
            assert b_rows[0][1] == pytest.approx(240.0)

            await db.close()


# ---- Config Tests ----

class TestConfig:
    """Test configuration loading."""

    def test_default_config(self):
        config = BotConfig()
        assert config.app.mode == "paper"
        assert config.risk.max_risk_per_trade == 0.02
        assert config.ai.confluence_threshold == 3
        assert len(config.trading.pairs) > 0

    def test_risk_validation(self):
        """Test that invalid risk values are rejected."""
        with pytest.raises(Exception):
            from src.core.config import RiskConfig
            RiskConfig(max_risk_per_trade=0.50)  # Over 10% should fail


# ---- Runtime Guard Tests ----

class TestRuntimeGuards:
    """Test startup/runtime guard behavior."""

    def test_main_rejects_python_314(self, monkeypatch):
        import main as main_module

        monkeypatch.setattr(main_module.sys, "version_info", (3, 14, 0))
        with pytest.raises(SystemExit) as exc:
            main_module.main()
        assert exc.value.code == 1

    def test_engine_canary_mode_restricts_pairs_and_scan_interval(self):
        from src.core.engine import BotEngine

        cfg = BotConfig(
            trading={
                "pairs": ["BTC/USD", "ETH/USD", "SOL/USD"],
                "scan_interval_seconds": 15,
                "canary_mode": True,
                "canary_pairs": ["ETH/USD", "SOL/USD"],
                "canary_max_pairs": 1,
                "canary_scan_interval_seconds": 45,
            }
        )
        engine = BotEngine(config_override=cfg, enable_dashboard=False)

        assert engine.canary_mode is True
        assert engine.pairs == ["ETH/USD"]
        assert engine.scan_interval == 45


# ---- API Tenant/Auth Tests ----

class _FakeDB:
    def __init__(self, api_key_map=None, tenants=None):
        self._api_key_map = api_key_map or {}
        self._tenants = tenants or {}

    async def get_tenant_id_by_api_key(self, api_key: str):
        return self._api_key_map.get(api_key)

    async def get_tenant(self, tenant_id: str):
        return self._tenants.get(tenant_id)


class _FakeEngine:
    def __init__(self, api_secret: str, db: _FakeDB, default_tenant_id: str = "default"):
        self.db = db
        self.config = type("Cfg", (), {})()
        self.config.billing = type("Billing", (), {})()
        self.config.billing.tenant = type("Tenant", (), {})()
        self.config.billing.tenant.default_tenant_id = default_tenant_id
        self._api_secret = api_secret


class TestApiTenantAuth:
    @pytest.mark.asyncio
    async def test_resolve_tenant_mismatch_rejected(self):
        from src.api.server import DashboardServer

        server = DashboardServer()
        api_secret = "ADMIN"
        server._api_secret = api_secret

        db = _FakeDB(api_key_map={"TENANTKEY": "t1"}, tenants={"t1": {"status": "active"}})
        eng = _FakeEngine(api_secret, db, default_tenant_id="default")
        server._bot_engine = eng

        with pytest.raises(HTTPException) as exc:
            await server.resolve_tenant_id(requested_tenant_id="t2", api_key="TENANTKEY")
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_resolve_tenant_inactive_rejected(self):
        from src.api.server import DashboardServer

        server = DashboardServer()
        api_secret = "ADMIN"
        server._api_secret = api_secret

        db = _FakeDB(api_key_map={"TENANTKEY": "t1"}, tenants={"t1": {"status": "past_due"}})
        eng = _FakeEngine(api_secret, db, default_tenant_id="default")
        server._bot_engine = eng

        with pytest.raises(HTTPException) as exc:
            await server.resolve_tenant_id(requested_tenant_id="", api_key="TENANTKEY")
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_resolve_tenant_requires_api_key_when_strict(self):
        from src.api.server import DashboardServer

        server = DashboardServer()
        api_secret = "ADMIN"
        server._api_secret = api_secret

        db = _FakeDB(api_key_map={"TENANTKEY": "t1"}, tenants={"t1": {"status": "active"}})
        eng = _FakeEngine(api_secret, db, default_tenant_id="default")
        server._bot_engine = eng

        with pytest.raises(HTTPException) as exc:
            await server.resolve_tenant_id(requested_tenant_id="", api_key="", require_api_key=True)
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_resolve_tenant_invalid_key_rejected_when_strict(self):
        from src.api.server import DashboardServer

        server = DashboardServer()
        api_secret = "ADMIN"
        server._api_secret = api_secret

        db = _FakeDB(api_key_map={"TENANTKEY": "t1"}, tenants={"t1": {"status": "active"}})
        eng = _FakeEngine(api_secret, db, default_tenant_id="default")
        server._bot_engine = eng

        with pytest.raises(HTTPException) as exc:
            await server.resolve_tenant_id(requested_tenant_id="", api_key="NOPE", require_api_key=True)
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_resolve_tenant_checks_all_engine_dbs(self):
        from src.api.server import DashboardServer

        server = DashboardServer()
        db1 = _FakeDB(api_key_map={"TENANTKEY_A": "tenant_a"}, tenants={"tenant_a": {"status": "active"}})
        db2 = _FakeDB(api_key_map={"TENANTKEY_B": "tenant_b"}, tenants={"tenant_b": {"status": "active"}})
        eng1 = _FakeEngine("ADMIN", db1, default_tenant_id="default")
        eng2 = _FakeEngine("ADMIN", db2, default_tenant_id="default")
        hub = type("Hub", (), {"engines": [eng1, eng2], "config": eng1.config, "db": eng1.db})()
        server._bot_engine = hub

        tenant = await server.resolve_tenant_id(
            requested_tenant_id="",
            api_key="TENANTKEY_B",
            require_api_key=True,
        )
        assert tenant == "tenant_b"


class _FakeTradeDB:
    async def get_tenant_id_by_api_key(self, api_key: str):
        return None

    async def get_tenant(self, tenant_id: str):
        return None

    async def get_trade_history(self, limit: int = 100, tenant_id: str = "default"):
        return [
            {
                "id": 1,
                "pair": "BTC/USD",
                "side": "buy",
                "status": "closed",
                "entry_time": "2026-02-14T00:00:00Z",
                "exit_time": "2026-02-14T00:10:00Z",
                "entry_price": 100.0,
                "exit_price": 110.0,
                "quantity": 1.0,
                "size_usd": 100.0,
                "pnl": 9.0,
                "pnl_pct": 0.09,
                "stop_loss": 90.0,
                "take_profit": 120.0,
                "confidence": 0.7,
                "strategy": "trend",
                "reason": "test",
                "metadata": "{}",
            }
        ]


class _FakeCfgForExport:
    def __init__(self):
        self.app = type("App", (), {"mode": "paper"})()
        self.dashboard = type(
            "Dash",
            (),
            {
                "require_api_key_for_reads": True,
                "rate_limit_enabled": True,
                "rate_limit_requests_per_minute": 240,
                "rate_limit_burst": 60,
            },
        )()
        self.billing = type("Billing", (), {})()
        self.billing.tenant = type("Tenant", (), {"default_tenant_id": "default"})()


class _FakeEngineForExport:
    def __init__(self):
        self.db = _FakeTradeDB()
        self.config = _FakeCfgForExport()


class _FakeMarketDataForChart:
    def __init__(self):
        base = 1_700_000_000
        self._times = np.array([base + i * 60 for i in range(360)], dtype=float)
        base_px = 50_000.0
        self._opens = np.array([base_px + i * 0.8 for i in range(360)], dtype=float)
        self._highs = self._opens + 5.0
        self._lows = self._opens - 5.0
        self._closes = self._opens + 1.2
        self._volumes = np.array([10.0 + (i % 5) for i in range(360)], dtype=float)

    def _slice(self, arr, n=None):
        if n is None:
            return arr
        return arr[-int(n):]

    def get_times(self, pair: str, n=None):
        return self._slice(self._times, n)

    def get_opens(self, pair: str, n=None):
        return self._slice(self._opens, n)

    def get_highs(self, pair: str, n=None):
        return self._slice(self._highs, n)

    def get_lows(self, pair: str, n=None):
        return self._slice(self._lows, n)

    def get_closes(self, pair: str, n=None):
        return self._slice(self._closes, n)

    def get_volumes(self, pair: str, n=None):
        return self._slice(self._volumes, n)


class _FakeEngineForChart:
    def __init__(self):
        self.db = _FakeTradeDB()
        self.config = _FakeCfgForExport()
        self.market_data = _FakeMarketDataForChart()
        self.exchange_name = "kraken"
        self.pairs = ["BTC/USD"]


class _FakeRestClientForChart:
    async def get_ohlc(self, pair: str, interval: int = 1, since: int | None = None):
        step = max(1, int(interval)) * 60
        start = int(since or (time.time() - (500 * step)))
        bars = []
        px = 40_000.0
        for i in range(520):
            ts = start + (i * step)
            o = px + (i * 2.0)
            h = o + 8.0
            low = o - 8.0
            c = o + 1.5
            v = 50.0 + (i % 10)
            bars.append([float(ts), o, h, low, c, 0.0, v, 1.0])
        return bars


class _FakeEngineForChartWithRest(_FakeEngineForChart):
    def __init__(self):
        super().__init__()
        self.rest_client = _FakeRestClientForChart()


class TestApiExports:
    def test_export_trades_csv_requires_key_and_returns_csv(self):
        from src.api.server import DashboardServer

        server = DashboardServer()
        server._admin_key = "ADMIN"
        server._bot_engine = _FakeEngineForExport()

        client = TestClient(server.app)
        r = client.get("/api/v1/export/trades.csv", headers={"X-API-Key": "ADMIN"})
        assert r.status_code == 200
        assert "text/csv" in r.headers.get("content-type", "")
        body = r.text
        assert "id,pair,side" in body.splitlines()[0]
        assert "BTC/USD" in body


class TestApiChart:
    def test_chart_endpoint_returns_aggregated_candles(self):
        from src.api.server import DashboardServer

        server = DashboardServer()
        server._admin_key = "ADMIN"
        server._bot_engine = _FakeEngineForChart()

        client = TestClient(server.app)
        r = client.get(
            "/api/v1/chart",
            params={"pair": "BTC/USD", "timeframe": "5m", "limit": 120},
            headers={"X-API-Key": "ADMIN"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body.get("pair") == "BTC/USD"
        assert body.get("timeframe") == "5m"
        assert body.get("source") == "cache"
        assert isinstance(body.get("candles"), list)
        assert len(body["candles"]) > 0
        first = body["candles"][0]
        assert {"time", "open", "high", "low", "close", "volume"} <= set(first.keys())

    def test_chart_endpoint_normalizes_timeframe_alias(self):
        from src.api.server import DashboardServer

        server = DashboardServer()
        server._admin_key = "ADMIN"
        server._bot_engine = _FakeEngineForChart()

        client = TestClient(server.app)
        r = client.get(
            "/api/v1/chart",
            params={"pair": "BTC/USD", "timeframe": "1H"},
            headers={"X-API-Key": "ADMIN"},
        )
        assert r.status_code == 200
        assert r.json().get("timeframe") == "1h"

    def test_chart_endpoint_uses_rest_history_for_daily_timeframe(self):
        from src.api.server import DashboardServer

        server = DashboardServer()
        server._admin_key = "ADMIN"
        server._bot_engine = _FakeEngineForChartWithRest()

        client = TestClient(server.app)
        r = client.get(
            "/api/v1/chart",
            params={"pair": "BTC/USD", "timeframe": "1d", "limit": 120},
            headers={"X-API-Key": "ADMIN"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body.get("timeframe") == "1d"
        assert body.get("source") == "rest"
        assert isinstance(body.get("candles"), list)
        assert len(body.get("candles", [])) >= 100


class TestApiMiddleware:
    def test_security_headers_present(self):
        from src.api.server import DashboardServer

        server = DashboardServer()
        server._admin_key = "ADMIN"
        server._bot_engine = _FakeEngineForExport()

        client = TestClient(server.app)
        r = client.get("/api/v1/health")
        assert r.status_code == 200
        assert r.headers.get("x-content-type-options") == "nosniff"
        assert r.headers.get("x-frame-options") == "DENY"
        assert "content-security-policy" in {k.lower(): v for k, v in r.headers.items()}

    def test_rate_limiting_blocks_excess_requests(self):
        from src.api.server import DashboardServer

        server = DashboardServer()
        server._admin_key = "ADMIN"
        eng = _FakeEngineForExport()
        # Tight limits for the test
        eng.config.dashboard.rate_limit_enabled = True
        eng.config.dashboard.rate_limit_requests_per_minute = 1
        eng.config.dashboard.rate_limit_burst = 1
        server._bot_engine = eng

        client = TestClient(server.app)
        h = {"X-API-Key": "ADMIN"}
        r1 = client.get("/api/v1/status", headers=h)
        r2 = client.get("/api/v1/status", headers=h)
        assert r1.status_code == 200
        assert r2.status_code == 429


# ---- ML Pipeline Consistency Tests ----

class TestMLPipeline:
    """Test ML feature ordering and normalization consistency."""

    def test_predictor_normalization_order_mapping(self, tmp_path):
        norm_path = tmp_path / "normalization.json"
        norm_path.write_text(
            json.dumps({
                "feature_names": ["a", "b"],
                "mean": [0.0, 0.0],
                "std": [1.0, 1.0],
            })
        )

        features = TradePredictorFeatures(feature_names=["b", "a"])
        assert features.load_normalization(str(norm_path))

        vec = features.extract({"a": 1.0, "b": 2.0})
        # Normalization order is ["a","b"], so vector should be [1,2]
        assert np.allclose(vec, np.array([1.0, 2.0], dtype=np.float32))

    def test_trainer_feature_ordering(self, tmp_path):
        trainer = ModelTrainer(
            db=None,
            model_dir=str(tmp_path),
            feature_names=["a", "b"],
        )
        training_data = [
            {"features": {"b": 100.0, "a": 1.0}, "label": 1.0},
            {"features": {"b": 130.0, "a": 2.0}, "label": 0.0},
            {"features": {"b": 200.0, "a": 10.0}, "label": 1.0},
        ]

        X_train, y_train, X_val, y_val = trainer._prepare_data(training_data)
        assert X_train is not None
        assert y_train is not None

        norm = json.loads((tmp_path / "normalization.json").read_text())
        mean = np.array(norm["mean"], dtype=np.float32)
        std = np.array(norm["std"], dtype=np.float32)
        raw_recon = (X_train * std) + mean

        expected = np.array([
            [1.0, 100.0],
            [2.0, 130.0],
            [10.0, 200.0],
        ], dtype=np.float32)
        # Split/shuffle order is not guaranteed; validate values regardless of row order.
        raw_sorted = raw_recon[np.argsort(raw_recon[:, 0])]
        expected_sorted = expected[np.argsort(expected[:, 0])]
        assert np.allclose(raw_sorted, expected_sorted, atol=1e-5)


# ---- Vault Tests ----

class TestVault:
    """Test secure vault envelope handling."""

    def test_vault_checksum_mismatch_rejected(self, tmp_path):
        from src.core.vault import SecureVault

        vault_path = tmp_path / "vault.enc"
        v = SecureVault(vault_path=str(vault_path))
        v.initialize("pw")
        v.set("k", "v")

        env = json.loads(vault_path.read_text())
        env["checksum"] = "0" * len(env.get("checksum") or "0" * 16)
        vault_path.write_text(json.dumps(env, indent=2))

        v2 = SecureVault(vault_path=str(vault_path))
        with pytest.raises(ValueError):
            v2.initialize("pw")


# ---- Telegram Check-in Tests ----

class _FakePerfDB:
    async def get_performance_stats(self, tenant_id: str = "default"):
        return {
            "open_positions": 2,
            "total_trades": 10,
            "win_rate": 0.6,
            "total_pnl": 123.45,
            "today_pnl": -12.34,
        }


class _FakeWS:
    is_connected = True


class _FakeBotEngineForTelegram:
    def __init__(self):
        self.mode = "paper"
        self._trading_paused = False
        self._running = True
        self._start_time = time.time() - 1234
        self.ws_client = _FakeWS()
        self.db = _FakePerfDB()
        self.tenant_id = "default"


class TestTelegramCheckins:
    @pytest.mark.asyncio
    async def test_telegram_checkin_message_builds(self):
        from src.utils.telegram import TelegramBot

        bot = TelegramBot(token="t", chat_ids=["1"])
        bot.set_bot_engine(_FakeBotEngineForTelegram())
        msg = await bot._build_checkin_message()
        assert "Bot Check-in" in msg
        assert "Total Trades" in msg

    def test_telegram_secrets_dir_fallback(self, tmp_path, monkeypatch):
        from src.utils.telegram import TelegramBot

        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CHAT_IDS", raising=False)
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

        sec = tmp_path / ".secrets"
        sec.mkdir()
        (sec / "telegram_token").write_text("TOK\n")
        (sec / "telegram_chat_id").write_text("123\n")

        bot = TelegramBot(token="", chat_ids=None, secrets_dir=str(sec))
        assert bot.token == "TOK"
        assert bot.chat_ids == ["123"]


class TestLoggingSafety:
    def test_setup_logging_silences_httpx(self, tmp_path, monkeypatch):
        import logging

        from src.core.logger import setup_logging

        monkeypatch.chdir(tmp_path)
        setup_logging(log_level="INFO", log_dir="logs")
        assert logging.getLogger("httpx").level >= logging.WARNING


# ---- Circuit Breaker Tests ----

class _FakeDBForPause:
    def __init__(self):
        self.thoughts = []

    async def log_thought(self, *args, **kwargs):
        self.thoughts.append({"args": args, "kwargs": kwargs})


class _FakeTelegramForPause:
    def __init__(self):
        self.messages = []

    async def send_message(self, text: str, parse_mode: str = "Markdown"):
        self.messages.append(text)


class _FakeWSClient:
    def __init__(self, is_connected: bool):
        self.is_connected = is_connected


class TestCircuitBreakers:
    @pytest.mark.asyncio
    async def test_auto_pause_on_stale_data(self):
        from src.core.engine import BotEngine

        eng = BotEngine(enable_dashboard=False)
        eng._running = True
        eng.db = _FakeDBForPause()
        eng.telegram_bot = _FakeTelegramForPause()
        eng.config.monitoring.stale_data_pause_after_checks = 1

        await eng._apply_circuit_breakers(["BTC/USD"])
        assert eng._trading_paused is True
        assert len(eng.db.thoughts) >= 1
        assert any("AUTO-PAUSE" in m or "AUTO-PAUSED" in m for m in eng.telegram_bot.messages)

    @pytest.mark.asyncio
    async def test_auto_pause_on_ws_disconnect(self):
        from src.core.engine import BotEngine

        eng = BotEngine(enable_dashboard=False)
        eng._running = True
        eng.db = _FakeDBForPause()
        eng.telegram_bot = _FakeTelegramForPause()
        eng.ws_client = _FakeWSClient(is_connected=False)
        eng.config.monitoring.ws_disconnect_pause_after_seconds = 1
        eng._ws_disconnected_since = time.time() - 10

        await eng._apply_circuit_breakers([])
        assert eng._trading_paused is True
