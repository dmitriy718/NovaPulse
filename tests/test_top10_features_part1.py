from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any, Dict, List

from fastapi.testclient import TestClient

from src.api.server import DashboardServer
from src.core.config import BotConfig
from src.execution.risk_manager import RiskManager


class _FeatureDB:
    def __init__(self) -> None:
        self.backtest_runs: List[Dict[str, Any]] = []
        self.signal_events: set[str] = set()
        self.state: Dict[str, Any] = {}

    async def insert_backtest_run(self, **kwargs) -> None:
        self.backtest_runs.append(kwargs)

    async def get_backtest_runs(self, limit: int = 25, tenant_id: str = "default"):
        rows = [r for r in self.backtest_runs if r.get("tenant_id", "default") == tenant_id]
        out: List[Dict[str, Any]] = []
        for r in rows[-limit:]:
            out.append(
                {
                    "run_id": r.get("run_id"),
                    "tenant_id": r.get("tenant_id"),
                    "exchange": r.get("exchange"),
                    "pair": r.get("pair"),
                    "timeframe": r.get("timeframe"),
                    "mode": r.get("mode"),
                    "status": r.get("status"),
                    "run_type": r.get("run_type"),
                    "params": r.get("params", {}),
                    "result": r.get("result", {}),
                    "started_at": r.get("started_at", ""),
                    "completed_at": r.get("completed_at", ""),
                    "created_at": r.get("completed_at", ""),
                }
            )
        return list(reversed(out))

    async def has_processed_signal_webhook_event(self, event_id: str) -> bool:
        return event_id in self.signal_events

    async def mark_signal_webhook_event_processed(
        self,
        event_id: str,
        *,
        source: str = "",
        payload_hash: str = "",
        tenant_id: str = "default",
    ) -> bool:
        if event_id in self.signal_events:
            return False
        self.signal_events.add(event_id)
        return True

    async def log_thought(self, *args, **kwargs):
        return None

    async def set_state(self, key: str, value: Any):
        self.state[key] = value


class _FeatureExecutor:
    async def close_all_positions(self, reason: str = "", tenant_id: str = "default"):
        return 2


class _FeatureMarketData:
    def get_latest_price(self, pair: str) -> float:
        return 50_000.0


class _FeatureRestClient:
    async def get_ohlc(self, pair: str, interval: int = 1, since: int | None = None):
        step = max(1, int(interval)) * 60
        start = int(since or (time.time() - (600 * step)))
        bars = []
        px = 40_000.0
        for i in range(640):
            ts = start + (i * step)
            o = px + (i * 1.5)
            h = o + 6.0
            l = o - 6.0
            c = o + 1.2
            v = 100.0 + (i % 10)
            bars.append([float(ts), o, h, l, c, 0.0, v, 1.0])
        return bars


class _FeatureEngine:
    def __init__(self):
        self.config = BotConfig(
            webhooks={
                "enabled": True,
                "secret": "test_signal_secret",
                "allowed_sources": ["tradingview"],
            }
        )
        self.config.dashboard.require_api_key_for_reads = True
        self.exchange_name = "kraken"
        self.mode = "paper"
        self.tenant_id = "default"
        self.pairs = ["BTC/USD"]
        self.db = _FeatureDB()
        self.market_data = _FeatureMarketData()
        self.rest_client = _FeatureRestClient()
        self.executor = _FeatureExecutor()
        self.risk_manager = RiskManager(
            initial_bankroll=1000.0,
            max_risk_per_trade=0.02,
            max_daily_loss=0.10,
            max_position_usd=400.0,
            cooldown_seconds=0,
            max_concurrent_positions=5,
        )
        self.predictor = None
        self._trading_paused = False

    async def execute_external_signal(self, payload: Dict[str, Any], source: str = "webhook"):
        return {"ok": True, "trade_id": "trade_ext_1"}


def _make_server_with_feature_engine() -> tuple[DashboardServer, _FeatureEngine, TestClient]:
    engine = _FeatureEngine()
    server = DashboardServer()
    server._admin_key = "ADMIN"
    server._bot_engine = engine
    return server, engine, TestClient(server.app)


def test_risk_manager_hard_daily_trade_cap_blocks_new_entries():
    rm = RiskManager(
        initial_bankroll=10000.0,
        max_risk_per_trade=0.02,
        max_daily_loss=0.10,
        max_position_usd=1000.0,
        cooldown_seconds=0,
        max_concurrent_positions=5,
        max_daily_trades=2,
    )
    rm._daily_reset_date = time.strftime("%Y-%m-%d", time.gmtime())
    rm._daily_trades = 2

    sized = rm.calculate_position_size(
        pair="BTC/USD",
        entry_price=100.0,
        stop_loss=99.0,
        take_profit=102.0,
        confidence=0.9,
    )
    assert sized.allowed is False
    assert "Daily trade cap" in sized.reason


def test_risk_manager_exposure_cap_limits_position_size():
    rm = RiskManager(
        initial_bankroll=10000.0,
        max_risk_per_trade=0.05,
        max_daily_loss=0.10,
        max_position_usd=5000.0,
        cooldown_seconds=0,
        max_concurrent_positions=10,
        max_total_exposure_pct=0.20,
    )
    rm.register_position("t1", "BTC/USD", "buy", 100.0, 1500.0)

    sized = rm.calculate_position_size(
        pair="ETH/USD",
        entry_price=100.0,
        stop_loss=99.0,
        take_profit=104.0,
        confidence=0.9,
    )
    assert sized.allowed is True
    assert sized.size_usd <= 500.0 + 1e-6


def test_backtest_run_endpoint_executes_and_persists():
    _, engine, client = _make_server_with_feature_engine()
    r = client.post(
        "/api/v1/backtest/run",
        json={
            "pair": "BTC/USD",
            "timeframe": "5m",
            "bars": 280,
            "mode": "simple",
        },
        headers={"X-API-Key": "ADMIN"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["run_id"].startswith("bt_")
    assert body["pair"] == "BTC/USD"
    assert body["timeframe"] == "5m"
    assert body["run_type"] == "backtest"
    assert len(engine.db.backtest_runs) == 1


def test_signal_webhook_signature_and_idempotency():
    _, _, client = _make_server_with_feature_engine()
    payload = {
        "event_id": "sig-123",
        "source": "tradingview",
        "pair": "BTC/USD",
        "direction": "long",
        "confidence": 0.72,
    }
    raw = json.dumps(payload).encode("utf-8")
    sig = hmac.new(
        b"test_signal_secret",
        raw,
        hashlib.sha256,
    ).hexdigest()

    h = {
        "X-Signal-Signature": sig,
        "X-Signal-Source": "tradingview",
    }
    first = client.post("/api/v1/signals/webhook", content=raw, headers=h)
    second = client.post("/api/v1/signals/webhook", content=raw, headers=h)

    assert first.status_code == 200
    assert first.json()["duplicate"] is False
    assert second.status_code == 200
    assert second.json()["duplicate"] is True


def test_paper_reset_endpoint_resets_runtime_state():
    _, engine, client = _make_server_with_feature_engine()
    rm = engine.risk_manager
    rm.register_position("t1", "BTC/USD", "buy", 100.0, 250.0)
    rm._daily_trades = 3
    rm._daily_pnl = -10.0
    rm.current_bankroll = 900.0

    r = client.post("/api/v1/paper/reset", headers={"X-API-Key": "ADMIN"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["closed_positions"] == 2
    assert rm.current_bankroll == rm.initial_bankroll
    assert rm.get_risk_report()["open_positions"] == 0
    assert rm.get_risk_report()["daily_trades"] == 0
