from __future__ import annotations

import time

import pytest

from src.core.config import BotConfig
from src.stocks.swing_engine import StockSwingEngine


class _FakeDB:
    def __init__(self) -> None:
        self.inserted = []
        self.logs = []
        self.open_rows = []
        self.closed = []
        self.performance_stats = {
            "total_pnl": 0.0,
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
        }

    async def insert_trade(self, row, tenant_id: str = "default"):
        self.inserted.append((row, tenant_id))

    async def log_thought(
        self,
        category: str,
        message: str,
        severity: str = "info",
        metadata=None,
        tenant_id: str = "default",
    ):
        self.logs.append(
            {
                "category": category,
                "message": message,
                "severity": severity,
                "metadata": metadata,
                "tenant_id": tenant_id,
            }
        )

    async def get_open_trades(self, tenant_id: str = "default"):
        return list(self.open_rows)

    async def close_trade(
        self,
        trade_id: str,
        exit_price: float,
        pnl: float,
        pnl_pct: float,
        fees: float = 0.0,
        slippage: float = 0.0,
        tenant_id: str = "default",
    ):
        self.closed.append(
            {
                "trade_id": trade_id,
                "exit_price": exit_price,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "fees": fees,
                "slippage": slippage,
                "tenant_id": tenant_id,
            }
        )

    async def get_performance_stats(self, tenant_id: str = "default"):
        return dict(self.performance_stats)


def _live_cfg() -> BotConfig:
    return BotConfig(
        app={"mode": "live"},
        stocks={
            "symbols": ["AAPL"],
            "max_position_usd": 100.0,
            "min_hold_days": 1,
            "max_hold_days": 7,
        },
    )


def _paper_cfg() -> BotConfig:
    return BotConfig(
        app={"mode": "paper"},
        stocks={
            "symbols": ["AAPL"],
            "max_position_usd": 100.0,
            "min_hold_days": 1,
            "max_hold_days": 7,
            "estimated_fee_pct_per_side": 0.001,
            "estimated_slippage_pct_per_side": 0.002,
        },
    )


@pytest.mark.asyncio
async def test_live_open_tracks_pending_order_when_not_yet_filled():
    engine = StockSwingEngine(config_override=_live_cfg())
    fake_db = _FakeDB()
    engine.db = fake_db

    async def _submit_market_order(**kwargs):
        return {"id": "ord-1", "status": "accepted", "filled_qty": "0"}

    engine.alpaca.submit_market_order = _submit_market_order

    opened = await engine._open_trade("AAPL", 100.0)

    assert opened is True
    assert "AAPL" in engine._pending_opens
    assert len(fake_db.inserted) == 0
    assert engine._execution_stats["orders_rejected"] == 0
    assert engine._execution_stats["orders_pending"] == 1


@pytest.mark.asyncio
async def test_reconcile_pending_open_materializes_trade_after_fill():
    engine = StockSwingEngine(config_override=_live_cfg())
    fake_db = _FakeDB()
    engine.db = fake_db
    engine._pending_opens["AAPL"] = {
        "order_id": "ord-2",
        "requested_qty": 1.0,
        "submit_price": 100.0,
        "created_ts": time.time(),
    }

    async def _get_order(order_id: str):
        assert order_id == "ord-2"
        return {
            "id": "ord-2",
            "status": "filled",
            "filled_qty": "1.2",
            "filled_avg_price": "101.5",
        }

    engine.alpaca.get_order = _get_order

    await engine._reconcile_pending_opens()

    assert "AAPL" not in engine._pending_opens
    assert engine._execution_stats["orders_pending"] == 0
    assert engine._execution_stats["orders_filled"] == 1
    assert len(fake_db.inserted) == 1
    row, tenant_id = fake_db.inserted[0]
    assert tenant_id == engine.tenant_id
    assert row["pair"] == "AAPL"
    assert float(row["quantity"]) == pytest.approx(1.2)
    assert float(row["entry_price"]) == pytest.approx(101.5)
    assert row["metadata"]["broker_order_id"] == "ord-2"
    assert row["metadata"]["broker_order_status"] == "filled"


