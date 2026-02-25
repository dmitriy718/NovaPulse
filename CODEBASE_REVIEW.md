# NovaPulse v4.5.0 — Full Codebase Review

**Date:** 2026-02-25  
**Scope:** All 72 source files (~29,500 lines), 30 test files (~4,500 lines), config, DevOps, and static assets  
**Methodology:** Automated deep-dive of every module with focus on correctness, security, reliability, and maintainability

---

## Executive Summary

NovaPulse is a well-engineered trading system with solid architecture and thoughtful design choices. The codebase demonstrates strong domain expertise in algorithmic trading, security-conscious API design, and robust error handling patterns. However, the review identified **8 critical bugs**, **19 high-severity issues**, and numerous medium/low findings across security, concurrency, data integrity, and code quality.

### Key Strengths
- Clean module separation (core / strategies / execution / exchange / AI / data / billing)
- "Trade or Die" error philosophy — non-critical subsystem failures never halt trading
- Multi-tenant isolation in the API/billing layer
- Vault-based secret encryption with Fernet/PBKDF2
- Comprehensive 40+ endpoint REST API with CSRF, rate limiting, and security headers
- Static dashboard with proper XSS escaping
- Good test stub design with realistic `StubDB`, `StubMarketData`, `StubRiskManager`

### Key Risks
- Thread safety gaps in core data structures and state management
- Several division-by-zero and array bounds bugs in trading strategies
- Largest file (`server.py`, 3,498 lines) is a maintenance liability
- Test coverage gaps on critical paths (live execution, WebSocket reconnection)
- Multi-tenant data leakage possible in database queries

---

## 1. Critical Bugs (P0 — Fix Immediately)

### BUG-1: Funding Rate Strategy — Double Division by 100
**File:** `src/strategies/funding_rate.py:103`  
**Impact:** Strategy threshold is 100x too small, causing it to trigger on normal funding rates  
```python
extreme = self.funding_extreme_pct / 100.0  # Already 0.01, becomes 0.0001
```
**Fix:** Remove the division — `funding_extreme_pct` is already a decimal (0.01 = 1%).

### BUG-2: Confluence Detector — AttributeError on Empty Signals
**File:** `src/ai/confluence.py:969`  
**Impact:** Crash when `directional_signals` is empty; `primary_signal` is `None`, accessing `.entry_price` raises  
**Fix:** Add `if primary_signal is None: return None` guard.

### BUG-3: MarketDataCache — Negative Modulo on Empty Buffer
**File:** `src/exchange/market_data.py:203, 227`  
**Impact:** When buffer is empty (`position=0`), `(position - 1) % capacity` yields `capacity - 1`, reading uninitialized data  
**Fix:** Add `if self.size == 0: return` guard before modulo operations.

### BUG-4: RingBuffer Not Thread-Safe
**File:** `src/core/structures.py` (entire file)  
**Impact:** Concurrent access from scan loop, WS loop, and position loop can corrupt buffer data, sizes, and positions  
**Fix:** Add `threading.Lock` around `append`, `append_many`, `view`, `latest`, `get_last`.

### BUG-5: Restart Supervisor Treats Normal Completion as Failure
**File:** `main.py:253-258`  
**Impact:** When a background task completes normally (e.g., scan finishes), it's counted as a failure and triggers exponential backoff  
```python
await coro_factory()
if engine._running:
    failures += 1  # ← Normal completion treated as failure
```
**Fix:** Only increment `failures` on exception.

### BUG-6: Risk Manager — Trailing Stop Init Wrong for Shorts
**File:** `src/execution/risk_manager.py:381`  
**Impact:** For short positions, `trailing_high` is initialized to `0` instead of `float("inf")`, causing the trailing stop to never activate  
```python
trailing_high=entry_price if side == "buy" else 0  # Should be float("inf") for sells
```
**Fix:** Use `float("inf")` for sell side.

### BUG-7: Multi-Tenant Data Leakage in Database Queries
**File:** `src/core/database.py:709-790, 843-926`  
**Impact:** When `tenant_id=None`, queries return data from ALL tenants. In multi-tenant billing deployments, one tenant can see another's trades  
**Fix:** Make `tenant_id` required in all tenant-scoped queries, or default to `"default"`.

### BUG-8: Reversal Strategy — Uninitialized Confirmation Variables
**File:** `src/strategies/reversal.py:171-184`  
**Impact:** When the confirmation loop doesn't run (insufficient data), `higher_lows` and `higher_closes` default to `True`, generating false signals  
**Fix:** Initialize to `False` and only set `True` if loop runs and confirms.

---

## 2. High-Severity Issues (P1 — Fix Before Production)

### Security

| # | Issue | File | Impact |
|---|-------|------|--------|
| SEC-1 | Anonymous read access by default | `server.py:1166-1167` | Unauthenticated users can read portfolio, trades, P&L |
| SEC-2 | Ephemeral auto-generated secrets | `server.py:105-113` | Session secret and admin key regenerate on restart, invalidating all sessions |
| SEC-3 | Plaintext password fallback | `server.py:1090-1093` | Dev mode allows plaintext passwords; if misconfigured in prod, insecure |
| SEC-4 | CSP allows `unsafe-inline` | `server.py:952-959` | XSS attack surface if inline scripts are injected |
| SEC-5 | No webhook rate limiting | `server.py:3012-3040` | Stripe webhook endpoint has no rate limiting; DoS vector |

