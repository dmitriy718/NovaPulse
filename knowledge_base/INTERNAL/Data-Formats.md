# NovaPulse Data Formats

**Version:** 4.0.0
**Last Updated:** 2026-02-22

---

## SQLite Database Schema

**File:** `src/core/database.py`
**Location:** `data/trading.db` (configurable via `app.db_path` or `DB_PATH` env)
**Mode:** WAL (Write-Ahead Logging) for concurrent read/write

### WAL PRAGMAs

Applied at startup:
```sql
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA cache_size=-16000;     -- 16MB page cache
PRAGMA temp_store=MEMORY;
PRAGMA mmap_size=67108864;    -- 64MB memory-mapped I/O
```

### Tables

#### `trades`

The core trade ledger. Every open and closed trade is recorded here.

```sql
CREATE TABLE trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id TEXT UNIQUE NOT NULL,         -- Format: "T-<12-hex-chars>"
    pair TEXT NOT NULL,                     -- e.g. "BTC/USD"
    side TEXT NOT NULL CHECK(side IN ('buy', 'sell')),
    entry_price REAL NOT NULL,
    exit_price REAL,
    quantity REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'open'
        CHECK(status IN ('open', 'closed', 'cancelled', 'error')),
    strategy TEXT NOT NULL,                -- Primary strategy name
    confidence REAL,                       -- AI confidence (0-1)
    stop_loss REAL,
    take_profit REAL,
    trailing_stop REAL,
    pnl REAL DEFAULT 0.0,                  -- Net P&L (after fees)
    pnl_pct REAL DEFAULT 0.0,             -- P&L as percentage
    fees REAL DEFAULT 0.0,                 -- Total fees (entry + exit)
    slippage REAL DEFAULT 0.0,
    entry_time TEXT NOT NULL,              -- ISO 8601 UTC
    exit_time TEXT,                         -- ISO 8601 UTC
    duration_seconds REAL,
    notes TEXT,
    metadata TEXT,                         -- JSON blob (see below)
    tenant_id TEXT DEFAULT 'default',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
```

**Trade metadata JSON structure:**
```json
{
    "confluence_count": 3,
    "is_sure_fire": true,
    "obi": 0.25,
    "book_score": 0.35,
    "size_usd": 450.00,
    "risk_amount": 11.25,
    "kelly_fraction": 0.0312,
    "slippage": 0.0001,
    "fees": 1.17,
    "entry_fee": 0.72,
    "entry_fee_rate": 0.0016,
    "exit_fee_rate": 0.0026,
    "requested_units": 0.00687,
    "filled_units": 0.00687,
    "partial_fill": false,
    "mode": "paper",
    "order_type": "limit",
    "post_only": false,
    "planned_entry_price": 65400.00,
    "planned_stop_loss": 63765.00,
    "planned_take_profit": 68670.00,
    "trend_regime": "trend",
    "vol_regime": "mid_vol",
    "vol_level": 0.45,
    "vol_expanding": false,
    "order_txid": "OXXXXX-XXXXX-XXXXXX",
    "exchange_stop_txid": "OYYYYY-YYYYY-YYYYYY",
    "stop_loss_state": {
        "initial_sl": 63765.00,
        "current_sl": 65400.00,
        "breakeven_activated": true,
        "trailing_activated": true,
        "trailing_high": 66500.00,
        "trailing_low": null
    },
    "partial_exits": [
        {
            "tier": 0,
            "qty": 0.00343,
            "price": 68670.00,
            "pnl": 11.22,
            "fee": 0.59,
            "time": "2026-02-22T15:30:00Z"
        }
    ],
    "exit_tier": 1,
    "partial_pnl_accumulated": 11.22
}
```

#### `thought_log`

AI decision log displayed in the dashboard feed.

```sql
CREATE TABLE thought_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,               -- ISO 8601 UTC
    category TEXT NOT NULL,                -- "trade", "risk", "system", "execution"
    message TEXT NOT NULL,                 -- Human-readable message
    severity TEXT DEFAULT 'info'
        CHECK(severity IN ('debug', 'info', 'warning', 'error', 'critical')),
    metadata TEXT,                         -- JSON blob
    tenant_id TEXT DEFAULT 'default'
);
```

