# Nova|Pulse Architecture

**Version:** 5.0.0
**Last Updated:** 2026-03-01

---

## System Overview

Nova|Pulse is a Python asyncio multi-asset trading bot. It runs 12 technical analysis strategies in parallel across crypto and stock markets, combines their signals through a confluence engine with family diversity scoring, validates them with AI/ML models, sizes positions using Kelly Criterion with correlation adjustment, and executes trades on Kraken, Coinbase, and Alpaca with adaptive exit management.

The system is designed as a single-process, multi-task asyncio application deployed in Docker. All persistence is via SQLite (WAL mode). An optional Elasticsearch pipeline provides analytics mirroring.

---

## High-Level Data Flow

```
+-------------------------------------------------------------------+
|                        MARKET DATA LAYER                           |
|                                                                    |
|   Kraken WS v2          Coinbase WS          Polygon REST          |
|   (ticker, OHLC,        (ticker, candles)     (daily bars,         |
|    order book,                                 grouped bars)        |
|    trade stream)         Coinbase REST                              |
|                          (candle polling                            |
|                           every 60s)                                |
+--------+-----------------+-------------------+--------------------+
         |                 |                   |
         v                 v                   v
+-------------------------------------------------------------------+
|                     MarketDataCache                                |
|   RingBuffer arrays: closes, highs, lows, volumes, opens, times   |
|   Per-pair ticker cache, order book cache, book analysis cache     |
|   Stale detection, warmup tracking                                 |
+-------------------------------------------------------------------+
         |
         v
+-------------------------------------------------------------------+
|                    BOT ENGINE (engine.py)                          |
|                                                                    |
|   Background tasks (asyncio.create_task with _run_with_restart):   |
|     _main_scan_loop       - Pair scanning (event + timer driven)   |
|     _position_mgmt_loop   - SL/TP/trailing management (2s)        |
|     _ws_data_loop         - WebSocket streaming                    |
|     _health_monitor       - Data freshness, circuit breakers       |
|     _reconciliation_loop  - DB vs exchange position sync (5min)    |
|     _cleanup_loop         - Prune old metrics/thoughts (hourly)    |
|     auto_retrainer        - ML model retraining                    |
|     auto_tuner            - Weekly strategy weight tuning          |
|     priority_schedule     - Crypto vs stocks session routing       |
|     dashboard_server      - Uvicorn serving FastAPI                |
|     telegram/discord/slack - Notification bots                     |
|     es_collectors         - External data ingestion                |
+-------------------------------------------------------------------+
         |
         v
+-------------------------------------------------------------------+
|                    CONFLUENCE DETECTOR                              |
|   12 strategies run in parallel per pair per timeframe             |
|                                                                    |
|   Keltner(0.25) MeanRev(0.20) VolSqueeze(0.18) VWAP(0.15)       |
|   OrderFlow(0.12) MktStruct(0.12) Supertrend(0.12) FundRate(0.10)|
|   Trend(0.08) Ichimoku(0.08) StochDiv(0.06) Reversal(0.06)       |
|                                                                    |
|   -> Weighted scoring -> Regime multipliers -> Family diversity    |
|   -> Opposition penalty -> OBI vote -> ConfluenceSignal           |
+-------------------------------------------------------------------+
         |
         v
+-------------------------------------------------------------------+
|                    AI INTELLIGENCE LAYER                            |
|                                                                    |
|   TFLitePredictor    SessionAnalyzer    LeadLagTracker (v5.0)     |
|   ContinuousLearner  RegimeTransitionPredictor (v5.0)             |
|   EnsembleModel (v5.0)  OnChainDataClient (v5.0)                 |
|   BayesianOptimizer (v5.0)  EventCalendar (v5.0)                 |
+-------------------------------------------------------------------+
         |
         v
+-------------------------------------------------------------------+
|                    RISK MANAGEMENT                                  |
|                                                                    |
|   RiskManager           GlobalRiskAggregator (singleton)           |
|   - Kelly Criterion     - Cross-engine exposure                    |
|   - ATR stops           AnomalyDetector (v5.0)                    |
|   - Correlation sizing  - Spread/volume/depth monitoring           |
|   - Structural stops    - Auto-pause on anomaly                    |
|   - Liquidity sizing                                               |
+-------------------------------------------------------------------+
         |
         v
+-------------------------------------------------------------------+
|                    TRADE EXECUTOR                                   |
|                                                                    |
|   execute_signal -> validate -> size -> place_order                |
|   Smart exit tiers -> trailing management -> position close        |
|   Limit entry with chase -> market fallback                        |
|   Paper mode simulation -> Live mode exchange orders               |
+-------------------------------------------------------------------+
         |
         v
+-------------------------------------------------------------------+
|                    EXCHANGE REST APIs                               |
|   Kraken REST | Coinbase REST | Alpaca REST                       |
+-------------------------------------------------------------------+
         |
         v
+-------------------------------------------------------------------+
|                    PERSISTENCE                                      |
|   SQLite (WAL mode)        Elasticsearch (optional mirror)         |
|   - trades, positions      - candles, order book, trades           |
|   - thought_log            - Fear/Greed, CoinGecko, CryptoPanic   |
|   - ml_features            - on-chain data                         |
|   - strategy_attribution   Index lifecycle management              |
|   - anomaly_events                                                 |
+-------------------------------------------------------------------+
```

