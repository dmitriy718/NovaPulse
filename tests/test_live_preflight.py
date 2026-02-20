from __future__ import annotations

from scripts.live_preflight import run_preflight


def test_live_preflight_allow_paper_mode(monkeypatch):
    monkeypatch.delenv("KRAKEN_API_KEY", raising=False)
    monkeypatch.delenv("KRAKEN_API_SECRET", raising=False)
    monkeypatch.setenv("MAX_RISK_PER_TRADE", "0.01")
    code = run_preflight(require_live=False, strict=False)
    assert code in (0, 2)
