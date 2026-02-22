# NovaPulse Preflight Audit — First Review

**Date:** 2026-02-22
**Reviewer:** Claude Opus 4.6 (Senior Web App Engineer + Fintech Systems Architect)
**Codebase:** NovaPulse v3.0.0 — Multi-strategy AI crypto trading engine
**Scope:** 65 Python source files (~25.5K LOC), 24 test files, 16 strategies, Docker + CI/CD

---

## Executive Summary

NovaPulse is an impressive, well-architected trading system. The codebase shows clear evidence of security-conscious engineering (parameterized SQL, CSRF protection, Argon2 hashing, 1Password references, vault encryption). The trading logic has multiple defense layers (Kelly sizing, circuit breakers, drawdown scaling, correlation guards). However, the following issues must be addressed before any live deployment:

1. **CRITICAL — EC private keys on disk:** Two Coinbase API key files (`keys/novapulse.json`, `NovaPulse.json`) contain live EC private keys on the local filesystem. Not tracked in git, but must be rotated immediately.
2. **CRITICAL — Slack bot fail-open:** When `SLACK_ALLOWED_CHANNEL_ID` is unset, any workspace user can execute `/trading-close-all` and `/trading-kill`.
3. **CRITICAL — No exchange-native stop orders:** All stops are software-managed. A bot crash leaves positions fully unprotected until restart.
4. **HIGH — Zero test coverage on `execute_signal()`:** The single most critical function in the system has no direct test.
5. **HIGH — `close_all_positions()` untested end-to-end:** The emergency stop control has no integration test.
6. **HIGH — Ghost position risk on exit failure:** After 3 failed exit attempts, the trade is marked "error" but the broker position remains open with no reconciliation.
7. **MEDIUM — Smart Exit (dual TP) disabled by default.** If 2-TP structure is required, it needs to be enabled in config.
8. **MEDIUM — Login endpoint has no brute-force protection.**
9. **MEDIUM — CSP allows `unsafe-inline` scripts** — XSS mitigation effectively bypassed.
10. **LOW — Missing HSTS header, admin username pre-filled on login page.**

**Overall Assessment:** The codebase is at ~85% production readiness. Phase 1 fixes (below) are required before live trading. Phase 2 items should follow within the first week.

---

## Risk Register

