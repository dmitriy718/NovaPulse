"""Tests for Feature 7: Anomaly Detection and Protective Circuit Breaker."""

from __future__ import annotations

import time
from collections import deque
from unittest.mock import MagicMock, patch

import pytest

from src.execution.anomaly_detector import AnomalyDetector
from src.core.config import BotConfig, MonitoringConfig, AnomalyDetectorConfig


class TestAnomalyDetectorUnit:
    def _make_detector(self, **kwargs) -> AnomalyDetector:
        defaults = {
            "spread_threshold_mult": 3.0,
            "volume_threshold_mult": 5.0,
            "correlation_threshold": 0.60,
            "depth_drop_threshold": 0.50,
            "pause_seconds": 300,
            "min_history_samples": 5,  # Low for tests
        }
        defaults.update(kwargs)
        return AnomalyDetector(**defaults)

    def test_spread_anomaly_detected(self):
        det = self._make_detector(min_history_samples=5)
        for _ in range(10):
            det.update_spread("BTC/USD", 0.001)
        result = det.check_spread_anomaly("BTC/USD", 0.005)  # 5x avg
        assert result is not None
        assert "Spread anomaly" in result

    def test_spread_normal_no_anomaly(self):
        det = self._make_detector(min_history_samples=5)
        for _ in range(10):
            det.update_spread("BTC/USD", 0.001)
        result = det.check_spread_anomaly("BTC/USD", 0.002)  # 2x avg, below 3x threshold
        assert result is None

    def test_volume_anomaly_without_price_move(self):
        det = self._make_detector(min_history_samples=5)
        for _ in range(10):
            det.update_volume("BTC/USD", 1000)
        result = det.check_volume_anomaly("BTC/USD", 6000, price_change_pct=0.001)
        assert result is not None
        assert "Volume anomaly" in result

    def test_volume_spike_with_price_move_ok(self):
        det = self._make_detector(min_history_samples=5)
        for _ in range(10):
            det.update_volume("BTC/USD", 1000)
        result = det.check_volume_anomaly("BTC/USD", 6000, price_change_pct=0.02)  # 2% move = legitimate
        assert result is None

    def test_correlation_anomaly_majority_same_direction(self):
        det = self._make_detector()
        directions = {"BTC/USD": "long", "ETH/USD": "long", "SOL/USD": "long", "XRP/USD": "short"}
        result = det.check_correlation_anomaly(directions)  # 75% same direction
        assert result is not None
        assert "Correlation anomaly" in result

    def test_correlation_mixed_ok(self):
        det = self._make_detector()
        directions = {"BTC/USD": "long", "ETH/USD": "short", "SOL/USD": "long", "XRP/USD": "short"}
        result = det.check_correlation_anomaly(directions)  # 50/50 split
        assert result is None

    def test_depth_drop_anomaly(self):
        det = self._make_detector(min_history_samples=5)
        for _ in range(10):
            det.update_depth("BTC/USD", 100000)
        result = det.check_depth_anomaly("BTC/USD", 30000)  # 70% drop
        assert result is not None
        assert "Depth anomaly" in result

    def test_depth_stable_ok(self):
        det = self._make_detector(min_history_samples=5)
        for _ in range(10):
            det.update_depth("BTC/USD", 100000)
        result = det.check_depth_anomaly("BTC/USD", 80000)  # 20% drop, below 50% threshold
        assert result is None

    def test_cooldown_prevents_repeated_pauses(self):
        det = self._make_detector(pause_seconds=60, min_history_samples=5)
        # Trigger an anomaly
        for _ in range(10):
            det.update_spread("BTC/USD", 0.001)
        md = MagicMock()
        md.get_spread.return_value = 0.005
        md.get_order_book.return_value = {}
        det.run_all_checks(md, ["BTC/USD"])
        assert det.is_paused()
        # Record the pause time
        first_until = det._paused_until
        # Running again shouldn't extend the pause
        det.run_all_checks(md, ["BTC/USD"])
        # Paused_until should not be re-set (stays the same)
        assert det._paused_until == first_until

    def test_anomaly_log_records_events(self):
        det = self._make_detector(min_history_samples=5)
        for _ in range(10):
            det.update_spread("BTC/USD", 0.001)
        md = MagicMock()
        md.get_spread.return_value = 0.005
        md.get_order_book.return_value = {}
        det.run_all_checks(md, ["BTC/USD"])
        log = det.get_anomaly_log()
        assert len(log) >= 1

    def test_min_history_requirement(self):
        det = self._make_detector(min_history_samples=20)
        # Only add 5 samples (below 20 minimum)
        for _ in range(5):
            det.update_spread("BTC/USD", 0.001)
        result = det.check_spread_anomaly("BTC/USD", 0.010)  # 10x but insufficient history
        assert result is None


class TestAnomalyDetectorIntegration:
    def test_anomaly_detector_disabled_by_config(self):
        cfg = AnomalyDetectorConfig(enabled=False)
        assert cfg.enabled is False

    def test_config_parses_anomaly_detector(self):
        cfg = BotConfig(monitoring={"anomaly_detector": {"enabled": True, "pause_seconds": 600}})
        assert cfg.monitoring.anomaly_detector.enabled is True
        assert cfg.monitoring.anomaly_detector.pause_seconds == 600

    def test_engine_continues_without_anomaly(self):
        det = AnomalyDetector(min_history_samples=5)
        assert not det.is_paused()
        # No data -> no anomalies -> not paused
        md = MagicMock()
        md.get_spread.return_value = 0.001
        md.get_order_book.return_value = {}
        anomalies = det.run_all_checks(md, ["BTC/USD"])
        assert len(anomalies) == 0
        assert not det.is_paused()

    def test_engine_pauses_on_anomaly(self):
        det = AnomalyDetector(min_history_samples=5, pause_seconds=60)
        for _ in range(10):
            det.update_spread("BTC/USD", 0.001)
        md = MagicMock()
        md.get_spread.return_value = 0.005
        md.get_order_book.return_value = {}
        anomalies = det.run_all_checks(md, ["BTC/USD"])
        assert len(anomalies) > 0
        assert det.is_paused()
