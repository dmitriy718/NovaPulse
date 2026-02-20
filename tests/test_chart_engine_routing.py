from __future__ import annotations

from types import SimpleNamespace

from src.api.server import DashboardServer


def _engine(exchange_name: str, account_id: str, pairs):
    return SimpleNamespace(
        exchange_name=exchange_name,
        tenant_id=account_id,
        pairs=list(pairs),
    )


def _server_with_engines(engines):
    server = DashboardServer()
    server._bot_engine = SimpleNamespace(engines=list(engines))
    return server


def test_split_exchange_account_parses_combined_token():
    ex, acct = DashboardServer._split_exchange_account("kraken:main", "")
    assert ex == "kraken"
    assert acct == "main"


def test_resolve_chart_engine_uses_exchange_and_account_scope():
    eng_main = _engine("kraken", "main", ["BTC/USD"])
    eng_swing = _engine("kraken", "swing", ["BTC/USD"])
    server = _server_with_engines([eng_main, eng_swing])

    resolved = server._resolve_chart_engine("BTC/USD", "kraken", "swing")

    assert resolved is eng_swing


def test_resolve_chart_engine_accepts_legacy_exchange_account_value():
    eng_main = _engine("kraken", "main", ["BTC/USD"])
    eng_swing = _engine("kraken", "swing", ["BTC/USD"])
    server = _server_with_engines([eng_main, eng_swing])

    resolved = server._resolve_chart_engine("BTC/USD", "kraken:swing")

    assert resolved is eng_swing

