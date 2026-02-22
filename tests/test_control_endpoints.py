"""
Tests for HTTP control endpoints (pause, resume, close_all) and
TradeExecutor.close_all_positions() direct invocation.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.execution.executor import TradeExecutor

from tests.conftest import StubDB, StubMarketData, StubRiskManager

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ADMIN_KEY = "test-admin-key-12345"
SESSION_SECRET = "test-session-secret"

_OPEN_TRADES = [
    {
        "trade_id": "t-1",
        "pair": "BTC/USD",
        "side": "buy",
        "entry_price": 50000,
        "quantity": 0.1,
        "metadata": "{}",
        "strategy": "keltner",
    },
    {
        "trade_id": "t-2",
        "pair": "ETH/USD",
        "side": "sell",
        "entry_price": 3000,
        "quantity": 1.0,
        "metadata": "{}",
        "strategy": "trend",
    },
]


# ---------------------------------------------------------------------------
# 1. Direct test: close_all_positions()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_all_positions_closes_both_trades():
    """TradeExecutor.close_all_positions() should close every open trade in the DB."""
    db = StubDB(open_trades=_OPEN_TRADES)
    market_data = StubMarketData(prices={"BTC/USD": 52000.0, "ETH/USD": 2800.0})
    risk_manager = StubRiskManager()
    executor = TradeExecutor(
        rest_client=None,
        market_data=market_data,
        risk_manager=risk_manager,
        db=db,
        mode="paper",
    )

    count = await executor.close_all_positions("emergency_test")

    assert count == 2
    assert "t-1" in db.closed_trades
    assert "t-2" in db.closed_trades


# ---------------------------------------------------------------------------
# HTTP endpoint helpers
# ---------------------------------------------------------------------------


def _make_server(monkeypatch):
    """Build a DashboardServer wired to a fake bot engine."""
    monkeypatch.setenv("DASHBOARD_ADMIN_KEY", ADMIN_KEY)
    monkeypatch.setenv("DASHBOARD_SESSION_SECRET", SESSION_SECRET)

    from src.api.server import DashboardServer

    server = DashboardServer()

    # Minimal bot engine mock
    db_mock = StubDB(open_trades=_OPEN_TRADES)
    executor_mock = SimpleNamespace(
        close_all_positions=_async_close_all_returning(3),
    )
    config = SimpleNamespace(
        app=SimpleNamespace(mode="paper"),
        billing=SimpleNamespace(
            tenant=SimpleNamespace(default_tenant_id="default"),
        ),
    )
    engine = SimpleNamespace(
        config=config,
        _trading_paused=False,
        _priority_paused=False,
        db=db_mock,
        executor=executor_mock,
        exchange_name="kraken",
        tenant_id="default",
        pairs=["BTC/USD"],
        mode="paper",
        _running=True,
        _start_time=0,
        _scan_count=0,
    )
    server.set_bot_engine(engine)
    return server, engine


def _async_close_all_returning(n: int):
    """Return an async callable that resolves to *n*."""

    async def _close_all(reason="manual", tenant_id=None):
        return n

    return _close_all


# ---------------------------------------------------------------------------
# 2. POST /api/v1/control/pause -- with valid admin key
# ---------------------------------------------------------------------------


def test_pause_with_valid_admin_key(monkeypatch):
    server, engine = _make_server(monkeypatch)
    client = TestClient(server.app)

    resp = client.post(
        "/api/v1/control/pause",
        headers={"X-API-Key": ADMIN_KEY},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "paused"
    assert engine._trading_paused is True


# ---------------------------------------------------------------------------
# 3. POST /api/v1/control/pause -- without auth
# ---------------------------------------------------------------------------


def test_pause_without_auth_returns_403(monkeypatch):
    server, _engine = _make_server(monkeypatch)
    client = TestClient(server.app)

    resp = client.post("/api/v1/control/pause")

    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# 4. POST /api/v1/control/resume -- with valid admin key
# ---------------------------------------------------------------------------


def test_resume_with_valid_admin_key(monkeypatch):
    server, engine = _make_server(monkeypatch)
    # Pre-set paused so we can verify it flips to False
    engine._trading_paused = True
    client = TestClient(server.app)

    resp = client.post(
        "/api/v1/control/resume",
        headers={"X-API-Key": ADMIN_KEY},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "resumed"
    assert engine._trading_paused is False


# ---------------------------------------------------------------------------
# 5. POST /api/v1/control/close_all -- with valid admin key
# ---------------------------------------------------------------------------


def test_close_all_with_valid_admin_key(monkeypatch):
    server, _engine = _make_server(monkeypatch)
    client = TestClient(server.app)

    resp = client.post(
        "/api/v1/control/close_all",
        headers={"X-API-Key": ADMIN_KEY},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["closed"] == 3
