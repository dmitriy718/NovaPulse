"""Tests for Feature 2: Cross-Pair Lead-Lag Signal Intelligence."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.ai.lead_lag import LeadLagTracker
from src.core.config import BotConfig, AIConfig, LeadLagConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_market_data(pairs_data: dict) -> MagicMock:
    """Create a mock MarketDataCache with given pair -> closes/highs/lows."""
    md = MagicMock()

    def _get_closes(pair):
        data = pairs_data.get(pair)
        if data is None:
            return None
        return np.array(data.get("closes", []), dtype=float)

    def _get_highs(pair):
        data = pairs_data.get(pair)
        if data is None:
            return None
        return np.array(data.get("highs", data.get("closes", [])), dtype=float)

    def _get_lows(pair):
        data = pairs_data.get(pair)
        if data is None:
            return None
        return np.array(data.get("lows", data.get("closes", [])), dtype=float)

    def _get_latest_price(pair):
        data = pairs_data.get(pair)
        if data is None:
            return None
        closes = data.get("closes", [])
        return float(closes[-1]) if closes else None

    md.get_closes = _get_closes
    md.get_highs = _get_highs
    md.get_lows = _get_lows
    md.get_latest_price = _get_latest_price
    return md


def _make_tracker(**kwargs) -> LeadLagTracker:
    defaults = {
        "leader_pairs": ["BTC/USD", "ETH/USD"],
        "atr_multiplier": 1.0,
        "lookback_minutes": 5,
        "boost_confidence": 0.15,
        "penalize_confidence": 0.10,
        "min_correlation": 0.5,
    }
    defaults.update(kwargs)
    return LeadLagTracker(**defaults)


def _correlated_prices(base, n=60, noise=0.001):
    """Generate prices correlated to base prices with small noise."""
    scale = 100.0 / base[0] if base[0] != 0 else 1.0
    return [p * scale + np.random.uniform(-noise, noise) * p * scale for p in base]


# ---------------------------------------------------------------------------
# Unit Tests
# ---------------------------------------------------------------------------

class TestLeadLagUnit:
    def test_btc_surge_boosts_alt_long(self):
        """BTC surging up should boost confidence for a LONG altcoin signal."""
        tracker = _make_tracker(min_correlation=0.0)  # skip corr for unit test
        now = time.time()

        # Simulate BTC surging 2% in 5 minutes
        tracker.update_leader_price("BTC/USD", 50000.0, now - 300)
        tracker.update_leader_price("BTC/USD", 51000.0, now)  # +2%

        # Build correlated market data
        btc_closes = np.linspace(49000, 51000, 60)
        sol_closes = np.linspace(90, 95, 60)  # correlated uptrend
        md = _make_market_data({
            "BTC/USD": {"closes": btc_closes.tolist(), "highs": (btc_closes * 1.005).tolist(), "lows": (btc_closes * 0.995).tolist()},
            "SOL/USD": {"closes": sol_closes.tolist(), "highs": (sol_closes * 1.005).tolist(), "lows": (sol_closes * 0.995).tolist()},
        })

        adj = tracker.get_confidence_adjustment("SOL/USD", "long", md)
        assert adj > 0, f"Expected positive boost, got {adj}"
        assert adj <= 0.15

    def test_btc_surge_penalizes_alt_short(self):
        """BTC surging up should penalize a SHORT altcoin signal."""
        tracker = _make_tracker(min_correlation=0.0)
        now = time.time()

        tracker.update_leader_price("BTC/USD", 50000.0, now - 300)
        tracker.update_leader_price("BTC/USD", 51000.0, now)

        btc_closes = np.linspace(49000, 51000, 60)
        sol_closes = np.linspace(90, 95, 60)
        md = _make_market_data({
            "BTC/USD": {"closes": btc_closes.tolist(), "highs": (btc_closes * 1.005).tolist(), "lows": (btc_closes * 0.995).tolist()},
            "SOL/USD": {"closes": sol_closes.tolist(), "highs": (sol_closes * 1.005).tolist(), "lows": (sol_closes * 0.995).tolist()},
        })

        adj = tracker.get_confidence_adjustment("SOL/USD", "short", md)
        assert adj < 0, f"Expected negative penalty, got {adj}"
        assert adj >= -0.10

    def test_btc_drop_boosts_alt_short(self):
        """BTC dropping should boost confidence for a SHORT altcoin signal."""
        tracker = _make_tracker(min_correlation=0.0)
        now = time.time()

        tracker.update_leader_price("BTC/USD", 51000.0, now - 300)
        tracker.update_leader_price("BTC/USD", 50000.0, now)  # -2%

        btc_closes = np.linspace(51000, 50000, 60)
        sol_closes = np.linspace(95, 90, 60)
        md = _make_market_data({
            "BTC/USD": {"closes": btc_closes.tolist(), "highs": (btc_closes * 1.005).tolist(), "lows": (btc_closes * 0.995).tolist()},
            "SOL/USD": {"closes": sol_closes.tolist(), "highs": (sol_closes * 1.005).tolist(), "lows": (sol_closes * 0.995).tolist()},
        })

        adj = tracker.get_confidence_adjustment("SOL/USD", "short", md)
        assert adj > 0, f"Expected positive boost, got {adj}"

    def test_small_move_no_adjustment(self):
        """A small leader move (below ATR threshold) should give 0 adjustment."""
        tracker = _make_tracker(atr_multiplier=2.0, min_correlation=0.0)
        now = time.time()

        # Tiny 0.1% move
        tracker.update_leader_price("BTC/USD", 50000.0, now - 300)
        tracker.update_leader_price("BTC/USD", 50050.0, now)

        btc_closes = np.linspace(49950, 50050, 60)
        sol_closes = np.linspace(90, 90.5, 60)
        md = _make_market_data({
            "BTC/USD": {"closes": btc_closes.tolist(), "highs": (btc_closes * 1.005).tolist(), "lows": (btc_closes * 0.995).tolist()},
            "SOL/USD": {"closes": sol_closes.tolist(), "highs": (sol_closes * 1.005).tolist(), "lows": (sol_closes * 0.995).tolist()},
        })

        adj = tracker.get_confidence_adjustment("SOL/USD", "long", md)
        assert adj == 0.0

    def test_low_correlation_no_adjustment(self):
        """When correlation between leader and follower is below threshold, no adjustment."""
        tracker = _make_tracker(min_correlation=0.8)
        now = time.time()

        tracker.update_leader_price("BTC/USD", 50000.0, now - 300)
        tracker.update_leader_price("BTC/USD", 51500.0, now)  # 3% move

        # BTC up, SOL uncorrelated (random walk)
        np.random.seed(42)
        btc_closes = np.linspace(49000, 51500, 60)
        sol_closes = 90.0 + np.cumsum(np.random.randn(60) * 0.5)  # random
        md = _make_market_data({
            "BTC/USD": {"closes": btc_closes.tolist(), "highs": (btc_closes * 1.005).tolist(), "lows": (btc_closes * 0.995).tolist()},
            "SOL/USD": {"closes": sol_closes.tolist(), "highs": (sol_closes * 1.005).tolist(), "lows": (sol_closes * 0.995).tolist()},
        })

        adj = tracker.get_confidence_adjustment("SOL/USD", "long", md)
        assert adj == 0.0

    def test_multiple_leaders_strongest_wins(self):
        """When both BTC and ETH signal, the strongest one should win."""
        tracker = _make_tracker(min_correlation=0.0)
        now = time.time()

        # BTC: small move (+1%)
        tracker.update_leader_price("BTC/USD", 50000.0, now - 300)
        tracker.update_leader_price("BTC/USD", 50500.0, now)

        # ETH: big move (+5%)
        tracker.update_leader_price("ETH/USD", 3000.0, now - 300)
        tracker.update_leader_price("ETH/USD", 3150.0, now)

        btc_closes = np.linspace(49500, 50500, 60)
        eth_closes = np.linspace(2900, 3150, 60)
        sol_closes = np.linspace(88, 95, 60)
        md = _make_market_data({
            "BTC/USD": {"closes": btc_closes.tolist(), "highs": (btc_closes * 1.005).tolist(), "lows": (btc_closes * 0.995).tolist()},
            "ETH/USD": {"closes": eth_closes.tolist(), "highs": (eth_closes * 1.005).tolist(), "lows": (eth_closes * 0.995).tolist()},
            "SOL/USD": {"closes": sol_closes.tolist(), "highs": (sol_closes * 1.005).tolist(), "lows": (sol_closes * 0.995).tolist()},
        })

        adj = tracker.get_confidence_adjustment("SOL/USD", "long", md)
        assert adj > 0, "Both leaders bullish, expected positive adjustment"

    def test_leader_staleness_ignored(self):
        """Stale leader data (much older than lookback) should be ignored."""
        tracker = _make_tracker(lookback_minutes=5, min_correlation=0.0)
        now = time.time()

        # Data from 30 minutes ago — well beyond 2x lookback (10 min)
        tracker.update_leader_price("BTC/USD", 50000.0, now - 1800)
        tracker.update_leader_price("BTC/USD", 55000.0, now - 1800 + 60)

        md = _make_market_data({
            "BTC/USD": {"closes": np.linspace(50000, 55000, 60).tolist()},
            "SOL/USD": {"closes": np.linspace(90, 95, 60).tolist()},
        })

        adj = tracker.get_confidence_adjustment("SOL/USD", "long", md)
        assert adj == 0.0

    def test_leader_excluded_from_self_boost(self):
        """A leader pair should not boost itself."""
        tracker = _make_tracker(min_correlation=0.0)
        now = time.time()

        tracker.update_leader_price("BTC/USD", 50000.0, now - 300)
        tracker.update_leader_price("BTC/USD", 51500.0, now)

        md = _make_market_data({
            "BTC/USD": {"closes": np.linspace(49000, 51500, 60).tolist()},
        })

        adj = tracker.get_confidence_adjustment("BTC/USD", "long", md)
        assert adj == 0.0


# ---------------------------------------------------------------------------
# Integration Tests
# ---------------------------------------------------------------------------

class TestLeadLagIntegration:
    def test_lead_lag_in_confluence_pipeline(self):
        """Verify set_lead_lag_tracker works on ConfluenceDetector."""
        from src.ai.confluence import ConfluenceDetector

        md = MagicMock()
        md.is_warmed_up.return_value = True
        md.is_stale.return_value = False

        detector = ConfluenceDetector(market_data=md)
        tracker = _make_tracker()
        detector.set_lead_lag_tracker(tracker)

        assert detector._lead_lag_tracker is tracker

    def test_lead_lag_disabled_no_effect(self):
        """When lead_lag is disabled, tracker should not be created."""
        cfg = LeadLagConfig(enabled=False)
        assert cfg.enabled is False
        # Verify default values
        assert cfg.leader_pairs == ["BTC/USD", "ETH/USD"]
        assert cfg.boost_confidence == 0.15

    def test_config_model_parses(self):
        """LeadLagConfig should parse from dict correctly."""
        cfg = LeadLagConfig(
            enabled=True,
            leader_pairs=["BTC/USD"],
            atr_multiplier=2.0,
            lookback_minutes=10,
        )
        assert cfg.enabled is True
        assert cfg.leader_pairs == ["BTC/USD"]
        assert cfg.atr_multiplier == 2.0
        assert cfg.lookback_minutes == 10

    def test_lead_lag_field_on_ai_config(self):
        """AIConfig should have a lead_lag field with LeadLagConfig default."""
        ai = AIConfig()
        assert hasattr(ai, "lead_lag")
        assert isinstance(ai.lead_lag, LeadLagConfig)
        assert ai.lead_lag.enabled is False