| ID | Severity | Area | Finding | Exploit / Failure Scenario | Fix Plan | Effort | Status |
|----|----------|------|---------|---------------------------|----------|--------|--------|
| R01 | **Critical** | Security | EC private keys on disk (`keys/novapulse.json`, `NovaPulse.json`) contain live Coinbase CDP keys | Anyone with filesystem access can trade/withdraw from linked Coinbase accounts | Revoke keys in Coinbase CDP, delete files, rotate credentials | 15 min | **Open** |
| R02 | **Critical** | Security | Slack bot `_is_authorized()` returns `True` when `allowed_channel_id` is unset (`slack_bot.py:49-53`) | Any Slack workspace member can execute `/trading-kill`, `/trading-close-all` | Change default to `return False` (fail-closed) | 5 min | **Open** |
| R03 | **Critical** | Trading | No exchange-native stop orders — all stops managed in-process only | Bot crash/OOM/power loss leaves positions unprotected for 30-120s+ until restart | Document as known risk + ensure `reinitialize_positions()` is robust; consider exchange-side OCO orders for live mode | 2-4 hrs | **Open** |
| R04 | **High** | Testing | `execute_signal()` — the core trading pipeline — has zero direct test coverage (`executor.py:208`) | Regression in signal validation, sizing, or order placement would go undetected | Write 5-8 unit tests covering happy path, duplicate rejection, stale signal, confidence threshold | 2 hrs | **Open** |
| R05 | **High** | Testing | `close_all_positions()` and control endpoints (`/pause`, `/resume`, `/close_all`) have no HTTP integration tests | Auth bypass or endpoint regression could prevent emergency stop from working | Write integration tests hitting HTTP endpoints with auth | 1.5 hrs | **Open** |
| R06 | **High** | Trading | Ghost positions on exit failure: after 3 failed exit retries, trade marked `status="error"` but broker position stays open (`executor.py:820-829`) | Unmanaged broker position with no bot awareness — potential unlimited loss | Add position reconciliation check against exchange on startup + periodic reconciliation | 3 hrs | **Open** |
| R07 | **Medium** | Trading | Smart Exit (tiered TP) disabled by default (`config.py:487`). Only single flat TP per trade. | If dual-TP is a product requirement, trades exit with single TP only | Enable in `config.yaml` and verify tier configuration | 15 min | **Open** |
| R08 | **Medium** | Security | No brute-force protection on `/login` endpoint (`server.py:1235-1248`) | Online dictionary/credential stuffing attack at 4 req/s sustained | Add per-username failed-attempt counter with lockout after 5 failures | 1 hr | **Open** |
| R09 | **Medium** | Security | CSP allows `script-src 'unsafe-inline'` (`server.py:925`) | Any XSS injection executes in admin context — could issue close-all, exfiltrate session | Refactor inline handlers to external JS; use nonces for CSP | 3-4 hrs | **Open** |
| R10 | **Medium** | Security | Admin username pre-filled in login HTML (`server.py:1225`) | Reduces attacker work to password-only brute force | Remove `value=` attribute from username input | 5 min | **Open** |
| R11 | **Medium** | Security | Missing HSTS header (`server.py:909-929`) | Browser downgrades to HTTP on first visit — MITM risk for session cookies | Add `Strict-Transport-Security` header in production | 10 min | **Open** |
| R12 | **Medium** | Security | Webhook secrets stored as plaintext in SQLite `copy_trading_providers` table (`database.py:259-266`) | SQLite file backup/exfiltration exposes all webhook signing secrets | Hash webhook secrets; verify against hash | 1.5 hrs | **Open** |
| R13 | **Medium** | Testing | Stripe webhook signature verification bypassed in tests — `_FakeStripeService.verify_webhook()` always returns True | Invalid webhook payloads not tested for rejection | Write test with invalid/missing signature asserting 400 response | 45 min | **Open** |
| R14 | **Medium** | Testing | `reinitialize_positions()` post-restart position restore has no test | Silent failure would leave positions without stop-loss tracking after restart | Write test with pre-seeded open trades verifying RiskManager registration | 1 hr | **Open** |
| R15 | **Medium** | Trading | Alpaca stock orders have no retry logic (`alpaca_client.py:92-101`) | Single network blip silently drops buy/sell order | Add 1-2 retry attempts with backoff | 30 min | **Open** |
| R16 | **Medium** | Trading | Stock engine has no market-hours guard (`swing_engine.py:474-534`) | Orders submitted on weekends/holidays are queued or rejected | Add US market hours check before order submission | 45 min | **Open** |
| R17 | **Low** | Trading | Correlation groups hardcoded to 8 pairs (`executor.py:92-101`) | New config pairs get no correlation grouping — concentrated exposure risk | Make correlation groups configurable in config.yaml | 30 min | **Open** |
| R18 | **Low** | Testing | `test_ws_update_resilience.py:133` has timing-based assertion (`assert elapsed < 0.35`) | Flaky on slow CI runners | Increase threshold or use mocked time | 10 min | **Open** |
| R19 | **Low** | Testing | Strategy tests use unseeded `np.random` in `test_core.py` | Non-reproducible test data across runs | Use `np.random.default_rng(seed)` like `test_strategy_replay.py` | 15 min | **Open** |
| R20 | **Low** | Config | Kraken `PAIR_MAP` only covers 8 pairs (`kraken_rest.py:47-56`) | Unconfigured pairs use `pair.replace("/","")` — may not match Kraken names | Expand map or add dynamic pair resolution | 20 min | **Open** |

---

## Security Findings

### Confirmed Secure (No Action Required)

These areas were audited and found correctly implemented:

