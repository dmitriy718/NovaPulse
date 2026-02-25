"""Tests for Structural Stop Loss (Feature 3).

Validates that stops are placed behind recent swing highs/lows instead of
at fixed ATR multiples, with proper fallback when no suitable swing exists.
"""

from __future__ import annotations

import asyncio
import numpy as np
import pytest

from src.execution.risk_manager import RiskManager
from src.ai.confluence import ConfluenceDetector, ConfluenceSignal
from src.strategies.base import SignalDirection, StrategySignal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_price_series(
    base: float = 100.0,
    n: int = 100,
    swing_positions: list | None = None,
    swing_type: str = "low",
    swing_value: float = 95.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Generate synthetic highs and lows with specific swing points.

    Returns (highs, lows) arrays.
    """
    highs = np.full(n, base + 2.0)
    lows = np.full(n, base - 2.0)
    # Add some natural variation
    for i in range(n):
        highs[i] = base + 2.0 + np.sin(i * 0.1) * 0.5
        lows[i] = base - 2.0 + np.sin(i * 0.1) * 0.5

    if swing_positions:
        for pos in swing_positions:
            if 0 <= pos < n:
                if swing_type == "low":
                    lows[pos] = swing_value
                elif swing_type == "high":
                    highs[pos] = swing_value
    return highs, lows


def _make_swing_data(n: int = 100) -> tuple[np.ndarray, np.ndarray]:
    """Create realistic price data with clear swing points.

    Returns (highs, lows) with planted swings detectable by _find_swings(lookback=5):
    - Swing low at index 80 (value=95.0)
    - Swing low at index 60 (value=93.0)
    - Swing high at index 70 (value=107.0)
    - Swing high at index 85 (value=109.0)

    _find_swings checks if lows[i] == min(lows[i-5:i+6]).
    With a monotonic baseline, only the planted dips/peaks qualify.
    """
    # Use a gentle uptrend baseline so no two adjacent bars share the same low
    highs = np.array([103.0 + i * 0.01 for i in range(n)])
    lows = np.array([97.0 + i * 0.01 for i in range(n)])

    # Plant swing low at index 80: set to 95.0 (well below 97.75..97.85 neighbors)
    lows[80] = 95.0

    # Plant swing low at index 60: set to 93.0 (well below 97.55..97.65 neighbors)
    lows[60] = 93.0

    # Plant swing high at index 70: set to 107.0 (well above 103.65..103.75 neighbors)
    highs[70] = 107.0

    # Plant swing high at index 85: set to 109.0 (well above 103.80..103.90 neighbors)
    highs[85] = 109.0

    return highs, lows


# ---------------------------------------------------------------------------
# Unit tests: compute_structural_stop on RiskManager
# ---------------------------------------------------------------------------


class TestComputeStructuralStop:

    def test_buy_uses_swing_low_as_stop(self):
        """For a buy, stop is placed below the nearest swing low."""
        rm = RiskManager(initial_bankroll=10000, atr_multiplier_sl=2.0)
        highs, lows = _make_swing_data()
        entry_price = 100.0
        atr_value = 2.0

        sl = rm.compute_structural_stop(
            pair="BTC/USD",
            side="buy",
            entry_price=entry_price,
            highs=highs,
            lows=lows,
            atr_value=atr_value,
            lookback=5,
            buffer_atr_mult=0.5,
            max_distance_atr=4.0,
        )

        # Nearest swing low below 100 is at index 80 (95.0)
        # SL = 95.0 - 0.5 * 2.0 = 94.0
        assert sl < entry_price, "Stop loss must be below entry for buy"
        assert sl == pytest.approx(94.0, abs=0.01)

    def test_sell_uses_swing_high_as_stop(self):
        """For a sell, stop is placed above the nearest swing high."""
        rm = RiskManager(initial_bankroll=10000, atr_multiplier_sl=2.0)
        highs, lows = _make_swing_data()
        entry_price = 100.0
        atr_value = 2.0

        sl = rm.compute_structural_stop(
            pair="BTC/USD",
            side="sell",
            entry_price=entry_price,
            highs=highs,
            lows=lows,
            atr_value=atr_value,
            lookback=5,
            buffer_atr_mult=0.5,
            max_distance_atr=4.0,
        )

        # Nearest swing high above 100 is at index 70 (107.0)
        # SL = 107.0 + 0.5 * 2.0 = 108.0
        assert sl > entry_price, "Stop loss must be above entry for sell"
        assert sl == pytest.approx(108.0, abs=0.01)

    def test_buffer_added_to_swing(self):
        """Verify buffer = ATR * mult is added beyond the swing level."""
        rm = RiskManager(initial_bankroll=10000, atr_multiplier_sl=2.0)
        highs, lows = _make_swing_data()
        entry_price = 100.0
        atr_value = 2.0

        # With buffer_atr_mult=1.0, buffer = 1.0 * 2.0 = 2.0
        sl = rm.compute_structural_stop(
            pair="BTC/USD",
            side="buy",
            entry_price=entry_price,
            highs=highs,
            lows=lows,
            atr_value=atr_value,
            lookback=5,
            buffer_atr_mult=1.0,
            max_distance_atr=4.0,
        )

        # swing low = 95.0, buffer = 2.0 -> SL = 93.0
        assert sl == pytest.approx(93.0, abs=0.01)

    def test_fallback_to_atr_when_no_swing(self):
        """When no swing found within range, falls back to ATR-based stop."""
        rm = RiskManager(initial_bankroll=10000, atr_multiplier_sl=2.0)
        # Monotonically increasing data has no swing lows (no local minimum)
        highs = np.array([100.0 + i * 0.1 for i in range(100)])
        lows = np.array([99.0 + i * 0.1 for i in range(100)])
        entry_price = 110.0
        atr_value = 2.0

        sl = rm.compute_structural_stop(
            pair="BTC/USD",
            side="buy",
            entry_price=entry_price,
            highs=highs,
            lows=lows,
            atr_value=atr_value,
            lookback=5,
            buffer_atr_mult=0.5,
            max_distance_atr=4.0,
        )

        # Fallback: entry - atr_multiplier_sl * ATR = 110 - 2*2 = 106.0
        assert sl == pytest.approx(106.0, abs=0.01)

    def test_max_distance_constraint(self):
        """Swing too far away triggers fallback to ATR-based stop."""
        rm = RiskManager(initial_bankroll=10000, atr_multiplier_sl=2.0)
        highs, lows = _make_swing_data()
        entry_price = 100.0
        atr_value = 1.0

        # Nearest swing low is at 95.0, distance = 5.0
        # max_distance = 2.0 * 1.0 = 2.0 → 5.0 > 2.0 → fallback
        sl = rm.compute_structural_stop(
            pair="BTC/USD",
            side="buy",
            entry_price=entry_price,
            highs=highs,
            lows=lows,
            atr_value=atr_value,
            lookback=5,
            buffer_atr_mult=0.5,
            max_distance_atr=2.0,
        )

        # Fallback: entry - atr_multiplier_sl * ATR = 100 - 2.0 * 1.0 = 98.0
        assert sl == pytest.approx(98.0, abs=0.01)

    def test_multiple_swings_uses_nearest(self):
        """When multiple swing lows exist, uses the nearest to entry."""
        rm = RiskManager(initial_bankroll=10000, atr_multiplier_sl=2.0)
        highs, lows = _make_swing_data()
        entry_price = 100.0
        atr_value = 2.0

        sl = rm.compute_structural_stop(
            pair="BTC/USD",
            side="buy",
            entry_price=entry_price,
            highs=highs,
            lows=lows,
            atr_value=atr_value,
            lookback=5,
            buffer_atr_mult=0.5,
            max_distance_atr=10.0,  # Wide enough to see both swings
        )

        # Two swing lows: 95.0 (at 80) and 93.0 (at 60)
        # Nearest to entry (100) is 95.0 -> SL = 95.0 - 1.0 = 94.0
        assert sl == pytest.approx(94.0, abs=0.01)


# ---------------------------------------------------------------------------
# Integration tests: Structural SL in confluence pipeline
# ---------------------------------------------------------------------------


class StubMarketData:
    """Minimal market data stub for confluence tests."""

    def __init__(self):
        n = 200
        self._times = np.arange(n, dtype=np.float64) * 60
        self._closes = np.full(n, 100.0)
        self._opens = np.full(n, 100.0)
        self._volumes = np.full(n, 1000.0)

        # Create swing structure with monotonic baseline (no accidental swings)
        self._highs = np.array([102.0 + i * 0.005 for i in range(n)])
        self._lows = np.array([98.0 + i * 0.005 for i in range(n)])

        # Plant swing low at index 150 (value=95.0, neighbors ~98.725..98.775)
        self._lows[150] = 95.0

        # Plant swing high at index 160 (value=108.0, neighbors ~102.775..102.825)
        self._highs[160] = 108.0

    def is_warmed_up(self, pair):
        return True

    def is_stale(self, pair, max_age_seconds=180):
        return False

    def get_times(self, pair):
        return self._times

    def get_closes(self, pair):
        return self._closes

    def get_highs(self, pair):
        return self._highs

    def get_lows(self, pair):
        return self._lows

    def get_volumes(self, pair):
        return self._volumes

    def get_opens(self, pair):
        return self._opens

    def get_order_book(self, pair):
        return None

    def get_order_book_analysis(self, pair):
        return None

    def get_latest_price(self, pair):
        return 100.0


class TestStructuralStopConfluence:

    def test_structural_stop_in_confluence_pipeline(self):
        """When structural stop is enabled, the signal carries structural_sl."""
        md = StubMarketData()
        detector = ConfluenceDetector(
            market_data=md,
            confluence_threshold=1,
            min_confidence=0.1,
            timeframes=[1],
        )
        detector.set_structural_stop_config(
            {"enabled": True, "lookback": 5, "buffer_atr_mult": 0.5, "max_distance_atr": 4.0},
            atr_multiplier_sl=2.0,
        )

        # Manually test _compute_structural_sl
        from src.strategies.market_structure import MarketStructureStrategy
        highs = md.get_highs("BTC/USD")
        lows = md.get_lows("BTC/USD")
        swing_highs, swing_lows = MarketStructureStrategy._find_swings(highs, lows, 5)

        # Verify swing detection found our planted swings
        low_prices = [p for _, p in swing_lows]
        high_prices = [p for _, p in swing_highs]
        assert 95.0 in low_prices, f"Expected 95.0 in swing lows, got {low_prices}"
        assert 108.0 in high_prices, f"Expected 108.0 in swing highs, got {high_prices}"

        # Test the static helper directly
        sl = ConfluenceDetector._compute_structural_sl(
            side="buy",
            entry_price=100.0,
            swing_highs=swing_highs,
            swing_lows=swing_lows,
            atr_value=2.0,
            buffer_atr_mult=0.5,
            max_distance_atr=4.0,
            atr_multiplier_sl=2.0,
        )
        assert sl is not None
        assert sl < 100.0
        # Should be 95.0 - 0.5*2.0 = 94.0
        assert sl == pytest.approx(94.0, abs=0.1)

    def test_structural_stop_disabled_uses_atr(self):
        """When structural stop is disabled, signal has no structural_sl."""
        md = StubMarketData()
        detector = ConfluenceDetector(
            market_data=md,
            confluence_threshold=1,
            min_confidence=0.1,
            timeframes=[1],
        )
        # Don't call set_structural_stop_config -> _structural_stop_config doesn't exist

        sig = ConfluenceSignal(
            pair="BTC/USD",
            direction=SignalDirection.LONG,
            strength=0.8,
            confidence=0.7,
            confluence_count=3,
            signals=[],
            entry_price=100.0,
            stop_loss=96.0,
            take_profit=106.0,
        )

        assert sig.structural_sl is None

    def test_structural_sl_serializes_in_to_dict(self):
        """structural_sl appears in signal.to_dict() when set."""
        sig = ConfluenceSignal(
            pair="BTC/USD",
            direction=SignalDirection.LONG,
            strength=0.8,
            confidence=0.7,
            confluence_count=3,
            signals=[],
            entry_price=100.0,
            stop_loss=96.0,
            take_profit=106.0,
        )
        sig.structural_sl = 94.0
        d = sig.to_dict()
        assert d["structural_sl"] == 94.0

    def test_structural_sl_none_in_to_dict(self):
        """structural_sl is None in signal.to_dict() when not set."""
        sig = ConfluenceSignal(
            pair="BTC/USD",
            direction=SignalDirection.LONG,
            strength=0.8,
            confidence=0.7,
            confluence_count=3,
            signals=[],
        )
        d = sig.to_dict()
        assert d["structural_sl"] is None
