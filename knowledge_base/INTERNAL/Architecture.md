# NovaPulse Architecture

**Version:** 4.0.0
**Last Updated:** 2026-02-22

---

## System Overview

NovaPulse is a Python asyncio cryptocurrency trading bot that runs 9 technical analysis strategies in parallel, combines their signals through a confluence engine, validates them with AI/ML models, sizes positions using Kelly Criterion, and executes trades on Kraken or Coinbase exchanges.

```
+-------------------------------------------------------------------+
|                        MARKET DATA LAYER                           |
|                                                                    |
|   Kraken WS v2          Coinbase WS          REST Candle Poll      |
|   (ticker, OHLC,        (ticker, candles)     (fallback for         |
|    order book,                                 Coinbase)            |
|    trade stream)                                                   |
+--------+-----------------+-------------------+--------------------+
         |                 |                   |
         v                 v                   v
+-------------------------------------------------------------------+
|                     MarketDataCache                                |
|   RingBuffer arrays: closes, highs, lows, volumes, opens, times   |
|   Per-pair ticker cache, order book cache, book analysis cache     |
+-------------------------------------------------------------------+
         |
         v
+-------------------------------------------------------------------+
|                        BOT ENGINE                                  |
|   main.py -> BotEngine (engine.py)                                 |
|                                                                    |
|   Background tasks:                                                |
|     scan_loop          - Event-driven pair scanning                 |
|     position_loop      - Stop/trailing/TP management (2s interval) |
|     ws_loop            - WebSocket data streaming                  |
|     health_monitor     - Data freshness + circuit breakers         |
|     reconciliation     - DB vs exchange position sync (5min)       |
|     cleanup_loop       - Old metrics/thoughts pruning (hourly)     |
|     auto_retrainer     - ML model retraining                       |
|     auto_tuner         - Weekly strategy weight tuning             |
|     priority_schedule  - Crypto vs stocks session routing          |
|     dashboard_server   - Uvicorn serving FastAPI                   |
|     telegram/discord/  - Notification + command bots               |
|     slack bots                                                     |
|     es_collectors      - Fear/Greed, CoinGecko, CryptoPanic,      |
|                          on-chain data                             |
+-------------------------------------------------------------------+
         |
         v
+-------------------------------------------------------------------+
|                    CONFLUENCE DETECTOR                              |
|   9 strategies run in parallel per pair per timeframe              |
|                                                                    |
|   +----------+  +---------------+  +----------+  +-----------+    |
|   | Keltner  |  | Mean Reversion|  | Ichimoku |  | Order Flow|    |
|   | (0.30)   |  | (0.25)        |  | (0.15)   |  | (0.15)    |    |
|   +----------+  +---------------+  +----------+  +-----------+    |
|   +----------+  +------------------+  +-----------+               |
|   | Trend    |  | Stochastic Div   |  | Vol Squeeze|              |
|   | (0.15)   |  | (0.12)           |  | (0.12)     |              |
|   +----------+  +------------------+  +-----------+               |
|   +-----------+  +----------+                                      |
|   | Supertrend|  | Reversal |                                      |
|   | (0.10)    |  | (0.10)   |                                      |
|   +-----------+  +----------+                                      |
|                                                                    |
|   Multi-Timeframe: 1/5/15 min candles, 2/3 agreement required     |
|   Regime Detection: Trend/Range x High/Mid/Low Vol                 |
|   Session Analyzer: Per-hour confidence multiplier                 |
|   Strategy Guardrails: Auto-disable underperformers                |
+-------------------------------------------------------------------+
         |
         v
+-------------------------------------------------------------------+
|                      AI / ML LAYER                                 |
|                                                                    |
|   TFLitePredictor: Pre-trained signal quality model                |
|   ContinuousLearner: Online SGD updated after every closed trade   |
|   Blended confidence: 60% TFLite + 40% online (when both active)  |
+-------------------------------------------------------------------+
         |
         v
+-------------------------------------------------------------------+
|                     RISK MANAGER                                   |
|                                                                    |
|   Position sizing: Fixed-fractional (primary) + Kelly cap          |
|   ATR-based SL/TP with percentage floors (2.5% SL, 5.0% TP)      |
|   Drawdown scaling, volatility regime sizing, streak adjustment    |
|   Max concurrent positions, correlation group limits               |
|   Daily loss limit, risk of ruin check, global cooldown on loss    |
+-------------------------------------------------------------------+
         |
         v
+-------------------------------------------------------------------+
|                     TRADE EXECUTOR                                 |
|                                                                    |
|   Entry: Limit order at best ask/bid, chase up to N attempts,     |
|          fallback to market if limit fails                         |
|   Exit:  Market order with 3-retry typed exception handling        |
|   Stops: Software trailing + exchange-native stop backstop         |
|   Smart Exit: Multi-tier partial closes (50%@1xTP, 30%@1.5xTP)   |
+-------------------------------------------------------------------+
         |
         v
+-------------------------------------------------------------------+
|                   EXCHANGE REST API                                |
|                                                                    |
|   Kraken REST:  place_order, cancel_order, get_open_orders,       |
|                 get_closed_orders, get_ohlc, get_order_info        |
|   Coinbase REST: place_order, cancel_order, get_ohlc, etc.        |
+-------------------------------------------------------------------+
```

