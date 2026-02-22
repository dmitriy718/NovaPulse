"""Tests for TradeExecutor.execute_signal() covering all gate checks and happy path."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from src.execution.risk_manager import RiskManager
from src.strategies.base import SignalDirection

from tests.conftest import StubDB, StubMarketData, make_signal, make_executor


# ---------------------------------------------------------------------------
# Local helper wrapping conftest.make_executor for this file's conventions.
# Tests in this module use a real RiskManager and only need the executor
# (not the (executor, rm) tuple returned by make_executor).
# ---------------------------------------------------------------------------

_DEFAULT_RM = dict(
    initial_bankroll=10000.0,
    max_risk_per_trade=0.02,
    max_position_usd=500.0,
    cooldown_seconds=0,
    max_concurrent_positions=10,
    min_risk_reward_ratio=1.0,
)


def _make_test_executor(
    db=None,
    market_data=None,
    risk_manager=None,
    max_trades_per_hour=0,
    quiet_hours_utc=None,
):
    """Return just the TradeExecutor with a real RiskManager by default."""
    rm = risk_manager or RiskManager(**_DEFAULT_RM)
    executor, _ = make_executor(
        db=db,
        market_data=market_data,
        risk_manager=rm,
        max_trades_per_hour=max_trades_per_hour,
        quiet_hours_utc=quiet_hours_utc,
    )
    return executor


# ---------------------------------------------------------------------------
# 1. Happy path -- paper fill
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_happy_path_paper_fill():
    """A valid LONG signal with sufficient confidence should produce a trade."""
    db = StubDB()
    executor = _make_test_executor(db=db)
    signal = make_signal()

    trade_id = await executor.execute_signal(signal)

    assert trade_id is not None
    assert trade_id.startswith("T-")
    assert len(db.trades) == 1

    record = db.trades[0]
    assert record["pair"] == "BTC/USD"
    assert record["side"] == "buy"
    assert record["status"] == "open"
    assert record["strategy"] == "keltner"
    assert record["entry_price"] > 0
    assert record["quantity"] > 0
    assert record["stop_loss"] > 0
    assert record["take_profit"] > 0


# ---------------------------------------------------------------------------
# 2. Neutral signal rejected
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_neutral_signal_rejected():
    """A NEUTRAL direction signal is immediately rejected."""
    db = StubDB()
    executor = _make_test_executor(db=db)
    signal = make_signal(direction=SignalDirection.NEUTRAL)

    result = await executor.execute_signal(signal)

    assert result is None
    assert len(db.trades) == 0


# ---------------------------------------------------------------------------
# 3. Stale signal discard (>60s old)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stale_signal_discarded():
    """A signal whose timestamp is more than 60 seconds old returns None."""
    db = StubDB()
    executor = _make_test_executor(db=db)

    old_ts = (datetime.now(timezone.utc) - timedelta(seconds=90)).isoformat()
    signal = make_signal(timestamp=old_ts)

    result = await executor.execute_signal(signal)

    assert result is None
    assert len(db.trades) == 0


# ---------------------------------------------------------------------------
# 4. Low confidence rejection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_low_confidence_rejected():
    """A signal with confidence below 0.50 is rejected."""
    db = StubDB()
    executor = _make_test_executor(db=db)
    signal = make_signal(confidence=0.40)

    result = await executor.execute_signal(signal)

    assert result is None
    assert len(db.trades) == 0


@pytest.mark.asyncio
async def test_confidence_decay_pushes_below_threshold():
    """A signal aged 25s decays confidence by 0.40, dropping 0.70 below 0.50."""
    db = StubDB()
    executor = _make_test_executor(db=db)

    # 25 seconds old: decay = (25-5)*0.02 = 0.40 -> effective = 0.70-0.40 = 0.30
    old_ts = (datetime.now(timezone.utc) - timedelta(seconds=25)).isoformat()
    signal = make_signal(confidence=0.70, timestamp=old_ts)

    result = await executor.execute_signal(signal)

    assert result is None
    assert len(db.trades) == 0


# ---------------------------------------------------------------------------
# 5. Duplicate pair rejection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_duplicate_pair_rejected():
    """When the DB already has an open trade for the same pair, returns None."""
    db = StubDB()
    db._open_trades = [{"pair": "BTC/USD", "side": "buy", "trade_id": "existing"}]
    executor = _make_test_executor(db=db)
    signal = make_signal(pair="BTC/USD")

    result = await executor.execute_signal(signal)

    assert result is None
    assert len(db.trades) == 0


@pytest.mark.asyncio
async def test_different_pair_not_rejected():
    """An open trade on a different pair does not block entry on a new pair."""
    db = StubDB()
    db._open_trades = [{"pair": "ETH/USD", "side": "buy", "trade_id": "existing"}]
    executor = _make_test_executor(db=db)
    signal = make_signal(pair="BTC/USD")

    result = await executor.execute_signal(signal)

    assert result is not None
    assert len(db.trades) == 1


# ---------------------------------------------------------------------------
# 6. Quiet hours filter
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_quiet_hours_filter_blocks():
    """Signal during a configured quiet hour is rejected."""
    db = StubDB()
    current_hour = datetime.now(timezone.utc).hour
    executor = _make_test_executor(db=db, quiet_hours_utc=(current_hour,))
    signal = make_signal()

    result = await executor.execute_signal(signal)

    assert result is None
    assert len(db.trades) == 0


@pytest.mark.asyncio
async def test_quiet_hours_filter_passes_outside_quiet():
    """Signal outside configured quiet hours proceeds normally."""
    db = StubDB()
    current_hour = datetime.now(timezone.utc).hour
    # Pick an hour that is definitely not the current one.
    quiet_hour = (current_hour + 6) % 24
    executor = _make_test_executor(db=db, quiet_hours_utc=(quiet_hour,))
    signal = make_signal()

    result = await executor.execute_signal(signal)

    assert result is not None
    assert len(db.trades) == 1


# ---------------------------------------------------------------------------
# 7. Trade rate throttle
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_trade_rate_throttle_blocks():
    """When max_trades_per_hour is reached, the signal is rejected."""
    db = StubDB()
    db._count_trades_since_value = 5
    executor = _make_test_executor(db=db, max_trades_per_hour=5)
    signal = make_signal()

    result = await executor.execute_signal(signal)

    assert result is None
    assert len(db.trades) == 0
    # Verify the thought was logged
    assert any(
        "trade-rate limit" in str(args)
        for args, _ in db.thoughts
    )


@pytest.mark.asyncio
async def test_trade_rate_throttle_passes_under_limit():
    """When recent trades are below the limit, the signal proceeds."""
    db = StubDB()
    db._count_trades_since_value = 2
    executor = _make_test_executor(db=db, max_trades_per_hour=5)
    signal = make_signal()

    result = await executor.execute_signal(signal)

    assert result is not None
    assert len(db.trades) == 1


@pytest.mark.asyncio
async def test_trade_rate_throttle_disabled_when_zero():
    """When max_trades_per_hour=0 (default), the throttle is skipped."""
    db = StubDB()
    db._count_trades_since_value = 999
    executor = _make_test_executor(db=db, max_trades_per_hour=0)
    signal = make_signal()

    result = await executor.execute_signal(signal)

    # count_trades_since should never be called
    assert db.count_calls == 0
    assert result is not None


# ---------------------------------------------------------------------------
# 8. Correlation group limit
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_correlation_group_limit_blocks():
    """When the correlation group has max positions, the new signal is rejected."""
    db = StubDB()
    # SOL/USD and AVAX/USD are both in the "alt_l1" group.
    # Pre-fill with 2 open trades in the same group (max is 2).
    db._open_trades = [
        {"pair": "SOL/USD", "side": "buy", "trade_id": "t1"},
        {"pair": "AVAX/USD", "side": "buy", "trade_id": "t2"},
    ]
    executor = _make_test_executor(db=db)
    # DOT/USD is also in "alt_l1".
    signal = make_signal(pair="DOT/USD")

    result = await executor.execute_signal(signal)

    assert result is None
    assert len(db.trades) == 0


@pytest.mark.asyncio
async def test_correlation_group_allows_under_limit():
    """When the correlation group has room, the signal proceeds."""
    db = StubDB()
    # Only 1 position in the "alt_l1" group, max is 2.
    db._open_trades = [
        {"pair": "SOL/USD", "side": "buy", "trade_id": "t1"},
    ]
    executor = _make_test_executor(db=db)
    signal = make_signal(pair="DOT/USD")

    result = await executor.execute_signal(signal)

    assert result is not None
    assert len(db.trades) == 1


@pytest.mark.asyncio
async def test_uncorrelated_pair_not_blocked():
    """A pair with no correlation group is never blocked by group limits."""
    db = StubDB()
    db._open_trades = [
        {"pair": "SOL/USD", "side": "buy", "trade_id": "t1"},
        {"pair": "AVAX/USD", "side": "buy", "trade_id": "t2"},
    ]
    executor = _make_test_executor(db=db)
    # BTC/USD is in the "btc" group -- only one member, so it cannot be blocked.
    signal = make_signal(pair="BTC/USD")

    result = await executor.execute_signal(signal)

    assert result is not None
    assert len(db.trades) == 1


# ---------------------------------------------------------------------------
# Additional edge cases
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_short_signal_happy_path():
    """A valid SHORT signal fills with side='sell'."""
    db = StubDB()
    market_data = StubMarketData()
    executor = _make_test_executor(db=db, market_data=market_data)
    signal = make_signal(
        direction=SignalDirection.SHORT,
        entry_price=50000.0,
        stop_loss=51500.0,
        take_profit=47500.0,
    )

    trade_id = await executor.execute_signal(signal)

    assert trade_id is not None
    assert len(db.trades) == 1
    assert db.trades[0]["side"] == "sell"


@pytest.mark.asyncio
async def test_trade_record_metadata_fields():
    """Verify critical metadata fields are populated on the trade record."""
    db = StubDB()
    executor = _make_test_executor(db=db)
    signal = make_signal()

    trade_id = await executor.execute_signal(signal)

    assert trade_id is not None
    record = db.trades[0]
    meta = record["metadata"]
    assert "confluence_count" in meta
    assert meta["confluence_count"] == 3
    assert meta["is_sure_fire"] is True
    assert meta["mode"] == "paper"
    assert "slippage" in meta
    assert "fees" in meta
    assert meta["size_usd"] > 0


@pytest.mark.asyncio
async def test_signal_at_exactly_60s_is_discarded():
    """A signal aged exactly 61 seconds is over the 60s threshold and discarded."""
    db = StubDB()
    executor = _make_test_executor(db=db)

    old_ts = (datetime.now(timezone.utc) - timedelta(seconds=61)).isoformat()
    signal = make_signal(timestamp=old_ts)

    result = await executor.execute_signal(signal)

    assert result is None


@pytest.mark.asyncio
async def test_confidence_exactly_at_threshold():
    """A signal with confidence exactly 0.50 should pass the gate."""
    db = StubDB()
    executor = _make_test_executor(db=db)
    signal = make_signal(confidence=0.50)

    result = await executor.execute_signal(signal)

    # confidence 0.50 is not < 0.50, so should pass
    assert result is not None
    assert len(db.trades) == 1
