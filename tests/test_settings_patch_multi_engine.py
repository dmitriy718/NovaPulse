from __future__ import annotations

from fastapi.testclient import TestClient

from src.api.server import DashboardServer
from src.core.config import BotConfig


class _SettingsDB:
    def __init__(self) -> None:
        self.logs = []

    async def log_thought(self, category: str, message: str, **kwargs):
        self.logs.append({"category": category, "message": message, "kwargs": kwargs})


class _SettingsConfluence:
    def __init__(self) -> None:
        self.obi_counts_as_confluence = False
        self.obi_weight = 0.0
        self.confluence_threshold = 0
        self.min_confidence = 0.0


class _SettingsRisk:
    def __init__(self) -> None:
        self.max_risk_per_trade = 0.0
        self.max_daily_loss = 0.0
        self.max_daily_trades = 0
        self.max_position_usd = 0.0
        self.max_total_exposure_pct = 0.0
        self.atr_multiplier_sl = 0.0
        self.atr_multiplier_tp = 0.0
        self.trailing_activation_pct = 0.0
        self.trailing_step_pct = 0.0
        self.breakeven_activation_pct = 0.0
        self.kelly_fraction = 0.0
        self.global_cooldown_seconds_on_loss = 0


class _SettingsExecutor:
    def __init__(self) -> None:
        self.max_trades_per_hour = 0


class _SettingsEngine:
    def __init__(self, tenant_id: str, exchange_name: str) -> None:
        self.config = BotConfig()
        self.tenant_id = tenant_id
        self.exchange_name = exchange_name
        self.confluence = _SettingsConfluence()
        self.risk_manager = _SettingsRisk()
        self.executor = _SettingsExecutor()
        self.scan_interval = self.config.trading.scan_interval_seconds
        self.db = _SettingsDB()


def _make_client():
    e1 = _SettingsEngine("main", "kraken")
    e2 = _SettingsEngine("swing", "coinbase")
    hub = type("Hub", (), {"engines": [e1, e2]})()
    server = DashboardServer()
    server._admin_key = "ADMIN"
    server._bot_engine = hub
    return e1, e2, server, TestClient(server.app)


def test_patch_settings_fans_out_to_all_engines(monkeypatch):
    e1, e2, _, client = _make_client()
    saved_payloads = []

    def _fake_save(payload):
        saved_payloads.append(payload)

    monkeypatch.setattr("src.core.config.save_to_yaml", _fake_save)

    resp = client.patch(
        "/api/v1/settings",
        json={
            "ai": {
                "confluence_threshold": 2,
                "min_confidence": 0.58,
                "obi_counts_as_confluence": True,
            },
            "risk": {"max_daily_trades": 11},
            "trading": {"scan_interval_seconds": 17, "max_trades_per_hour": 9},
        },
        headers={"X-API-Key": "ADMIN"},
    )
    assert resp.status_code == 200
    for eng in (e1, e2):
        assert eng.config.ai.confluence_threshold == 2
        assert eng.config.ai.min_confidence == 0.58
        assert eng.config.ai.obi_counts_as_confluence is True
        assert eng.config.risk.max_daily_trades == 11
        assert eng.config.trading.scan_interval_seconds == 17
        assert eng.config.trading.max_trades_per_hour == 9
        assert eng.confluence.confluence_threshold == 2
        assert eng.confluence.min_confidence == 0.58
        assert eng.confluence.obi_counts_as_confluence is True
        assert eng.risk_manager.max_daily_trades == 11
        assert eng.scan_interval == 17
        assert eng.executor.max_trades_per_hour == 9
        assert eng.db.logs
    assert len(saved_payloads) == 1
    assert saved_payloads[0]["trading"]["scan_interval_seconds"] == 17


def test_patch_settings_bool_parser_is_strict(monkeypatch):
    e1, e2, _, client = _make_client()
    monkeypatch.setattr("src.core.config.save_to_yaml", lambda payload: None)

    ok = client.patch(
        "/api/v1/settings",
        json={"monitoring": {"auto_pause_on_drawdown": "false"}},
        headers={"X-API-Key": "ADMIN"},
    )
    assert ok.status_code == 200
    assert e1.config.monitoring.auto_pause_on_drawdown is False
    assert e2.config.monitoring.auto_pause_on_drawdown is False

    bad = client.patch(
        "/api/v1/settings",
        json={"monitoring": {"auto_pause_on_drawdown": "definitely"}},
        headers={"X-API-Key": "ADMIN"},
    )
    assert bad.status_code == 400
    assert "Invalid boolean value for monitoring.auto_pause_on_drawdown" in bad.text
