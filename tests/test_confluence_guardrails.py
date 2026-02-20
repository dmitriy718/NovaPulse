from __future__ import annotations

import time

from src.ai.confluence import ConfluenceDetector
from src.exchange.market_data import MarketDataCache


def _get_strategy_row(detector: ConfluenceDetector, name: str):
    rows = detector.get_strategy_stats()
    for row in rows:
        if row.get("name") == name:
            return row
    return {}


def test_runtime_guardrail_auto_disables_degraded_strategy():
    detector = ConfluenceDetector(
        market_data=MarketDataCache(max_bars=64),
        strategy_guardrails_enabled=True,
        strategy_guardrails_min_trades=5,
        strategy_guardrails_window_trades=5,
        strategy_guardrails_min_win_rate=0.60,
        strategy_guardrails_min_profit_factor=1.20,
        strategy_guardrails_disable_minutes=30,
    )

    for _ in range(5):
        detector.record_trade_result("keltner", pnl=-12.0)

    keltner = _get_strategy_row(detector, "keltner")
    assert keltner.get("runtime_disabled") is True
    assert "guardrail" in (keltner.get("runtime_disable_reason") or "")


def test_runtime_guardrail_disables_temporarily(monkeypatch):
    detector = ConfluenceDetector(
        market_data=MarketDataCache(max_bars=64),
        strategy_guardrails_enabled=True,
        strategy_guardrails_min_trades=5,
        strategy_guardrails_window_trades=5,
        strategy_guardrails_min_win_rate=0.60,
        strategy_guardrails_min_profit_factor=1.20,
        strategy_guardrails_disable_minutes=1,
    )

    for _ in range(5):
        detector.record_trade_result("keltner", pnl=-8.0)

    first = _get_strategy_row(detector, "keltner")
    assert first.get("runtime_disabled") is True

    now = time.time()
    monkeypatch.setattr("src.ai.confluence.time.time", lambda: now + 120.0)
    second = _get_strategy_row(detector, "keltner")
    assert second.get("runtime_disabled") is False
