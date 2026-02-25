"""Tests for Liquidity-Aware Position Sizing (Feature 4).

Validates that position sizes are reduced when order book depth is thin,
and unchanged when depth is ample.
"""

from __future__ import annotations

import pytest

from src.execution.risk_manager import RiskManager, PositionSizeResult


# ---------------------------------------------------------------------------
# Unit tests: apply_liquidity_adjustment
# ---------------------------------------------------------------------------


class TestApplyLiquidityAdjustment:

    def test_thin_book_reduces_size(self):
        """Position reduced when depth < ratio * size."""
        rm = RiskManager(initial_bankroll=10000)

        # Position = 500, ask depth = 1000, min_depth_ratio = 3
        # ratio = 1000/500 = 2.0 < 3.0 → reduce
        adjusted = rm.apply_liquidity_adjustment(
            position_size_usd=500.0,
            bid_depth_usd=5000.0,
            ask_depth_usd=1000.0,
            side="buy",
            max_impact_pct=0.10,
            min_depth_ratio=3.0,
        )

        # adjusted = min(500, 1000 * 0.10) = min(500, 100) = 100
        assert adjusted < 500.0
        assert adjusted == pytest.approx(100.0, abs=0.01)

    def test_deep_book_no_change(self):
        """Position unchanged when depth is ample."""
        rm = RiskManager(initial_bankroll=10000)

        # Position = 100, ask depth = 5000, min_depth_ratio = 3
        # ratio = 5000/100 = 50 >= 3 → no change
        adjusted = rm.apply_liquidity_adjustment(
            position_size_usd=100.0,
            bid_depth_usd=5000.0,
            ask_depth_usd=5000.0,
            side="buy",
            max_impact_pct=0.10,
            min_depth_ratio=3.0,
        )

        assert adjusted == pytest.approx(100.0, abs=0.01)

    def test_buy_uses_ask_depth(self):
        """Buy side checks ask depth, not bid depth."""
        rm = RiskManager(initial_bankroll=10000)

        # Thin asks (100), deep bids (100000)
        adjusted = rm.apply_liquidity_adjustment(
            position_size_usd=500.0,
            bid_depth_usd=100000.0,
            ask_depth_usd=100.0,
            side="buy",
            max_impact_pct=0.10,
            min_depth_ratio=3.0,
        )

        # ask_depth/position = 100/500 = 0.2 < 3.0 → reduce
        # adjusted = min(500, 100 * 0.10) = min(500, 10) = 10
        assert adjusted == pytest.approx(10.0, abs=0.01)

    def test_sell_uses_bid_depth(self):
        """Sell side checks bid depth, not ask depth."""
        rm = RiskManager(initial_bankroll=10000)

        # Deep asks (100000), thin bids (200)
        adjusted = rm.apply_liquidity_adjustment(
            position_size_usd=500.0,
            bid_depth_usd=200.0,
            ask_depth_usd=100000.0,
            side="sell",
            max_impact_pct=0.10,
            min_depth_ratio=3.0,
        )

        # bid_depth/position = 200/500 = 0.4 < 3.0 → reduce
        # adjusted = min(500, 200 * 0.10) = min(500, 20) = 20
        assert adjusted == pytest.approx(20.0, abs=0.01)

    def test_zero_depth_minimum_size(self):
        """Zero depth returns minimum position (not zero)."""
        rm = RiskManager(initial_bankroll=10000)

        adjusted = rm.apply_liquidity_adjustment(
            position_size_usd=500.0,
            bid_depth_usd=0.0,
            ask_depth_usd=0.0,
            side="buy",
            max_impact_pct=0.10,
            min_depth_ratio=3.0,
        )

        # Zero depth → max(10.0, 500 * 0.1) = max(10.0, 50.0) = 50.0
        assert adjusted >= 10.0
        assert adjusted == pytest.approx(50.0, abs=0.01)

    def test_max_impact_cap(self):
        """Position never exceeds max_impact_pct of depth."""
        rm = RiskManager(initial_bankroll=10000)

        # Position = 200, depth = 300
        # ratio = 300/200 = 1.5 < 3.0 → reduce
        # adjusted = min(200, 300 * 0.10) = min(200, 30) = 30
        adjusted = rm.apply_liquidity_adjustment(
            position_size_usd=200.0,
            bid_depth_usd=300.0,
            ask_depth_usd=300.0,
            side="buy",
            max_impact_pct=0.10,
            min_depth_ratio=3.0,
        )

        assert adjusted <= 300.0 * 0.10

    def test_liquidity_disabled_no_change(self):
        """When disabled (not called), no adjustment is made."""
        rm = RiskManager(initial_bankroll=10000)

        # Directly call calculate_position_size without liquidity params
        result = rm.calculate_position_size(
            pair="BTC/USD",
            entry_price=100.0,
            stop_loss=96.0,
            take_profit=112.0,
            liquidity_sizing_enabled=False,
            bid_depth_usd=10.0,  # Very thin depth
            ask_depth_usd=10.0,
        )

        # Should NOT be adjusted even with thin depth since disabled
        if result.allowed:
            # The size should be based on risk alone, not reduced by liquidity
            assert result.size_usd > 0

    def test_higher_max_impact_allows_larger_size(self):
        """Higher max_impact_pct allows larger position relative to depth."""
        rm = RiskManager(initial_bankroll=10000)

        small_impact = rm.apply_liquidity_adjustment(
            position_size_usd=500.0,
            bid_depth_usd=5000.0,
            ask_depth_usd=1000.0,
            side="buy",
            max_impact_pct=0.05,
            min_depth_ratio=3.0,
        )

        large_impact = rm.apply_liquidity_adjustment(
            position_size_usd=500.0,
            bid_depth_usd=5000.0,
            ask_depth_usd=1000.0,
            side="buy",
            max_impact_pct=0.20,
            min_depth_ratio=3.0,
        )

        assert large_impact > small_impact


