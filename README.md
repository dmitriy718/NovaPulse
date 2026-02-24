# NovaPulse (v4.5.0)

Operator-grade AI trading system: multi-strategy signal engine across crypto and stocks, risk-first execution with adaptive exits, hardened control plane, and continuous self-improvement.

## What You Get (55+ Features)

Trading + Intelligence:
1. Multi-pair market scanning (configurable interval, 8 default crypto pairs + 96 dynamic stocks)
2. Multi-exchange support (Kraken WS v2 + REST, Coinbase Advanced Trade, Alpaca stocks)
3. Twelve parallel TA strategies (Keltner, Mean Reversion, Volatility Squeeze, VWAP Momentum Alpha, Order Flow, Market Structure, Supertrend, Funding Rate, Trend, Ichimoku, Stochastic Divergence, Reversal)
4. Strategy confluence scoring with adaptive weighting (Sharpe-based sliding window)
5. Strategy family diversity scoring (7 families: mean reversion, trend following, momentum, microstructure, VWAP, structure, sentiment)
6. Multi-timeframe analysis (1/5/15-min candles, 2/3 agreement required)
7. Volatility regime detection (Garman-Klass) with regime-specific strategy weight multipliers (capped at 2.0x)
8. Order-book microstructure weighting (imbalance + spoof heuristics)
9. Funding rate integration (Kraken Futures perpetual funding rates as sentiment signal)
10. AI entry gating model (TFLite when available; safe fallback when not)
11. Continuous learner (online SGD, incremental) for non-blocking improvement over time
12. Session-aware trading (per-hour confidence multipliers from historical win rates)
13. Auto Strategy Tuner (weekly performance analysis, auto-disable underperformers)
14. Dynamic stock universe scanner (96 stocks: 4 pinned + 92 by volume, hourly refresh)
15. Paper trading mode (default) and live trading mode (explicit enable)
16. Backtester (same logic as live path; used for promotion gates)
17. Feature logging for every decision (for later supervised training)

Execution + Risk:
18. Kelly Criterion position sizing (quarter-Kelly with cap) + fixed-fractional fallback
19. Correlation-based position sizing (Pearson corr > 0.7 → automatic size reduction)
20. Cross-engine risk aggregation (GlobalRiskAggregator caps total exposure across all exchanges)
21. ATR-based initial stop loss and take profit with percentage-based floors (2.5% SL / 5.0% TP)
22. Dynamic trailing stops (configurable activation + step size)
23. Volatility-regime-aware trailing stops (wider in high vol, tighter in low vol)
24. Breakeven activation logic (moves SL to entry after configurable profit)
25. Smart exit system (multi-tier partial position closing at 1x, 1.5x, trailing)
26. Time-based exit tightening (stagnant positions get targets reduced)
27. Risk-of-ruin monitoring and exposure throttling
28. Daily loss limit and drawdown-scaled sizing
29. Trade cooldowns (global + per-strategy, configurable per strategy)
30. Max concurrent positions with correlation group limiting
31. Slippage/spread sanity checks (configurable)
32. Circuit breakers (stale data, WS disconnect, consecutive losses, drawdown) that auto-pause trading
33. Exchange-native stop orders as crash-proof backstop (survives bot downtime)
34. Trade rate throttle and quiet hours filtering
35. Typed exchange exception hierarchy (transient vs permanent errors, smart retry)
36. Single-instance host lock to prevent double-trading on the same volume