- **SQL injection protection:** All queries use parameterized `?` placeholders. `update_trade` uses a `TRADE_UPDATE_COLUMNS` frozenset whitelist for column names.
- **API key storage:** Tenant API keys stored as SHA-256 hashes in `tenant_api_keys` table.
- **CSRF protection:** Control endpoints enforce double-submit cookie pattern with `secrets.compare_digest`.
- **Password hashing:** Argon2 (preferred) and bcrypt both supported via `DASHBOARD_ADMIN_PASSWORD_HASH`. Plaintext passwords blocked in production (`set_bot_engine` raises `RuntimeError`).
- **Session security:** `itsdangerous.URLSafeTimedSerializer` with configurable TTL, `httponly=True`, `samesite="strict"`, `secure=True` in production.
- **Vault encryption:** PBKDF2 with 480,000 iterations + Fernet (AES-128-CBC + HMAC). Atomic writes with `.tmp` rename.
- **`.env` secrets:** All secrets use 1Password `op://` references — no plaintext credentials committed.
- **CORS:** Explicitly enumerated origins; no wildcard `*`.
- **Rate limiting:** Token bucket per-IP with memory-exhaustion protection (10K bucket cap, periodic eviction).
- **WebSocket auth:** `/ws/live` respects same session/API key auth as REST endpoints.
- **Stripe webhooks:** `stripe.Webhook.construct_event` signature verification before processing.
- **Signal webhook replay:** Idempotency keys stored in `signal_webhook_events` table.
- **Dependencies:** No known-vulnerable packages in `requirements.txt` as of Feb 2026.

### Issues Requiring Action

| ID | File:Line | Finding | Severity |
|----|-----------|---------|----------|
| R01 | `keys/novapulse.json:3`, `NovaPulse.json:3` | Live EC private keys on disk (not in git, but present on filesystem) | Critical |
| R02 | `src/utils/slack_bot.py:49-53` | Fail-open authorization — any workspace user can issue kill/close commands | Critical |
| R08 | `src/api/server.py:1235-1248` | No brute-force protection on `/login` | Medium |
| R09 | `src/api/server.py:925` | `script-src 'unsafe-inline'` nullifies CSP XSS protection | Medium |
| R10 | `src/api/server.py:1225` | Admin username pre-filled in login HTML source | Medium |
| R11 | `src/api/server.py:909-929` | Missing `Strict-Transport-Security` header | Medium |
| R12 | `src/core/database.py:259-266` | Webhook secrets stored as plaintext in SQLite | Medium |

---

## Trading Integrity Findings

### Order Lifecycle

The order lifecycle is well-structured:

```
Signal → Validation → Risk Check → Sizing → Limit Order → Fill Monitoring → DB Record → SL/TP Init
                                                                                          ↓
Position Management Loop (every 2s) → Trailing Stop → Breakeven → Smart Exit Tiers → TP Check
                                                                                          ↓
Close Position → Exit Order (market, 3 retries) → Fee Calc → PnL → DB Close → ML Label → Risk Update
```

**Strengths:**
- Signal age decay (2%/sec over 5s, discard after 60s) — prevents stale signal execution
- Limit orders for entry with chase logic (2 repricing attempts + market fallback)
- SL/TP shift on fill slippage preserves risk distances
- Entry + exit fees correctly included in net PnL calculation
- Comprehensive metadata stored per trade (Kelly fraction, slippage, fees, planned vs actual levels)
- ML features logged at entry, labeled at close — clean training data pipeline

**Issues:**

| ID | File:Line | Finding | Impact |
|----|-----------|---------|--------|
| R03 | System-wide | All stops are software-managed — no exchange-native stop orders | Bot crash = unprotected positions |
| R06 | `executor.py:820-829` | Ghost positions: exit failure marks trade as "error" but broker position stays open | Potential unlimited loss on failed exit |
| R07 | `config.py:487` | Smart Exit (tiered partial-close TPs) disabled by default | Only single flat TP unless explicitly enabled |
| R15 | `alpaca_client.py:92-101` | Alpaca orders have no retry logic | Network blip silently drops order |
| R16 | `swing_engine.py:474-534` | Stock engine submits orders without market-hours check | Weekend/holiday orders rejected or queued |
| R17 | `executor.py:92-101` | Correlation groups hardcoded to 8 pairs | New pairs get no correlation protection |

### Risk Controls — Verified Working

