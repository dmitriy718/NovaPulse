# NovaPulse Database Schema and Persistence

**Version:** 5.0.0
**Last Updated:** 2026-02-27

---

## Overview

NovaPulse uses SQLite as its canonical data store. Every trade, log entry, metric, ML feature, and system state value is persisted in SQLite. Elasticsearch is an optional analytics mirror; SQLite is the source of truth. The database layer is designed for concurrent access within a single-process async environment using WAL mode.

**File:** `src/core/database.py` (~1681 lines)
**Class:** `DatabaseManager`

---

## Connection Configuration

### PRAGMA Settings

Applied on every connection open:

```sql
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA cache_size = -16000;          -- 16 MB page cache
PRAGMA temp_store = MEMORY;          -- temp tables in RAM
PRAGMA mmap_size = 67108864;         -- 64 MB memory-mapped I/O
```

| PRAGMA | Value | Rationale |
|--------|-------|-----------|
| `journal_mode=WAL` | Write-Ahead Logging | Allows concurrent readers during writes; no reader blocking |
| `synchronous=NORMAL` | Reduced fsync | WAL + NORMAL is safe against process crashes (not power loss); acceptable for trading bot |
| `cache_size=-16000` | 16 MB | Keeps hot pages in memory; negative value = KB (not pages) |
| `temp_store=MEMORY` | In-memory temps | Avoids temp file I/O for ORDER BY, GROUP BY |
| `mmap_size=67108864` | 64 MB | Memory-maps the DB file for faster random reads |

### Database Files

Each engine gets its own database file:

| Engine | Database File |
|--------|--------------|
| Kraken (main account) | `trading_kraken_main.db` |
| Coinbase (swing account) | `trading_coinbase_swing.db` |
| Stocks (default) | `trading_stocks_default.db` |

All files live in the `data/` directory (or Docker volume mount).

---

## Table Schemas

### trades

The primary ledger of all trade activity.

```sql
CREATE TABLE IF NOT EXISTS trades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id        TEXT UNIQUE NOT NULL,
    tenant_id       TEXT NOT NULL DEFAULT 'default',
    pair            TEXT NOT NULL,
    side            TEXT NOT NULL,              -- 'LONG' or 'SHORT'
    entry_price     REAL NOT NULL,
    quantity         REAL NOT NULL,
    stop_loss       REAL,
    take_profit     REAL,
    trailing_stop   REAL,
    strategy        TEXT,                       -- strategy name that generated signal
    status          TEXT NOT NULL DEFAULT 'OPEN',  -- 'OPEN', 'CLOSED', 'CANCELLED'
    entry_time      TEXT NOT NULL,              -- ISO 8601 timestamp
    exit_time       TEXT,
    exit_price      REAL,
    exit_reason     TEXT,                       -- 'stop_loss', 'take_profit', 'trailing_stop', 'manual', 'signal'
    pnl             REAL,                       -- absolute P&L in USD
    pnl_pct         REAL,                       -- percentage P&L
    fees            REAL DEFAULT 0,             -- total round-trip fees
    metadata        TEXT,                       -- JSON blob for extra data
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_trades_tenant ON trades(tenant_id);
CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
CREATE INDEX IF NOT EXISTS idx_trades_pair ON trades(pair);
CREATE INDEX IF NOT EXISTS idx_trades_entry_time ON trades(entry_time);
CREATE INDEX IF NOT EXISTS idx_trades_strategy ON trades(strategy);
```

### thought_log

Structured logging for the bot's decision-making process. Used for debugging and post-hoc analysis.

```sql
CREATE TABLE IF NOT EXISTS thought_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id   TEXT NOT NULL DEFAULT 'default',
    timestamp   TEXT NOT NULL,
    level       TEXT NOT NULL,                  -- 'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'
    message     TEXT NOT NULL,
    context     TEXT,                           -- JSON blob with structured context
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_thought_tenant ON thought_log(tenant_id);
CREATE INDEX IF NOT EXISTS idx_thought_timestamp ON thought_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_thought_level ON thought_log(level);
```

### metrics

Time-series metrics for performance tracking and dashboard display.

```sql
CREATE TABLE IF NOT EXISTS metrics (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id   TEXT NOT NULL DEFAULT 'default',
    timestamp   TEXT NOT NULL,
    name        TEXT NOT NULL,                  -- metric name (e.g., 'equity', 'drawdown', 'win_rate')
    value       REAL NOT NULL,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_metrics_tenant ON metrics(tenant_id);
CREATE INDEX IF NOT EXISTS idx_metrics_name ON metrics(name);
CREATE INDEX IF NOT EXISTS idx_metrics_timestamp ON metrics(timestamp);
```

### ml_features

Training data for the ML pipeline. Each row corresponds to a trade decision point.

