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


def test_resolve_backtest_friction_uses_distinct_fee_and_slippage_defaults():
    engine = SimpleNamespace(
        config=SimpleNamespace(
            exchange=SimpleNamespace(taker_fee=0.0026),
        )
    )

    slippage_pct, fee_pct = DashboardServer._resolve_backtest_friction(engine, {})

    assert slippage_pct == 0.001
    assert fee_pct == 0.0026


def test_resolve_backtest_friction_accepts_explicit_overrides():
    engine = SimpleNamespace(
        config=SimpleNamespace(
            exchange=SimpleNamespace(taker_fee=0.0026),
        )
    )

    slippage_pct, fee_pct = DashboardServer._resolve_backtest_friction(
        engine,
        {"slippage_pct": 0.0004, "fee_pct": 0.0011},
    )

    assert slippage_pct == 0.0004
    assert fee_pct == 0.0011


def test_aggregate_performance_stats_weights_sharpe_sortino_by_trades():
    server = DashboardServer()
    agg = server._aggregate_performance_stats(
        [
            {"total_trades": 10, "winning_trades": 6, "losing_trades": 4, "sharpe_ratio": 1.0, "sortino_ratio": 1.2},
            {"total_trades": 30, "winning_trades": 15, "losing_trades": 15, "sharpe_ratio": 0.5, "sortino_ratio": 0.7},
        ]
    )

    assert agg["sharpe_ratio"] == 0.625
    assert agg["sortino_ratio"] == 0.825