#### `metrics`

Time-series performance metrics for dashboard charts.

```sql
CREATE TABLE metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    metric_name TEXT NOT NULL,             -- e.g. "bankroll", "drawdown", "win_rate"
    metric_value REAL NOT NULL,
    tags TEXT,                             -- JSON blob
    tenant_id TEXT DEFAULT 'default'
);
```

#### `ml_features`

Feature vectors tied to trades for ML model training.

```sql
CREATE TABLE ml_features (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    pair TEXT NOT NULL,
    features TEXT NOT NULL,                -- JSON feature vector
    label REAL,                            -- 1.0 = profitable, 0.0 = loss (set at trade close)
    trade_id TEXT,
    tenant_id TEXT DEFAULT 'default',
    FOREIGN KEY (trade_id) REFERENCES trades(trade_id)
);
```

#### `order_book_snapshots`

Order book state at trade entry for ML training data.

```sql
CREATE TABLE order_book_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pair TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    bid_volume REAL,
    ask_volume REAL,
    obi REAL,                              -- Order Book Imbalance (-1 to 1)
    spread REAL,
    whale_detected INTEGER DEFAULT 0,
    snapshot_data TEXT,                     -- JSON: {"bids": [...], "asks": [...]}
    trade_id TEXT,
    tenant_id TEXT DEFAULT 'default'
);
```

#### `signals`

Raw strategy signal log (all signals, not just acted-upon).

```sql
CREATE TABLE signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    pair TEXT NOT NULL,
    strategy TEXT NOT NULL,
    direction TEXT NOT NULL CHECK(direction IN ('long', 'short', 'neutral')),
    strength REAL NOT NULL,
    confluence_count INTEGER DEFAULT 0,
    ai_confidence REAL,
    acted_upon INTEGER DEFAULT 0,
    metadata TEXT
);
```

#### `daily_summary`

Per-day aggregate statistics, unique per tenant.

```sql
CREATE TABLE daily_summary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,                     -- "YYYY-MM-DD"
    total_trades INTEGER DEFAULT 0,
    winning_trades INTEGER DEFAULT 0,
    losing_trades INTEGER DEFAULT 0,
    total_pnl REAL DEFAULT 0.0,
    max_drawdown REAL DEFAULT 0.0,
    win_rate REAL DEFAULT 0.0,
    metadata TEXT,
    tenant_id TEXT DEFAULT 'default',
    UNIQUE(date, tenant_id)
);
```

#### `system_state`

Key-value store for runtime state persistence across restarts.

```sql
CREATE TABLE system_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT DEFAULT (datetime('now'))
);
```

#### `tenants`

Multi-tenant registry with Stripe integration.

```sql
CREATE TABLE tenants (
    tenant_id TEXT PRIMARY KEY,
    name TEXT,
    email TEXT,
    stripe_customer_id TEXT,
    stripe_subscription_id TEXT,
    plan TEXT DEFAULT 'free',
    status TEXT DEFAULT 'active',          -- "active", "trialing", "past_due", "cancelled"
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
```

#### `tenant_api_keys`

Hashed API key to tenant_id mapping.

```sql
CREATE TABLE tenant_api_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,          -- SHA-256 hash of API key
    label TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
```

#### `stripe_webhook_events`

Idempotency table for Stripe webhook processing.

```sql
CREATE TABLE stripe_webhook_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT UNIQUE NOT NULL,
    event_type TEXT NOT NULL,
    processed_at TEXT DEFAULT (datetime('now')),
    metadata TEXT
);
```

#### `signal_webhook_events`

Idempotency table for inbound signal webhook processing.

```sql
CREATE TABLE signal_webhook_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT UNIQUE NOT NULL,
    source TEXT,
    processed_at TEXT DEFAULT (datetime('now')),
    metadata TEXT
);
```

#### `backtest_runs`

History of backtest and optimization runs.

