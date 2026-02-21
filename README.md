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
25. Rate limiting (token bucket; per-IP with stale eviction)
26. Security headers + `Cache-Control: no-store` for API responses
27. Audit log stream ("thought log") for decisions and operator actions
28. Telegram command center (status, pause/resume, close_all, kill) + scheduled check-ins
29. CSV export of trades for reconciliation
30. 72-96 hour stress monitor (API/WS/data freshness/activity) with auth support
31. Signed signal webhook intake (`/api/v1/signals/webhook`) with idempotency tracking
32. Backtest + optimization API endpoints (`/api/v1/backtest/run`, `/api/v1/backtest/optimize`)
33. Strategy marketplace templates + apply endpoint
34. Copy-trading provider registry (tenant-scoped)
35. Ops heartbeat endpoint + VPS watchdog helper (`scripts/vps_watchdog.py`)

Resilience:
- **Graceful Error Handler** ("Trade or Die"): classifies errors as CRITICAL / DEGRADED / TRANSIENT. Only exchange-auth or database failures stop trading. All other subsystem failures (Telegram, Discord, Slack, dashboard, ML, billing) are logged and skipped so the bot keeps trading.

## Security Notes (Reality Check)

This repo is hardened with fail-closed defaults and multiple safety nets, but no software can guarantee "zero risk." Treat any system that can place real orders as high-risk: run behind a firewall/VPN, rotate keys, and use exchange API key restrictions (IP allowlists, no-withdrawal keys).

## Quick Start (Docker -- Recommended)

```bash
git clone https://github.com/dmitriy718/NovaPulse.git
cd NovaPulse
cp .env.example .env
# Edit .env with your API keys (paper mode by default)

./SuperStart.sh
```

This builds the Docker image, starts the container, and waits for it to become healthy.

Dashboard: `http://127.0.0.1:8090` (default host binding).

## SuperStart.sh Commands

| Command | Description |
|---------|-------------|
| `./SuperStart.sh` | Build & start the trading bot |
| `./SuperStart.sh --stress` | Quick 5-minute stress test |
| `./SuperStart.sh --stress72` | Full 72-hour stress monitor |
| `./SuperStart.sh --stop` | Stop all containers |
| `./SuperStart.sh --logs` | Follow live container logs |
| `./SuperStart.sh --status` | Show container health & status |
| `./SuperStart.sh --rebuild` | Force rebuild image (no cache) |
| `./SuperStart.sh --shell` | Open shell in running container |
| `./SuperStart.sh --help` | Show help |

Set `FAST_SETUP=1` to skip `git pull` on start.

## Docker Compose (Manual)

```bash
cd NovaPulse
cp .env.example .env
docker compose up -d --build
docker compose logs -f trading-bot
```

## Stress Test

The stress monitor is a non-disruptive, observation-only resilience checker. It periodically hits the bot's API, WebSocket, and data freshness endpoints to verify the bot is alive and trading.

```bash
# Quick 5-minute test (via Docker)
./SuperStart.sh --stress

# Full 72-hour monitor (via Docker)
./SuperStart.sh --stress72

# Manual (local Python)
python stress_test.py --hours 96 --interval 5 --api-key "$DASHBOARD_READ_KEY"
```

## Quick Start (Local -- No Docker)

```bash
cd NovaPulse
cp .env.example .env
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

## Health Monitoring

Automated health checks and log watchers with Telegram notifications:

```bash
# One-shot health check (cron-friendly)
./scripts/health_check.sh

# Live error log watcher
./scripts/log_watch.sh
```

`scripts/health_check.sh` now aggregates across all resolved account/exchange DB files (not just the first DB).

For unattended VPS operation, run:

```bash
python scripts/vps_watchdog.py --url "http://127.0.0.1:8090/api/v1/ops/heartbeat" --api-key "$DASHBOARD_READ_KEY"
```

## Live Trading Checklist (Do Not Skip)

1. Set `TRADING_MODE=paper` for 24h+ with stress monitor.
2. Set `DASHBOARD_ADMIN_KEY` and `DASHBOARD_SESSION_SECRET` (strong, non-placeholder).
3. For production UI on `nova.horizonsvc.com`, set
   `DASHBOARD_PUBLIC_ORIGIN=https://nova.horizonsvc.com` and
   `DASHBOARD_CORS_ORIGINS=https://nova.horizonsvc.com`.
