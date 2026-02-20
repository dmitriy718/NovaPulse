from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Dict, List, Optional

from fastapi.testclient import TestClient

from src.api.server import DashboardServer
from src.core.config import BotConfig
from src.execution.risk_manager import RiskManager


class _Part2DB:
    def __init__(self):
        self.providers: Dict[str, Dict[str, Any]] = {}
        self.signal_events: set[str] = set()
        self.thoughts: List[Dict[str, Any]] = []

    async def log_thought(self, category: str, message: str, **kwargs):
        self.thoughts.append({"category": category, "message": message, "kwargs": kwargs})

    async def upsert_copy_trading_provider(self, **kwargs):
        provider_id = kwargs["provider_id"]
        self.providers[provider_id] = {
            "provider_id": provider_id,
            "tenant_id": kwargs.get("tenant_id", "default"),
            "name": kwargs.get("name", provider_id),
            "source": kwargs.get("source", ""),
            "enabled": bool(kwargs.get("enabled", True)),
            "webhook_secret": kwargs.get("webhook_secret", ""),
            "metadata": kwargs.get("metadata", {}),
        }

    async def get_copy_trading_providers(self, *, tenant_id: Optional[str] = "default", enabled_only: bool = False):
        rows = [p for p in self.providers.values() if p.get("tenant_id") == (tenant_id or "default")]
        if enabled_only:
            rows = [p for p in rows if p.get("enabled")]
        return rows

    async def get_copy_trading_provider(self, *, provider_id: str, tenant_id: Optional[str] = "default"):
        p = self.providers.get(provider_id)
        if p and p.get("tenant_id") == (tenant_id or "default"):
            return p
        return None

    async def has_processed_signal_webhook_event(self, event_id: str) -> bool:
        return event_id in self.signal_events

    async def mark_signal_webhook_event_processed(self, event_id: str, **kwargs):
        if event_id in self.signal_events:
            return False
        self.signal_events.add(event_id)
        return True

    async def get_tenant_id_by_api_key(self, api_key: str):
        return None


class _Part2MarketData:
    def __init__(self, stale: bool = False):
        self._stale = stale

    def get_latest_price(self, pair: str) -> float:
        return 50_000.0

    def get_bar_count(self, pair: str) -> int:
        return 320

    def is_stale(self, pair: str, max_age_seconds: int = 600) -> bool:
        return self._stale


class _Part2WS:
    is_connected = True


class _Part2Confluence:
    def __init__(self):
        self.calls = 0

    def configure_strategies(self, *args, **kwargs):
        self.calls += 1


class _Part2AlertBot:
    def __init__(self):
        self.messages: List[str] = []

    async def send_message(self, text: str, *args, **kwargs):
        self.messages.append(text)
        return True


class _Part2Engine:
    def __init__(self, *, stale: bool = False):
        self.config = BotConfig(
            webhooks={
                "enabled": True,
                "secret": "global_secret",
                "allowed_sources": ["tradingview"],
            }
        )
        self.config.dashboard.require_api_key_for_reads = True
        self.exchange_name = "kraken"
        self.mode = "paper"
        self.tenant_id = "default"
        self.pairs = ["BTC/USD"]
        self.db = _Part2DB()
        self.market_data = _Part2MarketData(stale=stale)
        self.ws_client = _Part2WS()
        self.confluence = _Part2Confluence()
        self.risk_manager = RiskManager(
            initial_bankroll=1000.0,
            max_risk_per_trade=0.02,
            max_daily_loss=0.10,
            max_position_usd=200.0,
            cooldown_seconds=0,
            max_concurrent_positions=5,
        )
        self.telegram_bot = _Part2AlertBot()
        self.discord_bot = _Part2AlertBot()
        self.slack_bot = _Part2AlertBot()
        self._running = True
        self._trading_paused = False
        self._scan_count = 0
        self._start_time = 1.0
        self.scan_interval = 30
        self.canary_mode = False

    async def execute_external_signal(self, payload: Dict[str, Any], source: str = "webhook"):
        return {"ok": True, "trade_id": "ext_2"}


def _mk_client(stale: bool = False):
    engine = _Part2Engine(stale=stale)
    server = DashboardServer()
    server._admin_key = "ADMIN"
    server._bot_engine = engine
    return engine, TestClient(server.app)


def test_marketplace_list_and_apply_template():
    engine, client = _mk_client()
    listed = client.get("/api/v1/marketplace/strategies", headers={"X-API-Key": "ADMIN"})
    assert listed.status_code == 200
    templates = listed.json().get("templates", [])
    assert len(templates) >= 3

    applied = client.post(
        "/api/v1/marketplace/strategies/apply",
        json={"template_id": "keltner_focus", "persist": False},
        headers={"X-API-Key": "ADMIN"},
    )
    assert applied.status_code == 200
    assert applied.json()["ok"] is True
    assert engine.confluence.calls >= 1
    assert engine.config.strategies.keltner.weight == 0.42


def test_copy_trading_provider_crud():
    _, client = _mk_client()
    created = client.post(
        "/api/v1/copy-trading/providers",
        json={
            "provider_id": "prov1",
            "name": "Provider One",
            "source": "tradingview",
            "webhook_secret": "provsecret",
        },
        headers={"X-API-Key": "ADMIN"},
    )
    assert created.status_code == 200
    assert created.json()["provider_id"] == "prov1"

    listed = client.get("/api/v1/copy-trading/providers", headers={"X-API-Key": "ADMIN"})
    assert listed.status_code == 200
    rows = listed.json()["providers"]
    assert len(rows) == 1
    assert rows[0]["provider_id"] == "prov1"
    assert rows[0]["webhook_secret"] == "***"

    updated = client.patch(
        "/api/v1/copy-trading/providers/prov1",
        json={"enabled": False},
        headers={"X-API-Key": "ADMIN"},
    )
    assert updated.status_code == 200
    assert updated.json()["ok"] is True


def test_signal_webhook_uses_provider_secret_when_present():
    _, client = _mk_client()
    create = client.post(
        "/api/v1/copy-trading/providers",
        json={
            "provider_id": "provsig",
            "name": "Signal Provider",
            "source": "tradingview",
            "webhook_secret": "provider_specific_secret",
        },
        headers={"X-API-Key": "ADMIN"},
    )
    assert create.status_code == 200

    payload = {
        "provider_id": "provsig",
        "event_id": "event-9001",
        "source": "tradingview",
        "pair": "BTC/USD",
        "direction": "long",
    }
    raw = json.dumps(payload).encode("utf-8")
    sig = hmac.new(b"provider_specific_secret", raw, hashlib.sha256).hexdigest()

    r = client.post(
        "/api/v1/signals/webhook",
        content=raw,
        headers={
            "X-Signal-Signature": sig,
            "X-Signal-Source": "tradingview",
        },
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["duplicate"] is False


def test_ops_heartbeat_reports_degraded_when_data_stale():
    _, client = _mk_client(stale=True)
    r = client.get("/api/v1/ops/heartbeat", headers={"X-API-Key": "ADMIN"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "degraded"
    assert body["engines"][0]["stale_pairs_count"] >= 1


def test_alerts_test_endpoint_fans_out_to_bots():
    engine, client = _mk_client()
    r = client.post(
        "/api/v1/alerts/test",
        json={"message": "integration-test"},
        headers={"X-API-Key": "ADMIN"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert set(body["delivered"]) == {"telegram", "discord", "slack"}
    assert engine.telegram_bot.messages
    assert engine.discord_bot.messages
    assert engine.slack_bot.messages