```sql
CREATE TABLE backtest_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT UNIQUE NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    config TEXT,                            -- JSON: backtest configuration
    results TEXT,                           -- JSON: performance results
    tenant_id TEXT DEFAULT 'default'
);
```

#### `copy_trading_providers`

Registry for webhook signal providers (copy trading).

```sql
CREATE TABLE copy_trading_providers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_id TEXT UNIQUE NOT NULL,
    name TEXT,
    webhook_url TEXT,
    secret TEXT,
    enabled INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now'))
);
```

---

## REST API Response Formats

### GET /api/v1/health

```json
{
    "status": "healthy",
    "version": "3.0.0",
    "timestamp": "2026-02-22T14:30:00.123456Z"
}
```

### GET /api/v1/status

```json
{
    "status": "running",
    "exchange": "kraken",
    "mode": "paper",
    "paused": false,
    "uptime_seconds": 86400,
    "scan_count": 1440,
    "pairs": ["BTC/USD", "ETH/USD", "SOL/USD"],
    "scan_interval": 60,
    "ws_connected": true
}
```

### GET /api/v1/trades

```json
{
    "trades": [
        {
            "trade_id": "T-abc123def456",
            "pair": "BTC/USD",
            "side": "buy",
            "entry_price": 65432.10,
            "exit_price": 66543.21,
            "quantity": 0.00687,
            "status": "closed",
            "strategy": "keltner",
            "confidence": 0.78,
            "stop_loss": 63765.00,
            "take_profit": 68670.00,
            "pnl": 7.63,
            "pnl_pct": 0.017,
            "fees": 2.34,
            "entry_time": "2026-02-22T10:00:00Z",
            "exit_time": "2026-02-22T14:30:00Z",
            "metadata": { ... }
        }
    ]
}
```

### GET /api/v1/risk

```json
{
    "bankroll": 10234.56,
    "initial_bankroll": 10000.00,
    "total_return_pct": 2.35,
    "peak_bankroll": 10500.00,
    "current_drawdown": 2.53,
    "max_drawdown_pct": 3.14,
    "daily_pnl": 45.67,
    "daily_trades": 3,
    "open_positions": 2,
    "total_exposure_usd": 890.00,
    "risk_of_ruin": 0.0001,
    "drawdown_factor": 1.00,
    "remaining_capacity_usd": 4227.28,
    "max_daily_trades": 0,
    "max_total_exposure_pct": 0.50,
    "trade_count": 127,
    "consecutive_wins": 2,
    "consecutive_losses": 0
}
```

### GET /api/v1/strategies

```json
{
    "strategies": [
        {
            "name": "keltner",
            "enabled": true,
            "weight": 0.30,
            "kind": "strategy",
            "total_trades": 45,
            "wins": 38,
            "losses": 7,
            "win_rate": 0.844,
            "avg_pnl": 5.23,
            "total_pnl": 235.35,
            "runtime_disabled": false,
            "runtime_disabled_until": null,
            "runtime_disable_reason": null
        }
    ]
}
```

---

## WebSocket Message Format

### Connection

```
ws://localhost:8090/ws/live?key=YOUR_API_KEY
```

### Server Messages

Messages are JSON objects pushed at the dashboard refresh interval:

```json
{
    "type": "update",
    "timestamp": "2026-02-22T14:30:00Z",
    "status": { ... },
    "positions": [ ... ],
    "performance": { ... },
    "risk": { ... },
    "thoughts": [ ... ]
}
```

### Heartbeat

Server sends periodic heartbeats to detect stale connections. Clients that do not respond are disconnected.

---

## Structlog JSON Format

All application logs use structured JSON:

```json
{
    "event": "Trade executed",
    "level": "info",
    "logger": "executor",
    "timestamp": "2026-02-22T14:30:00.123456Z",
    "trade_id": "T-abc123def456",
    "pair": "BTC/USD",
    "side": "buy",
    "price": 65432.10,
    "size_usd": 450.00,
    "mode": "paper"
}
```

### Log Levels