| Control | Default | File:Line | Verified |
|---------|---------|-----------|----------|
| Max risk per trade | 2% of bankroll | `risk_manager.py:96` | Yes |
| Max daily loss | 5% of initial bankroll | `risk_manager.py:97,317` | Yes |
| Max position USD | $500 | `risk_manager.py:98` | Yes |
| Max concurrent positions | 5 | `risk_manager.py:102` | Yes |
| Max total exposure | 50% of bankroll | `risk_manager.py:103` | Yes |
| Kelly fraction | Quarter-Kelly (0.25) | `risk_manager.py:99` | Yes |
| Max stop distance | 10% of entry price | `risk_manager.py:210` | Yes |
| Min risk-reward ratio | 1.2:1 | `risk_manager.py:113` | Yes |
| Global cooldown after loss | 30 min | `risk_manager.py:110` | Yes |
| Per-pair cooldown | 300s (paper: 60s) | `engine.py:652` | Yes |
| Drawdown scaling | 0.15x at >18% DD | `risk_manager.py:637-659` | Yes |
| Risk of Ruin threshold | 1% (blocks if >1%) | `risk_manager.py:101` | Yes |
| Circuit breaker: stale data | Auto-pause after 3 checks | `engine.py:204-216` | Yes |
| Circuit breaker: WS disconnect | Auto-pause after 300s | `engine.py:219-231` | Yes |
| Circuit breaker: consecutive losses | Auto-pause after 4 losses | `engine.py:234-242` | Yes |
| Circuit breaker: drawdown | Auto-pause at 8% | `engine.py:245-253` | Yes |
| Duplicate pair guard | One position per pair | `executor.py:275-279` | Yes |
| Correlation group guard | Max 2 per group | `executor.py:282-290` | Yes |
| Instance lock | Prevents double-trading | `main.py` | Yes |

### SL/TP Logic

- **Stop Loss:** ATR-based with 2.25x multiplier, floored at 2.5% min distance (`indicators.py:35-66`)
- **Take Profit:** ATR-based with 3.0x multiplier, floored at 5.0% min distance
- **Trailing Stop:** Activates at 1.5% profit, trails from highest price with 0.5% step, accelerates at 3% and 5% profit
- **Breakeven:** Moves stop to entry price at 1.0% profit
- **Smart Exit Tiers (when enabled):** 50% close at 1x TP distance, 60% at 1.5x, remainder trailing

---

## Test & QA Findings

### Coverage Summary

| Area | Coverage | Quality | Launch Risk |
|------|----------|---------|-------------|
| Technical indicators | Good | Strong (math verified) | Low |
| Strategy signal generation | Moderate | Type-contract only, not direction | Medium |
| Confluence/guardrails | Moderate | Good | Medium |
| **`execute_signal()` (core loop)** | **None** | **N/A** | **Critical** |
| **`close_all_positions()` (emergency)** | **None** | **N/A** | **Critical** |
| **Control endpoints via HTTP** | **None** | **N/A** | **High** |
| Risk manager sizing | Good | Strong | Low |
| Stop loss / trailing | Good | Strong | Low |
| Database operations | Good | Strong (real SQLite in tmpdir) | Low |
| Stripe webhook signature | None (mocked away) | Inaccurate mock | High |
| Stripe event DB state transitions | None | N/A | High |
| API auth / tenant resolution | Partial | Moderate | Medium |
| Backtester | Smoke only | Superficial | Medium |
| ML pipeline | Moderate | Moderate | Low |
| Stocks/Alpaca reconciliation | Good | Strong | Low |
| Multi-engine routing | Good | Strong | Low |
| Circuit breakers | Good | Strong | Low |
| `reinitialize_positions()` | None | N/A | High |

### Critical Missing Tests (Must-Have Before Launch)

1. **`execute_signal()` full pipeline** — paper fill happy path, duplicate pair rejection, stale signal discard, confidence threshold, quiet hours filter
2. **`close_all_positions()` end-to-end** — HTTP endpoint with auth, verify DB trades closed
3. **Control endpoints via HTTP** — `/pause`, `/resume` with auth guard verification
4. **Stripe webhook rejection** — invalid/missing signature returns 400
5. **`reinitialize_positions()` restore** — open trades re-registered in RiskManager on restart

### Test Infrastructure Notes

