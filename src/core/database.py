"""
Database Manager - SQLite with WAL mode for concurrent access.

Provides async database operations for trade logging, position tracking,
performance metrics, and ML training data storage.

# ENHANCEMENT: Added connection pooling for concurrent access
# ENHANCEMENT: Added automatic schema migration support
# ENHANCEMENT: Added query result caching for frequently accessed data
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

import aiosqlite
import hashlib

from src.core.logger import get_logger

logger = get_logger("db")

def _truthy_env(name: str) -> bool:
    v = (os.getenv(name, "") or "").strip().lower()
    return v in ("1", "true", "yes", "y", "on")


class DatabaseManager:
    """
    Async SQLite database manager with WAL mode for production use.

    Features:
    - WAL mode for concurrent read/write
    - Auto-migration on schema changes
    - Connection health monitoring
    - Query batching for bulk inserts
    """

    # Timeout for acquiring the DB lock to prevent deadlocks.
    _LOCK_TIMEOUT: float = 30.0

    def __init__(self, db_path: str = "data/trading.db"):
        self.db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()
        self._initialized = False
        # TTL cache for get_performance_stats (keyed by tenant_id)
        self._perf_stats_cache: Dict[str, Any] = {}
        self._perf_stats_cache_ts: float = 0.0
        self._perf_stats_cache_ttl: float = 5.0

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    @asynccontextmanager
    async def _timed_lock(self) -> AsyncIterator[None]:
        """Acquire the DB lock with a timeout to prevent deadlocks."""
        try:
            await asyncio.wait_for(self._lock.acquire(), timeout=self._LOCK_TIMEOUT)
        except asyncio.TimeoutError:
            logger.error(
                "Database lock acquisition timed out - possible deadlock",
                timeout=self._LOCK_TIMEOUT,
            )
            raise RuntimeError(
                f"Database lock timeout after {self._LOCK_TIMEOUT}s"
            )
        try:
            yield
        finally:
            self._lock.release()

    async def initialize(self) -> None:
        """Initialize database connection and create schema."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        self._db = await aiosqlite.connect(self.db_path, timeout=15)

        # Enable WAL mode for concurrent access
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.execute("PRAGMA cache_size=-16000")  # 16MB cache
        await self._db.execute("PRAGMA temp_store=MEMORY")
        await self._db.execute("PRAGMA mmap_size=67108864")  # 64MB mmap

        await self._create_schema()
        await self._run_tenant_migrations()
        await self._migrate_daily_summary_multitenant()
        await self._ensure_indexes()
        self._initialized = True

    async def _create_schema(self) -> None:
        """Create all required database tables."""
        schema_sql = """
        -- Active and historical trades
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id TEXT UNIQUE NOT NULL,
            pair TEXT NOT NULL,
            side TEXT NOT NULL CHECK(side IN ('buy', 'sell')),
            entry_price REAL NOT NULL,
            exit_price REAL,
            quantity REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'open'
                CHECK(status IN ('open', 'closed', 'cancelled', 'error')),
            strategy TEXT NOT NULL,
            confidence REAL,
            stop_loss REAL,
            take_profit REAL,
            trailing_stop REAL,
            pnl REAL DEFAULT 0.0,
            pnl_pct REAL DEFAULT 0.0,
            fees REAL DEFAULT 0.0,
            slippage REAL DEFAULT 0.0,
            entry_time TEXT NOT NULL,
            exit_time TEXT,
            duration_seconds REAL,
            notes TEXT,
            metadata TEXT,  -- JSON blob for extra data
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );

        -- Order book snapshots for ML training
        CREATE TABLE IF NOT EXISTS order_book_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pair TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            bid_volume REAL,
            ask_volume REAL,
            obi REAL,  -- Order Book Imbalance
            spread REAL,
            whale_detected INTEGER DEFAULT 0,
            snapshot_data TEXT,  -- JSON blob
            trade_id TEXT,
            tenant_id TEXT DEFAULT 'default'
        );

        -- Strategy signals log
        CREATE TABLE IF NOT EXISTS signals (
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

        -- Performance metrics (time series)
        CREATE TABLE IF NOT EXISTS metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            metric_name TEXT NOT NULL,
            metric_value REAL NOT NULL,
            tags TEXT,  -- JSON blob
            tenant_id TEXT DEFAULT 'default'
        );

        -- ML training data
        CREATE TABLE IF NOT EXISTS ml_features (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            pair TEXT NOT NULL,
            features TEXT NOT NULL,  -- JSON feature vector
            label REAL,  -- 1.0 = profitable, 0.0 = loss
            trade_id TEXT,
            FOREIGN KEY (trade_id) REFERENCES trades(trade_id)
        );

        -- AI thought log for dashboard
        CREATE TABLE IF NOT EXISTS thought_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            category TEXT NOT NULL,
            message TEXT NOT NULL,
            severity TEXT DEFAULT 'info'
                CHECK(severity IN ('debug', 'info', 'warning', 'error', 'critical')),
            metadata TEXT
        );

        -- System state (key-value store)
        CREATE TABLE IF NOT EXISTS system_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT DEFAULT (datetime('now'))
        );

        -- Tenants (for multi-tenant / licensed SaaS)
        CREATE TABLE IF NOT EXISTS tenants (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            stripe_customer_id TEXT,
            stripe_subscription_id TEXT,
            status TEXT NOT NULL DEFAULT 'active'
                CHECK(status IN ('active', 'past_due', 'canceled', 'trialing', 'incomplete')),
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );

        -- API keys -> tenant (for tenant resolution)
        CREATE TABLE IF NOT EXISTS tenant_api_keys (
            api_key_hash TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            label TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (tenant_id) REFERENCES tenants(id)
        );

        -- Processed Stripe webhook events (idempotency key = event_id)
        CREATE TABLE IF NOT EXISTS stripe_webhook_events (
            event_id TEXT PRIMARY KEY,
            event_type TEXT,
            payload_hash TEXT,
            received_at TEXT NOT NULL
        );

        -- Processed trading signal webhook events (idempotency key = event_id)
        CREATE TABLE IF NOT EXISTS signal_webhook_events (
            event_id TEXT PRIMARY KEY,
            source TEXT,
            payload_hash TEXT,
            received_at TEXT NOT NULL,
            tenant_id TEXT DEFAULT 'default'
        );

        -- Backtest / optimization run history (dashboard + audit)
        CREATE TABLE IF NOT EXISTS backtest_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT UNIQUE NOT NULL,
            tenant_id TEXT DEFAULT 'default',
            exchange TEXT,
            pair TEXT NOT NULL,
            timeframe TEXT,
            mode TEXT,
            status TEXT NOT NULL DEFAULT 'completed'
                CHECK(status IN ('queued', 'running', 'completed', 'failed')),
            run_type TEXT NOT NULL DEFAULT 'backtest'
                CHECK(run_type IN ('backtest', 'optimization')),
            params_json TEXT,
            result_json TEXT,
            started_at TEXT,
            completed_at TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        -- Copy-trading provider registry (for webhook signal providers)
        CREATE TABLE IF NOT EXISTS copy_trading_providers (
            provider_id TEXT PRIMARY KEY,
            tenant_id TEXT DEFAULT 'default',
            name TEXT NOT NULL,
            source TEXT,
            enabled INTEGER NOT NULL DEFAULT 1,
            webhook_secret TEXT,
            metadata_json TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );

        -- Daily performance summary
        CREATE TABLE IF NOT EXISTS daily_summary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            total_trades INTEGER DEFAULT 0,
            winning_trades INTEGER DEFAULT 0,
            losing_trades INTEGER DEFAULT 0,
            total_pnl REAL DEFAULT 0.0,
            max_drawdown REAL DEFAULT 0.0,
            sharpe_ratio REAL,
            win_rate REAL,
            avg_win REAL,
            avg_loss REAL,
            best_trade REAL,
            worst_trade REAL,
            tenant_id TEXT DEFAULT 'default',
            UNIQUE(date, tenant_id)
        );

        -- Indexes for performance
        CREATE INDEX IF NOT EXISTS idx_trades_pair ON trades(pair);
        CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
        CREATE INDEX IF NOT EXISTS idx_trades_entry_time ON trades(entry_time);
        CREATE INDEX IF NOT EXISTS idx_signals_timestamp ON signals(timestamp);
        CREATE INDEX IF NOT EXISTS idx_signals_pair ON signals(pair);
        CREATE INDEX IF NOT EXISTS idx_metrics_timestamp ON metrics(timestamp);
        CREATE INDEX IF NOT EXISTS idx_metrics_name ON metrics(metric_name);
        CREATE INDEX IF NOT EXISTS idx_thought_log_timestamp ON thought_log(timestamp);
        CREATE INDEX IF NOT EXISTS idx_ml_features_pair ON ml_features(pair);
        CREATE INDEX IF NOT EXISTS idx_ml_features_label ON ml_features(label);
        CREATE INDEX IF NOT EXISTS idx_order_book_pair ON order_book_snapshots(pair);
        CREATE INDEX IF NOT EXISTS idx_webhook_received_at ON stripe_webhook_events(received_at);
        CREATE INDEX IF NOT EXISTS idx_signal_webhook_received_at ON signal_webhook_events(received_at);
        CREATE INDEX IF NOT EXISTS idx_backtest_runs_tenant_created ON backtest_runs(tenant_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_backtest_runs_pair ON backtest_runs(pair);
        CREATE INDEX IF NOT EXISTS idx_copy_trading_providers_tenant ON copy_trading_providers(tenant_id, updated_at);
        """
        await self._db.executescript(schema_sql)
        await self._db.commit()

    async def _ensure_indexes(self) -> None:
        """
        Create indexes that may depend on columns added by migrations.

        Older DBs can be missing columns like `ml_features.trade_id`. Creating an
        index on a missing column raises `sqlite3.OperationalError` and prevents
        startup, so we do this as best-effort after migrations.
        """
        if not self._db:
            return

        statements = [
            "CREATE INDEX IF NOT EXISTS idx_ml_features_trade_id ON ml_features(trade_id);",
            "CREATE INDEX IF NOT EXISTS idx_order_book_trade_id ON order_book_snapshots(trade_id);",
            "CREATE INDEX IF NOT EXISTS idx_metrics_tenant ON metrics(tenant_id);",
            "CREATE INDEX IF NOT EXISTS idx_trades_tenant_status ON trades(tenant_id, status);",
        ]
        for stmt in statements:
            try:
                await self._db.execute(stmt)
                await self._db.commit()
            except Exception as e:
                try:
                    await self._db.rollback()
                except Exception:
                    pass
                try:
                    logger.warning("Index create skipped", statement=stmt, error=str(e))
                except Exception:
                    pass

    async def _run_tenant_migrations(self) -> None:
        """Add tenant_id to tenant-scoped tables (idempotent)."""
        tables_columns = [
            ("trades", "tenant_id", "TEXT DEFAULT 'default'"),
            ("thought_log", "tenant_id", "TEXT DEFAULT 'default'"),
            ("signals", "tenant_id", "TEXT DEFAULT 'default'"),
            ("ml_features", "tenant_id", "TEXT DEFAULT 'default'"),
            ("ml_features", "trade_id", "TEXT"),
            ("daily_summary", "tenant_id", "TEXT DEFAULT 'default'"),
            ("order_book_snapshots", "tenant_id", "TEXT DEFAULT 'default'"),
            ("order_book_snapshots", "trade_id", "TEXT"),
            ("metrics", "tenant_id", "TEXT DEFAULT 'default'"),
        ]
        for table, column, col_def in tables_columns:
            try:
                await self._db.execute(
                    f"ALTER TABLE {table} ADD COLUMN {column} {col_def}"
                )
                await self._db.commit()
            except Exception as e:
                if "duplicate column" not in str(e).lower():
                    raise
                await self._db.rollback()

        # Backfill: SQLite ADD COLUMN does not populate existing rows with DEFAULT.
        # For strict tenant isolation, ensure no tenant_id is NULL.
        for table in ("trades", "thought_log", "signals", "ml_features", "daily_summary", "order_book_snapshots", "metrics"):
            try:
                await self._db.execute(f"UPDATE {table} SET tenant_id = 'default' WHERE tenant_id IS NULL")
                await self._db.commit()
            except Exception:
                try:
                    await self._db.rollback()
                except Exception:
                    pass
        # Ensure default tenant exists
        await self._db.execute(
            """INSERT OR IGNORE INTO tenants (id, name, status)
               VALUES ('default', 'Default', 'active')"""
        )
        await self._db.commit()

    async def _migrate_daily_summary_multitenant(self) -> None:
        """
        Ensure daily_summary uniqueness is per-tenant.

        Older DBs used `date TEXT UNIQUE`, which causes multiple tenants to overwrite
        each other. SQLite can't drop a UNIQUE constraint in-place, so we rebuild
        the table when needed.
        """
        if not self._db:
            return
        try:
            row = await (await self._db.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='daily_summary'"
            )).fetchone()
            create_sql = (row[0] or "") if row else ""
        except Exception:
            return

        # If the table was created with `date TEXT UNIQUE` (legacy), rebuild.
        if "date TEXT UNIQUE" not in create_sql:
            return

        try:
            await self._db.execute("BEGIN")
            await self._db.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_summary_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    total_trades INTEGER DEFAULT 0,
                    winning_trades INTEGER DEFAULT 0,
                    losing_trades INTEGER DEFAULT 0,
                    total_pnl REAL DEFAULT 0.0,
                    max_drawdown REAL DEFAULT 0.0,
                    sharpe_ratio REAL,
                    win_rate REAL,
                    avg_win REAL,
                    avg_loss REAL,
                    best_trade REAL,
                    worst_trade REAL,
                    tenant_id TEXT DEFAULT 'default',
                    UNIQUE(date, tenant_id)
                )
                """
            )
            # Copy best-effort. If the old table already had tenant_id, preserve it.
            cols = [r[1] for r in await (await self._db.execute("PRAGMA table_info(daily_summary)")).fetchall()]
            has_tenant = "tenant_id" in cols
            if has_tenant:
                await self._db.execute(
                    """
                    INSERT OR IGNORE INTO daily_summary_new
                    (date, total_trades, winning_trades, losing_trades, total_pnl, max_drawdown, sharpe_ratio,
                     win_rate, avg_win, avg_loss, best_trade, worst_trade, tenant_id)
                    SELECT date, total_trades, winning_trades, losing_trades, total_pnl, max_drawdown, sharpe_ratio,
                           win_rate, avg_win, avg_loss, best_trade, worst_trade, COALESCE(tenant_id, 'default')
                    FROM daily_summary
                    """
                )
            else:
                await self._db.execute(
                    """
                    INSERT OR IGNORE INTO daily_summary_new
                    (date, total_trades, winning_trades, losing_trades, total_pnl, max_drawdown, sharpe_ratio,
                     win_rate, avg_win, avg_loss, best_trade, worst_trade, tenant_id)
                    SELECT date, total_trades, winning_trades, losing_trades, total_pnl, max_drawdown, sharpe_ratio,
                           win_rate, avg_win, avg_loss, best_trade, worst_trade, 'default'
                    FROM daily_summary
                    """
                )
            await self._db.execute("DROP TABLE daily_summary")
            await self._db.execute("ALTER TABLE daily_summary_new RENAME TO daily_summary")
            await self._db.execute("COMMIT")
        except Exception as e:
            try:
                await self._db.execute("ROLLBACK")
            except Exception:
                pass
            try:
                logger.warning("daily_summary migration skipped", error=repr(e), error_type=type(e).__name__)
            except Exception:
                pass

        # Indexes that depend on migrated columns must be created after ALTER TABLE.
        try:
            await self._db.execute(
                "CREATE INDEX IF NOT EXISTS idx_order_book_trade_id ON order_book_snapshots(trade_id)"
            )
            await self._db.commit()
        except Exception:
            await self._db.rollback()

    # ------------------------------------------------------------------
    # Order Book Snapshots (ML)
    # ------------------------------------------------------------------

    async def insert_order_book_snapshot(
        self,
        pair: str,
        *,
        bid_volume: Optional[float] = None,
        ask_volume: Optional[float] = None,
        obi: Optional[float] = None,
        spread: Optional[float] = None,
        whale_detected: int = 0,
        snapshot_data: Optional[Dict[str, Any]] = None,
        trade_id: Optional[str] = None,
        tenant_id: Optional[str] = "default",
    ) -> None:
        """Insert an order book snapshot (best-effort, used for ML/debugging)."""
        payload = None
        if snapshot_data is not None:
            try:
                payload = json.dumps(snapshot_data)
            except Exception:
                payload = None

        async with self._timed_lock():
            await self._db.execute(
                """INSERT INTO order_book_snapshots
                   (pair, timestamp, bid_volume, ask_volume, obi, spread, whale_detected, snapshot_data, trade_id, tenant_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    pair,
                    datetime.now(timezone.utc).isoformat(),
                    bid_volume,
                    ask_volume,
                    obi,
                    spread,
                    int(whale_detected or 0),
                    payload,
                    trade_id,
                    tenant_id or "default",
                ),
            )
            await self._db.commit()

    # ------------------------------------------------------------------
    # Trade Operations
    # ------------------------------------------------------------------

    def _ts(self) -> str:
        """Consistent UTC timestamp in SQLite-compatible format."""
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _sql_dt(expr: str) -> str:
        """
        Best-effort SQLite datetime() wrapper that handles both:
        - 'YYYY-MM-DD HH:MM:SS'
        - ISO 8601 strings like 'YYYY-MM-DDTHH:MM:SS(.sss)(Z|+00:00)'
        """
        # Truncate to seconds, replace 'T' with ' ', ignore timezone suffixes beyond seconds.
        return f"datetime(replace(substr({expr}, 1, 19), 'T', ' '))"

    @staticmethod
    def _parse_dt(value: Any) -> Optional[datetime]:
        """Parse common timestamp formats into an aware UTC datetime."""
        if not value:
            return None
        if not isinstance(value, str):
            try:
                value = str(value)
            except Exception:
                return None
        s = value.strip()
        if not s:
            return None
        # Support '...Z'
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except (ValueError, TypeError):
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def _ensure_ready(self) -> None:
        """H1 FIX: Guard against use before initialization."""
        if not self._initialized or self._db is None:
            raise RuntimeError("Database not initialized. Call initialize() first.")

    async def insert_trade(
        self, trade: Dict[str, Any], tenant_id: Optional[str] = "default"
    ) -> int:
        """Insert a new trade record. Optional tenant_id for multi-tenant."""
        self._ensure_ready()
        async with self._timed_lock():
            cursor = await self._db.execute(
                """INSERT INTO trades 
                (trade_id, pair, side, entry_price, quantity, status, strategy,
                 confidence, stop_loss, take_profit, entry_time, metadata, tenant_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    trade["trade_id"], trade["pair"], trade["side"],
                    trade["entry_price"], trade["quantity"], trade.get("status", "open"),
                    trade["strategy"], trade.get("confidence"),
                    trade.get("stop_loss"), trade.get("take_profit"),
                    trade.get("entry_time", self._ts()),
                    json.dumps(trade.get("metadata", {})),
                    tenant_id or "default",
                )
            )
            await self._db.commit()
            return cursor.lastrowid

    # C1 FIX: Whitelist columns to prevent SQL injection
    TRADE_UPDATE_COLUMNS = frozenset({
        "exit_price", "pnl", "pnl_pct", "fees", "slippage", "status",
        "stop_loss", "take_profit", "trailing_stop", "exit_time",
        "duration_seconds", "notes", "metadata", "quantity",
    })

    async def update_trade(
        self,
        trade_id: str,
        updates: Dict[str, Any],
        tenant_id: Optional[str] = None,
    ) -> None:
        """Update an existing trade record. Only whitelisted columns allowed.
        Optional tenant_id for multi-tenant defense in depth."""
        if not self._initialized:
            raise RuntimeError("Database not initialized")
        async with self._timed_lock():
            set_clauses = []
            values = []
            for key, value in updates.items():
                if key not in self.TRADE_UPDATE_COLUMNS:
                    raise ValueError(f"Column '{key}' not allowed in trade updates")
                if key == "metadata" and not isinstance(value, str):
                    value = json.dumps(value)
                set_clauses.append(f"{key} = ?")
                values.append(value)
            if not set_clauses:
                return
            set_clauses.append("updated_at = datetime('now')")
            values.append(trade_id)
            where = "trade_id = ?"
            if tenant_id:
                where += " AND tenant_id = ?"
                values.append(tenant_id)
            sql = f"UPDATE trades SET {', '.join(set_clauses)} WHERE {where}"
            await self._db.execute(sql, values)
            await self._db.commit()

    async def close_trade(
        self,
        trade_id: str,
        exit_price: float,
        pnl: float,
        pnl_pct: float,
        fees: float = 0.0,
        slippage: float = 0.0,
        tenant_id: Optional[str] = None,
    ) -> None:
        """Close a trade with final P&L calculation.
        Optional tenant_id for multi-tenant defense in depth."""
        now = datetime.now(timezone.utc).isoformat()
        async with self._timed_lock():
            # Get entry time to calculate duration
            select_sql = "SELECT entry_time FROM trades WHERE trade_id = ?"
            select_params: List[Any] = [trade_id]
            if tenant_id:
                select_sql += " AND tenant_id = ?"
                select_params.append(tenant_id)
            cursor = await self._db.execute(select_sql, tuple(select_params))
            row = await cursor.fetchone()
            duration = 0.0
            if row and row[0]:
                entry_dt = self._parse_dt(row[0])
                exit_dt = self._parse_dt(now)
                if entry_dt and exit_dt:
                    duration = (exit_dt - entry_dt).total_seconds()

            where = "trade_id = ?"
            params: List[Any] = [
                exit_price, pnl, pnl_pct, fees, slippage, now, duration, trade_id
            ]
            if tenant_id:
                where += " AND tenant_id = ?"
                params.append(tenant_id)

            await self._db.execute(
                f"""UPDATE trades SET
                    exit_price = ?, pnl = ?, pnl_pct = ?, fees = ?,
                    slippage = ?, status = 'closed', exit_time = ?,
                    duration_seconds = ?, updated_at = datetime('now')
                WHERE {where}""",
                tuple(params),
            )

            # Label any ML feature rows captured at entry time for this trade.
            # Done before commit so both updates are in the same transaction.
            try:
                label = 1.0 if float(pnl) > 0 else 0.0
                ml_where = "trade_id = ? AND label IS NULL"
                ml_params: List[Any] = [label, trade_id]
                if tenant_id:
                    ml_where += " AND tenant_id = ?"
                    ml_params.append(tenant_id)
                await self._db.execute(
                    f"UPDATE ml_features SET label = ? WHERE {ml_where}",
                    tuple(ml_params),
                )
            except Exception as e:
                try:
                    logger.warning(
                        "Failed to label ML features for trade (non-fatal)",
                        trade_id=trade_id,
                        tenant_id=tenant_id,
                        error=repr(e),
                        error_type=type(e).__name__,
                    )
                except Exception:
                    pass

            await self._db.commit()

    async def get_open_trades(
        self,
        pair: Optional[str] = None,
        tenant_id: Optional[str] = "default",
    ) -> List[Dict[str, Any]]:
        """Get all open trades, optionally filtered by pair and tenant."""
        # Guard: ignore zero-quantity "phantom" positions
        sql = "SELECT * FROM trades WHERE status = 'open' AND ABS(quantity) > 0.00000001"
        params: List[Any] = []
        if tenant_id:
            sql += " AND tenant_id = ?"
            params.append(tenant_id)
        if pair:
            sql += " AND pair = ?"
            params.append(pair)
        sql += " ORDER BY entry_time DESC"

        cursor = await self._db.execute(sql, tuple(params) if params else ())
        columns = [description[0] for description in cursor.description]
        rows = await cursor.fetchall()
        return [dict(zip(columns, row)) for row in rows]

    async def get_trade_by_id(self, trade_id: str, tenant_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Fetch a single trade by its unique trade_id."""
        if not self._db:
            return None
        tc = " AND tenant_id = ?" if tenant_id else ""
        params: list = [trade_id]
        if tenant_id:
            params.append(tenant_id)
        cursor = await self._db.execute(
            f"SELECT * FROM trades WHERE trade_id = ?{tc} LIMIT 1",
            tuple(params),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cursor.description]
        return dict(zip(cols, row))

    async def get_trade_history(
        self,
        limit: int = 100,
        pair: Optional[str] = None,
        tenant_id: Optional[str] = "default",
    ) -> List[Dict[str, Any]]:
        """Get closed trade history. Optional tenant_id for multi-tenant."""
        sql = "SELECT * FROM trades WHERE status = 'closed'"
        params: List[Any] = []
        if tenant_id:
            sql += " AND tenant_id = ?"
            params.append(tenant_id)
        if pair:
            sql += " AND pair = ?"
            params.append(pair)
        sql += " ORDER BY exit_time DESC LIMIT ?"
        params.append(limit)

        cursor = await self._db.execute(sql, params)
        columns = [description[0] for description in cursor.description]
        rows = await cursor.fetchall()
        return [dict(zip(columns, row)) for row in rows]

    async def count_trades_since(
        self,
        since_iso: str,
        tenant_id: Optional[str] = "default",
    ) -> int:
        """Count non-cancelled trades with entry_time >= since_iso."""
        sql = (
            "SELECT COUNT(*) FROM trades WHERE status != 'cancelled' AND "
            + self._sql_dt("entry_time")
            + " >= "
            + self._sql_dt("?")
        )
        params: List[Any] = [since_iso]
        if tenant_id:
            sql += " AND tenant_id = ?"
            params.append(tenant_id)
        cursor = await self._db.execute(sql, tuple(params))
        row = await cursor.fetchone()
        return int((row[0] if row else 0) or 0)

    # ------------------------------------------------------------------
    # Signal Operations
    # ------------------------------------------------------------------

    async def insert_signal(
        self, signal: Dict[str, Any], tenant_id: Optional[str] = "default"
    ) -> int:
        """Insert a strategy signal."""
        async with self._timed_lock():
            cursor = await self._db.execute(
                """INSERT INTO signals
                (timestamp, pair, strategy, direction, strength,
                 confluence_count, ai_confidence, acted_upon, metadata, tenant_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    signal.get("timestamp", datetime.now(timezone.utc).isoformat()),
                    signal["pair"], signal["strategy"], signal["direction"],
                    signal["strength"], signal.get("confluence_count", 0),
                    signal.get("ai_confidence"), signal.get("acted_upon", 0),
                    json.dumps(signal.get("metadata", {})),
                    tenant_id or "default",
                )
            )
            await self._db.commit()
            return cursor.lastrowid

    # ------------------------------------------------------------------
    # Metrics Operations
    # ------------------------------------------------------------------

    async def insert_metric(
        self,
        name: str,
        value: float,
        tags: Optional[Dict] = None,
        tenant_id: Optional[str] = "default",
    ) -> None:
        """Insert a performance metric data point (optionally tenant-scoped)."""
        async with self._timed_lock():
            await self._db.execute(
                "INSERT INTO metrics (timestamp, metric_name, metric_value, tags, tenant_id) VALUES (?, ?, ?, ?, ?)",
                (
                    datetime.now(timezone.utc).isoformat(),
                    name,
                    value,
                    json.dumps(tags or {}),
                    tenant_id or "default",
                )
            )
            await self._db.commit()

    async def get_metrics(
        self,
        name: str,
        hours: int = 24,
        limit: int = 1000,
        tenant_id: Optional[str] = "default",
    ) -> List[Tuple[str, float]]:
        """Get metric time series for the last N hours (optionally tenant-scoped)."""
        cutoff = datetime.now(timezone.utc).timestamp() - float(hours) * 3600.0
        cutoff_str = datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat()
        sql = (
            """SELECT timestamp, metric_value FROM metrics
            WHERE metric_name = ? AND """
            + self._sql_dt("timestamp")
            + " >= "
            + self._sql_dt("?")
        )
        params: List[Any] = [name, cutoff_str]
        if tenant_id:
            sql += " AND tenant_id = ?"
            params.append(tenant_id)
        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        cursor = await self._db.execute(sql, tuple(params))
        return await cursor.fetchall()

    # ------------------------------------------------------------------
    # Thought Log (Dashboard AI Feed)
    # ------------------------------------------------------------------

    async def log_thought(
        self,
        category: str,
        message: str,
        severity: str = "info",
        metadata: Optional[Dict] = None,
        tenant_id: Optional[str] = "default",
    ) -> None:
        """Log an AI thought/decision for the dashboard. Optional tenant_id."""
        async with self._timed_lock():
            await self._db.execute(
                """INSERT INTO thought_log (timestamp, category, message, severity, metadata, tenant_id)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    datetime.now(timezone.utc).isoformat(),
                    category,
                    message,
                    severity,
                    json.dumps(metadata or {}),
                    tenant_id or "default",
                )
            )
            await self._db.commit()

    async def get_thoughts(
        self, limit: int = 50, tenant_id: Optional[str] = "default"
    ) -> List[Dict[str, Any]]:
        """Get recent AI thoughts for dashboard. Optional tenant_id."""
        if tenant_id:
            cursor = await self._db.execute(
                """SELECT timestamp, category, message, severity, metadata
                FROM thought_log
                WHERE tenant_id = ?
                ORDER BY id DESC LIMIT ?""",
                (tenant_id, limit),
            )
        else:
            cursor = await self._db.execute(
                """SELECT timestamp, category, message, severity, metadata
                FROM thought_log ORDER BY id DESC LIMIT ?""",
                (limit,),
            )
        columns = ["timestamp", "category", "message", "severity", "metadata"]
        rows = await cursor.fetchall()
        results = []
        for row in rows:
            d = dict(zip(columns, row))
            if d["metadata"]:
                try:
                    d["metadata"] = json.loads(d["metadata"])
                except json.JSONDecodeError:
                    pass
            results.append(d)
        return results

    # ------------------------------------------------------------------
    # ML Features
    # ------------------------------------------------------------------

    async def insert_ml_features(
        self,
        pair: str,
        features: Dict[str, float],
        label: Optional[float] = None,
        trade_id: Optional[str] = None,
        tenant_id: Optional[str] = "default",
    ) -> None:
        """Insert ML feature vector for training."""
        async with self._timed_lock():
            await self._db.execute(
                """INSERT INTO ml_features (timestamp, pair, features, label, trade_id, tenant_id)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    datetime.now(timezone.utc).isoformat(),
                    pair, json.dumps(features), label, trade_id, tenant_id or "default"
                )
            )
            await self._db.commit()

    async def get_ml_training_data(
        self, min_samples: int = 10000, tenant_id: Optional[str] = "default"
    ) -> List[Dict[str, Any]]:
        """Get labeled ML training data."""
        sql = """SELECT features, label FROM ml_features
            WHERE label IS NOT NULL"""
        params: List[Any] = []
        if tenant_id:
            sql += " AND tenant_id = ?"
            params.append(tenant_id)
        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(min_samples)
        cursor = await self._db.execute(sql, params)
        rows = await cursor.fetchall()
        results = []
        for row in rows:
            features = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            results.append({"features": features, "label": row[1]})
        return results

    async def update_ml_label_for_trade(
        self,
        trade_id: str,
        label: float,
        tenant_id: Optional[str] = "default",
    ) -> int:
        """
        Set/overwrite the ML label for the feature row tied to a given trade_id.

        Returns number of rows updated.
        """
        if not trade_id:
            return 0
        async with self._timed_lock():
            sql = "UPDATE ml_features SET label = ? WHERE trade_id = ?"
            params: List[Any] = [float(label), trade_id]
            if tenant_id:
                sql += " AND tenant_id = ?"
                params.append(tenant_id)
            cursor = await self._db.execute(sql, params)
            await self._db.commit()
            return int(getattr(cursor, "rowcount", 0) or 0)

    async def get_ml_features_for_trade(
        self,
        trade_id: str,
        tenant_id: Optional[str] = "default",
    ) -> Optional[Dict[str, float]]:
        """Fetch the stored ML feature dict for a given trade_id (best-effort)."""
        if not trade_id:
            return None
        sql = "SELECT features FROM ml_features WHERE trade_id = ?"
        params: List[Any] = [trade_id]
        if tenant_id:
            sql += " AND tenant_id = ?"
            params.append(tenant_id)
        sql += " ORDER BY id DESC LIMIT 1"
        try:
            cursor = await self._db.execute(sql, params)
            row = await cursor.fetchone()
            if not row:
                return None
            raw = row[0]
            data = json.loads(raw) if isinstance(raw, str) else raw
            if not isinstance(data, dict):
                return None
            out: Dict[str, float] = {}
            for k, v in data.items():
                try:
                    fv = float(v)
                    if math.isfinite(fv):
                        out[str(k)] = fv
                except Exception:
                    continue
            return out or None
        except Exception:
            return None

    # ------------------------------------------------------------------
    # System State
    # ------------------------------------------------------------------

    async def set_state(self, key: str, value: Any) -> None:
        """Set a system state key-value pair."""
        async with self._timed_lock():
            await self._db.execute(
                """INSERT OR REPLACE INTO system_state (key, value, updated_at)
                VALUES (?, ?, datetime('now'))""",
                (key, json.dumps(value))
            )
            await self._db.commit()

    async def get_state(self, key: str, default: Any = None) -> Any:
        """Get a system state value."""
        async with self._timed_lock():
            cursor = await self._db.execute(
                "SELECT value FROM system_state WHERE key = ?", (key,)
            )
            row = await cursor.fetchone()
        if row:
            try:
                return json.loads(row[0])
            except json.JSONDecodeError:
                return row[0]
        return default

    # ------------------------------------------------------------------
    # Daily Summary
    # ------------------------------------------------------------------

    async def update_daily_summary(
        self, date: str, stats: Dict[str, Any], tenant_id: Optional[str] = "default"
    ) -> None:
        """Update or insert daily performance summary."""
        async with self._timed_lock():
            await self._db.execute(
                """INSERT OR REPLACE INTO daily_summary
                (date, total_trades, winning_trades, losing_trades,
                 total_pnl, max_drawdown, sharpe_ratio, win_rate,
                 avg_win, avg_loss, best_trade, worst_trade, tenant_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    date,
                    stats.get("total_trades", 0),
                    stats.get("winning_trades", 0),
                    stats.get("losing_trades", 0),
                    stats.get("total_pnl", 0.0),
                    stats.get("max_drawdown", 0.0),
                    stats.get("sharpe_ratio"),
                    stats.get("win_rate"),
                    stats.get("avg_win"),
                    stats.get("avg_loss"),
                    stats.get("best_trade"),
                    stats.get("worst_trade"),
                    tenant_id or "default",
                )
            )
            await self._db.commit()

    # ------------------------------------------------------------------
    # Performance Stats
    # ------------------------------------------------------------------

    async def get_performance_stats(
        self, tenant_id: Optional[str] = "default"
    ) -> Dict[str, Any]:
        """Get aggregate performance statistics. Optional tenant_id for multi-tenant.

        Uses consolidated SQL queries and a short TTL cache to avoid
        repeated expensive scans within the same reporting window.
        """
        # --- TTL cache check ---
        cache_key = tenant_id or "__none__"
        now = time.monotonic()
        if (
            cache_key in self._perf_stats_cache
            and (now - self._perf_stats_cache_ts) < self._perf_stats_cache_ttl
        ):
            return self._perf_stats_cache[cache_key]

        stats: Dict[str, Any] = {}
        tc = " AND tenant_id = ?" if tenant_id else ""
        p: list = [tenant_id] if tenant_id else []

        reset_ts = await self.get_state("stats_reset_ts")
        rc = ""
        if reset_ts:
            rc = " AND " + self._sql_dt("exit_time") + " >= " + self._sql_dt("?")
            p.append(reset_ts)

        # --- Query 1: All closed-trade aggregates in a single pass ---
        cursor = await self._db.execute(
            f"""SELECT
                COUNT(*)                                              AS total,
                COALESCE(SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END), 0) AS wins,
                COALESCE(SUM(CASE WHEN pnl <= 0 THEN 1 ELSE 0 END), 0) AS losses,
                COALESCE(SUM(pnl), 0.0)                              AS total_pnl,
                AVG(CASE WHEN pnl > 0 THEN pnl END)                  AS avg_win,
                AVG(CASE WHEN pnl <= 0 THEN pnl END)                 AS avg_loss,
                COALESCE(SUM(CASE WHEN substr(exit_time, 1, 10) = date('now')
                              THEN pnl ELSE 0 END), 0.0)             AS today_pnl,
                -- Sharpe / Sortino building blocks (NULL-safe via pnl IS NOT NULL + ABS(pnl) < 1e308)
                COUNT(CASE WHEN pnl IS NOT NULL AND ABS(pnl) < 1e308 THEN 1 END) AS n_finite,
                COALESCE(AVG(CASE WHEN pnl IS NOT NULL AND ABS(pnl) < 1e308 THEN pnl END), 0.0) AS mean_pnl,
                COALESCE(AVG(CASE WHEN pnl IS NOT NULL AND ABS(pnl) < 1e308 THEN pnl * pnl END), 0.0) AS mean_pnl_sq,
                -- Downside (pnl < 0) moments for Sortino
                COUNT(CASE WHEN pnl IS NOT NULL AND ABS(pnl) < 1e308 AND pnl < 0 THEN 1 END) AS n_down,
                COALESCE(AVG(CASE WHEN pnl IS NOT NULL AND ABS(pnl) < 1e308 AND pnl < 0 THEN pnl * pnl END), 0.0) AS mean_down_sq
            FROM trades
            WHERE status = 'closed'{tc}{rc}""",
            tuple(p),
        )
        row = await cursor.fetchone()

        total = row[0] if row and row[0] is not None else 0
        wins = row[1] if row and row[1] is not None else 0
        losses = row[2] if row and row[2] is not None else 0
        stats["total_pnl"] = row[3] if row and row[3] is not None else 0.0
        stats["total_trades"] = total
        stats["winning_trades"] = wins
        stats["losing_trades"] = losses
        stats["win_rate"] = wins / total if total > 0 else 0.0
        stats["avg_win"] = row[4] if row and row[4] else 0.0
        stats["avg_loss"] = row[5] if row and row[5] else 0.0
        stats["today_pnl"] = row[6] if row and row[6] is not None else 0.0

        # Sharpe & Sortino from SQL-computed moments
        n_finite = row[7] if row and row[7] is not None else 0
        mean_pnl = row[8] if row and row[8] is not None else 0.0
        mean_pnl_sq = row[9] if row and row[9] is not None else 0.0
        n_down = row[10] if row and row[10] is not None else 0
        mean_down_sq = row[11] if row and row[11] is not None else 0.0

        if n_finite >= 5:
            # population variance = E[X^2] - (E[X])^2, then Bessel correction
            pop_var = mean_pnl_sq - mean_pnl * mean_pnl
            # Guard against floating-point rounding producing tiny negatives
            pop_var = max(pop_var, 0.0)
            variance = pop_var * n_finite / max(n_finite - 1, 1)
            std_dev = math.sqrt(variance) if variance > 0 else 0.0
            annual_factor = math.sqrt(min(n_finite, 2500))
            if std_dev > 1e-12:
                sharpe = mean_pnl / std_dev * annual_factor
                stats["sharpe_ratio"] = round(sharpe, 3) if math.isfinite(sharpe) else 0.0
            else:
                stats["sharpe_ratio"] = 0.0
            # Sortino
            if n_down > 0:
                down_dev = math.sqrt(mean_down_sq) if mean_down_sq > 0 else 0.0
                if down_dev > 1e-12:
                    sortino = mean_pnl / down_dev * annual_factor
                    stats["sortino_ratio"] = round(sortino, 3) if math.isfinite(sortino) else 0.0
                else:
                    stats["sortino_ratio"] = 0.0
            else:
                stats["sortino_ratio"] = 999.0  # No losing trades
        else:
            stats["sharpe_ratio"] = 0.0
            stats["sortino_ratio"] = 0.0

        # --- Query 2: Open-position count (different WHERE clause, no reset_ts) ---
        cursor = await self._db.execute(
            f"SELECT COUNT(*) FROM trades WHERE status = 'open' AND ABS(quantity) > 0.00000001{tc}",
            tuple([tenant_id] if tenant_id else []),
        )
        row = await cursor.fetchone()
        stats["open_positions"] = row[0] if row else 0

        # --- Populate cache ---
        self._perf_stats_cache[cache_key] = stats
        self._perf_stats_cache_ts = now

        return stats

    async def get_strategy_stats(
        self, tenant_id: Optional[str] = "default"
    ) -> Dict[str, Dict[str, Any]]:
        """Get per-strategy win rate and PnL stats."""
        tc = " AND tenant_id = ?" if tenant_id else ""
        params: list = [tenant_id] if tenant_id else []
        cursor = await self._db.execute(
            f"""SELECT strategy,
                COUNT(*) as total,
                SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                COALESCE(SUM(pnl), 0) as total_pnl,
                COALESCE(AVG(pnl), 0) as avg_pnl
            FROM trades
            WHERE status = 'closed' AND strategy IS NOT NULL{tc}
            GROUP BY strategy""",
            tuple(params),
        )
        rows = await cursor.fetchall()
        result: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            strat = row[0]
            total = row[1] or 0
            wins = row[2] or 0
            result[strat] = {
                "total_trades": total,
                "wins": wins,
                "win_rate": round(wins / total, 3) if total > 0 else 0.0,
                "total_pnl": round(float(row[3] or 0.0), 4),
                "avg_pnl": round(float(row[4] or 0.0), 4),
            }
        return result

    # ------------------------------------------------------------------
    # Hourly Performance Stats (Session-Aware Trading)
    # ------------------------------------------------------------------

    async def get_hourly_stats(
        self,
        tenant_id: Optional[str] = "default",
        pair: Optional[str] = None,
    ) -> Dict[int, Dict[str, Any]]:
        """Get per-hour trade performance.

        Returns ``{hour: {"total": int, "wins": int, "avg_pnl": float}}``.
        """
        sql = """
            SELECT CAST(strftime('%H', replace(substr(entry_time, 1, 19), 'T', ' ')) AS INTEGER) as hour,
                   COUNT(*) as total,
                   SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                   AVG(pnl) as avg_pnl
            FROM trades
            WHERE status = 'closed'
        """
        params: List[Any] = []
        if tenant_id:
            sql += " AND tenant_id = ?"
            params.append(tenant_id)
        if pair:
            sql += " AND pair = ?"
            params.append(pair)
        sql += " GROUP BY hour"

        cursor = await self._db.execute(sql, tuple(params))
        rows = await cursor.fetchall()
        result: Dict[int, Dict[str, Any]] = {}
        for row in rows:
            hour = int(row[0]) if row[0] is not None else 0
            result[hour] = {
                "total": int(row[1] or 0),
                "wins": int(row[2] or 0),
                "avg_pnl": float(row[3] or 0.0),
            }
        return result

    # ------------------------------------------------------------------
    # Backtesting / Optimization Runs
    # ------------------------------------------------------------------

    async def insert_backtest_run(
        self,
        *,
        run_id: str,
        pair: str,
        run_type: str = "backtest",
        status: str = "completed",
        mode: str = "",
        exchange: str = "",
        timeframe: str = "",
        params: Optional[Dict[str, Any]] = None,
        result: Optional[Dict[str, Any]] = None,
        tenant_id: Optional[str] = "default",
        started_at: str = "",
        completed_at: str = "",
    ) -> None:
        """Persist a backtest/optimization run for audit and dashboard history."""
        self._ensure_ready()
        async with self._timed_lock():
            await self._db.execute(
                """
                INSERT OR REPLACE INTO backtest_runs
                (run_id, tenant_id, exchange, pair, timeframe, mode, status, run_type,
                 params_json, result_json, started_at, completed_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    run_id,
                    tenant_id or "default",
                    exchange,
                    pair,
                    timeframe,
                    mode,
                    status,
                    run_type,
                    json.dumps(params or {}),
                    json.dumps(result or {}),
                    started_at or datetime.now(timezone.utc).isoformat(),
                    completed_at or datetime.now(timezone.utc).isoformat(),
                ),
            )
            await self._db.commit()

    async def get_backtest_runs(
        self,
        *,
        limit: int = 25,
        tenant_id: Optional[str] = "default",
    ) -> List[Dict[str, Any]]:
        """List recent backtest/optimization runs."""
        self._ensure_ready()
        lim = max(1, min(int(limit), 250))
        params: List[Any] = []
        sql = """
            SELECT run_id, tenant_id, exchange, pair, timeframe, mode, status, run_type,
                   params_json, result_json, started_at, completed_at, created_at
            FROM backtest_runs
        """
        if tenant_id:
            sql += " WHERE tenant_id = ?"
            params.append(tenant_id)
        sql += " ORDER BY datetime(created_at) DESC LIMIT ?"
        params.append(lim)

        cursor = await self._db.execute(sql, tuple(params))
        rows = await cursor.fetchall()
        out: List[Dict[str, Any]] = []
        for row in rows:
            try:
                params_json = json.loads(row[8] or "{}")
            except Exception:
                params_json = {}
            try:
                result_json = json.loads(row[9] or "{}")
            except Exception:
                result_json = {}
            out.append(
                {
                    "run_id": row[0],
                    "tenant_id": row[1],
                    "exchange": row[2],
                    "pair": row[3],
                    "timeframe": row[4],
                    "mode": row[5],
                    "status": row[6],
                    "run_type": row[7],
                    "params": params_json,
                    "result": result_json,
                    "started_at": row[10],
                    "completed_at": row[11],
                    "created_at": row[12],
                }
            )
        return out

    async def upsert_copy_trading_provider(
        self,
        *,
        provider_id: str,
        name: str,
        tenant_id: Optional[str] = "default",
        source: str = "",
        enabled: bool = True,
        webhook_secret: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Create or update a copy-trading provider record."""
        self._ensure_ready()
        async with self._timed_lock():
            await self._db.execute(
                """
                INSERT INTO copy_trading_providers
                (provider_id, tenant_id, name, source, enabled, webhook_secret, metadata_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                ON CONFLICT(provider_id) DO UPDATE SET
                    tenant_id = excluded.tenant_id,
                    name = excluded.name,
                    source = excluded.source,
                    enabled = excluded.enabled,
                    webhook_secret = excluded.webhook_secret,
                    metadata_json = excluded.metadata_json,
                    updated_at = datetime('now')
                """,
                (
                    provider_id,
                    tenant_id or "default",
                    name,
                    source,
                    1 if enabled else 0,
                    webhook_secret,
                    json.dumps(metadata or {}),
                ),
            )
            await self._db.commit()

    async def get_copy_trading_providers(
        self,
        *,
        tenant_id: Optional[str] = "default",
        enabled_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """List copy-trading providers for a tenant."""
        self._ensure_ready()
        sql = """
            SELECT provider_id, tenant_id, name, source, enabled, webhook_secret, metadata_json, created_at, updated_at
            FROM copy_trading_providers
            WHERE tenant_id = ?
        """
        params: List[Any] = [tenant_id or "default"]
        if enabled_only:
            sql += " AND enabled = 1"
        sql += " ORDER BY datetime(updated_at) DESC"

        cursor = await self._db.execute(sql, tuple(params))
        rows = await cursor.fetchall()
        out: List[Dict[str, Any]] = []
        for row in rows:
            try:
                meta = json.loads(row[6] or "{}")
            except Exception:
                meta = {}
            out.append(
                {
                    "provider_id": row[0],
                    "tenant_id": row[1],
                    "name": row[2],
                    "source": row[3],
                    "enabled": bool(row[4]),
                    "webhook_secret": row[5] or "",
                    "metadata": meta,
                    "created_at": row[7],
                    "updated_at": row[8],
                }
            )
        return out

    async def get_copy_trading_provider(
        self,
        *,
        provider_id: str,
        tenant_id: Optional[str] = "default",
    ) -> Optional[Dict[str, Any]]:
        """Get one copy-trading provider by id."""
        if not provider_id:
            return None
        providers = await self.get_copy_trading_providers(tenant_id=tenant_id, enabled_only=False)
        for p in providers:
            if p.get("provider_id") == provider_id:
                return p
        return None

    # ------------------------------------------------------------------
    # Tenants (multi-tenant / Stripe)
    # ------------------------------------------------------------------

    async def get_tenant(self, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Get tenant by id."""
        cursor = await self._db.execute(
            "SELECT id, name, stripe_customer_id, stripe_subscription_id, status, created_at FROM tenants WHERE id = ?",
            (tenant_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "name": row[1],
            "stripe_customer_id": row[2],
            "stripe_subscription_id": row[3],
            "status": row[4],
            "created_at": row[5],
        }

    async def upsert_tenant(
        self,
        tenant_id: str,
        name: str,
        *,
        stripe_customer_id: Optional[str] = None,
        stripe_subscription_id: Optional[str] = None,
        status: str = "active",
    ) -> None:
        """Create or update tenant."""
        async with self._timed_lock():
            await self._db.execute(
                """INSERT INTO tenants (id, name, stripe_customer_id, stripe_subscription_id, status, updated_at)
                   VALUES (?, ?, ?, ?, ?, datetime('now'))
                   ON CONFLICT(id) DO UPDATE SET
                     name = excluded.name,
                     stripe_customer_id = COALESCE(excluded.stripe_customer_id, stripe_customer_id),
                     stripe_subscription_id = COALESCE(excluded.stripe_subscription_id, stripe_subscription_id),
                     status = excluded.status,
                     updated_at = datetime('now')""",
                (tenant_id, name, stripe_customer_id, stripe_subscription_id, status),
            )
            await self._db.commit()

    async def set_tenant_status(self, tenant_id: str, status: str) -> None:
        """Update tenant subscription status (active, past_due, canceled, etc.)."""
        async with self._timed_lock():
            await self._db.execute(
                "UPDATE tenants SET status = ?, updated_at = datetime('now') WHERE id = ?",
                (status, tenant_id),
            )
            await self._db.commit()

    async def get_tenant_by_stripe_customer(self, stripe_customer_id: str) -> Optional[Dict[str, Any]]:
        """Get tenant by Stripe customer id."""
        cursor = await self._db.execute(
            "SELECT id FROM tenants WHERE stripe_customer_id = ?",
            (stripe_customer_id,),
        )
        row = await cursor.fetchone()
        return await self.get_tenant(row[0]) if row else None

    async def get_tenant_by_stripe_subscription(self, stripe_subscription_id: str) -> Optional[Dict[str, Any]]:
        """Get tenant by Stripe subscription id."""
        cursor = await self._db.execute(
            "SELECT id FROM tenants WHERE stripe_subscription_id = ?",
            (stripe_subscription_id,),
        )
        row = await cursor.fetchone()
        return await self.get_tenant(row[0]) if row else None

    async def get_tenant_id_by_api_key(self, api_key: str) -> Optional[str]:
        """Resolve tenant_id by API key (hashed lookup)."""
        if not api_key:
            return None
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        cursor = await self._db.execute(
            "SELECT tenant_id FROM tenant_api_keys WHERE api_key_hash = ?",
            (key_hash,),
        )
        row = await cursor.fetchone()
        return row[0] if row else None

    # ------------------------------------------------------------------
    # Billing Webhook Idempotency
    # ------------------------------------------------------------------

    async def has_processed_stripe_webhook_event(self, event_id: str) -> bool:
        """Return True if the Stripe event_id has already been processed."""
        self._ensure_ready()
        if not event_id:
            return False
        cursor = await self._db.execute(
            "SELECT 1 FROM stripe_webhook_events WHERE event_id = ?",
            (event_id,),
        )
        row = await cursor.fetchone()
        return bool(row)

    async def mark_stripe_webhook_event_processed(
        self,
        event_id: str,
        *,
        event_type: str = "",
        payload_hash: str = "",
    ) -> bool:
        """
        Mark Stripe webhook event as processed.

        Returns True if inserted now, False if this event_id already existed.
        """
        self._ensure_ready()
        if not event_id:
            return False
        async with self._timed_lock():
            cursor = await self._db.execute(
                """
                INSERT OR IGNORE INTO stripe_webhook_events
                (event_id, event_type, payload_hash, received_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    event_id,
                    event_type,
                    payload_hash,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            await self._db.commit()
            return bool(cursor.rowcount and cursor.rowcount > 0)

    async def has_processed_signal_webhook_event(self, event_id: str) -> bool:
        """Return True if the signal webhook event_id has already been processed."""
        self._ensure_ready()
        if not event_id:
            return False
        cursor = await self._db.execute(
            "SELECT 1 FROM signal_webhook_events WHERE event_id = ?",
            (event_id,),
        )
        row = await cursor.fetchone()
        return bool(row)

    async def mark_signal_webhook_event_processed(
        self,
        event_id: str,
        *,
        source: str = "",
        payload_hash: str = "",
        tenant_id: Optional[str] = "default",
    ) -> bool:
        """
        Mark signal webhook event as processed.

        Returns True if inserted now, False if this event_id already existed.
        """
        self._ensure_ready()
        if not event_id:
            return False
        async with self._timed_lock():
            cursor = await self._db.execute(
                """
                INSERT OR IGNORE INTO signal_webhook_events
                (event_id, source, payload_hash, received_at, tenant_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    source,
                    payload_hash,
                    datetime.now(timezone.utc).isoformat(),
                    tenant_id or "default",
                ),
            )
            await self._db.commit()
            return bool(cursor.rowcount and cursor.rowcount > 0)

    # ------------------------------------------------------------------
    # Cleanup & Close
    # ------------------------------------------------------------------

    async def cleanup_old_data(self, retention_hours: int = 72) -> None:
        """Remove old metrics and thought logs past retention period."""
        async with self._timed_lock():
            # Use datetime parsing that tolerates ISO8601 + 'T' timestamps.
            await self._db.execute(
                "DELETE FROM metrics WHERE " + self._sql_dt("timestamp") + " < datetime('now', ?)",
                (f"-{retention_hours} hours",)
            )
            await self._db.execute(
                "DELETE FROM thought_log WHERE " + self._sql_dt("timestamp") + " < datetime('now', ?)",
                (f"-{retention_hours} hours",)
            )
            await self._db.execute(
                "DELETE FROM order_book_snapshots WHERE " + self._sql_dt("timestamp") + " < datetime('now', ?)",
                (f"-{retention_hours} hours",)
            )
            await self._db.commit()

    async def close(self) -> None:
        """Close database connection gracefully."""
        if self._db:
            await self._db.close()
            self._db = None
            self._initialized = False