| Level | Usage |
|-------|-------|
| DEBUG | Detailed diagnostic information |
| INFO | Normal operations (trade executed, scan complete) |
| WARNING | Risk blocks, cooldowns, degraded conditions |
| ERROR | Failed operations that need attention |
| CRITICAL | Unrecoverable failures (exit order permanently failed) |

### Sensitive Data Masking

Fields containing `api_key`, `api_secret`, `password`, `token`, `secret` are automatically masked to `first4****last4` format.

---

## Elasticsearch Index Formats

When ES is enabled, data is mirrored to indexes with the prefix `novapulse-`:

### Trade Events (`novapulse-trades`)

```json
{
    "event": "closed",
    "timestamp": 1708617000,
    "trade_id": "T-abc123def456",
    "tenant_id": "default",
    "pair": "BTC/USD",
    "side": "buy",
    "strategy": "keltner",
    "mode": "paper",
    "status": "closed",
    "entry_price": 65432.10,
    "exit_price": 66543.21,
    "quantity": 0.00687,
    "size_usd": 450.00,
    "pnl": 7.63,
    "pnl_pct": 0.017,
    "reason": "take_profit",
    "fees": 2.34,
    "canonical_source": "sqlite",
    "analytics_mirror": true
}
```

### External Data Indexes

| Index | Source | Fields |
|-------|--------|--------|
| `novapulse-sentiment` | Fear & Greed Index, CryptoPanic | score, sentiment, source, timestamp |
| `novapulse-market` | CoinGecko | market_cap, volume_24h, price, change_pct |
| `novapulse-onchain` | On-chain data | active_addresses, transaction_volume, etc. |
| `novapulse-candles` | OHLCV data | open, high, low, close, volume, pair, timeframe |
| `novapulse-orderbook` | Order book snapshots | bids, asks, obi, spread |

### Index Lifecycle

Retention is configured per index type in `elasticsearch.retention_days`:
- Candles: 90 days
- Orderbook: 30 days
- Sentiment/market/onchain: 180 days
- Trades: 365 days

### Important Note

**SQLite is the canonical ledger.** ES is a mirror for analytics and visualization only. If data diverges, SQLite is the source of truth. Every ES document includes `"canonical_source": "sqlite"` and `"analytics_mirror": true` to make this explicit.

---

## In-Memory Data Structures

### RingBuffer (`src/core/structures.py`)

NumPy-backed circular buffer for O(1) candle storage:

```python
class RingBuffer:
    capacity: int       # Fixed size (e.g., 1000)
    dtype: np.dtype     # numpy float64
    _buffer: np.ndarray # Pre-allocated array
    _head: int          # Write pointer
    _count: int         # Current element count
```

Methods:
- `append(value)` - O(1) insert
- `view()` - Zero-copy slice of valid data
- `latest(n)` - Last N values
- `get_last(n)` - Synonym for latest

### MarketDataCache (`src/exchange/market_data.py`)

Per-pair storage of OHLCV data using RingBuffers:
- `closes`, `highs`, `lows`, `volumes`, `opens`, `times` - RingBuffer arrays
- `ticker` cache - Latest bid/ask/price per pair
- `order_book` cache - Current order book per pair
- `book_analysis` cache - Computed OBI/book_score per pair
- Staleness tracking per pair (last update timestamp)

### ConfluenceSignal (`src/ai/confluence.py`)

Aggregated signal from multi-strategy analysis:
```python
@dataclass
ConfluenceSignal:
    pair: str
    direction: SignalDirection  # LONG/SHORT/NEUTRAL
    strength: float             # 0-1
    confidence: float           # 0-1
    confluence_count: int
    signals: List[StrategySignal]
    obi: float
    book_score: float
    obi_agrees: bool
    is_sure_fire: bool
    entry_price: float
    stop_loss: float
    take_profit: float
    regime: str                 # "trend"/"range"
    volatility_regime: str      # "high_vol"/"mid_vol"/"low_vol"
    vol_level: float            # 0-1 percentile
    vol_expanding: bool
    timeframe_agreement: int
    timeframes: Dict[str, str]
    timestamp: str              # ISO 8601
```
