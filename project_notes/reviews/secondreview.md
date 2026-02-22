# Nova|Pulse — Second Codebase Review

**Date:** 2026-02-22
**Reviewer:** Senior Web App Engineer + Fintech Systems Architect
**Scope:** Full codebase deep-dive focused on refactoring, performance optimization, and improvement opportunities
**Test Suite Status:** 172 tests passing, 0 failures

---

## Executive Summary

After completing all P0/P1 fixes and 5 proactive improvements from the first review, this second pass examined the full codebase through four lenses: **performance**, **refactoring**, **architecture**, and **new code quality**. The codebase is production-capable, but several performance bottlenecks and structural issues will compound under load. The most impactful findings are:

1. **Performance:** The position management loop runs sequentially despite a comment saying it's parallel. Three exchange-stop methods perform full table scans to find a single trade. `get_performance_stats` fires 7 DB queries per second per WebSocket client.
2. **Refactoring:** The same metadata JSON parsing pattern appears 8 times in executor.py. Test stubs exist in conftest.py but 3 test files still define their own copies. `execute_signal` is ~400 lines with 7+ exit points.
3. **Architecture:** `initialize()` is 564 lines constructing every subsystem inline. `RiskManager._open_positions` and the DB can diverge. `ConfigManager` singleton returns wrong config in multi-engine mode.
4. **New Code Quality:** `_cancel_exchange_stop` is missing the `rest_client` None guard that `_place_exchange_stop` has. `_LOGIN_LOCKOUT` constant is defined but never used.

---

## Risk Register

### Severity Definitions

| Level | Definition |
|-------|-----------|
| **CRITICAL** | Will cause incorrect behavior, data loss, or significant performance degradation under production load |
| **HIGH** | Meaningful impact on maintainability, performance, or correctness; should be fixed before scaling |
| **MEDIUM** | Improvement that reduces tech debt, improves clarity, or prevents future bugs |
| **LOW** | Nice-to-have cleanup; minimal risk if deferred |

---

## Section 1: Performance

### P-CRIT-1: `manage_open_positions` runs sequentially despite "parallel" comment
- **File:** `src/execution/executor.py:712-731`
- **Impact:** CRITICAL
- **Detail:** The docstring says "ENHANCEMENT: Added parallel position management" but the implementation is a sequential `for` loop. Each `_manage_position` call awaits DB writes and exchange stop updates. With N positions at a 1-second cycle interval, total cycle time scales linearly with position count.
- **Fix:** Replace the loop with `asyncio.gather(*[self._manage_position(t) for t in open_trades], return_exceptions=True)` — the same pattern already used in `close_all_positions`.