@pytest.mark.asyncio
async def test_reconcile_pending_open_clears_terminal_reject():
    engine = StockSwingEngine(config_override=_live_cfg())
    fake_db = _FakeDB()
    engine.db = fake_db
    engine._pending_opens["AAPL"] = {
        "order_id": "ord-3",
        "requested_qty": 1.0,
        "submit_price": 100.0,
        "created_ts": time.time(),
    }

    async def _get_order(order_id: str):
        assert order_id == "ord-3"
        return {"id": "ord-3", "status": "rejected", "filled_qty": "0"}

    engine.alpaca.get_order = _get_order

    await engine._reconcile_pending_opens()

    assert "AAPL" not in engine._pending_opens
    assert engine._execution_stats["orders_pending"] == 0
    assert engine._execution_stats["orders_rejected"] == 1
    assert len(fake_db.inserted) == 0


@pytest.mark.asyncio
async def test_startup_reconcile_materializes_broker_position():
    engine = StockSwingEngine(config_override=_live_cfg())
    fake_db = _FakeDB()
    engine.db = fake_db

    async def _list_open_positions():
        return [{"symbol": "AAPL", "qty": "1.5", "avg_entry_price": "123.4"}]

    engine.alpaca.list_open_positions = _list_open_positions

    await engine._reconcile_broker_positions(source="startup")

    assert len(fake_db.inserted) == 1
    row, _ = fake_db.inserted[0]
    assert row["pair"] == "AAPL"
    assert float(row["quantity"]) == pytest.approx(1.5)
    assert float(row["entry_price"]) == pytest.approx(123.4)
    assert engine._execution_stats["orders_filled"] == 0


@pytest.mark.asyncio
async def test_pending_reconcile_uses_broker_positions_when_order_lookup_missing():
    engine = StockSwingEngine(config_override=_live_cfg())
    fake_db = _FakeDB()
    engine.db = fake_db
    engine._pending_opens["AAPL"] = {
        "order_id": "ord-missing",
        "requested_qty": 1.0,
        "submit_price": 100.0,
        "created_ts": time.time(),
    }

    async def _list_open_positions():
        return [{"symbol": "AAPL", "qty": "1.25", "avg_entry_price": "101.2"}]

    async def _get_order(order_id: str):
        assert order_id == "ord-missing"
        return None

    engine.alpaca.list_open_positions = _list_open_positions
    engine.alpaca.get_order = _get_order

    await engine._reconcile_pending_opens()

    assert "AAPL" not in engine._pending_opens
    assert len(fake_db.inserted) == 1
    row, _ = fake_db.inserted[0]
    assert float(row["quantity"]) == pytest.approx(1.25)
    assert float(row["entry_price"]) == pytest.approx(101.2)


@pytest.mark.asyncio
async def test_close_trade_records_net_pnl_with_fees_and_slippage():
    engine = StockSwingEngine(config_override=_paper_cfg())
    fake_db = _FakeDB()
    engine.db = fake_db

    trade = {
        "trade_id": "S-test-close",
        "pair": "AAPL",
        "quantity": 1.0,
        "entry_price": 100.0,
    }
    closed = await engine._close_trade(trade, reason="unit_test", force=True, market_price=110.0)

    assert closed is True
    assert len(fake_db.closed) == 1
    row = fake_db.closed[0]
    assert row["fees"] == pytest.approx(0.21, abs=1e-6)
    assert row["slippage"] == pytest.approx(0.42, abs=1e-6)
    assert row["pnl"] == pytest.approx(9.37, abs=1e-6)


def test_stock_algorithm_stats_use_real_values():
    engine = StockSwingEngine(config_override=_paper_cfg())
    engine.risk_manager.record_closed_trade(10.0)
    engine.risk_manager.record_closed_trade(-5.0)

    stats = engine.get_algorithm_stats()[0]
    assert stats["trades"] == 2
    assert stats["win_rate"] == pytest.approx(0.5)
    assert stats["avg_pnl"] == pytest.approx(2.5)