---

## Component Map

### Core Components

| File | Class/Module | Responsibility |
|------|-------------|----------------|
| `main.py` | `main()`, `run_bot()` | Entry point. Preflight checks, instance lock, top-level supervisor with restart loop, signal handling, background task orchestration |
| `src/core/engine.py` | `BotEngine` | Central orchestrator. Initializes all subsystems, runs scan/position/WS/health loops, coordinates shutdown |
| `src/core/config.py` | `ConfigManager`, `BotConfig` | Pydantic-validated config from YAML + env overrides. Thread-safe singleton with hot-reload |
| `src/core/database.py` | `DatabaseManager` | Async SQLite with WAL mode. Schema creation, migrations, tenant isolation, TTL caching |
| `src/core/control_router.py` | `ControlRouter` | Unified pause/resume/close_all/kill/status interface used by Web, Telegram, Discord, Slack |
| `src/core/logger.py` | `get_logger()`, `setup_logging()` | Structlog JSON logging with console + file + Telegram + dashboard alert sinks |
| `src/core/structures.py` | `RingBuffer` | NumPy-backed circular buffer for O(1) candle append and zero-copy sliding windows |
| `src/core/multi_engine.py` | `MultiEngineHub`, `MultiControlRouter` | Multi-exchange mode: wraps multiple BotEngine instances under one dashboard |

### AI / Strategy Components

| File | Class/Module | Responsibility |
|------|-------------|----------------|
| `src/ai/confluence.py` | `ConfluenceDetector` | Runs all 9 strategies in parallel, computes weighted confluence, applies regime/session adjustments |
| `src/ai/predictor.py` | `TFLitePredictor` | TFLite model inference for signal quality scoring |
| `src/ai/order_book.py` | `OrderBookAnalyzer` | Microstructure analysis: OBI, book score, whale detection |
| `src/ai/session_analyzer.py` | `SessionAnalyzer` | Per-hour confidence multiplier derived from historical win rates |

### Execution Components

| File | Class/Module | Responsibility |
|------|-------------|----------------|
| `src/execution/executor.py` | `TradeExecutor` | Full trade lifecycle: signal validation, order placement, fill monitoring, position management, smart exit |
| `src/execution/risk_manager.py` | `RiskManager` | Position sizing (Kelly), stop loss management (trailing/breakeven), daily loss limits, cooldowns |

### Exchange Components

| File | Class/Module | Responsibility |
|------|-------------|----------------|
| `src/exchange/kraken_ws.py` | `KrakenWebSocketClient` | Kraken WebSocket v2: ticker, OHLC, order book, trade subscriptions with auto-reconnect |
| `src/exchange/kraken_rest.py` | `KrakenRESTClient` | Kraken REST: OHLC history, order placement, account queries. Rate-limited with retry |
| `src/exchange/coinbase_rest.py` | `CoinbaseRESTClient` | Coinbase Advanced Trade REST API with JWT auth |
| `src/exchange/coinbase_ws.py` | `CoinbaseWebSocketClient` | Coinbase WebSocket for real-time data |
| `src/exchange/market_data.py` | `MarketDataCache` | In-memory OHLCV storage using RingBuffers, staleness tracking, spread calculation |
| `src/exchange/exceptions.py` | Exception hierarchy | `ExchangeError > TransientExchangeError > RateLimitError`, `PermanentExchangeError > AuthenticationError > InsufficientFundsError > InvalidOrderError` |

