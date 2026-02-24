# NovaPulse Multi-Engine Architecture

**Version:** 4.5.0
**Last Updated:** 2026-02-24

---

## Overview

NovaPulse supports running multiple independent trading engines within a single process. Each engine targets a specific exchange and account, with its own database, WebSocket connections, REST clients, risk manager, and background tasks. The `MultiEngineHub` orchestrates startup, shutdown, and cross-engine coordination.

---

## MultiEngineHub

**File:** `src/core/multi_engine.py` (~171 lines)
**Class:** `MultiEngineHub`

### Account Specification

Engines are defined in `config.yaml` as a comma-separated string:

```yaml
accounts: "main:kraken,swing:coinbase"
```

Each segment follows the pattern `{account_name}:{exchange}`. The hub parses this and instantiates one `BotEngine` per segment, plus a `StockSwingEngine` if stock trading is enabled.

```python
# Resulting engines:
# BotEngine(account="main", exchange="kraken")     -> trading_kraken_main.db
# BotEngine(account="swing", exchange="coinbase")   -> trading_coinbase_swing.db
# StockSwingEngine(account="default")               -> trading_stocks_default.db
```

### Per-Engine Isolation

Each engine receives its own:

| Resource | Naming Pattern |
|----------|---------------|
| SQLite database | `trading_{exchange}_{account}.db` |
| TFLite model | `models/{exchange}_{account}/signal_model.tflite` |
| Online model | `models/{exchange}_{account}/online_model.pkl` |
| Scaler | `models/{exchange}_{account}/scaler.pkl` |
| WebSocket client | One per exchange instance |
| REST client | One per exchange instance |
| RiskManager | Independent bankroll tracking |
| Background tasks | Full set per engine |

Engines share the same process and event loop but have no direct data coupling. They communicate only through the hub's coordination methods.

### Startup Sequence

```
MultiEngineHub.start()
  1. Parse accounts string
  2. For each account:
     a. Resolve API keys from environment
     b. Initialize DatabaseManager with per-engine DB path
     c. Create exchange client (KrakenREST/CoinbaseREST)
     d. Create BotEngine with all dependencies
  3. If stocks enabled:
     a. Create PolygonClient, AlpacaClient, UniverseScanner
     b. Create StockSwingEngine
  4. Start all engines concurrently (asyncio.gather)
  5. Start priority scheduler
  6. Start dashboard server (wraps hub)
  7. Start GlobalRiskAggregator
```

### Shutdown Sequence

```
MultiEngineHub.stop()
  1. Cancel priority scheduler
  2. Stop GlobalRiskAggregator
  3. Stop all engines concurrently (asyncio.gather)
     -> Each engine: cancel tasks, close WS, flush DB
  4. Stop dashboard server
  5. Close all DB connections
```

---

## Environment Resolution

API keys are resolved per-account using a prefix pattern:

```
{ACCOUNT_NAME_UPPER}_{KEY_NAME}
```

| Account | Variable | Example |
|---------|----------|---------|
| `main:kraken` | `MAIN_KRAKEN_API_KEY` | `abc123...` |
| `main:kraken` | `MAIN_KRAKEN_API_SECRET` | `def456...` |
| `swing:coinbase` | `SWING_COINBASE_API_KEY` | `ghi789...` |
| `swing:coinbase` | `SWING_COINBASE_API_SECRET` | `jkl012...` |
| stocks | `ALPACA_API_KEY` | `mno345...` |
| stocks | `POLYGON_API_KEY` | `pqr678...` |

If a prefixed variable is not found, the client falls back to the unprefixed name (e.g., `KRAKEN_API_KEY`). This allows single-account deployments to work without prefixes.

---

## MultiControlRouter

**File:** `src/core/multi_engine.py`
**Class:** `MultiControlRouter` (inner class)

Routes control commands from the dashboard or Telegram/Discord bots to all engines simultaneously.

| Command | Method | Behavior |
|---------|--------|----------|
| Pause all | `pause_all()` | Calls `engine.pause()` on every engine |
| Resume all | `resume_all()` | Calls `engine.resume()` on every engine |
| Close all positions | `close_all()` | Calls `engine.close_all_positions()` on every engine |
| Get status | `get_all_status()` | Aggregates status dicts from all engines |

