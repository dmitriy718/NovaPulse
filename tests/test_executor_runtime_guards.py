from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.execution.executor import TradeExecutor

from tests.conftest import StubDB, StubMarketData, StubRiskManager


@pytest.mark.asyncio
async def test_manage_position_persists_stop_state_even_when_sl_unchanged():
    db = StubDB()
    market_data = StubMarketData(prices={"BTC/USD": 101.0})
    risk = StubRiskManager()
    executor = TradeExecutor(
        rest_client=None,
        market_data=market_data,
        risk_manager=risk,
        db=db,
        mode="paper",
    )
    trade = {
        "trade_id": "t-1",
        "pair": "BTC/USD",
        "side": "buy",
        "entry_price": 100.0,
        "quantity": 1.0,
        "stop_loss": 95.0,
        "take_profit": 0.0,
        "strategy": "trend",
        "metadata": "{}",
        "entry_time": datetime.now(timezone.utc).isoformat(),
    }

    await executor._manage_position(trade)

    assert len(db.updates) == 1
    _, updates, _ = db.updates[0]
    assert float(updates["stop_loss"]) == 95.0
    assert isinstance(updates["metadata"].get("stop_loss_state"), dict)


@pytest.mark.asyncio
async def test_recent_trades_count_uses_short_ttl_cache():
    db = StubDB(count_trades_since_value=3)
    executor = TradeExecutor(
        rest_client=None,
        market_data=StubMarketData(),
        risk_manager=StubRiskManager(),
        db=db,
        mode="paper",
    )
    cutoff = datetime.now(timezone.utc).isoformat()

    first = await executor._get_recent_trades_count(cutoff)
    second = await executor._get_recent_trades_count(cutoff)

    assert first == 3
    assert second == 3
    assert db.count_calls == 1

    executor._recent_trades_cache_at = 0.0
    third = await executor._get_recent_trades_count(cutoff)
    assert third == 3
    assert db.count_calls == 2