---

## Component Inventory

### Core (`src/core/`)

| File | Class/Function | Purpose |
|------|---------------|---------|
| `engine.py` | `BotEngine` | Main orchestrator, owns all subsystems, manages lifecycle |
| `config.py` | `ConfigManager`, Pydantic models | Typed config with validation, `get_config()`, `load_config_with_overrides()` |
| `database.py` | `DatabaseManager` | SQLite WAL, async operations, schema migrations, TTL cache for perf stats |
| `control_router.py` | `ControlRouter`, `EngineInterface` | Unified control plane (pause/resume/close_all/kill/status) |
| `multi_engine.py` | `MultiEngineHub`, `MultiControlRouter` | Multi-exchange aggregation, `resolve_db_path()`, `resolve_trading_accounts()` |
| `logger.py` | `get_logger()`, `setup_logging()` | Structlog JSON logging with rotation |
| `structures.py` | `RingBuffer` | Fixed-size NumPy array buffer for OHLCV data |
| `error_handler.py` | `GracefulErrorHandler` | Error classification (CRITICAL/DEGRADED/TRANSIENT) |
| `runtime_safety.py` | Exception handlers | Global and asyncio exception handlers |

### AI (`src/ai/`)

| File | Class | Purpose |
|------|-------|---------|
| `confluence.py` | `ConfluenceDetector`, `ConfluenceSignal` | Runs all strategies, computes confluence, produces signals |
| `predictor.py` | `TFLitePredictor` | TFLite model inference for trade scoring |
| `order_book.py` | `OrderBookAnalyzer` | Order book imbalance, book score, whale detection |
| `session_analyzer.py` | `SessionAnalyzer` | Per-hour win rate tracking, confidence multipliers |
| `lead_lag.py` | `LeadLagTracker` | (v5.0) BTC/ETH leader move -> follower confidence adj |
| `regime_predictor.py` | `RegimeTransitionPredictor` | (v5.0) Squeeze/ADX/vol/chop voting for transition state |
| `ensemble_model.py` | `EnsembleModel` | (v5.0) LightGBM + TFLite weighted average |
| `bayesian_optimizer.py` | `BayesianOptimizer` | (v5.0) Optuna TPE parameter search |

### Execution (`src/execution/`)

| File | Class | Purpose |
|------|-------|---------|
| `executor.py` | `TradeExecutor` | Order placement, fill processing, smart exit, P&L recording |
| `risk_manager.py` | `RiskManager`, `PositionSizeResult`, `StopLossState` | Kelly sizing, stops, trailing, breakeven, daily limits |
| `global_risk.py` | `GlobalRiskAggregator` | Singleton cross-engine exposure cap |
| `anomaly_detector.py` | `AnomalyDetector` | (v5.0) Spread/volume/depth anomaly detection + pause |

### Exchange (`src/exchange/`)

| File | Class | Purpose |
|------|-------|---------|
| `kraken_ws.py` | `KrakenWebSocketClient` | Kraken WS v2: subscribe, reconnect, data dispatch |
| `kraken_rest.py` | `KrakenRESTClient` | Kraken REST: candles, balances, orders, signed requests |
| `coinbase_rest.py` | `CoinbaseRESTClient` | Coinbase Advanced Trade: candles, orders, balances |
| `coinbase_ws.py` | `CoinbaseWebSocketClient` | Coinbase WS: ticker, order book |
| `market_data.py` | `MarketDataCache` | RingBuffer OHLCV per pair, ticker cache, stale detection |
| `funding_rates.py` | `FundingRateClient` | Kraken Futures public API, 5-min TTL cache, circuit breaker |
| `exceptions.py` | `TransientExchangeError`, `PermanentExchangeError`, `RateLimitError` | Typed exception hierarchy |
| `onchain_data.py` | `OnChainDataClient` | (v5.0) On-chain sentiment fetch (stub) |

### Strategies (`src/strategies/`)

All inherit from `BaseStrategy` in `base.py`. Each implements `analyze(closes, highs, lows, volumes, opens, indicator_cache)` returning `Optional[StrategySignal]`.

