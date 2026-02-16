# NovaPulse v3 -- Comprehensive Code Review (Claude Opus 4.6)

**Date**: 2026-02-16
**Reviewer**: Claude Opus 4.6 (1M context)
**Scope**: Full codebase read -- every `.py`, `.yaml`, `.sh`, `.md`, `.toml`, `.yml`, and config file
**Python source files**: ~35 files, ~12,000+ lines of production code
**Test file**: 1 file (`tests/test_core.py`), ~49 tests

---

## 1. What Is NovaPulse?

NovaPulse is an **operator-grade AI cryptocurrency trading system** designed for unattended operation on both cloud servers and Raspberry Pi. It combines:

- **8 parallel technical analysis strategies** (Keltner, Trend, Mean Reversion, Momentum, VWAP Momentum Alpha, RSI Mean Reversion, Breakout, Reversal) through a weighted confluence voting engine
- **AI entry gating** via TFLite neural network + online SGD incremental learner
- **Risk-first execution** with Kelly Criterion sizing, ATR-based stops, trailing stops, breakeven logic, drawdown-scaled sizing, circuit breakers, and daily loss limits
- **Multi-exchange support** (Kraken REST/WS, Coinbase Advanced Trade REST/WS)
- **Hardened control plane** via FastAPI dashboard (REST + WebSocket), Telegram, Discord, and Slack bots
- **SaaS billing** via Stripe with multi-tenant DB isolation
- **Continuous self-improvement** via auto-retraining pipeline (TFLite) and online incremental learning (SGD)

The system is deployed on a Raspberry Pi 5 (primary trading) and a DigitalOcean droplet (agent/chat stack).

---

## 2. Architecture Overview

```
main.py (lifecycle supervisor with retry + jitter)
  |
  +-- BotEngine (single-exchange) or MultiEngineHub (multi-exchange)
       |
       +-- KrakenRESTClient / CoinbaseRESTClient  (exchange adapters)
       +-- KrakenWebSocketClient / CoinbaseWebSocketClient
       +-- MarketDataCache (RingBuffer-backed OHLCV per pair)
       +-- ConfluenceDetector
       |     +-- 8 x BaseStrategy subclasses
       |     +-- IndicatorCache (lazy per-scan memoization)
       |     +-- Regime detection (trend/range, high/low vol)
       |     +-- Multi-timeframe resampling (1m/5m/15m)
       +-- TFLitePredictor (optional neural net gating)
       +-- ContinuousLearner (online SGD, incremental)
       +-- OrderBookAnalyzer (microstructure scoring)
       +-- RiskManager (Kelly, trailing stops, circuit breakers)
       +-- TradeExecutor (limit orders, paper/live, partial fill handling)
       +-- DatabaseManager (SQLite WAL, multi-tenant)
       +-- DashboardServer (FastAPI + WebSocket)
       +-- ControlRouter -> TelegramBot / DiscordBot / SlackBot
       +-- ModelTrainer + AutoRetrainer (ProcessPoolExecutor)
       +-- StripeService (billing webhooks)
```

**Key design patterns**:
- Singleton ConfigManager with Pydantic validation
- Event-driven scan queue (price-move triggers + timeout fallback)
- Exponential backoff restart wrapper for all background tasks
- Auto-pause circuit breakers (stale data, WS disconnect, repeated failures)
- Atomic model deployment (train in subprocess, rename into place)
- Single-instance host lock (fcntl flock) to prevent double-trading

---

## 3. Module-by-Module Review

### 3.1 Core (`src/core/`)