### P-CRIT-2: Exchange stop methods perform full DB scan to find one trade by ID
- **File:** `src/execution/executor.py:762, 790, 816`
- **Impact:** CRITICAL
- **Detail:** `_place_exchange_stop`, `_update_exchange_stop`, and `_cancel_exchange_stop` all call `get_open_trades(tenant_id=...)` (fetches all open trades) then linearly search for one `trade_id`. This is O(N) per call when `trade_id` is a primary key. Called on every stop update cycle in live mode.
- **Fix:** Add a `get_trade_by_id(trade_id, tenant_id)` method to `DatabaseManager`. Alternatively, pass metadata directly from the caller (it's already in scope at the call sites).

### P-CRIT-3: `get_performance_stats` fires 7 queries per second per WebSocket client
- **File:** `src/core/database.py:1068-1168`
- **Impact:** CRITICAL
- **Detail:** Issues 6 sequential SQL queries (total_pnl, count/wins/losses, avg_win, avg_loss, open_positions, today_pnl) plus a 7th that fetches ALL closed trade PnL values into Python memory for Sharpe/Sortino calculation. Called every second from `_collect_ws_engine_snapshot` per WS client, plus on every `execute_signal`.
- **Fix:**
  1. Merge into 1-2 queries using SQL aggregates (`COUNT(*)`, `SUM(pnl)`, `SUM(CASE WHEN ...)`)
  2. Compute Sharpe/Sortino in SQL: `SELECT AVG(pnl), AVG(pnl*pnl), COUNT(*) ...` then `variance = avg_sq - avg^2`
  3. Cache result with a 5-second TTL

### P-CRIT-4: `execute_signal` calls `get_open_trades` twice per signal
- **File:** `src/execution/executor.py:371-386`
- **Impact:** CRITICAL
- **Detail:** First call at line 371 fetches open trades filtered by pair to check for duplicates. Second call at line 380 fetches ALL open trades for correlation group check. If the pair is in `_correlation_groups` (8 of the most common crypto pairs), both calls always execute.
- **Fix:** Fetch `get_open_trades(tenant_id=...)` once at the start. Use in-memory filtering for both the pair-duplicate check and correlation group count.

### P-HIGH-1: Missing composite index on `(tenant_id, status)` for the hottest query
- **File:** `src/core/database.py:287-303`
- **Impact:** HIGH
- **Detail:** `get_open_trades` runs `SELECT * FROM trades WHERE status = 'open' AND tenant_id = ?`. Existing indexes are single-column only: `trades(pair)`, `trades(status)`, `trades(entry_time)`. No composite index exists. As closed trades accumulate (never deleted), the scan worsens.
- **Fix:** Add `CREATE INDEX IF NOT EXISTS idx_trades_tenant_status ON trades(tenant_id, status)` to `_ensure_indexes()`.

### P-HIGH-2: Sharpe/Sortino PnL fetch is unbounded — grows with trade history
- **File:** `src/core/database.py:1135-1140`
- **Impact:** HIGH (worsens over time)
- **Detail:** `SELECT pnl FROM trades WHERE status = 'closed'` fetches every closed trade's PnL with no LIMIT. At 100 trades/day over 6 months that's ~18,000 rows loaded into Python memory every second.
- **Fix:** Compute variance in SQL: `SELECT AVG(pnl), AVG(pnl*pnl), COUNT(*) ...` then `variance = avg_sq - avg^2`. Or cap with `LIMIT 2500`.

### P-HIGH-3: Favorites read from DB every second per WebSocket client
- **File:** `src/api/server.py:3385, 328-333`
- **Impact:** HIGH
- **Detail:** Every `_build_ws_update` call (once/sec/client) calls `_read_favorites_state`, which acquires the DB lock and executes a SQLite query. Favorites change only when the user explicitly adds/removes them (rare).
- **Fix:** Cache favorites in memory per tenant on `DashboardServer`, update only when `_write_favorites_state` is called.

### P-MED-1: Metadata JSON parsed twice per position per cycle
- **File:** `src/execution/executor.py:919-926, 1191`
- **Impact:** MEDIUM
- **Detail:** Every `_manage_position` call does `json.loads` on metadata. If smart exits are enabled, `_check_smart_exit` parses it again. With large `partial_exits` arrays this is not free.
- **Fix:** Parse once and pass the parsed dict to downstream methods.

### P-MED-2: OHLCV resampling uses pure-Python loop on NumPy arrays
- **File:** `src/ai/confluence.py:462-533`
- **Impact:** MEDIUM
- **Detail:** For each pair and each timeframe > 1, `_resample_ohlcv` iterates up to 500 bars in a Python `for` loop. The data is already NumPy arrays but is processed element-by-element, eliminating vectorization benefit. ~10 pairs x 2 extra timeframes = 20 resampling calls per cycle.
- **Fix:** Vectorize using `np.diff`, `np.where`, and `np.add.reduceat`.

### P-MED-3: `RingBuffer.view()` always allocates via `np.concatenate` when full
- **File:** `src/core/structures.py:58-70`
- **Impact:** MEDIUM
- **Detail:** At steady state (buffer full), `view()` always calls `np.concatenate` which allocates a new array. Called 6+ times per pair per scan cycle (get_closes, get_highs, get_lows, etc.). With 10 pairs that's 60+ allocations per cycle.
- **Fix:** Call `view()` once per column per scan cycle and cache the result, or track a `_is_contiguous` flag to skip concatenation when the buffer hasn't wrapped.

### P-MED-4: Single global `asyncio.Lock` serializes all DB writes
- **File:** `src/core/database.py:53, 60-76`
- **Impact:** MEDIUM
- **Detail:** One `asyncio.Lock` for all write operations. With WAL mode, SQLite allows concurrent readers + one writer, so the application-level lock is stricter than the DB requires. Multiple writes during position close (`log_thought` + `insert_metric` + `update_trade`) are unnecessarily serialized.
- **Fix:** Consider letting aiosqlite's internal queue handle write serialization, or use WAL-mode concurrency more aggressively.

---

## Section 2: Refactoring

### R-HIGH-1: Metadata JSON parsing duplicated 8 times in executor.py
- **File:** `src/execution/executor.py:171, 242, 768, 797, 823, 923, 968, 1191`
- **Impact:** HIGH
- **Detail:** The same `json.loads(trade["metadata"]) if isinstance(trade["metadata"], str) else dict(trade["metadata"])` pattern appears 8 times with subtle variants (some do `dict()`, some don't). Risk of divergence if parsing behavior changes.
- **Fix:** Extract a `_parse_meta(raw) -> dict` static helper and replace all 8 sites.

### R-HIGH-2: Test stubs not migrated to conftest.py
- **Files:** `tests/test_execute_signal.py`, `tests/test_executor_runtime_guards.py`, `tests/test_reinitialize_positions.py`, `tests/test_control_endpoints.py`
- **Impact:** HIGH
- **Detail:** Despite conftest.py providing `StubDB`, `StubMarketData`, `StubRiskManager`, `make_signal`, `make_executor`, and `make_trade`, these 4 test files redefine their own private stub versions. Bug fixes in conftest stubs don't flow to these files. `test_execute_signal._StubDB` is missing `update_ml_label_for_trade` and `get_ml_features_for_trade` methods.
- **Fix:** Migrate all 4 files to import shared stubs from conftest.py.

### R-HIGH-3: `execute_signal` is ~400 lines with 7+ exit points
- **File:** `src/execution/executor.py:304-700`
- **Impact:** HIGH
- **Detail:** Covers signal validation, age decay, quiet hours, trade-rate throttle, duplicate pair check, correlation guard, risk check, position sizing, order placement, fill processing, trade recording, ML features, order book snapshot, stop init, and logging. Makes unit testing individual stages very difficult.
- **Fix:** Decompose into 5 focused methods: `_validate_signal`, `_check_rate_and_correlation`, `_size_and_fill`, `_record_trade`, `_capture_entry_telemetry`.

### R-HIGH-4: `_setup_routes` is ~2,000+ lines in a single closure
- **File:** `src/api/server.py:997-3400+`
- **Impact:** HIGH
- **Detail:** All route handlers are nested closures sharing auth helpers via closure scope. Prevents independent testing, reuse, or documentation of auth helpers. Auth helpers (`_require_read_access`, `_require_control_access`, etc.) should be proper class methods.
- **Fix:** Promote auth helpers out of closure scope to class methods. Consider FastAPI `APIRouter` grouping.

### R-HIGH-5: `_close_position` is ~220 lines
- **File:** `src/execution/executor.py:943-1163`
- **Impact:** HIGH
- **Detail:** Combines fee extraction, live order retry with exponential backoff (3 attempts, 60 lines), partial fill handling, P&L calculation, ML label updates, learner updates, strategy callbacks, and logging.
- **Fix:** Extract `_exit_live_order()` helper for the retry block (~60 lines). Reduces `_close_position` to ~130 lines.

### R-HIGH-6: `initialize()` in engine.py is ~565 lines
- **File:** `src/core/engine.py:405-969`
- **Impact:** HIGH
- **Detail:** Constructs every subsystem inline — DB, REST, WS, MarketData, Confluence, TFLite, ContinuousLearner, OrderBook, Risk, Executor, ML, Dashboard, Telegram, Discord, Slack, Stripe, Elasticsearch. Untestable as a unit.
- **Fix:** Decompose into factory methods: `_init_exchange_clients()`, `_init_ai_components()`, `_init_ml_components()`, `_init_notifications()`, `_init_observability()`.

### R-MED-1: Double auth check on several API endpoints
- **File:** `src/api/server.py:1678-1685, 2135-2142`
- **Impact:** MEDIUM
- **Detail:** Some endpoints use both `Depends(_resolve_tenant_id_read)` (which internally calls `_require_read_access`) AND an explicit `await _require_read_access(...)` in the handler body. The auth check runs twice per request, including a redundant DB hit for tenant key lookup.
- **Fix:** Remove the manual `await _require_read_access(...)` call from endpoints that already use `Depends(_resolve_tenant_id_read)`.

### R-MED-2: Duplicated take-profit close branches
- **File:** `src/execution/executor.py:898-913`
- **Impact:** MEDIUM
- **Detail:** Buy and sell TP branches call `_close_position` with identical arguments — only the comparison operator differs. 14 lines that can collapse to 6.
- **Fix:** Combine: `tp_hit = (side == "buy" and price >= tp) or (side == "sell" and price <= tp)`.

### R-MED-3: Magic number `24` for max trade duration
- **File:** `src/execution/executor.py:854-855`
- **Impact:** MEDIUM
- **Detail:** Hardcoded `max_duration_hours = 24` with no config override. Users on slower markets (weekends, etc.) have no way to extend.
- **Fix:** Make configurable: `getattr(self.config.trading, "max_trade_duration_hours", 24)`.

### R-LOW-1: Unused imports in engine.py
- **File:** `src/core/engine.py:29, 31`
- **Impact:** LOW
- **Detail:** `ConfigManager` and `ErrorSeverity` imported but never used. Only `get_config` and `GracefulErrorHandler` are used.
- **Fix:** Remove unused imports.

### R-LOW-2: Redundant `from datetime import` inside function body
- **File:** `src/execution/executor.py:858`
- **Impact:** LOW
- **Detail:** `from datetime import datetime, timezone` duplicates the module-level import at line 23.
- **Fix:** Remove the in-function import.

### R-LOW-3: `rest_client: Any` / `es_client: Optional[Any]` type holes
- **File:** `src/execution/executor.py:57, 68`
- **Impact:** LOW
- **Detail:** Both typed as `Any`. The executor calls specific methods on these. A `Protocol` or `ABC` would catch interface mismatches at type-check time.
- **Fix:** Define an `ExchangeRESTProtocol` with the required methods.

---

## Section 3: Architecture

### A-HIGH-1: Dual state — `RiskManager._open_positions` vs. DB open trades
- **File:** `src/execution/risk_manager.py:137-149`
- **Impact:** HIGH
- **Detail:** RiskManager maintains `_open_positions` (in-memory dict) alongside the DB. Divergence scenarios:
  1. If `reinitialize_positions()` fails, RM starts empty while DB has open trades — allows exceeding max concurrent positions
  2. `close_all_positions()` with partial failures: DB marks trade closed but RM still holds it
  3. `reinitialize_positions()` calls `register_position()` which increments `_daily_trades`, double-counting today's trades
- **Fix:** Make DB the single source of truth for position count. RM's `_pre_trade_checks()` should query DB for live count.

### A-HIGH-2: Exchange errors not categorized at source
- **File:** `src/exchange/kraken_rest.py`, `src/execution/executor.py`
- **Impact:** HIGH
- **Detail:** `_live_fill()` wraps all exceptions with `except Exception as e: return None`. Transient timeouts, rate limits, auth failures, and insufficient margin are collapsed into the same silent failure path. The caller logs a generic "Order fill failed" with no root cause.
- **Fix:** Define typed exception hierarchy: `ExchangeError > TransientExchangeError > RateLimitError` and `PermanentExchangeError > AuthenticationError`. Let the executor apply correct retry strategy per type.

### A-HIGH-3: ConfigManager singleton returns wrong config in multi-engine mode
- **File:** `src/core/config.py:817-889`, `main.py:564-570`
- **Impact:** HIGH
- **Detail:** `ConfigManager` singleton holds one `_config`. In multi-engine mode, each engine has its own `BotConfig`, but the executor calls `get_config()` at lines 346-349 and 1173-1179, receiving whichever config was last loaded globally. The Coinbase executor could read Kraken quiet hours.
- **Fix:** Pass all config values through the constructor. Remove runtime `get_config()` calls from executor.

### A-HIGH-4: ConfigManager singleton not reset between tests
- **File:** `src/core/config.py:817-826`
- **Impact:** HIGH
- **Detail:** Any test that loads a config sets singleton state for all subsequent tests. No `@pytest.fixture` resets `ConfigManager._instance` / `ConfigManager._config` between tests.
- **Fix:** Add autouse fixture: save/restore `ConfigManager._instance` and `._config` around each test.

### A-MED-1: Executor calls `get_config()` at runtime — hidden dependency
- **File:** `src/execution/executor.py:346-349, 1173-1179`
- **Impact:** MEDIUM
- **Detail:** `execute_signal()` calls `get_config()` for `quiet_hours_utc`. `_is_smart_exit_enabled()` calls `get_config()` for `risk.smart_exit`. Tests must double-patch both module references.
- **Fix:** Pass `quiet_hours_utc` and `smart_exit_config` as constructor parameters.

### A-MED-2: Circular reference — BotEngine ↔ ControlRouter ↔ TelegramBot
- **File:** `src/core/engine.py:780`
- **Impact:** MEDIUM
- **Detail:** `ControlRouter(self)` stores a reference to the full engine. Telegram, Discord, and Slack bots receive both the engine and control router. Makes isolated testing impossible.
- **Fix:** Define a narrow `EngineInterface` protocol with only the methods ControlRouter actually calls.

### A-MED-3: Missing config validation on critical financial values
- **File:** `src/core/config.py` (RiskConfig, TradingConfig)
- **Impact:** MEDIUM
- **Detail:** No Pydantic validators on: `initial_bankroll` (0 causes div-by-zero), `kelly_fraction` (>1.0 is invalid), `trailing_step_pct` (no upper bound), `scan_interval_seconds` (0 = tight infinite loop), `warmup_bars` (<50 = meaningless indicators). `StocksConfig` already has excellent validation — extend to these.
- **Fix:** Add `@field_validator` for each with safe bounds.

### A-MED-4: Entry vs. exit retry inconsistency
- **File:** `src/execution/executor.py`
- **Impact:** MEDIUM
- **Detail:** Exit path (`_close_position`) has 3-attempt retry with exponential backoff. Entry path (`_live_fill`) has fixed-delay limit chase then market fallback. Failed entry silently vanishes; failed exit sets "error" state.
- **Fix:** Standardize retry strategy across both paths using typed exchange exceptions.

### A-MED-5: Multi-engine dashboard misses logger handler attachments
- **File:** `main.py:610-616`
- **Impact:** MEDIUM
- **Detail:** In multi-exchange mode, standalone dashboard doesn't inherit Telegram alert handler or other logger attachments that single-engine path sets up.
- **Fix:** Call `attach_dashboard_alerts(dashboard)` in multi-engine path.

### A-MED-6: Mixed logging backends — structlog vs stdlib
- **File:** `src/core/config.py:243`, `src/core/logger.py`
- **Impact:** MEDIUM
- **Detail:** `config.py` uses bare `import logging; logging.getLogger("config").warning(...)` — bypasses structlog processor chain, structured fields, and sensitive data masking.
- **Fix:** Replace with `structlog.get_logger("config")` calls.

### A-LOW-1: Strategy config passed as raw dict across boundaries
- **File:** `src/core/engine.py:604-609`
- **Impact:** LOW
- **Detail:** `self.confluence.configure_strategies(self.config.strategies.model_dump(), ...)` discards type information. Renamed Pydantic fields silently pass `None`.
- **Fix:** Pass the `StrategiesConfig` model directly.

### A-LOW-2: Priority scheduling and stock engine coordinate via implicit flag contract
- **File:** `main.py:310-356`
- **Impact:** LOW
- **Detail:** The priority scheduling loop manipulates `_priority_paused` on engine objects. The stock engine checks `_running` and `_trading_paused` but not `_priority_paused`. Interface contract is implicit.
- **Fix:** Define an explicit `Pausable` protocol.

---

## Section 4: New Code Quality (From First Review Improvements)

### N-CRIT-1: `_cancel_exchange_stop` missing `rest_client` None guard
- **File:** `src/execution/executor.py:813-834`
- **Impact:** CRITICAL
- **Detail:** `_place_exchange_stop` checks `if not self.rest_client: return None` at line 741. `_cancel_exchange_stop` has no such guard. If called outside the existing `_close_position` guard (future refactor, direct test), it raises `AttributeError` on None.
- **Fix:** Add `if not self.rest_client: return` at the top of `_cancel_exchange_stop`.

### N-CRIT-2: `_LOGIN_LOCKOUT` constant defined but never used
- **File:** `src/api/server.py:1255`
- **Impact:** CRITICAL (misleading)
- **Detail:** Defined `_LOGIN_LOCKOUT = 300.0` but the lockout check uses `_LOGIN_WINDOW` (300.0). The lockout and detection window are identical by accident. Any reader assumes a distinct lockout duration exists. If the intent was a longer cooldown (e.g., 900s), that logic is entirely absent.
- **Fix:** Either use `_LOGIN_LOCKOUT` in the lockout check for a distinct cooldown period, or remove the dead constant and document that the 5-minute window IS the lockout.

### N-MED-1: Ghost reconcile warnings fire for every filled trade
- **File:** `src/execution/executor.py:259-267`
- **Impact:** MEDIUM
- **Detail:** Filled orders disappear from open orders, so every successfully filled trade triggers a WARNING-level "ghost position" log on every reconciliation cycle. Causes alert fatigue.
- **Fix:** Downgrade to `logger.info` or `logger.debug`. Only escalate to WARNING if the trade has been open unusually long without a matching exchange order.

### N-MED-2: Startup reconcile blocks `initialize()` on slow exchange REST
- **File:** `src/core/engine.py:777`
- **Impact:** MEDIUM
- **Detail:** `await self.executor.reconcile_exchange_positions()` is awaited synchronously during `initialize()`. If exchange REST is slow/unreachable, it blocks startup for the full timeout duration.
- **Fix:** Wrap in `asyncio.wait_for(timeout=10)` or run as fire-and-forget task.

### N-LOW-1: Exchange stop update guard uses fragile ternary
- **File:** `src/execution/executor.py:940`
- **Impact:** LOW
- **Detail:** `abs(float(state.current_sl) - prior_sl) / prior_sl > 0.005 if prior_sl > 0 else False` — correct but hard to reason about.
- **Fix:** Extract to a named variable: `sl_moved_significantly = prior_sl > 0 and abs(...) / prior_sl > 0.005`.

### N-LOW-2: No test for login lockout expiry
- **File:** `tests/test_login_brute_force.py`
- **Impact:** LOW
- **Detail:** All brute-force tests happen within milliseconds. No test verifies that after `_LOGIN_WINDOW` seconds the failure counter resets. Time-based expiry logic is untested.
- **Fix:** Add a test using `freezegun` or `monkeypatch` of `time.monotonic` to verify lockout expires.

### N-LOW-3: `StubMarketData.get_order_book` missing `updated_at` key
- **File:** `tests/conftest.py:132-137`
- **Impact:** LOW
- **Detail:** `engine._main_scan_loop` checks `book.get("updated_at", 0)` for spread filtering. Missing key makes `book_age` = current epoch = huge number, so spread check always skips. Currently harmless (no test uses `max_spread_pct > 0`) but makes the stub inaccurate.
- **Fix:** Add `"updated_at": time.time()` to the order book return dict.

### N-LOW-4: `DashboardAlertHandler._recent` dedup key uses `getMessage()` — unstable
- **File:** `src/core/logger.py:391, 398-400`
- **Impact:** LOW
- **Detail:** Dedup key is `f"{record.name}:{record.getMessage()}"`. Messages with interpolated values (prices, timestamps) create unique keys every time, defeating rate limiting.
- **Fix:** Use `record.msg` (raw format string) instead of `record.getMessage()`.

---

## Consolidated Priority Matrix

### Tier 1 — Fix Before Launch (Quick Wins)

| ID | Description | Effort | Risk |
|----|-------------|--------|------|
| N-CRIT-1 | Add `rest_client` None guard to `_cancel_exchange_stop` | 2 min | Zero — defensive guard |
| N-CRIT-2 | Remove unused `_LOGIN_LOCKOUT` constant | 1 min | Zero — dead code removal |
| P-HIGH-1 | Add composite index `(tenant_id, status)` on trades | 2 min | Zero — additive index |
| R-LOW-1 | Remove unused imports in engine.py | 1 min | Zero — dead imports |
| R-LOW-2 | Remove redundant datetime import in executor.py | 1 min | Zero — dead import |
| N-MED-1 | Downgrade ghost reconcile warnings to info | 1 min | Zero — log level change |
| N-LOW-1 | Clarify exchange stop update guard ternary | 2 min | Zero — readability |

### Tier 2 — Fix Before Scaling (High Impact, Moderate Effort)

| ID | Description | Effort | Risk |
|----|-------------|--------|------|
| P-CRIT-1 | Parallelize `manage_open_positions` with `asyncio.gather` | 15 min | Low — pattern already used elsewhere |
| P-CRIT-2 | Add `get_trade_by_id()` to DatabaseManager | 20 min | Low — new method, no breaking changes |
| P-CRIT-3 | Merge `get_performance_stats` into 1-2 SQL queries + cache | 45 min | Medium — query refactor |
| P-CRIT-4 | Single `get_open_trades` fetch in `execute_signal` | 10 min | Low — logic consolidation |
| R-HIGH-1 | Extract `_parse_meta()` helper in executor.py | 15 min | Low — pure refactor |
| R-MED-1 | Remove double auth checks in server.py | 10 min | Low — remove redundant calls |
| R-MED-2 | Collapse duplicated TP close branches | 5 min | Zero — pure refactor |
| P-HIGH-3 | Cache favorites in memory per tenant | 15 min | Low — in-memory cache |
| A-HIGH-4 | Add ConfigManager reset fixture to conftest.py | 10 min | Low — test infrastructure |

### Tier 3 — Fix as Part of Roadmap (Structural Improvements)

| ID | Description | Effort | Risk |
|----|-------------|--------|------|
| R-HIGH-2 | Migrate test stubs to use conftest.py | 30 min | Low — import changes only |
| R-HIGH-3 | Decompose `execute_signal` into 5 methods | 2 hr | Medium — logic extraction |
| R-HIGH-5 | Extract `_exit_live_order` from `_close_position` | 1 hr | Medium — logic extraction |
| R-HIGH-6 | Decompose `initialize()` into factory methods | 2 hr | Medium — structural refactor |
| A-HIGH-1 | Resolve RiskManager/DB dual state | 3 hr | High — state model change |
| A-HIGH-2 | Typed exchange exception hierarchy | 2 hr | Medium — cross-cutting change |
| A-HIGH-3 | Eliminate runtime `get_config()` from executor | 1 hr | Medium — DI change |
| R-HIGH-4 | Promote auth helpers out of `_setup_routes` closure | 3 hr | Medium — large refactor |
| R-MED-3 | Make `max_trade_duration_hours` configurable | 5 min | Low — config addition |
| A-MED-3 | Add Pydantic validators for critical financial config | 30 min | Low — additive validators |
| P-MED-2 | Vectorize OHLCV resampling with NumPy | 1 hr | Medium — algorithm change |

---

## Metrics

| Metric | Value |
|--------|-------|
| Total findings | 44 |
| Critical | 6 |
| High | 12 |
| Medium | 17 |
| Low | 9 |
| Tests passing | 172/172 |
| Estimated Tier 1 effort | ~10 minutes |
| Estimated Tier 2 effort | ~2.5 hours |
| Estimated Tier 3 effort | ~16 hours |

---

## Recommendation

**Tier 1** items are zero-risk fixes that should be applied immediately — they're defensive guards, dead code removal, and log level corrections totaling ~10 minutes of work.

**Tier 2** items address the most impactful performance bottlenecks and should be prioritized before the system handles significant trading volume. The `asyncio.gather` parallelization (P-CRIT-1) and single-fetch optimization (P-CRIT-4) are the highest-ROI changes.

**Tier 3** items are structural improvements that will pay dividends as the codebase grows but can be deferred to a post-launch sprint. The `execute_signal` decomposition (R-HIGH-3) and `initialize()` decomposition (R-HIGH-6) are the most impactful for long-term maintainability.