---

## Data Flow: Market Tick to Trade Execution

1. **Market data arrives** via Kraken WS v2 (ticker, OHLC candle, order book update)
2. **WS handler** in `BotEngine` routes to `MarketDataCache`:
   - Ticker updates: latest close price updated in-place on current bar
   - OHLC updates: new bars appended to RingBuffer; completed bars enqueue the pair for scanning
   - Book updates: order book cache refreshed; `OrderBookAnalyzer` computes OBI + book score
3. **Event-driven scan** triggers when a bar closes or price moves more than `event_price_move_pct` (default 0.5%)
4. **ConfluenceDetector.analyze_pair()** runs per timeframe (1/5/15 min):
   - Resamples 1-min OHLCV to higher timeframes
   - Detects regime (trend/range, high/mid/low vol) using ADX + Garman-Klass volatility
   - Runs all 9 strategies in parallel with 5-second timeout per strategy
   - Computes weighted confluence: strategy weights x regime multipliers x adaptive performance factor
   - Applies session-aware multiplier from historical per-hour win rates
   - Combines timeframe results (2/3 agreement required for multi-TF)
5. **AI verification**: TFLite predictor + continuous online learner blend confidence
6. **Signal filtering**: minimum confluence count (default 3), minimum confidence (default 0.55), minimum risk-reward ratio, spread check
7. **RiskManager.calculate_position_size()**: fixed-fractional risk sizing, Kelly cap, drawdown scaling, volatility regime adjustment, exposure limits
8. **TradeExecutor.execute_signal()**: validates signal age, checks gates (quiet hours, rate throttle, duplicate pair, correlation group, cooldown), places limit order
9. **Order fill**: limit chase with N attempts + market fallback; exchange-native stop-loss placed as crash-proof backstop
10. **Position management loop** (every 2 seconds): updates trailing stops, checks stop-out/take-profit, runs smart exit tiers
11. **Trade closure**: market exit order with 3-retry typed exception handling, P&L calculation with entry+exit fees, ML label update, continuous learner feedback

---

## Multi-Timeframe Architecture

NovaPulse supports multi-timeframe analysis using 1-minute base candles:

```
1-min candles (base)
    |
    +-- Resample to 5-min  ---> Run all 9 strategies ---> Per-TF confluence signal
    |
    +-- Resample to 15-min ---> Run all 9 strategies ---> Per-TF confluence signal
    |
    +-- Use 1-min directly ---> Run all 9 strategies ---> Per-TF confluence signal
    |
    v
Combine timeframes:
  - Primary TF drives direction (default: 1-min)
  - 2/3 agreement required (configurable via multi_timeframe_min_agreement)
  - Confidence bonus scaled by TF weight (1-min: 1.0, 5-min: 1.3, 15-min: 1.5)
  - SL/TP taken from highest agreeing TF (wider = more survivable)
```

---

## Multi-Engine Mode

When `TRADING_ACCOUNTS` or `TRADING_EXCHANGES` is set, NovaPulse runs multiple `BotEngine` instances:

```
Account Specs: "main:kraken,swing:coinbase"
    |
    +-- BotEngine (kraken, account=main, db=data/trading_kraken_main.db)
    |
    +-- BotEngine (coinbase, account=swing, db=data/trading_coinbase_swing.db)
    |
    v
MultiEngineHub (wraps both engines for dashboard)
MultiControlRouter (routes pause/resume to all engines)
Single DashboardServer (shared uvicorn instance)
```

Each engine has its own:
- Database file (isolated by exchange + account_id)
- REST client with per-account API keys (resolved via `{ACCOUNT_PREFIX}_{KEY_NAME}` env vars)
- WebSocket connection
- Background task set

---

## Dashboard Server Architecture

The dashboard is a FastAPI application served by uvicorn on port 8080 (container):