### ML (`src/ml/`)

| File | Class | Purpose |
|------|-------|---------|
| `trainer.py` | `ModelTrainer`, `AutoRetrainer` | TFLite model training, periodic retraining loop |
| `continuous_learner.py` | `ContinuousLearner` | Online SGD between full retraining cycles |
| `strategy_tuner.py` | `StrategyTuner`, `AutoTuner` | Weekly performance analysis, weight rebalancing |

---

## Lifecycle

### Startup Sequence

1. `main.py:main()` -- Python version check, preflight checks, setup logging
2. `preflight_checks()` -- Create dirs, verify config, acquire instance lock
3. `run_bot()` -- Async entry point
4. Resolve trading accounts (single or multi-exchange)
5. Per engine: `BotEngine()` -> `initialize()` -> `warmup()`
6. StockSwingEngine init (if stocks enabled)
7. MultiEngineHub construction (if multi-exchange)
8. Dashboard server setup (uvicorn)
9. Signal handlers (SIGINT/SIGTERM -> shutdown event)
10. Background tasks created via `_run_with_restart()`
11. `shutdown_event.wait()` -- blocks until signal received

### Shutdown Sequence

1. Signal handler sets `_running = False` on all engines
2. `shutdown_event.set()` unblocks the main coroutine
3. `engine.stop()` -- cancels tasks, closes WS, closes DB
4. Stock engine stop
5. Dashboard server `should_exit = True`
6. Process exit

### `_run_with_restart()` Supervisor

Every background task runs through this supervisor:
- Catches exceptions, logs, retries with exponential backoff (2s base, 30s max)
- Quick exits (<30s) count as failures
- After N failures (default 3) on critical tasks, auto-pauses trading instead of crashing
- Failure counter resets after the task runs successfully for 10+ minutes

---

## Deployment Model

### Docker Compose

```yaml
services:
  trading-bot:
    build: .
    container_name: novatrader-trading-bot-1
    ports:
      - "8090:8080"
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
      - ./models:/app/models
      - ./config/config.yaml:/app/config/config.yaml:ro
      - ./.secrets/env:/app/.secrets/env:ro
    env_file:
      - .env
    restart: unless-stopped
```

### Deploy via rsync

```bash
rsync -avz --exclude='.git' --exclude='data/' --exclude='logs/' \
  ./ ops@165.245.143.68:/home/ops/novatrader/
ssh -i ~/.ssh/horizon ops@165.245.143.68 \
  "cd /home/ops/novatrader && docker compose up -d --build"
```

### Secrets Flow

```
.env.secrets.tpl          # op:// references (template)
    |
    v (scripts/resolve_secrets.sh + `op read`)
.secrets/env              # Plain values (volume-mounted)
    |
    v (src/utils/secrets.py at Python startup)
os.environ                # Available to all code
```

---

## Database Architecture

- **SQLite WAL mode** -- concurrent reads, serialized writes
- **One DB per engine** in multi-exchange: `trading_kraken_default.db`, `trading_coinbase_default.db`, `trading_stocks_default.db`
- **Read semaphore** (8 concurrent reads) prevents Python-level serialization
- **Write lock** with 30s timeout prevents deadlocks
- **Performance stats cache** with 5s TTL reduces dashboard query load
- **Schema migrations** run automatically on `initialize()`

Key tables: `trades`, `positions`, `thought_log`, `metrics`, `daily_summary`, `ml_features`, `system_state`, `order_book_snapshots`, `signals`, `strategy_attribution` (v5.0), `anomaly_events` (v5.0).

---

## Error Handling Philosophy

The **"Trade or Die"** principle: only fatal errors (exchange auth failure, database corruption) stop the bot. Everything else is classified and handled:

| Severity | Examples | Action |
|----------|---------|--------|
| CRITICAL | DB init failure, exchange auth | Stop bot |
| DEGRADED | WS disconnect, stale data | Auto-pause trading, keep monitoring |
| TRANSIENT | Rate limit, network timeout | Retry with backoff |

Background tasks never crash the bot. The `_run_with_restart()` supervisor catches all exceptions and retries. Critical tasks (scan_loop, position_loop, ws_loop) auto-pause trading after repeated failures.

---

## Performance Optimizations

- **Vectorized indicators** via NumPy (no Python loops for OHLCV math)
- **RingBuffer** contiguous memory for O(1) append, O(1) slice
- **Parallelized position management** via `asyncio.gather`
- **O(1) trade lookup** via `get_trade_by_id` (indexed)
- **Consolidated perf stats** -- 7 queries collapsed to 2, cached with 5s TTL
- **IndicatorCache** -- per-scan cache prevents redundant calculation across strategies
- **Read semaphore** -- 8 concurrent SQLite reads without write lock contention