- Framework: pytest 8.3.4 + pytest-asyncio (auto mode)
- No `conftest.py` — no shared fixtures
- No test tier markers (`@pytest.mark.unit` vs `@pytest.mark.integration`)
- CI: Python 3.11 + 3.12 matrix, plus walk-forward out-of-sample gate
- All tests run together via `pytest -q` — no separation

---

## Deployment Readiness Findings

### Docker / Compose

- Multi-stage build with non-root `trader` user — good security practice
- Health check: `curl /api/v1/health` every 30s with 120s start grace
- Memory limits: 2GB max / 512MB reserved
- Bind mounts for data, logs, models, config (read-only), secrets (read-only)
- `TRADING_MODE=paper` and `START_PAUSED=1` in Dockerfile — safe defaults
- Elasticsearch and Kibana services properly configured

### Environment / Config

- `.env` uses 1Password `op://` references — production secrets not in source
- `.env.example` has 173+ config options with clear documentation
- `config.yaml` at 406 lines with comprehensive Pydantic validation
- Env vars override YAML values (proper precedence)
- Live mode enforces: `DASHBOARD_ADMIN_KEY`, `DASHBOARD_SESSION_SECRET`, `DASHBOARD_ADMIN_PASSWORD_HASH` — will refuse to start without them

### CI/CD

- `tests.yml`: pytest on Python 3.11 + 3.12
- `secret-scan.yml`: gitleaks v2 on push/PR
- `release-ops.yml`: snapshot/rollback via manual dispatch
- `load-tests.yml`: K6 load testing (manual dispatch)
- **Gap:** No deployment pipeline (deploy to VPS is presumably manual via rsync/docker-compose)

### Production Readiness Checklist

| Item | Status | Notes |
|------|--------|-------|
| Non-root container user | Pass | `trader` user |
| Health checks | Pass | HTTP + Docker healthcheck |
| Graceful shutdown | Pass | SIGTERM handler, position preservation |
| Instance locking | Pass | `instance.lock` prevents double-run |
| Structured logging | Pass | structlog + JSON file driver |
| Error file separation | Pass | `errors.log` for ERROR+ |
| Log rotation | Pass | Docker JSON driver, 50MB x 5 files |
| Prometheus metrics | Available | `prometheus-client` in deps |
| Start-paused mode | Pass | `START_PAUSED=1` default in Dockerfile |
| Canary mode | Pass | Reduced pairs, tighter risk limits |
| Secrets management | Pass | 1Password `op://` + encrypted vault |
| Live mode guards | Pass | Refuses startup without required auth secrets |

---

## Action Plan

### Phase 1 — Must-Fix Before Launch

These items must be completed before any live trading. Estimated total: **~8 hours**.

| Priority | ID | Task | Effort |
|----------|----|------|--------|
| P0 | R01 | Revoke Coinbase API keys in CDP console; delete `keys/novapulse.json` and `NovaPulse.json` from disk | 15 min |
| P0 | R02 | Fix Slack bot `_is_authorized()` to fail-closed when `allowed_channel_id` is unset | 5 min |
| P1 | R04 | Write `execute_signal()` test suite (5-8 tests covering critical paths) | 2 hrs |
| P1 | R05 | Write `close_all_positions()` and control endpoint HTTP integration tests | 1.5 hrs |
| P1 | R06 | Add exchange position reconciliation at startup (compare broker vs DB open positions) | 2 hrs |
| P1 | R14 | Write `reinitialize_positions()` test | 1 hr |
| P2 | R08 | Add login brute-force protection (per-username lockout after 5 failures) | 1 hr |
| P2 | R10 | Remove admin username pre-fill from login page | 5 min |
| P2 | R11 | Add HSTS header in production mode | 10 min |

### Phase 2 — Should-Fix Soon After Launch (First Week)

| Priority | ID | Task | Effort |
|----------|----|------|--------|
| P3 | R07 | Enable Smart Exit in config.yaml (if dual-TP is required) and verify tier behavior | 30 min |
| P3 | R09 | Refactor inline scripts to external JS; tighten CSP to remove `'unsafe-inline'` | 3-4 hrs |
| P3 | R12 | Hash webhook secrets in `copy_trading_providers` table | 1.5 hrs |
| P3 | R13 | Write Stripe webhook signature rejection test | 45 min |
| P3 | R15 | Add retry logic to Alpaca order submission | 30 min |
| P3 | R16 | Add US market hours check in stock swing engine | 45 min |
| P3 | R18 | Fix flaky timing assertion in `test_ws_update_resilience.py` | 10 min |
| P3 | R19 | Seed `np.random` in `test_core.py` strategy tests | 15 min |

