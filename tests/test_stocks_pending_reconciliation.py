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