### Concurrency

| # | Issue | File | Impact |
|---|-------|------|--------|
| CONC-1 | Pause state modifications unsynchronized | `engine.py:152-153`, `control_router.py:76` | Concurrent pause/resume from API, Telegram, auto-pause can corrupt state |
| CONC-2 | Risk manager position dicts unlocked | `risk_manager.py:143-153` | Concurrent `register_position` + `close_position` can corrupt position tracking |
| CONC-3 | WebSocket order book updates unlocked | `coinbase_ws.py:50, 305-352` | Concurrent snapshot + delta updates can corrupt order book state |
| CONC-4 | Global risk aggregator updates unsynchronized | `engine.py:1427-1437` | Multi-engine concurrent exposure updates can produce incorrect totals |

### Reliability

| # | Issue | File | Impact |
|---|-------|------|--------|
| REL-1 | Shutdown doesn't guarantee task completion | `engine.py:1315-1327` | 15s timeout; tasks may still run after "shutdown" |
| REL-2 | Error recovery loops run forever | `engine.py:1370-1687` | Persistent failures (dead DB) cause infinite 5s retry loops without backoff |
| REL-3 | Fire-and-forget warmup tasks | `engine.py:1135` | Not tracked in `_tasks`; may continue after shutdown |
| REL-4 | Bankroll sync failure silently ignored | `engine.py:700-716` | If DB unavailable at init, bankroll starts at `initial_bankroll`, losing all historical P&L |

### Data Integrity

| # | Issue | File | Impact |
|---|-------|------|--------|
| DATA-1 | ES buffer silently drops data | `es_client.py:363-380` | When buffer full, oldest documents dropped without notification |
| DATA-2 | ES bulk failures not retried | `es_client.py:419-434` | `raise_on_error=False, stats_only=True` — individual doc failures not logged or retried |
| DATA-3 | CryptoPanic `seen_ids` memory leak | `ingestion.py:309-365` | Set grows unbounded; truncation logic uses unordered set slice |

---

## 3. Medium-Severity Issues (P2)

### Strategy Bugs

| # | Issue | File | Impact |
|---|-------|------|--------|
| STRAT-1 | Division by zero in Trend strategy | `trend.py:111, 120` | If `curr_ema_s` or `avg_vol` is 0, crash |
| STRAT-2 | Division by zero in Market Structure | `market_structure.py:144` | If `prev_swing_low` is 0, crash |
| STRAT-3 | Ichimoku SL can be negative | `ichimoku.py:171, 181` | If price is outside cloud, SL distance becomes negative |
| STRAT-4 | Supertrend direction check uses 0 | `supertrend.py:75` | Direction is ±1, never 0; check is always false |
| STRAT-5 | VWAP strength uses wrong denominator | `vwap_momentum_alpha.py:170` | Uses config `band_std` instead of actual `curr_std` |
| STRAT-6 | Mean reversion SHORT TP may be inverted | `mean_reversion.py:224` | Middle-band TP condition may fire incorrectly for shorts |
| STRAT-7 | Stochastic divergence array bounds | `stochastic_divergence.py:192` | Local low detection can IndexError at boundaries |
| STRAT-8 | Order flow spread EMA pollution | `order_flow.py:97` | Default spread 999.0 pollutes the EMA on first update |

### Architecture

| # | Issue | File | Impact |
|---|-------|------|--------|
| ARCH-1 | `server.py` is 3,498 lines | `src/api/server.py` | Maintenance burden; should split into route modules |
| ARCH-2 | Tenant resolution duplicated | `server.py:189-274` | Same logic appears in 3+ places |
| ARCH-3 | Dead code in REST clients | `kraken_rest.py:248`, `coinbase_rest.py:227` | Unreachable `RuntimeError` after retry loop |
| ARCH-4 | `param_tune.py`, `stress_test.py` in root | Root directory | Should be in `scripts/` |

### Configuration

| # | Issue | File | Impact |
|---|-------|------|--------|
| CFG-1 | ConfigManager singleton not thread-safe | `config.py:982-991` | Race condition on first load from multiple threads |
| CFG-2 | No validation on risk exposure cap | `config.py:649` | Allows 100% exposure (`max_total_exposure_pct=1.0`) |
| CFG-3 | Env override failures silently ignored | `config.py:256-278` | Invalid env values logged as warnings but skipped |
| CFG-4 | Hot-reload advertised but not implemented | `config.py:974` | Comment says "hot-reload" but no file watcher exists |

### Database

