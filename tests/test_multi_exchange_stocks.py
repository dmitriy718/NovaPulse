from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.core.config import BotConfig
from src.core.multi_engine import resolve_db_path, resolve_exchange_names, resolve_trading_accounts


def test_resolve_exchange_names_dedupes_trading_exchanges(monkeypatch):
    monkeypatch.setenv("TRADING_EXCHANGES", "kraken, coinbase,kraken")
    monkeypatch.delenv("TRADING_EXCHANGE", raising=False)
    monkeypatch.delenv("ACTIVE_EXCHANGE", raising=False)
    monkeypatch.delenv("EXCHANGE_NAME", raising=False)

    assert resolve_exchange_names("kraken") == ["kraken", "coinbase"]


def test_resolve_exchange_names_falls_back_to_active_exchange(monkeypatch):
    monkeypatch.setenv("TRADING_EXCHANGES", "")
    monkeypatch.delenv("TRADING_EXCHANGE", raising=False)
    monkeypatch.setenv("ACTIVE_EXCHANGE", "coinbase")
    monkeypatch.delenv("EXCHANGE_NAME", raising=False)

    assert resolve_exchange_names("kraken") == ["coinbase"]


def test_stocks_hold_window_is_validated():
    with pytest.raises(ValidationError):
        BotConfig(stocks={"min_hold_days": 5, "max_hold_days": 2})


def test_stocks_min_hold_days_must_be_at_least_one():
    with pytest.raises(ValidationError):
        BotConfig(stocks={"min_hold_days": 0})


def test_resolve_trading_accounts_from_env(monkeypatch):
    monkeypatch.setenv("TRADING_ACCOUNTS", "main:kraken,main:coinbase,swing:kraken")
    specs = resolve_trading_accounts("kraken", "")
    assert specs == [
        {"account_id": "main", "exchange": "kraken"},
        {"account_id": "main", "exchange": "coinbase"},
        {"account_id": "swing", "exchange": "kraken"},
    ]


def test_resolve_db_path_includes_account_suffix_for_multi():
    path = resolve_db_path("data/trading.db", "kraken", multi=True, account_id="main")
    assert path.endswith("trading_kraken_main.db")