```sql
CREATE TABLE IF NOT EXISTS ml_features (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id   TEXT NOT NULL DEFAULT 'default',
    pair        TEXT NOT NULL,
    features    TEXT NOT NULL,                  -- JSON object with feature values
    label       INTEGER,                       -- 1 = profitable, 0 = loss, NULL = pending
    trade_id    TEXT,                          -- links to trades.trade_id (set after trade closes)
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_ml_tenant ON ml_features(tenant_id);
CREATE INDEX IF NOT EXISTS idx_ml_trade_id ON ml_features(trade_id);
```

The `features` JSON contains the 12 core features (RSI, EMA ratio, BB position, etc.). The `label` is set to NULL when the feature row is created (at signal time) and updated to 0 or 1 when the associated trade closes.

### order_book_snapshots

Periodic L2 order book snapshots for ML training and analysis.

```sql
CREATE TABLE IF NOT EXISTS order_book_snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    pair        TEXT NOT NULL,
    timestamp   TEXT NOT NULL,
    snapshot    TEXT NOT NULL,                  -- JSON: {"bids": [[price, qty], ...], "asks": [[price, qty], ...]}
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_obs_pair ON order_book_snapshots(pair);
CREATE INDEX IF NOT EXISTS idx_obs_timestamp ON order_book_snapshots(timestamp);
```

### signals

Record of every confluence signal generated, regardless of whether it resulted in a trade.

```sql
CREATE TABLE IF NOT EXISTS signals (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id         TEXT NOT NULL DEFAULT 'default',
    timestamp         TEXT NOT NULL,
    pair              TEXT NOT NULL,
    direction         TEXT NOT NULL,            -- 'LONG' or 'SHORT'
    confidence        REAL NOT NULL,            -- 0.0 to 1.0
    strength          REAL NOT NULL,            -- raw confluence score
    strategy_signals  TEXT,                     -- JSON: per-strategy signal details
    ml_score          REAL,                     -- ML model confidence (if available)
    executed          INTEGER DEFAULT 0,        -- 1 if trade was opened, 0 if filtered
    filter_reason     TEXT,                     -- why signal was filtered (if not executed)
    created_at        TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_signals_tenant ON signals(tenant_id);
CREATE INDEX IF NOT EXISTS idx_signals_timestamp ON signals(timestamp);
CREATE INDEX IF NOT EXISTS idx_signals_pair ON signals(pair);
```

### daily_summary

Aggregated daily performance statistics per tenant.

```sql
CREATE TABLE IF NOT EXISTS daily_summary (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       TEXT NOT NULL DEFAULT 'default',
    date            TEXT NOT NULL,              -- YYYY-MM-DD
    total_trades    INTEGER DEFAULT 0,
    winning_trades  INTEGER DEFAULT 0,
    losing_trades   INTEGER DEFAULT 0,
    total_pnl       REAL DEFAULT 0,
    total_fees      REAL DEFAULT 0,
    max_drawdown    REAL DEFAULT 0,
    win_rate        REAL DEFAULT 0,
    avg_pnl_pct     REAL DEFAULT 0,
    best_trade_pnl  REAL DEFAULT 0,
    worst_trade_pnl REAL DEFAULT 0,
    UNIQUE(date, tenant_id)
);

CREATE INDEX IF NOT EXISTS idx_daily_tenant ON daily_summary(tenant_id);
CREATE INDEX IF NOT EXISTS idx_daily_date ON daily_summary(date);
```

### system_state

Key-value store for runtime state that must survive restarts.

```sql
CREATE TABLE IF NOT EXISTS system_state (
    key     TEXT PRIMARY KEY,
    value   TEXT NOT NULL
);
```

Common keys:

| Key | Value | Description |
|-----|-------|-------------|
| `stats_reset_ts` | ISO 8601 timestamp | When stats were last zeroed |
| `last_retrain_ts` | ISO 8601 timestamp | Last ML model training time |
| `last_tuner_run_ts` | ISO 8601 timestamp | Last strategy tuner execution |
| `bot_version` | `"5.0.0"` | Running version |
| `startup_ts` | ISO 8601 timestamp | Container start time |

### Multi-Tenant Tables

These tables support the SaaS/multi-tenant features:

```sql
CREATE TABLE IF NOT EXISTS tenants (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    email       TEXT,
    plan        TEXT DEFAULT 'free',
    created_at  TEXT DEFAULT (datetime('now')),
    active      INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS tenant_api_keys (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id   TEXT NOT NULL REFERENCES tenants(id),
    api_key     TEXT UNIQUE NOT NULL,
    label       TEXT,
    created_at  TEXT DEFAULT (datetime('now')),
    revoked     INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS stripe_webhook_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id        TEXT UNIQUE NOT NULL,
    event_type      TEXT NOT NULL,
    payload         TEXT NOT NULL,
    processed       INTEGER DEFAULT 0,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS signal_webhook_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       TEXT NOT NULL,
    webhook_url     TEXT NOT NULL,
    payload         TEXT NOT NULL,
    status_code     INTEGER,
    response        TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS backtest_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       TEXT NOT NULL,
    config          TEXT NOT NULL,              -- JSON: backtest parameters
    status          TEXT DEFAULT 'PENDING',     -- PENDING, RUNNING, COMPLETED, FAILED
    result          TEXT,                       -- JSON: backtest results
    started_at      TEXT,
    completed_at    TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS copy_trading_providers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       TEXT NOT NULL,
    provider_name   TEXT NOT NULL,
    active          INTEGER DEFAULT 1,
    config          TEXT,                       -- JSON: provider-specific config
    created_at      TEXT DEFAULT (datetime('now'))
);
```