### Phase 3 — Nice-to-Have

| Priority | ID | Task | Effort |
|----------|----|------|--------|
| P4 | R03 | Investigate exchange-native OCO/stop orders for live mode positions | 4-8 hrs |
| P4 | R17 | Make correlation groups configurable in config.yaml | 30 min |
| P4 | R20 | Expand Kraken PAIR_MAP or add dynamic pair resolution | 20 min |
| P4 | — | Add `conftest.py` with shared fixtures; add test tier markers | 1 hr |
| P4 | — | Add `pytest.mark.slow` to timing-dependent tests | 15 min |
| P4 | — | Add deployment pipeline (CI/CD → VPS) | 2-4 hrs |

---

## Proactive Improvements Proposed (Approval Required)

These are scope additions I believe would add significant value. None will be implemented without your approval.

### Proposal 1: Periodic Exchange Position Reconciliation Loop

**Recommendation:** Add a background task that periodically (every 5 min) queries the exchange for open positions and compares against the DB. Log discrepancies and optionally auto-correct.

**Justification:** Currently, ghost positions (R06) are only detected if noticed manually. This would catch: failed exits, positions opened by other tools on the same API key, and positions that survived a crash. The risk of financial loss from undetected ghost positions far outweighs the small development cost.

**Effort:** 3-4 hours

**Approval Question:** Should I implement a periodic position reconciliation loop that compares exchange state vs DB state?

---

### Proposal 2: Exchange-Native Stop Orders for Live Mode

**Recommendation:** When in live mode, place an exchange-native stop-loss order (Kraken supports `stop-loss` order type) immediately after entry fill. Update the exchange stop when trailing stop moves.

**Justification:** This is the single biggest reliability gap (R03). Software-only stops provide zero protection during bot downtime. Exchange-native stops survive any bot failure. This is standard practice for production trading systems.

**Effort:** 6-8 hours (Kraken API integration + trailing stop sync logic)

**Approval Question:** Should I implement exchange-native stop orders for live mode positions?

---

### Proposal 3: Login Brute-Force Protection with Exponential Backoff

**Recommendation:** Add per-username failed-attempt tracking with exponential backoff: 1s after 3 failures, 5s after 5, 30s after 8, account lock after 10 (with admin reset). Log all failed attempts with IP + timestamp.

**Justification:** The dashboard controls live trading operations. Combined with the pre-filled username (R10), online brute-force is currently trivial. This is a standard OWASP recommendation.

**Effort:** 1.5 hours

**Approval Question:** Should I implement login brute-force protection with exponential backoff?

---

### Proposal 4: Add `conftest.py` with Shared Test Fixtures

**Recommendation:** Create a `tests/conftest.py` with common fixtures: in-memory DB, mock market data, mock REST client, sample ConfluenceSignal factory, sample trade factory. Add `@pytest.mark.unit` and `@pytest.mark.integration` markers.

**Justification:** The current test suite duplicates mock setup across files. A shared fixture layer would make the critical missing tests (R04, R05, R14) faster to write and maintain. It would also enable `pytest -m unit` for fast development iteration.

**Effort:** 2 hours

**Approval Question:** Should I create a shared test fixture layer in `conftest.py`?

---

### Proposal 5: Comprehensive Error Alerting Dashboard Widget

**Recommendation:** Add a persistent "alerts" panel to the web dashboard that shows the last N system warnings/errors (ghost positions, failed exits, circuit breaker activations, auto-pauses) with timestamps and severity.

**Justification:** Currently, operational alerts go to Telegram/Discord/Slack (if configured), but the web dashboard only shows the thought feed. A dedicated alerts panel would give operators immediate visibility into critical events without relying on external messaging.

**Effort:** 3-4 hours

**Approval Question:** Should I add an operational alerts panel to the dashboard?

---

*Report generated by Claude Opus 4.6 — Preflight Audit Session 1*