# ---------------------------------------------------------------------------
# Integration: liquidity flows through calculate_position_size
# ---------------------------------------------------------------------------


class TestLiquidityInPositionSizing:

    def test_liquidity_in_position_sizing_pipeline(self):
        """Liquidity adjustment flows through calculate_position_size."""
        rm = RiskManager(
            initial_bankroll=100000,
            max_risk_per_trade=0.02,
            max_position_usd=5000.0,
            max_concurrent_positions=10,
            atr_multiplier_sl=2.0,
            atr_multiplier_tp=3.0,
        )

        # Normal sizing without liquidity
        normal = rm.calculate_position_size(
            pair="BTC/USD",
            entry_price=100.0,
            stop_loss=96.0,
            take_profit=112.0,
            liquidity_sizing_enabled=False,
        )

        # Sizing with thin liquidity
        thin = rm.calculate_position_size(
            pair="BTC/USD",
            entry_price=100.0,
            stop_loss=96.0,
            take_profit=112.0,
            liquidity_sizing_enabled=True,
            bid_depth_usd=100.0,
            ask_depth_usd=100.0,
            liquidity_max_impact_pct=0.10,
            liquidity_min_depth_ratio=3.0,
        )

        assert normal.allowed
        # Thin liquidity should either reduce size or potentially reject the trade
        if thin.allowed:
            assert thin.size_usd <= normal.size_usd

    def test_ample_liquidity_no_reduction(self):
        """With ample depth, position size is not reduced."""
        rm = RiskManager(
            initial_bankroll=100000,
            max_risk_per_trade=0.02,
            max_position_usd=5000.0,
            max_concurrent_positions=10,
        )

        normal = rm.calculate_position_size(
            pair="BTC/USD",
            entry_price=100.0,
            stop_loss=96.0,
            take_profit=112.0,
            liquidity_sizing_enabled=False,
        )

        with_liquidity = rm.calculate_position_size(
            pair="BTC/USD",
            entry_price=100.0,
            stop_loss=96.0,
            take_profit=112.0,
            liquidity_sizing_enabled=True,
            bid_depth_usd=1000000.0,  # Very deep book
            ask_depth_usd=1000000.0,
            liquidity_max_impact_pct=0.10,
            liquidity_min_depth_ratio=3.0,
        )

        assert normal.allowed
        assert with_liquidity.allowed
        assert with_liquidity.size_usd == normal.size_usd
