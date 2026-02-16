# NovaPulse (v3)

Operator-grade AI crypto trading system: multi-strategy signal engine, risk-first execution, hardened control plane, and continuous self-improvement (guardrailed).

## What You Get (30 Features)

Trading + Intelligence:
1. Multi-pair market scanning (configurable interval)
2. Multi-exchange support (Kraken, Coinbase adapters)
3. Five parallel TA strategies (trend, mean reversion, momentum, breakout, reversal)
4. Strategy confluence scoring and weighted aggregation
5. Optional order-book microstructure weighting (imbalance + spoof heuristics)
6. AI entry gating model (TFLite when available; safe fallback when not)
7. Continuous learner (online, incremental) for non-blocking improvement over time
8. Feature logging for every decision (for later supervised training)
9. Paper trading mode (default) and live trading mode (explicit enable)
10. Backtester (same logic as live path; used for promotion gates)

Execution + Risk:
11. Fixed-fractional sizing (primary) with Kelly cap (when enough history)
12. ATR-based initial stop and dynamic trailing stop
13. Breakeven activation logic
14. Risk-of-ruin monitoring and exposure throttling
15. Daily loss limit and drawdown-scaled sizing
16. Trade cooldowns (global + per-strategy)
17. Max concurrent position limits
18. Slippage/spread sanity checks (configurable)
19. Circuit breakers (stale data, WS disconnect, repeated task failures) that auto-pause trading
20. Single-instance host lock to prevent double-trading on the same volume

Control Plane + Observability:
21. FastAPI dashboard (REST + WebSocket live stream)
22. Secure-by-default auth: web login session (httpOnly cookie) or API keys
23. Key scoping: separate read key vs admin/control key (admin-only by default)
24. CSRF protection for cookie-auth control actions (double-submit token)
25. Rate limiting (token bucket; per-IP)
26. Security headers + `Cache-Control: no-store` for API responses
27. Audit log stream ("thought log") for decisions and operator actions
28. Telegram command center (status, pause/resume, close_all, kill) + scheduled check-ins
29. CSV export of trades for reconciliation
30. 72-96 hour stress monitor (API/WS/data freshness/activity) with auth support

## Security Notes (Reality Check)

This repo is hardened with fail-closed defaults and multiple safety nets, but no software can guarantee "zero risk." Treat any system that can place real orders as high-risk: run behind a firewall/VPN, rotate keys, and use exchange API key restrictions (IP allowlists, no-withdrawal keys).

## Quick Start (Local)

```bash
cd NovaPulse
cp .env.example .env
# Edit .env (start in paper mode)

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

python main.py
```

Dashboard: `http://127.0.0.1:8080` (default).

## Docker (Recommended)

```bash
cd NovaPulse
cp .env.example .env
docker compose up -d --build
docker compose logs -f trading-bot
```

## Stress Monitor (72-96h)

```bash
cd NovaPulse
source venv/bin/activate
python stress_test.py --hours 96 --interval 5 --api-key "$DASHBOARD_READ_KEY"
```

## Live Trading Checklist (Do Not Skip)

1. Set `TRADING_MODE=paper` for 24h+ with stress monitor.
2. Set `DASHBOARD_ADMIN_KEY` and `DASHBOARD_SESSION_SECRET` (strong, non-placeholder).
3. Restrict API keys at the exchange: no withdrawals, least privilege, IP allowlist if possible.
4. Keep dashboard bound to localhost, expose only via VPN/reverse-proxy auth if needed.
5. Enable live mode only after backtests + paper performance gates pass.