4. Restrict API keys at the exchange: no withdrawals, least privilege, IP allowlist if possible.
5. If `SIGNAL_WEBHOOK_ENABLED=true`, set `SIGNAL_WEBHOOK_SECRET` and source allowlist (`SIGNAL_WEBHOOK_ALLOWED_SOURCES`).
6. If billing is enabled, set `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, and paid plan IDs (`STRIPE_PRICE_ID_PRO` and/or `STRIPE_PRICE_ID_PREMIUM`; `STRIPE_PRICE_ID` remains legacy fallback), then expose `POST /api/v1/billing/webhook`.
7. Keep dashboard bound to localhost, expose only via VPN/reverse-proxy auth if needed.
8. Enable live mode only after backtests + paper performance gates pass.

## Architecture

```
main.py (lifecycle supervisor with retry + jitter)
  |
  +-- GracefulErrorHandler ("Trade or Die" error classification)
  +-- BotEngine (single-exchange) or MultiEngineHub (multi-exchange)
       |
       +-- KrakenRESTClient / CoinbaseRESTClient
       +-- KrakenWebSocketClient / CoinbaseWebSocketClient
       +-- MarketDataCache (RingBuffer-backed OHLCV per pair)
       +-- ConfluenceDetector (8 strategies + regime detection)
       +-- TFLitePredictor (optional AI gating)
       +-- ContinuousLearner (online SGD)
       +-- OrderBookAnalyzer (microstructure scoring)
       +-- RiskManager (Kelly, trailing stops, circuit breakers)
       +-- TradeExecutor (limit orders, paper/live, partial fills)
       +-- DatabaseManager (SQLite WAL, multi-tenant, canonical ledger)
       +-- Elasticsearch pipeline (analytics/enrichment mirror, non-canonical)
       +-- DashboardServer (FastAPI + WebSocket)
       +-- ControlRouter -> TelegramBot / DiscordBot / SlackBot
       +-- ModelTrainer + AutoRetrainer (ProcessPoolExecutor)
       +-- StripeService (billing webhooks)
```

## Persistence Contract and Storage Paths

Canonical ledger and source of truth:

- SQLite is the only canonical trading ledger.
- Elasticsearch is analytics/enrichment mirror only (non-canonical).

Where data is saved:

- Crypto engine DB (single account): `data/trading.db`
- Crypto engine DB (multi-account): `data/trading_<exchange>_<account>.db`
- Stocks engine DB: `data/stocks.db`
- Model artifacts: `models/trade_predictor.tflite`, `models/normalization.json`, `models/continuous_sgd.joblib`
- Runtime logs: `logs/trading_bot.log`, `logs/errors.log`

How to verify live storage mapping:

```bash
curl -s -H "X-API-Key: $DASHBOARD_READ_KEY" http://127.0.0.1:8090/api/v1/storage
```

Startup logs now print:

- resolved SQLite absolute path per engine/account
- WAL/SHM file presence
- explicit persistence contract (`canonical_ledger=sqlite`, `elasticsearch_role=analytics_mirror`)
- ES sink target (`cloud` or `hosts`) and index prefix

## v3.0.0 Changelog

- Graceful Error Handler: "Trade or Die" error classification (CRITICAL / DEGRADED / TRANSIENT)
- Non-critical subsystem failures no longer prevent bot startup or trading
- Fixed: Coinbase WS sync callback crash
- Fixed: Discord bot open authorization (now deny-by-default)
- Fixed: Stripe global API key thread-safety
- Fixed: Kraken/Coinbase REST truthiness bugs (`start=0`, `since=0`)
- Fixed: Rate limiter memory leak (stale IP eviction)
- Fixed: Slack bot deprecated API + missing await
- Fixed: Version string consistency (single source of truth)
- Fixed: Kraken WS latency tracking
- Docker-first deployment via SuperStart.sh
- Stress test containerized (runs via docker compose)
