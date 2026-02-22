"""Tests for TradeExecutor.reinitialize_positions().

Verifies that position and stop-loss state is correctly restored from the
database into the RiskManager after a restart.
"""
from __future__ import annotations

import json

import pytest

from src.execution.risk_manager import StopLossState

from tests.conftest import StubDB, make_executor


def _trade(
    trade_id="t-1",
    pair="BTC/USD",
    side="buy",
    entry_price=50000.0,
    quantity=0.1,
    stop_loss=48000.0,
    strategy="trend",
    metadata=None,
):
    """Return a trade dict matching the shape returned by db.get_open_trades()."""
    record = {
        "trade_id": trade_id,
        "pair": pair,
        "side": side,
        "entry_price": entry_price,
        "quantity": quantity,
        "stop_loss": stop_loss,
        "strategy": strategy,
        "metadata": metadata,
    }
    return record


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reinitialize_registers_positions_in_risk_manager():
    """Two open trades in DB -> both get registered in RiskManager._open_positions."""
    trades = [
        _trade(trade_id="t-1", pair="BTC/USD", side="buy"),
        _trade(trade_id="t-2", pair="ETH/USD", side="sell", entry_price=3000.0, quantity=1.0, stop_loss=3200.0),
    ]
    db = StubDB(open_trades=trades)
    executor, rm = make_executor(db=db, use_real_risk_manager=True)

    await executor.reinitialize_positions()

    assert "t-1" in rm._open_positions
    assert "t-2" in rm._open_positions
    assert rm._open_positions["t-1"]["pair"] == "BTC/USD"
    assert rm._open_positions["t-2"]["pair"] == "ETH/USD"


@pytest.mark.asyncio
async def test_reinitialize_restores_stop_loss_state():
    """Trade with stop_loss > 0 -> StopLossState created in _stop_states."""
    trades = [_trade(trade_id="t-1", stop_loss=48000.0)]
    db = StubDB(open_trades=trades)
    executor, rm = make_executor(db=db, use_real_risk_manager=True)

    await executor.reinitialize_positions()

    assert "t-1" in rm._stop_states
    state = rm._stop_states["t-1"]
    assert isinstance(state, StopLossState)
    assert state.initial_sl == 48000.0
    assert state.current_sl == 48000.0


@pytest.mark.asyncio
async def test_reinitialize_skips_stop_loss_when_zero():
    """Trade with stop_loss = 0 -> no entry in _stop_states."""
    trades = [_trade(trade_id="t-1", stop_loss=0)]
    db = StubDB(open_trades=trades)
    executor, rm = make_executor(db=db, use_real_risk_manager=True)

    await executor.reinitialize_positions()

    # Position should still be registered
    assert "t-1" in rm._open_positions
    # But no stop state
    assert "t-1" not in rm._stop_states


@pytest.mark.asyncio
async def test_reinitialize_uses_metadata_size_usd():
    """When metadata contains size_usd, use it instead of entry_price * quantity."""
    meta = json.dumps({"size_usd": 5000.0})
    trades = [_trade(trade_id="t-1", entry_price=50000.0, quantity=0.1, metadata=meta)]
    db = StubDB(open_trades=trades)
    executor, rm = make_executor(db=db, use_real_risk_manager=True)

    await executor.reinitialize_positions()

    pos = rm._open_positions["t-1"]
    assert pos["size_usd"] == 5000.0
    # Confirm it is NOT the fallback value (50000 * 0.1 = 5000 happens to
    # match here, so use a more distinguishing value)
    meta2 = json.dumps({"size_usd": 7777.0})
    trades2 = [_trade(trade_id="t-2", entry_price=50000.0, quantity=0.1, metadata=meta2)]
    db2 = StubDB(open_trades=trades2)
    executor2, rm2 = make_executor(db=db2, use_real_risk_manager=True)

    await executor2.reinitialize_positions()

    pos2 = rm2._open_positions["t-2"]
    assert pos2["size_usd"] == 7777.0  # metadata value, NOT 50000*0.1=5000


@pytest.mark.asyncio
async def test_reinitialize_falls_back_to_computed_size():
    """No metadata -> size_usd should be entry_price * quantity."""
    trades = [_trade(trade_id="t-1", entry_price=50000.0, quantity=0.2, metadata=None)]
    db = StubDB(open_trades=trades)
    executor, rm = make_executor(db=db, use_real_risk_manager=True)

    await executor.reinitialize_positions()

    pos = rm._open_positions["t-1"]
    assert pos["size_usd"] == 50000.0 * 0.2  # 10000.0


@pytest.mark.asyncio
async def test_reinitialize_restores_trailing_state_from_metadata():
    """Metadata with stop_loss_state should populate trailing_high / trailing_low."""
    meta = json.dumps({
        "size_usd": 5000.0,
        "stop_loss_state": {
            "trailing_high": 52000.0,
            "trailing_low": 48000.0,
        },
    })
    trades = [_trade(trade_id="t-1", stop_loss=47000.0, metadata=meta)]
    db = StubDB(open_trades=trades)
    executor, rm = make_executor(db=db, use_real_risk_manager=True)

    await executor.reinitialize_positions()

    state = rm._stop_states["t-1"]
    assert state.trailing_high == 52000.0
    assert state.trailing_low == 48000.0


@pytest.mark.asyncio
async def test_reinitialize_handles_corrupted_metadata_gracefully():
    """Corrupted (non-JSON) metadata should not crash; position uses computed size."""
    trades = [_trade(trade_id="t-1", entry_price=50000.0, quantity=0.1, metadata="not-json")]
    db = StubDB(open_trades=trades)
    executor, rm = make_executor(db=db, use_real_risk_manager=True)

    # Should not raise
    await executor.reinitialize_positions()

    # Position should still be registered with fallback size_usd
    assert "t-1" in rm._open_positions
    pos = rm._open_positions["t-1"]
    assert pos["size_usd"] == 50000.0 * 0.1  # 5000.0


@pytest.mark.asyncio
async def test_reinitialize_no_open_trades():
    """Empty trade list -> no errors, no positions registered."""
    db = StubDB(open_trades=[])
    executor, rm = make_executor(db=db, use_real_risk_manager=True)

    await executor.reinitialize_positions()

    assert len(rm._open_positions) == 0
    assert len(rm._stop_states) == 0