Individual engines can also be targeted by name:

```python
router.pause("main:kraken")       # pause only the Kraken engine
router.resume("stocks:default")   # resume only the stock engine
```

---

## Priority Scheduler

**File:** `main.py`

The priority scheduler is a background task that coordinates engine activity based on NYSE market hours. It uses `zoneinfo.ZoneInfo("America/New_York")` for accurate timezone handling including DST transitions.

### Schedule Logic

```python
async def _priority_scheduler(self):
    while True:
        now = datetime.now(ZoneInfo("America/New_York"))
        is_weekday = now.weekday() < 5
        market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
        stock_hours = is_weekday and market_open <= now <= market_close

        for engine in self.crypto_engines:
            if stock_hours and not engine.is_paused:
                engine.pause()
            elif not stock_hours and engine.is_paused:
                engine.resume()

        if self.stock_engine:
            if stock_hours and self.stock_engine.is_paused:
                self.stock_engine.resume()
            elif not stock_hours and not self.stock_engine.is_paused:
                self.stock_engine.pause()

        await asyncio.sleep(30)
```

### Key Behaviors

- **Polling interval:** 30 seconds
- **Paused engines** stop scanning for new signals but continue monitoring open positions (stop-loss, take-profit, trailing stop checks remain active)
- **Weekends:** stocks paused all day; crypto runs without pause
- **Holidays:** not explicitly handled -- stocks will scan but Polygon returns no data and Alpaca rejects orders, so the engine is effectively idle

---

## GlobalRiskAggregator

**File:** `src/core/multi_engine.py`
**Class:** `GlobalRiskAggregator`

Bridges risk management across engines to prevent total account exposure from exceeding global limits.

### Aggregated Metrics

| Metric | Aggregation | Limit |
|--------|-------------|-------|
| Total open positions | Sum across all engines | `global_max_positions` (default: 20) |
| Total exposure USD | Sum of all position sizes | `global_max_exposure_usd` (default: 50,000) |
| Daily realized P&L | Sum across all engines | `global_daily_loss_limit_pct` (default: -5%) |

### Enforcement

Before any engine opens a new position, it queries the `GlobalRiskAggregator`:

```python
can_open = aggregator.check_global_limits(
    new_position_size_usd=proposed_size,
    engine_id="main:kraken"
)
```

If global limits would be breached, the trade is rejected with a log entry identifying which limit was hit. Individual engine limits (per-engine `max_positions`, `max_risk_per_trade`) are checked first; global limits are the outer boundary.

---

## Dashboard Integration

**File:** `src/api/server.py`
**Class:** `DashboardServer`

The dashboard server wraps the `MultiEngineHub` and exposes a unified view of all engines through the FastAPI REST API.

### Multi-Engine Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/status` | Aggregated status across all engines |
| `GET /api/positions` | All open positions, tagged with engine ID |
| `GET /api/trades` | Trade history from all engines |
| `GET /api/engine/{engine_id}/status` | Status for a specific engine |
| `POST /api/engine/{engine_id}/pause` | Pause a specific engine |
| `POST /api/engine/{engine_id}/resume` | Resume a specific engine |
| `POST /api/close-all` | Close all positions on all engines |

All responses include an `engine_id` field so the frontend can distinguish data sources.

### Config Keys

```yaml
accounts: "main:kraken,swing:coinbase"   # engine specification

stocks:
  enabled: true                           # enable stock engine

risk:
  global_max_positions: 20
  global_max_exposure_usd: 50000
  global_daily_loss_limit_pct: -5.0

dashboard:
  host: "0.0.0.0"
  port: 8080
  api_key: "${DASHBOARD_API_KEY}"
```

---

## ML Training Leader

One engine is designated as the ML training leader (first in the `accounts` list). The leader aggregates `ml_features` from all engine databases to train a unified model. See `ML-Training-Pipeline.md` for full details on cross-exchange training.

```yaml
accounts: "main:kraken,swing:coinbase"
# "main:kraken" is the leader -- it aggregates ml_features from all DBs
```