```
Client Browser / API Consumer
         |
    [Reverse Proxy] (optional HTTPS termination)
         |
    Host port 8090 --> Container port 8080
         |
    FastAPI (DashboardServer in src/api/server.py)
         |
    +-- GET  /api/v1/health       (public, no auth)
    +-- GET  /api/v1/status       (auth required)
    +-- GET  /api/v1/trades       (auth required)
    +-- GET  /api/v1/positions    (auth required)
    +-- GET  /api/v1/performance  (auth required)
    +-- GET  /api/v1/strategies   (auth required)
    +-- GET  /api/v1/risk         (auth required)
    +-- GET  /api/v1/thoughts     (auth required)
    +-- GET  /api/v1/scanner      (auth required)
    +-- POST /api/v1/control/*    (admin key required)
    +-- POST /api/v1/signal       (webhook secret required)
    +-- POST /api/v1/billing/*    (Stripe webhooks)
    +-- WS   /ws/live             (auth via query param)
    +-- POST /api/v1/login        (session-based web auth)
    +-- GET  /                    (static HTML dashboard)
```

Authentication model:
- `DASHBOARD_ADMIN_KEY` (or legacy `DASHBOARD_SECRET_KEY`): full admin access, required in live mode
- `DASHBOARD_READ_KEY`: read-only access to data endpoints
- Tenant API keys: per-tenant scoped access, resolved via hashed lookup in `tenant_api_keys` table
- Session-based web auth: username/password login with CSRF protection, cookie-based sessions

---

## Database Architecture

SQLite with WAL mode for concurrent read/write:

```
data/trading.db
  |
  +-- trades              (all trade records with tenant_id)
  +-- thought_log         (AI decision log for dashboard feed)
  +-- metrics             (time-series performance metrics)
  +-- ml_features         (feature vectors tied to trades)
  +-- order_book_snapshots (book state at entry for ML)
  +-- signals             (raw strategy signal log)
  +-- daily_summary       (per-day aggregate stats, per-tenant unique)
  +-- system_state        (key-value store for runtime state)
  +-- tenants             (multi-tenant registry with Stripe IDs)
  +-- tenant_api_keys     (hashed API key -> tenant_id mapping)
  +-- stripe_webhook_events (idempotency for Stripe webhooks)
  +-- signal_webhook_events (idempotency for signal webhooks)
  +-- backtest_runs       (backtest/optimization history)
  +-- copy_trading_providers (webhook signal provider registry)
```

WAL mode PRAGMAs applied at startup:
- `journal_mode=WAL` (concurrent readers + single writer)
- `synchronous=NORMAL` (durability vs performance tradeoff)
- `cache_size=-16000` (16MB page cache)
- `temp_store=MEMORY`
- `mmap_size=67108864` (64MB memory-mapped I/O)

---

## Docker Deployment Model

```
docker-compose.yml
  |
  +-- trading-bot (novapulse)
  |     Build: Dockerfile
  |     Ports: 8090:8080 (configurable via HOST_PORT/DASHBOARD_PORT)
  |     Volumes:
  |       ./data -> /app/data       (SQLite DBs, instance lock)
  |       ./logs -> /app/logs       (structlog output)
  |       ./models -> /app/models   (TFLite models)
  |       ./config -> /app/config:ro (config.yaml, read-only)
  |       ./.secrets -> /app/.secrets:ro (Telegram secrets)
  |     Resources: 2GB RAM, 2 CPUs (limits); 512MB, 0.5 CPU (reservations)
  |     Health: curl /api/v1/health every 30s
  |     Restart: unless-stopped
  |
  +-- elasticsearch (optional)
        Health: cluster health check
        Condition: service_healthy (soft dependency)
```

The bot runs as UID/GID from `BOT_UID`/`BOT_GID` env vars (default 1000) for bind mount permission compatibility.

---

## Lifecycle and Restart Behavior

1. `main()` runs preflight checks (directories, config, instance lock)
2. Top-level supervisor loop: up to 10 restarts with exponential backoff (2s-60s)
3. `run_bot()` initializes subsystems in dependency order:
   - Database (CRITICAL - failure aborts startup)
   - Exchange clients (CRITICAL)
   - Market data + session analyzer
   - AI components (NON-CRITICAL - failure logged, skipped)
   - Risk management + trade execution
   - ML training components (NON-CRITICAL)
   - Dashboard + billing (NON-CRITICAL)
   - Notifications (NON-CRITICAL)
   - Elasticsearch pipeline (NON-CRITICAL)
4. Background tasks run with `_run_with_restart()` wrapper: auto-restart on error with exponential backoff, auto-pause trading after 3 consecutive critical task failures
5. Shutdown on SIGINT/SIGTERM: cancel all tasks (15s timeout), close resources, flush ES buffer

Instance lock (`data/instance.lock`) prevents duplicate bot processes on the same host/volume.