| # | Issue | File | Impact |
|---|-------|------|--------|
| DB-1 | Missing indexes | `database.py` | No index on `(tenant_id, status, exit_time)` or `(tenant_id, metric_name, timestamp)` |
| DB-2 | Read semaphore unused | `database.py:57` | `_read_semaphore` defined but never used; all reads use exclusive `_lock` |
| DB-3 | `date('now')` in WHERE prevents index use | `database.py:1131` | String date comparison defeats `exit_time` index |
| DB-4 | No batch deletion in cleanup | `database.py:1658-1674` | Large deletions can lock database |

---

## 4. Low-Severity Issues (P3)

### Code Quality
- Inconsistent NaN handling across strategies (some check, some don't)
- Mix of `time.time()` and `datetime.now(timezone.utc)` for timestamps
- `logging.getLogger()` used in `config.py` instead of `get_logger()`
- No type annotations on some private methods in `engine.py`
- `import inside method` pattern in `kraken_rest.py:90`

### Testing
- No tests for live order execution path
- No tests for WebSocket reconnection
- No tests for risk manager circuit breakers
- `pytest-cov` installed but not used in CI
- No parallel test execution (`pytest-xdist`)
- 4 pre-existing test failures (3 in `test_login_brute_force.py`, 1 in `test_stocks_env_aliases.py`)

### DevOps
- No Prometheus metrics instrumentation (commented out in docker-compose)
- No image vulnerability scanning in CI
- `health_check.sh` is 514 lines of bash (should be Python)
- No database schema version validation in release workflow
- Stock universe scanner hardcodes UTC-5 without DST handling (`universe.py:68`)

### Frontend
- Silent error handling in several async JS functions (`dashboard.js:246-254, 274-281, 1672-1685`)
- No `DOMPurify` or equivalent for defense-in-depth against XSS

---

## 5. Positive Observations

These aspects of the codebase are well-done and worth highlighting:

| Area | What's Good |
|------|-------------|
| **Error Philosophy** | "Trade or Die" — subsystem failures (Telegram, Discord, ML, billing) never halt trading. Only exchange auth or DB failures are critical |
| **Vault Security** | Fernet encryption + PBKDF2 (480k iterations) + SHA256 checksums + atomic writes |
| **CSRF Protection** | Double-submit cookie pattern with origin checking |
| **Rate Limiting** | Token bucket per-IP with stale IP eviction |
| **Password Hashing** | Argon2 primary + bcrypt fallback |
| **API Key Masking** | Logger auto-masks keys/secrets/tokens in structured logs |
| **SQL Safety** | Parameterized queries + column whitelist for dynamic updates |
| **Exchange Exception Hierarchy** | Typed exceptions (transient vs permanent) with smart retry |
| **Test Stubs** | Realistic `StubDB`/`StubMarketData`/`StubRiskManager` with configurable behavior |
| **Multi-Timeframe Analysis** | Proper candle resampling with 2/3 timeframe agreement requirement |
| **Adaptive Strategy Weights** | Sharpe-ratio-based sliding window with sigmoid mapping |
| **Docker Security** | Non-root user, minimal base image, proper health checks, resource limits |
| **Live Preflight Validator** | 560-line comprehensive pre-production checklist |

---

## 6. Recommendations — Priority Order

### Immediate (before next production deploy)
1. Fix BUG-1 through BUG-8 (critical bugs listed above)
2. Address SEC-1: Default `DASHBOARD_REQUIRE_API_KEY_FOR_READS=true`
3. Fix CONC-1/CONC-2: Add `asyncio.Lock` for pause state and risk manager positions
4. Fix REL-2: Add circuit breaker / exponential backoff to error recovery loops

### Short-term (next 2-4 weeks)
5. Add division-by-zero guards to all strategies (STRAT-1 through STRAT-8)
6. Make `tenant_id` required in all database query methods (DATA-7)
7. Add webhook rate limiting (SEC-5)
8. Add RingBuffer locking (BUG-4)
9. Add missing database indexes (DB-1)
10. Add test coverage for live execution and WebSocket reconnection paths

### Medium-term (next 1-3 months)
11. Split `server.py` into route modules (ARCH-1)
12. Add Prometheus metrics instrumentation
13. Add `pytest-cov` to CI pipeline
14. Implement proper ES bulk retry with dead-letter queue
15. Remove plaintext password fallback (SEC-3)
16. Harden CSP — replace `unsafe-inline` with nonces

### Long-term (backlog)
17. Add distributed rate limiting (Redis-based) for multi-instance deployments
18. Implement proper hot-reload with file watching
19. Migrate `health_check.sh` to Python
20. Add image vulnerability scanning to CI
21. Standardize timestamp handling (UTC-aware `datetime` everywhere)

---

## 7. Metrics Summary

| Metric | Value |
|--------|-------|
| Total source files | 72 |
| Total source lines | ~29,500 |
| Total test files | 30 |
| Total test lines | ~4,500 |
| Largest file | `server.py` (3,498 lines) |
| Critical bugs found | 8 |
| High-severity issues | 19 |
| Medium-severity issues | 20 |
| Low-severity issues | 15+ |
| Test pass rate | 171/175 (97.7%) |
| Modules with no tests | ~15 (strategies, exchange clients, ML pipeline) |