#### `engine.py` -- Bot Engine (1068 lines)
- **Strengths**: Clean lifecycle phases (init -> warmup -> run -> stop). Event-driven scanning with `_scan_queue`. Circuit breakers auto-pause on stale data/WS disconnect. Graceful shutdown waits for all tasks.
- **Issues**:
  - Version string hardcoded as `"2.0.0"` in multiple places while `pyproject.toml` says `3.0.0`. Should use a single source of truth.
  - `_build_prediction_features` averages overlapping numeric keys from strategy metadata -- this is a reasonable heuristic but silently merges semantically different values (e.g., two strategies' `rsi` values get averaged).

#### `config.py` -- Configuration Manager (559 lines)
- **Strengths**: Pydantic validation with field validators. YAML + env override layering. Thread-safe singleton. Deep merge for multi-exchange overrides.
- **Issues**:
  - `ConfigManager` uses class-level `_lock = threading.Lock()` and `_instance` -- these are shared across all instances via the class, which is correct for a singleton but would break if someone subclassed it.
  - `_apply_env_overrides` has a complex mapping structure mixing tuples and type converters that is hard to extend. A registry pattern would be cleaner.

#### `database.py` -- Database Manager (1123 lines)
- **Strengths**: WAL mode with aggressive caching. Idempotent migrations. Column whitelist for update queries (prevents SQL injection). Tenant-scoped queries throughout. Atomic ML label updates on trade close.
- **Issues**:
  - `_sql_dt()` helper truncates timestamps to 19 chars and replaces `T` with space -- this silently drops timezone info and fractional seconds. Works for SQLite comparison but could cause subtle ordering bugs.
  - `cleanup_old_data` deletes `order_book_snapshots` but ML training might need historical snapshots. Should be configurable per table.
  - Single `asyncio.Lock` for all write operations means a slow INSERT blocks all other writes.

#### `logger.py` -- Structured Logging (212 lines)
- **Strengths**: Structlog with automatic sensitive data masking. Rotating file handlers (50MB main, 10MB errors). Telegram bot token scrubbing in log output.
- **No significant issues**.

#### `structures.py` -- RingBuffer (98 lines)
- **Strengths**: NumPy-backed O(1) append circular buffer. Zero-copy `view()` when not wrapped.
- **Issue**: `latest(n)` returns a concatenated copy when data wraps around. For hot paths (every tick), this allocation could be avoided with a pre-allocated output buffer.

#### `control_router.py` -- Control Router (148 lines)
- **Strengths**: Clean separation of concerns. All control channels (Web, Telegram, Discord, Slack) route through here. Tenant matching for multi-tenant safety.
- **No significant issues**.

#### `multi_engine.py` -- Multi-Exchange Orchestration (122 lines)
- **Strengths**: Fan-out control (pause/resume/close_all/kill across all engines). Clean DB path resolution with exchange suffix.
- **No significant issues**.

#### `vault.py` -- Encrypted Secrets Storage (188 lines)
- **Strengths**: PBKDF2 with 480K iterations. Fernet (AES-128-CBC + HMAC). Atomic write via tmp+replace. Checksum verification on load. Password rotation with backup.
- **Issue**: Backup file (`.bak`) is written unencrypted-metadata alongside encrypted data -- the salt is in plaintext in both files. This is by design (Fernet envelope) but worth noting.

#### `runtime_safety.py` -- Exception Handlers (139 lines)
- **Strengths**: Installs `sys.excepthook`, `threading.excepthook`, asyncio exception handler, and `faulthandler` with SIGUSR1 dump. Comprehensive crash observability.
- **No significant issues**.

---

### 3.2 Strategies (`src/strategies/`)

All 8 strategies follow an identical pattern:
1. Check data sufficiency (minimum bars)
2. Compute indicators (via cache or direct)
3. Score direction/strength/confidence
4. Compute fee-aware SL/TP via `compute_sl_tp` from `indicators.py`

#### `base.py` -- Strategy Base Class
- **Strengths**: `StrategySignal` dataclass with NaN/Inf sanitization. Performance tracking (win rate, avg PnL). `is_actionable` property (non-neutral + strength > 0.1).
- **No significant issues**.

#### `keltner.py` -- Keltner Channel (weight: 0.30, highest)
- **Strengths**: Band-touch entries with MACD histogram confirmation and RSI gating. Fee-aware stops. Regime-adaptive parameter adjustment.
- **Note**: This is the primary high-WR strategy and gets the most weight in confluence. No dedicated test exists for it.

#### Individual Strategy Quality (trend, mean_reversion, momentum, breakout, reversal, vwap_momentum_alpha, rsi_mean_reversion)
- **Strengths**: Each strategy has thoughtful scoring with multiple confirmation signals. Regime awareness in VWAP and RSI strategies. Fee-aware SL/TP.
- **Code Smell**: **SL/TP computation block is duplicated across all 8 strategies** (~15 identical lines each). This should be extracted to a `BaseStrategy.compute_stops()` method.
- **Issue in vwap_momentum_alpha.py**: Uses `tuple[np.ndarray, np.ndarray]` type hint (Python 3.10+ syntax). While NovaPulse targets 3.11+, the `from __future__ import annotations` import makes this a string annotation at runtime, so it works fine.

---

### 3.3 Exchange Adapters (`src/exchange/`)

#### `kraken_ws.py` -- Kraken WebSocket (420 lines)
- **Strengths**: Production-grade reconnection with exponential backoff. Subscription management with auto-resubscribe. Callback routing supports both sync and async handlers. Max message size limit (1MB).
- **Issue**: `latency_ms` property returns hardcoded `0.0` -- either implement it or remove it.

#### `kraken_rest.py` -- Kraken REST Client (550 lines)
- **Strengths**: HMAC-SHA512 authentication. Nonce collision prevention with async lock. Request deduplication for order safety (OrderedDict FIFO). Loop-based retries (avoids semaphore deadlock from recursive retry). Pair normalization map.
- **Issue**: `get_trades_history` uses `if start:` which would skip `start=0`. Should be `if start is not None:`.
- **Issue**: Pair map is hardcoded for 8 pairs -- adding a new pair requires code changes.

#### `coinbase_ws.py` -- Coinbase WebSocket (280 lines)
- **Strengths**: Message normalization to internal format. Local order book state management. Deduplication of subscription product IDs.
- **Bug**: `_route()` calls `await cb(data)` unconditionally without checking `asyncio.iscoroutinefunction(cb)`. Kraken WS correctly checks this. **Synchronous callbacks will crash with a TypeError**.

#### `coinbase_rest.py` -- Coinbase REST Client (400 lines)
- **Strengths**: JWT (ES256) authentication with 120s TTL. Dual HTTP clients (trading REST + market data). Normalizes responses to Kraken-like shape for engine compatibility.
- **Bug**: `get_ohlc` uses `if since:` which would skip `since=0`. Should be `if since is not None:`.
- **Security**: JWT private key loaded from file path and held in memory.

#### `market_data.py` -- Market Data Cache (450 lines)
- **Strengths**: RingBuffer-backed OHLCV per pair. Outlier rejection (20% deviation). Tolerance-based timestamp comparison. Async lock per pair.
- **Issue**: `update_bar` directly accesses `._data[idx]` on RingBuffer, bypassing the public API. Fragile but justified for performance.
- **Issue**: Outlier rejection threshold of 20% may reject legitimate crypto price moves (flash crashes, rapid pumps). Should be configurable per pair or volatility regime.

---

### 3.4 AI / ML (`src/ai/`, `src/ml/`)

#### `confluence.py` -- Multi-Strategy Confluence Detector (874 lines)
- **Strengths**: Weighted strategy scoring with regime-adaptive multipliers. OBI as optional synthetic "order_book" vote. Multi-timeframe resampling. Cooldown filtering. "Sure Fire" detection (3+ strategies + OBI agreement + min confidence).
- **Issue**: `_signal_history` grows unbounded between trims (trims at 1000, keeps 500). In a high-frequency scenario this list could grow large between trims.

#### `predictor.py` -- TFLite Predictor (367 lines)
- **Strengths**: Safe fallback to heuristic when TFLite unavailable. Prediction caching with TTL. Feature normalization supports both training-time params and static fallback. Model info API for dashboard.
- **Issue**: `_cache_key` uses MD5 hash of JSON-serialized features. MD5 is fine for cache keys but using `hashlib.md5` triggers security linter warnings. Consider `hashlib.sha256` or a simpler hash.

#### `order_book.py` -- Order Book Analyzer (413 lines)
- **Strengths**: Comprehensive analysis: OBI, whale detection, void detection, VWAP bid/ask, depth ratio, pressure assessment, liquidity score, spoofing detection, composite book_score.
- **No significant issues**.

#### `trainer.py` -- Model Trainer + AutoRetrainer (350 lines)
- **Strengths**: Training runs in `ProcessPoolExecutor` (non-blocking). Atomic model deployment via rename. EarlyStopping + LR reduction. Class weight balancing. Normalization saved alongside model.
- **Issue**: Model architecture is fixed (64-32-16 dense layers). No hyperparameter tuning for architecture.
- **Issue**: `AutoRetrainer.run()` has an infinite loop with no clean shutdown mechanism beyond `CancelledError`.

#### `continuous_learner.py` -- Online SGD Learner (200 lines)
- **Strengths**: Fail-safe design (returns `None` on any error). Atomic save via tmp+replace. Async lock. `min_updates_before_predict` prevents premature predictions.
- **Issue**: `partial_fit` on `StandardScaler` means normalization statistics drift over time, which could cause distribution shift relative to the model. Known online-learning trade-off.

#### `backtester.py` -- Backtesting Engine (550 lines)
- **Strengths**: Two modes: "simple" (standalone) and "parity" (uses same confluence/AI/risk as live). Monte Carlo simulation for confidence intervals. Comprehensive `BacktestResult` with Sharpe, profit factor, max drawdown, equity curve.
- **Issue**: Parity mode still assumes fills occur (no limit-order non-fill modeling).
- **Issue**: Sharpe annualization assumes 1-minute bars (`sqrt(525600)`). Should use actual bar frequency.

---

### 3.5 Execution (`src/execution/`)

#### `executor.py` -- Trade Executor (1096 lines)
- **Strengths**: Full lifecycle management (signal validation -> risk check -> sizing -> order -> fill -> record). Limit order support with chase + market fallback. Partial fill handling. ML feature recording at entry with labeling on close. Order book snapshot at entry for training data.
- **Issue**: `_paper_fill` uses `spread / 10` as slippage, which may underestimate real slippage for illiquid pairs.
- **Issue**: Live exit orders always use market orders ("safer for stops/TP"). This is correct for reliability but could be configurable.
- **Robustness**: Exit orders retry 3 times with exponential backoff. On permanent failure, trade is marked as `error` status (not lost).

#### `risk_manager.py` -- Risk Management Engine (621 lines)
- **Strengths**: Fixed-fractional sizing as primary method with Kelly as cap-only (sensible). Drawdown-scaled sizing (exponential reduction). Risk-of-ruin calculation (requires 50+ trades for statistical validity). Per-strategy cooldowns. Global cooldown on loss (30 min default). 50% max total exposure.
- **Issue**: `_trade_history` is kept in RAM and trimmed at 10K entries. On restart, this is lost -- risk metrics reset to zero until enough trades accumulate again.
- **Issue**: `_get_drawdown_factor` uses hardcoded step thresholds (2%/5%/10%/15%). A continuous function would be smoother.

---

### 3.6 API / Dashboard (`src/api/`)

#### `server.py` -- FastAPI Dashboard Server (1447 lines)
- **Strengths**: Comprehensive auth system (cookie sessions + API keys). CSRF protection (double-submit token + origin check). Security headers (X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Permissions-Policy, CSP). Per-IP token bucket rate limiting. WebSocket caching (1-second TTL). Multi-engine aggregation for all endpoints. CSV export. Stripe billing endpoints.
- **Issue**: Rate limiter `buckets` dict grows unbounded -- no eviction of stale IPs. Should add periodic cleanup.
- **Issue**: CSP allows `'unsafe-inline'` for both scripts and styles due to inline handlers in dashboard HTML.
- **Issue**: Login page pre-fills the admin username in the HTML form -- minor information disclosure.
- **Security**: Live mode enforces `DASHBOARD_ADMIN_KEY`, `DASHBOARD_SESSION_SECRET`, and `DASHBOARD_ADMIN_PASSWORD_HASH`. Paper mode generates ephemeral keys with warnings.

---

### 3.7 Utilities (`src/utils/`)

#### `indicators.py` -- Technical Indicators (550 lines)
- **Strengths**: Vectorized NumPy implementations. NaN-safety throughout. Fee-aware SL/TP computation. Population stddev for Bollinger Bands.
- **Issue**: EMA uses a Python `for` loop for propagation. For large datasets, this is the bottleneck. Numba JIT or `scipy.ndimage.uniform_filter1d` would significantly improve performance.
- **Issue**: `_cluster_levels` mutates the input list with `.sort()`. Should sort a copy.

#### `indicator_cache.py` -- Lazy Indicator Memoization (150 lines)
- **Strengths**: Clean memoization pattern. New instance per scan cycle (no invalidation needed). Shared computation across strategies within a cycle.
- **No significant issues**.

#### `telegram.py` -- Telegram Bot (680 lines)
- **Strengths**: 18 commands. Chat ID authorization allowlist. Rate limiting. Secrets directory fallback. Check-in loop. Handles 409 polling conflicts.
- **Issue**: Tight coupling to engine internals (accesses `_running`, `_trading_paused`, `_start_time` directly). Should use ControlRouter/public API exclusively.

#### `discord_bot.py` -- Discord Bot (250 lines)
- **Strengths**: Slash commands with ephemeral responses. Guild/channel authorization.
- **Security Issue**: `_is_authorized` returns `True` when both `allowed_channel_ids` and `allowed_guild_id` are empty. **All channels/guilds are authorized by default when no restrictions configured**.

#### `slack_bot.py` -- Slack Bot (220 lines)
- **Strengths**: Socket Mode (no public URL needed). Channel authorization.
- **Issue**: Uses `asyncio.get_event_loop()` (deprecated in Python 3.12+). Should use `asyncio.get_running_loop()`.
- **Issue**: `ack()` is called without `await` -- in async mode, this could silently fail.

---

### 3.8 Billing (`src/billing/`)

#### `stripe_service.py` -- Stripe Integration (200 lines)
- **Strengths**: Checkout session creation. Webhook signature verification. Subscription lifecycle handling (paid, failed, deleted).
- **Bug**: `_api()` sets `stripe.api_key` globally on every call -- **not thread-safe**. Should use per-request auth via `stripe.api_key` parameter or Stripe client instances.

---

### 3.9 Tests (`tests/test_core.py`)

- **49 tests** covering indicators, strategies, exchange helpers, backtester, risk manager, database, config, API tenant auth, API exports, API middleware, ML pipeline, vault, Telegram check-ins, logging safety, and circuit breakers.
- **Coverage Gaps**:
  - No tests for **Keltner strategy** (the primary strategy by weight 0.30)
  - No tests for **Coinbase REST** order placement/cancellation
  - No tests for **Discord bot** or **Slack bot**
  - No tests for **ContinuousLearner** (online SGD)
  - No tests for **indicator edge cases** (empty arrays, single element, all-NaN)
  - Strategy tests only verify return type, not signal direction/correctness for known scenarios
  - No **integration tests** for full scan-analyze-trade cycle
  - No **property-based tests** for execution edge cases (partial fills, retries, close_all during reconnect)

---

### 3.10 Configuration & DevOps

#### `config/config.yaml`
- Well-organized. Conservative risk settings ($200 max position, 0.5% per trade, 5% daily loss limit). 8 trading pairs. Multi-timeframe enabled (1/5/15 min). Strategy cooldowns of 600s each.

#### `Dockerfile`
- Multi-stage build. Non-root user. Tini for signal handling. Health check. Good security practices.

#### `docker-compose.yml`
- Resource limits (2G RAM, 2 CPU). Log rotation (50MB x 5). Named volumes. Bridge network.
- **Note**: Prometheus and Grafana are commented out but scaffolded.

#### `SuperStart.sh`
- Raspberry Pi deployment script. Git pull, venv creation, pip install, bot start with nohup. Uses `requirements-pi.txt` (no TensorFlow) for faster Pi installs.

#### Secret Scanning
- `.gitleaks.toml` + `.github/workflows/secret-scan.yml` + `.githooks/pre-commit` -- comprehensive secret scanning pipeline.
- **Pre-commit hook issue**: Uses `rg` (ripgrep) which may not be installed on all machines. Should fall back to `grep -E`.

---

## 4. Security Analysis

### 4.1 Strengths
- **Fail-closed auth in live mode**: Admin key, session secret, and password hash all required
- **CSRF protection**: Double-submit token + origin checking for cookie-auth control actions
- **Secret scanning**: Gitleaks CI + pre-commit hook + `.gitignore` for secrets
- **Vault encryption**: PBKDF2 (480K iterations) + Fernet with checksum verification
- **API key hashing**: Tenant API keys stored as SHA-256 hashes in DB
- **Webhook verification**: Stripe signature validation
- **Chat authorization**: Telegram chat ID allowlist, Discord guild/channel filtering
- **Security headers**: X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Permissions-Policy, CSP, Cache-Control: no-store for API
- **Rate limiting**: Per-IP token bucket
- **Log scrubbing**: Telegram bot tokens redacted from logs

### 4.2 Concerns

| Severity | Issue | Location |
|----------|-------|----------|
| **HIGH** | `.env` contains live Kraken API keys, Telegram bot token, Stripe live keys, and plaintext admin password | `.env` lines 12-13, 40, 71, 86-89 |
| **HIGH** | Discord bot authorizes all channels when no restrictions configured | `discord_bot.py:50` |
| **MEDIUM** | Stripe `api_key` set globally (not thread-safe) | `stripe_service.py:_api()` |
| **MEDIUM** | CSP allows `unsafe-inline` for scripts and styles | `server.py:358-365` |
| **MEDIUM** | Rate limiter bucket dict never evicts stale IPs (memory leak over time) | `server.py:372` |
| **MEDIUM** | Login page pre-fills admin username | `server.py:616` |
| **LOW** | MD5 used for prediction cache keys (triggers security linters) | `predictor.py:339` |
| **LOW** | Pre-commit hook requires `rg` (ripgrep) without fallback | `.githooks/pre-commit` |

### 4.3 Critical: Live Secrets in `.env`

The `.env` file contains what appear to be **real credentials**:
- `KRAKEN_API_KEY` and `KRAKEN_API_SECRET` (56 and 88 chars respectively)
- `TELEGRAM_BOT_TOKEN` (looks like a real token format)
- `STRIPE_RESTRICTED_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_SECRET_KEY` (all `*_live_*` prefix)
- `DASHBOARD_ADMIN_PASSWORD=<REDACTED>` (plaintext password in .env)
- `DASHBOARD_SESSION_SECRET` (base64 encoded secret)

**If this `.env` has ever been committed to git history, all these credentials should be rotated immediately.** Even with `.gitignore`, if they were committed before being added to `.gitignore`, they remain in history.

---

## 5. Bugs Found

| # | Severity | Description | Location | Status |
|---|----------|-------------|----------|--------|
| 1 | **HIGH** | Coinbase WS `_route()` calls `await cb(data)` without checking if callback is async -- crashes on sync callbacks | `coinbase_ws.py` | **FIXED v3.0.0** |
| 2 | **HIGH** | Discord bot `_is_authorized` returns True when no restrictions configured (open to all) | `discord_bot.py:50` | **FIXED v3.0.0** |
| 3 | **MEDIUM** | Stripe `stripe.api_key` set globally on every API call (thread-unsafe) | `stripe_service.py:_api()` | **FIXED v3.0.0** |
| 4 | **MEDIUM** | `kraken_rest.py` `get_trades_history` uses `if start:` which skips `start=0` | `kraken_rest.py` | **FIXED v3.0.0** |
| 5 | **MEDIUM** | `coinbase_rest.py` `get_ohlc` uses `if since:` which skips `since=0` | `coinbase_rest.py` | **FIXED v3.0.0** |
| 6 | **MEDIUM** | Rate limiter `buckets` dict grows unbounded (no stale IP eviction) | `server.py:372` | **FIXED v3.0.0** |
| 7 | **LOW** | Slack bot uses deprecated `asyncio.get_event_loop()` | `slack_bot.py` | **FIXED v3.0.0** |
| 8 | **LOW** | Slack bot `ack()` called without `await` in async mode | `slack_bot.py` | **FIXED v3.0.0** |
| 9 | **LOW** | `indicators.py` `_cluster_levels` mutates input list via `.sort()` | `indicators.py` | Open |
| 10 | **LOW** | Version string hardcoded as `"2.0.0"` in engine/main while pyproject says `3.0.0` | `engine.py:171`, `main.py:479` | **FIXED v3.0.0** |
| 11 | **LOW** | Kraken WS `latency_ms` property returns hardcoded `0.0` | `kraken_ws.py` | **FIXED v3.0.0** |

---

## 6. Code Quality Assessment

### 6.1 Strengths
- **Consistent error handling**: Every background task wrapped in try/except with structured logging. Non-critical failures (ML features, order book snapshots) explicitly swallowed with comments explaining why.
- **Defensive programming**: Guards against None, empty, NaN, Inf throughout. `_ensure_ready()` on DB. Phantom position filtering (`ABS(quantity) > 0.00000001`).
- **Structured logging**: Structlog with context, automatic sensitive data masking, rotating file handlers.
- **Configuration**: Pydantic validation with sensible defaults. Environment override system.
- **Resilience**: Exponential backoff restarts for all tasks. Circuit breakers. Single-instance lock. Graceful shutdown.

### 6.2 Code Smells
1. **SL/TP block duplicated across 8 strategies** (~120 lines total duplication). Extract to base class.
2. **`server.py` is 1447 lines** with all routes defined inside `_setup_routes()`. Should split into separate router modules.
3. **`telegram.py` is 680 lines** with all command handlers inline. Should use a command registry pattern.
4. **Direct engine internal access** from Telegram bot (`_running`, `_trading_paused`, `_start_time`). Should use ControlRouter.
5. **Hardcoded pair maps** in `kraken_rest.py`. Should be fetched from exchange or configured.
6. **`param_tune.py`** missing `VWAPMomentumAlphaStrategy` and `RSIMeanReversionStrategy` from strategy maps and grids.

### 6.3 Documentation Quality
- Excellent inline documentation. Each module has a docstring explaining purpose and enhancements.
- Fix references throughout (e.g., "S1 FIX", "C3 FIX", "H6 FIX", "M17 FIX") trace back to previous reviews -- good traceability.
- Knowledge base documentation (`docs/kb-internal/`, `docs/kb-client/`, `knowledge_base/`) is thorough.

---

## 7. Previous Reviews Context

The codebase has been through **8 prior reviews** (FirstReview, SecondReview, GemRev, GPTReview, GPTRev2, GPTRev3, FinalTesting, FinalRep) between Feb 6-14, 2026. Key items that were fixed:

- SQL injection (column whitelist)
- Swapped volume/VWAP columns (broke all indicators)
- Missing auth on control endpoints
- Ticker handler injecting fake OHLC bars
- ML training blocking event loop (moved to ProcessPoolExecutor)
- Data leakage in ML normalization (fit on train split only)
- Symmetric fee/slippage accounting
- Order size precision and exchange minimum enforcement
- Limit-order chase with market fallback
- Adaptive strategy weighting via trade result recording
- Circuit breakers (auto-pause on stale data/WS disconnect)
- HTTP security headers and rate limiting
- CSRF protection for cookie-auth control actions
- Python 3.13 compatibility

---

## 8. Open Items from Previous Reviews (Still Unresolved)

1. **Exchange reconciliation**: No fill/position reconciliation against exchange records -- the largest open gap for live trading
2. **Limit-order chase uses ticker without freshness checks** (stale price risk in fast markets)
3. **Parity backtest does not model no-fill scenarios** (limit order rejection/timeout)
4. **Spread filter falls back to 0** when order book unavailable
5. **Multi-tenant boundary incomplete** for true SaaS (writes, state isolation)
6. **Rate limiting is in-memory/per-process** (not shared across replicas)
7. **Outlier rejection threshold** (20%) not configurable per pair/volatility
8. **Trade history in RiskManager is RAM-only** -- resets on restart

---

## 9. Recommendations

### Immediate (Fix Before Next Live Run)
1. **Rotate all credentials** in `.env` if they were ever committed to git. Run `git log --all --full-history -- .env` to check.
2. ~~**Fix Coinbase WS callback routing**~~ -- **FIXED v3.0.0**: Added `asyncio.iscoroutinefunction` check.
3. ~~**Fix Discord bot open authorization**~~ -- **FIXED v3.0.0**: Now deny-by-default when no restrictions configured.
4. ~~**Fix Stripe global API key**~~ -- **FIXED v3.0.0**: One-time init, cached module reference.
5. ~~**Fix version string inconsistency**~~ -- **FIXED v3.0.0**: Single source of truth via `src/__init__.__version__`.

### Short-Term (Next Sprint)
6. **Add Keltner strategy tests** -- it is the highest-weighted strategy with no dedicated tests.
7. **Extract SL/TP computation to base class** -- eliminate 8x code duplication.
8. ~~**Add rate limiter IP eviction**~~ -- **FIXED v3.0.0**: Periodic eviction of entries older than 10 minutes.
9. ~~**Fix `if start:` / `if since:` truthiness bugs**~~ -- **FIXED v3.0.0**: Changed to `is not None` checks.
10. **Add exchange reconciliation** -- periodic check that DB positions match exchange state.

### Medium-Term
11. **Split `server.py`** into separate route modules (auth, trades, control, billing, websocket).
12. **Add integration tests** for the full scan-analyze-trade cycle.
13. **Implement configurable outlier rejection** per pair based on historical volatility.
14. **Persist RiskManager trade history to DB** so risk metrics survive restarts.
15. **Remove inline JS/CSS from dashboard** to enable stricter CSP.

### Long-Term
16. **Migrate to PostgreSQL** if pursuing multi-tenant SaaS.
17. **Implement event-driven architecture** with proper message bus.
18. **Add RL-based position sizing** (proposed in PROJECT_STUDY).
19. **Build walk-forward validation** into param_tune.py.
20. **Add Numba JIT** to EMA computation for indicator performance.

---

## 10. Overall Assessment

**Grade: A-** (Operator-grade trading system with strong safety nets; not yet internet-exposed SaaS grade)

**What is excellent**:
- Multi-strategy confluence with regime-adaptive weighting is a sophisticated and well-implemented trading approach
- Risk management is institutional-quality (Kelly sizing, drawdown scaling, circuit breakers, daily loss limits)
- Error handling and resilience are production-grade (retry wrappers, graceful shutdown, auto-pause)
- Security posture is strong for a single-operator system (auth, CSRF, secret scanning, vault)

**What needs attention**:
- Live credentials in `.env` is the most urgent security concern
- A few bugs in exchange adapters (Coinbase WS callbacks, truthiness checks)
- Test coverage has gaps on the most critical components (Keltner strategy, Coinbase execution)
- Code duplication in strategies should be refactored
- Exchange reconciliation is the biggest gap for reliable live trading

**Bottom line**: NovaPulse is a mature, well-architected trading system that has been through extensive review and hardening. The core trading logic, risk management, and operational resilience are strong. The main risks are around the periphery: credential management, exchange adapter edge cases, and incomplete test coverage for the highest-value components.
