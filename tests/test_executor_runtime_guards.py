from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.execution.executor import TradeExecutor
from src.execution.risk_manager import StopLossState


class _StubDB:
    def __init__(self) -> None:
        self.updates = []
        self.count_calls = 0

    async def update_trade(self, trade_id, updates, tenant_id=None):
        self.updates.append((trade_id, updates, tenant_id))

    async def log_thought(self, *args, **kwargs):
        return None

    async def count_trades_since(self, cutoff, tenant_id=None):
        self.count_calls += 1
        return 3


class _StubMarketData:
    def is_stale(self, pair, max_age_seconds=120):
        return False

    def get_latest_price(self, pair):
        return 101.0

    def get_spread(self, pair):
        return 0.0


class _StubRiskManager:
    def __init__(self) -> None:
        self.state = StopLossState(initial_sl=95.0, current_sl=95.0)

    def update_stop_loss(self, trade_id, current_price, entry_price, side):
        return self.state

    def should_stop_out(self, trade_id, current_price, side):
        return False

    def close_position(self, trade_id, pnl):
        return None

    def reduce_position_size(self, trade_id, reduction_fraction=None, reduction_usd=0.0):
        return None


@pytest.mark.asyncio
async def test_manage_position_persists_stop_state_even_when_sl_unchanged():
    db = _StubDB()
    market_data = _StubMarketData()
    risk = _StubRiskManager()
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
    db = _StubDB()
    executor = TradeExecutor(
        rest_client=None,
        market_data=_StubMarketData(),
        risk_manager=_StubRiskManager(),
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
