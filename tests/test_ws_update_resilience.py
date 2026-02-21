from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from src.api.server import DashboardServer


class _FakeDB:
    def __init__(self, *, fail: bool = False, delay_seconds: float = 0.0) -> None:
        self.fail = fail
        self.delay_seconds = delay_seconds
        self.is_initialized = True

    async def get_performance_stats(self, tenant_id: str = "default"):
        await asyncio.sleep(self.delay_seconds)
        if self.fail:
            raise RuntimeError("stats failed")
        return {
            "total_pnl": 1.0,
            "total_trades": 1,
            "winning_trades": 1,
            "losing_trades": 0,
            "open_positions": 1,
            "today_pnl": 1.0,
            "avg_win": 1.0,
            "avg_loss": 0.0,
        }

    async def get_open_trades(self, tenant_id: str = "default"):
        await asyncio.sleep(self.delay_seconds)
        if self.fail:
            raise RuntimeError("open trades failed")
        return [
            {
                "pair": "BTC/USD",
                "side": "buy",
                "entry_price": 100.0,
                "quantity": 1.0,
                "entry_time": "2026-02-21T00:00:00+00:00",
            }
        ]

    async def get_thoughts(self, limit: int = 50, tenant_id: str = "default"):
        await asyncio.sleep(self.delay_seconds)
        if self.fail:
            raise RuntimeError("thoughts failed")
        return [{"timestamp": "2026-02-21T00:00:00+00:00", "message": "ok"}]

    async def get_state(self, key: str, default=None):
        return default


class _FakeMD:
    def get_latest_price(self, pair: str) -> float:
        return 101.0

    def get_bar_count(self, pair: str) -> int:
        return 10

    def is_stale(self, pair: str, max_age_seconds: int = 600) -> bool:
        return False


class _FakeRisk:
    def get_risk_report(self):
        return {"bankroll": 100.0, "current_drawdown": 0.0}


class _FakeEngine:
    def __init__(self, name: str, *, fail: bool = False, delay_seconds: float = 0.0) -> None:
        self.db = _FakeDB(fail=fail, delay_seconds=delay_seconds)
        self.market_data = _FakeMD()
        self.risk_manager = _FakeRisk()
        self.exchange_name = name
        self.tenant_id = name
        self.pairs = ["BTC/USD"]
        self.mode = "paper"
        self._running = True
        self._trading_paused = False
        self._priority_paused = False
        self._start_time = time.time() - 10
        self._scan_count = 1
        self.ws_client = SimpleNamespace(is_connected=True)

    def get_algorithm_stats(self):
        return [{"name": "stub", "enabled": True}]


def _wire_dashboard(engines):
    server = DashboardServer()
    cfg = SimpleNamespace(
        app=SimpleNamespace(mode="paper"),
        billing=SimpleNamespace(tenant=SimpleNamespace(default_tenant_id="default")),
    )
    server.set_bot_engine(SimpleNamespace(engines=engines, config=cfg))
    return server


@pytest.mark.asyncio
async def test_ws_update_continues_when_one_engine_snapshot_fails():
    server = _wire_dashboard(
        [
            _FakeEngine("kraken", fail=True, delay_seconds=0.01),
            _FakeEngine("coinbase", delay_seconds=0.01),
            _FakeEngine("stocks", delay_seconds=0.01),
        ]
    )
    payload = await server._build_ws_update("default")
    assert payload["type"] == "update"
    positions = payload["data"]["positions"]
    assert len(positions) == 2


@pytest.mark.asyncio
async def test_ws_update_snapshot_collection_is_parallelized():
    server = _wire_dashboard(
        [
            _FakeEngine("kraken", delay_seconds=0.05),
            _FakeEngine("coinbase", delay_seconds=0.05),
            _FakeEngine("stocks", delay_seconds=0.05),
        ]
    )
    start = time.perf_counter()
    payload = await server._build_ws_update("default")
    elapsed = time.perf_counter() - start

    assert payload["type"] == "update"
    # Parallel snapshots should stay comfortably below sequential 0.45s in this setup.
    assert elapsed < 0.35