---

## DatabaseManager API

### Important: No Direct `.execute()`

`DatabaseManager` does **not** expose a public `.execute()` method. To run raw SQL, access the underlying connection:

```python
# CORRECT:
db._db.execute("INSERT INTO system_state (key, value) VALUES (?, ?)", (k, v))
db._db.commit()

# WRONG (AttributeError):
db.execute("INSERT INTO ...")
```

### Async Wrapper Pattern

`DatabaseManager` wraps synchronous SQLite calls in `asyncio.to_thread()` to avoid blocking the event loop:

```python
async def get_open_trades(self, tenant_id: str = "default") -> List[dict]:
    return await asyncio.to_thread(self._get_open_trades_sync, tenant_id)

def _get_open_trades_sync(self, tenant_id: str) -> List[dict]:
    cursor = self._db.execute(
        "SELECT * FROM trades WHERE status = 'OPEN' AND tenant_id = ?",
        (tenant_id,)
    )
    return [dict(row) for row in cursor.fetchall()]
```

### TTL Caching on Performance Queries

Frequently called performance queries (win rate, total P&L, equity curve) are cached with a 5-second TTL to reduce DB load during dashboard polling:

```python
@ttl_cache(ttl=5)
async def get_performance_stats(self, tenant_id: str = "default") -> dict:
    ...
```

The cache is invalidated automatically after 5 seconds. It is also manually invalidated when a trade opens or closes.

### Key Methods

| Method | Description |
|--------|-------------|
| `open_trade(trade_data)` | Insert a new trade with status OPEN |
| `close_trade(trade_id, exit_data)` | Update trade with exit price, P&L, status CLOSED |
| `get_open_trades(tenant_id)` | All OPEN trades for a tenant |
| `get_closed_trades(tenant_id, limit)` | Recent CLOSED trades |
| `get_performance_stats(tenant_id)` | Win rate, total P&L, Sharpe, drawdown |
| `log_thought(level, message, context)` | Insert into thought_log |
| `record_metric(name, value)` | Insert into metrics |
| `save_ml_features(pair, features)` | Insert into ml_features with label=NULL |
| `label_ml_features(trade_id, label)` | Update label after trade closes |
| `save_signal(signal_data)` | Insert into signals |
| `save_daily_summary(date, stats)` | Upsert into daily_summary |
| `get_state(key)` | Read from system_state |
| `set_state(key, value)` | Upsert into system_state |
| `save_order_book_snapshot(pair, snapshot)` | Insert into order_book_snapshots |

---

## Stats Zeroing Procedure

When resetting statistics (e.g., for a stress test), the following tables are cleared while preserving ML training data:

```python
# Clear stats tables
db._db.execute("DELETE FROM thought_log WHERE tenant_id = ?", (tenant_id,))
db._db.execute("DELETE FROM metrics WHERE tenant_id = ?", (tenant_id,))
db._db.execute("DELETE FROM daily_summary WHERE tenant_id = ?", (tenant_id,))
db._db.execute("DELETE FROM signals WHERE tenant_id = ?", (tenant_id,))

# Set reset timestamp
db._db.execute(
    "INSERT OR REPLACE INTO system_state (key, value) VALUES (?, ?)",
    ("stats_reset_ts", datetime.utcnow().isoformat() + "Z")
)
db._db.commit()

# PRESERVE (do NOT delete):
# - trades (historical record, audit trail)
# - ml_features (ML training data)
# - order_book_snapshots (ML training data)
```

---

## Schema Migrations

`DatabaseManager.__init__()` runs `CREATE TABLE IF NOT EXISTS` for all tables on startup. This means new tables are added automatically when the code is updated. For column additions to existing tables, the `_migrate()` method checks the current schema and runs `ALTER TABLE` as needed:

```python
def _migrate(self):
    # Example: add trailing_stop column if it doesn't exist
    columns = {col[1] for col in self._db.execute("PRAGMA table_info(trades)").fetchall()}
    if "trailing_stop" not in columns:
        self._db.execute("ALTER TABLE trades ADD COLUMN trailing_stop REAL")
        self._db.commit()
```

Migrations are idempotent and safe to re-run.

---

## Backup and Recovery

SQLite with WAL mode supports online backups. The recommended approach:

```bash
# From the host (container volume is at /data/):
sqlite3 /data/trading_kraken_main.db ".backup /backups/kraken_main_$(date +%Y%m%d).db"
```

WAL mode ensures the backup is consistent even while the bot is actively writing. The `.backup` command acquires a read lock and copies the entire database atomically.

For Docker deployments, the database directory should be a named volume or bind mount to survive container restarts:

```yaml
volumes:
  - ./data:/app/data
```