Control Plane + Observability:
37. FastAPI dashboard (40+ REST endpoints + WebSocket live stream)
38. Secure-by-default auth: web login session (httpOnly cookie) or API keys
39. Key scoping: separate read key vs admin/control key (admin-only by default)
40. CSRF protection for cookie-auth control actions (double-submit token)
41. Rate limiting (token bucket; per-IP with stale eviction) + login brute-force protection
42. Security headers + `Cache-Control: no-store` for API responses
43. Audit log stream ("thought log") for all decisions and operator actions
44. Telegram command center (15+ commands: status, pnl, positions, risk, health, strategies, pause/resume, close_all, kill) + scheduled 30-min check-ins
45. Discord and Slack bot integrations with slash commands
46. CSV export of trades for reconciliation
47. 72-96 hour stress monitor (API/WS/data freshness/activity) with auth support
48. Signed signal webhook intake (`/api/v1/signals/webhook`) with idempotency tracking
49. Backtest + optimization API endpoints (`/api/v1/backtest/run`, `/api/v1/backtest/optimize`)
50. Strategy marketplace templates + apply endpoint
51. Copy-trading provider registry (tenant-scoped)
52. Ops heartbeat endpoint + VPS watchdog helper (`scripts/vps_watchdog.py`)
53. Stripe billing integration (Pro/Premium plans) with multi-tenant isolation
54. Elasticsearch analytics mirror (trades, candles, orderbook, sentiment, on-chain)
55. Priority scheduler (auto-switches between crypto and stock trading based on market hours)

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
  +-- PriorityScheduler (crypto vs stocks session routing)
  +-- BotEngine (single-exchange) or MultiEngineHub (multi-exchange)
  |    |
  |    +-- KrakenRESTClient / CoinbaseRESTClient
  |    +-- KrakenWebSocketClient / CoinbaseWebSocketClient
  |    +-- FundingRateClient (Kraken Futures public API)
  |    +-- MarketDataCache (RingBuffer-backed OHLCV per pair)
  |    +-- ConfluenceDetector (12 strategies + regime detection + MTF + family diversity)
  |    +-- TFLitePredictor (optional AI gating)
  |    +-- ContinuousLearner (online SGD)
  |    +-- OrderBookAnalyzer (microstructure scoring)
  |    +-- RiskManager (Kelly, trailing stops, circuit breakers, correlation sizing)
  |    +-- GlobalRiskAggregator (cross-engine exposure cap)
  |    +-- TradeExecutor (limit orders, paper/live, partial fills, adaptive exits)
  |    +-- DatabaseManager (SQLite WAL, multi-tenant, canonical ledger)
  |    +-- Elasticsearch pipeline (analytics/enrichment mirror, non-canonical)
  |    +-- DashboardServer (FastAPI + WebSocket)
  |    +-- ControlRouter -> TelegramBot / DiscordBot / SlackBot
  |    +-- ModelTrainer + AutoRetrainer (ProcessPoolExecutor)
  |    +-- StripeService (billing webhooks)
  |
  +-- StockSwingEngine
       +-- PolygonClient (daily bars)
       +-- AlpacaClient (order execution)
       +-- UniverseScanner (96 dynamic stocks)
```

## Strategy Portfolio (12 Strategies)

| Strategy | Weight | Family | Signal Basis |
|----------|--------|--------|--------------|
| Keltner Channel | 0.25 | Mean Reversion | KC band rebounds + MACD/RSI |
| Mean Reversion | 0.20 | Mean Reversion | BB extremes + RSI divergence |
| Volatility Squeeze | 0.18 | Momentum | TTM Squeeze (BB inside KC) + breakout |
| VWAP Momentum Alpha | 0.15 | VWAP | VWAP pullbacks in trending markets |
| Order Flow | 0.12 | Microstructure | Order book imbalance + spread |
| Market Structure | 0.12 | Structure | Swing HH/HL/LH/LL + pullback |
| Supertrend | 0.12 | Trend Following | ATR-based trend flips + volume |
| Funding Rate | 0.10 | Sentiment | Perpetual funding rate extremes |
| Trend | 0.08 | Trend Following | Fresh EMA cross + ADX filter |
| Ichimoku | 0.08 | Trend Following | Cloud/TK cross system |
| Stochastic Divergence | 0.06 | Mean Reversion | Stochastic K/D + price divergence |
| Reversal | 0.06 | Mean Reversion | Extreme RSI + confirmation candles |

## Persistence Contract and Storage Paths

Canonical ledger and source of truth:

- SQLite is the only canonical trading ledger.
- Elasticsearch is analytics/enrichment mirror only (non-canonical).

Where data is saved:

- Crypto engine DB (single account): `data/trading.db`
- Crypto engine DB (multi-account): `data/trading_<exchange>_<account>.db`
- Stocks engine DB: `data/trading_stocks_default.db`
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

## Full Changelog

See [CHANGELOG.md](CHANGELOG.md) for complete version history from v3.0.0 through v4.5.0.

## Documentation

- **Client documentation:** [`knowledge_base/CLIENT/`](knowledge_base/CLIENT/README.md) — user-facing guides
- **Internal documentation:** [`knowledge_base/INTERNAL/`](knowledge_base/INTERNAL/README.md) — developer/ops reference
- **Code reviews:** [`preflight/`](preflight/) — deep codebase review reports
