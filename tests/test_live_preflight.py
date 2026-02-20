from __future__ import annotations

from scripts.live_preflight import run_preflight
from src.core.config import BotConfig


def test_live_preflight_allow_paper_mode(monkeypatch):
    monkeypatch.delenv("KRAKEN_API_KEY", raising=False)
    monkeypatch.delenv("KRAKEN_API_SECRET", raising=False)
    monkeypatch.setenv("ELASTICSEARCH_ENABLED", "false")
    monkeypatch.setenv("MAX_RISK_PER_TRADE", "0.01")
    code = run_preflight(require_live=False, strict=False)
    assert code in (0, 2)


def test_live_preflight_accepts_account_scoped_credentials(monkeypatch):
    cfg = BotConfig(
        app={
            "mode": "live",
            "trading_accounts": "main:kraken,swing:coinbase",
            "trading_exchanges": "",
        },
        risk={"max_risk_per_trade": 0.01},
        trading={"max_trades_per_hour": 6},
    )
    monkeypatch.setattr("scripts.live_preflight.load_config_with_overrides", lambda: cfg)

    monkeypatch.delenv("KRAKEN_API_KEY", raising=False)
    monkeypatch.delenv("KRAKEN_API_SECRET", raising=False)
    monkeypatch.delenv("COINBASE_KEY_NAME", raising=False)
    monkeypatch.delenv("COINBASE_PRIVATE_KEY", raising=False)
    monkeypatch.setenv("MAIN_KRAKEN_API_KEY", "k-main")
    monkeypatch.setenv("MAIN_KRAKEN_API_SECRET", "s-main")
    monkeypatch.setenv("SWING_COINBASE_KEY_NAME", "organizations/org/apiKeys/key")
    monkeypatch.setenv("SWING_COINBASE_PRIVATE_KEY", "-----BEGIN PRIVATE KEY-----\\nabc\\n-----END PRIVATE KEY-----")
    monkeypatch.setenv("DASHBOARD_ADMIN_KEY", "admin-k")
    monkeypatch.setenv("DASHBOARD_SESSION_SECRET", "sess-k")
    monkeypatch.setenv("DASHBOARD_ADMIN_PASSWORD_HASH", "$2b$12$abcdefghijklmnopqrstuv")
    monkeypatch.setenv("ELASTICSEARCH_ENABLED", "false")
    code = run_preflight(require_live=True, strict=False)
    assert code == 0
