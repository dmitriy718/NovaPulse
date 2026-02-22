# NovaPulse (v4.0)

Operator-grade AI crypto trading system: multi-strategy signal engine, risk-first execution, hardened control plane, and continuous self-improvement (guardrailed).

## What You Get (35+ Features)

Trading + Intelligence:
1. Multi-pair market scanning (configurable interval, 8 default crypto pairs)
2. Multi-exchange support (Kraken WS v2 + REST, Coinbase Advanced Trade)
3. Nine parallel TA strategies (Keltner, Mean Reversion, Ichimoku, Order Flow, Trend, Stochastic Divergence, Volatility Squeeze, Supertrend, Reversal)
4. Strategy confluence scoring with adaptive weighting (Sharpe-based sliding window)
5. Multi-timeframe analysis (1/5/15-min candles, 2/3 agreement required)
6. Volatility regime detection (Garman-Klass) with regime-specific strategy weight multipliers
7. Order-book microstructure weighting (imbalance + spoof heuristics)
8. AI entry gating model (TFLite when available; safe fallback when not)
9. Continuous learner (online SGD, incremental) for non-blocking improvement over time
10. Session-aware trading (per-hour confidence multipliers from historical win rates)
11. Auto Strategy Tuner (weekly performance analysis, auto-disable underperformers)
12. Paper trading mode (default) and live trading mode (explicit enable)
13. Backtester (same logic as live path; used for promotion gates)
14. Feature logging for every decision (for later supervised training)

Execution + Risk:
15. Kelly Criterion position sizing (quarter-Kelly with cap) + fixed-fractional fallback
16. ATR-based initial stop loss and take profit with percentage-based floors (2.5% SL / 5.0% TP)
17. Dynamic trailing stops (configurable activation + step size)
18. Breakeven activation logic (moves SL to entry after configurable profit)
19. Smart exit system (multi-tier partial position closing at 1x, 1.5x, trailing)
20. Risk-of-ruin monitoring and exposure throttling
21. Daily loss limit and drawdown-scaled sizing
22. Trade cooldowns (global + per-strategy, configurable per strategy)
23. Max concurrent positions with correlation group limiting (prevents overexposure to similar assets)
24. Slippage/spread sanity checks (configurable)
25. Circuit breakers (stale data, WS disconnect, consecutive losses, drawdown) that auto-pause trading
26. Exchange-native stop orders as crash-proof backstop (survives bot downtime)
27. Trade rate throttle and quiet hours filtering
28. Typed exchange exception hierarchy (transient vs permanent errors, smart retry)
29. Single-instance host lock to prevent double-trading on the same volume

Control Plane + Observability:
30. FastAPI dashboard (40+ REST endpoints + WebSocket live stream)
31. Secure-by-default auth: web login session (httpOnly cookie) or API keys
32. Key scoping: separate read key vs admin/control key (admin-only by default)
33. CSRF protection for cookie-auth control actions (double-submit token)
34. Rate limiting (token bucket; per-IP with stale eviction) + login brute-force protection
35. Security headers + `Cache-Control: no-store` for API responses
36. Audit log stream ("thought log") for all decisions and operator actions
37. Telegram command center (15+ commands: status, pnl, positions, risk, health, strategies, pause/resume, close_all, kill) + scheduled 30-min check-ins
38. Discord and Slack bot integrations with slash commands
39. CSV export of trades for reconciliation
40. 72-96 hour stress monitor (API/WS/data freshness/activity) with auth support
41. Signed signal webhook intake (`/api/v1/signals/webhook`) with idempotency tracking
42. Backtest + optimization API endpoints (`/api/v1/backtest/run`, `/api/v1/backtest/optimize`)
43. Strategy marketplace templates + apply endpoint
44. Copy-trading provider registry (tenant-scoped)
45. Ops heartbeat endpoint + VPS watchdog helper (`scripts/vps_watchdog.py`)
46. Stripe billing integration (Pro/Premium plans) with multi-tenant isolation
47. Elasticsearch analytics mirror (trades, candles, orderbook, sentiment, on-chain)

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
       +-- ConfluenceDetector (9 strategies + regime detection + MTF)
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

## v4.0.0 Changelog (Strategy Overhaul)

New Strategies:
- **Ichimoku Cloud**: Replaces VWAP Momentum Alpha — cloud crossovers, Tenkan/Kijun analysis
- **Order Flow**: Microstructure-based signals from order book data (book score, imbalance, spread)
- **Stochastic Divergence**: Replaces RSI Mean Reversion — stochastic oscillator + price divergence detection
- **Volatility Squeeze**: Replaces Breakout — TTM Squeeze concept (BB inside KC + momentum breakout)
- **Supertrend**: ATR-based adaptive trend identification with volume confirmation

Removed Strategies (poor live performance):
- Momentum (8% WR), Breakout (0% WR), VWAP Momentum Alpha (33% WR), RSI Mean Reversion

New Features:
- Multi-timeframe analysis: 1/5/15-minute candles, 2/3 agreement required for entry
- Volatility regime detection (Garman-Klass) with regime-specific strategy weight multipliers
- Session-aware trading: per-hour confidence multipliers from historical win rates
- Auto Strategy Tuner: weekly DB analysis, auto-disable underperformers (Sharpe < -0.3)
- Smart exit system: multi-tier partial position closing (50%@1xTP, 30%@1.5xTP, 20% trailing)
- Exchange-native stop orders as crash-proof backstop
- Typed exchange exception hierarchy (transient vs permanent, smart retry strategy)
- Correlation group position limits (prevent overexposure to correlated assets)
- Trade rate throttle and quiet hours filtering
- Pydantic validators for all critical financial config values
- Login brute-force protection (5 failures in 5-min window = lockout)
- Multi-plan Stripe billing (Pro/Premium)

Performance Improvements:
- Parallelized position management (`asyncio.gather` for all open positions)
- O(1) trade lookup via `get_trade_by_id` (replaces full table scans)
- Consolidated performance stats into 2 SQL queries with 5s TTL cache (was 7 queries)
- Vectorized OHLCV resampling with NumPy
- RingBuffer contiguous optimization
- In-memory favorites cache

Architecture Improvements:
- Decomposed `execute_signal` into 5 focused methods
- Decomposed `initialize()` into 5 factory methods
- Extracted `_exit_live_order` retry helper
- Extracted `_parse_meta` helper (replaced 8 duplicate parsing sites)
- Promoted auth helpers from closure scope to class methods
- `EngineInterface` Protocol for control router decoupling
- Eliminated runtime `get_config()` from executor (constructor injection)
- ConfigManager reset fixture for test isolation

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
