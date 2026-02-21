# Final Testing And Comprehensive Code Review

**Project:** `aitradercursor2` (AI Crypto Trading Bot v2.0.0)  
**Review date:** 2026-02-14  
**Reviewer:** automated+manual pass (repo docs + code + tests)  
**Test run (local):** `./venv/bin/python -m pytest -q` (Python 3.13.7) -> **40 passed**  

## What This Project Is (4-7 Paragraphs)

This repository is a single-process crypto trading system that combines real-time market data ingestion (WebSocket + REST warmup), multiple technical-analysis strategies, a confluence layer that merges those strategies into a single decision, an optional ML-based predictor that gates entries, a risk manager that enforces sizing and safety limits, and an execution engine that can place orders in paper or live mode.

The core problem it was created to solve is: run automated trading across multiple pairs (and optionally multiple exchanges) while keeping operator visibility and control high, and keeping capital preservation mechanisms strong enough that the system can run unattended for long periods. The “visibility/control” surface is primarily a FastAPI dashboard (REST + WebSocket live stream) plus an optional Telegram control plane.

At a functional level, the code does implement the described pipeline end-to-end: it can warm up candles, maintain a rolling OHLCV cache, compute signals across several strategies, compute confluence (including optional order book weighting and a microstructure score), size trades with risk constraints, execute trades (paper or live), persist trades/thoughts/metrics to SQLite (WAL), and stream state to a browser dashboard.

Does it solve the problem as stated? For a single operator on a trusted network, it largely solves “run a bot and observe/control it,” and the codebase shows multiple rounds of hardening (staleness checks, one-position-per-pair enforcement, DB write locking, WS reconnect logic, control auth model, etc.). However, the current API security model is not production-SaaS safe by default (read endpoints and WebSocket can be accessed without credentials, falling back to the default tenant), and the system’s “production-grade” claim depends heavily on being deployed behind a reverse proxy with authentication and network restrictions.

Are there bugs? Yes. Most are not “syntax” bugs (tests pass), but production-impacting correctness/security issues: the dashboard read path is effectively unauthenticated by default; a tenant-id mismatch existed in executor close logging (fixed in this review); SQLite timestamp comparisons were inconsistent with ISO8601 strings and caused cleanup/today PnL logic to be unreliable (fixed in this review); and the engine health monitor previously could spawn duplicate WS loops under certain conditions (fixed in this review).

Is it production grade for heavy live traffic? Not yet, if “production grade” means internet-exposed, multi-tenant safe, and resilient under adversarial conditions. The trading pipeline itself is reasonably engineered for one operator, but the control plane needs stricter auth defaults, explicit tenancy boundaries throughout, stronger rate-limits and abuse controls, and more defensive data validation to be safe at scale. With those changes (plus more load/perf testing and more exhaustive exchange edge-case testing), it can be moved toward genuine production readiness.

What would I add for undeniable success? I would add a hardened security posture by default (auth required for reads, per-tenant scoping everywhere, and safe-by-default deployment templates), robust exchange abstraction tests (pair mapping, order lifecycle, partial fills, cancels, and reconnect/replay behavior), and a “truth” accounting system (consistent timestamps, deterministic PnL/fee accounting, and reconciliation against exchange fills). I would also add a full “paper-to-live” launch checklist baked into code: live-mode startup gating, sanity checks, and automated rollback/kill criteria.

## Architecture Reality Check (Docs vs Code)

The documentation map in `README.md`, `PROJECT_STUDY.md`, and `docs/kb-merged/01-overview-and-architecture.md` matches the code organization well:

- Orchestration: `main.py`, `src/core/engine.py`
- Data: `src/exchange/market_data.py`, `src/core/structures.py`
- Strategies: `src/strategies/*`, `src/utils/indicators.py`, `src/utils/indicator_cache.py`
- Confluence + AI gating: `src/ai/confluence.py`, `src/ai/predictor.py`, `src/ai/order_book.py`
- Risk + execution: `src/execution/risk_manager.py`, `src/execution/executor.py`
- Persistence: `src/core/database.py`
- Control + UI: `src/api/server.py`, `static/`
- Optional multi-exchange: `src/core/multi_engine.py`
- Optional billing/tenancy: `src/billing/stripe_service.py`

## Production Readiness Verdict

**Verdict:** strong “operator-grade” bot for trusted networks; **not** yet “internet-exposed production SaaS grade” by default.

Primary blockers to “heavy live traffic production ready”:

- Read/API/WebSocket auth defaults are too permissive (falls back to default tenant without credentials).
- Tenancy boundaries are not consistently enforced across all subsystems (control plane, DB access patterns, and multi-engine routing are “best effort,” not a hardened contract).
- DB timestamp format inconsistency previously broke key operational queries (cleanup, “today” PnL, retention); fixed here, but the overall timestamp strategy should still be simplified and standardized.
- Abuse controls are light (rate limiting, request validation, DoS protection, and CSP are minimal).
- Exchange execution correctness at scale needs more property tests and reconciliation logic (partial fills, stale order state, retry semantics).

## Findings (Ordered By Severity)

### Critical

1. **Unauthenticated read access defaults to `default` tenant**
   - Files: `src/api/server.py:107`, `src/api/server.py:403`
   - Detail: `_resolve_tenant_id` and `resolve_tenant_id()` allow empty `X-API-Key` and will return the default tenant. All read endpoints that depend on `_resolve_tenant_id` are therefore readable by unauthenticated callers if the API is reachable.
   - Impact: if the dashboard is exposed beyond localhost or a trusted network segment, anyone can read trades/positions/thoughts for the default tenant.
   - Recommendation: require auth for reads by default in non-local deployments, or add a config flag like `dashboard.require_api_key_for_reads` defaulting to `True` in live mode.

2. **WebSocket live feed can be accessed without credentials**
   - Files: `src/api/server.py:749`
   - Detail: `/ws/live` resolves tenant similarly and allows empty credentials to map to the default tenant.
   - Impact: real-time leakage of trading data and operational telemetry.
   - Recommendation: require at least tenant API key for WS, and consider separate “read token” vs “control token.”

### High

1. **Dashboard exposes tenant records without auth**
   - Files: `src/api/server.py:680`
   - Detail: `GET /api/v1/tenants/{tenant_id}` is unauthenticated.
   - Impact: leaks billing/tenant status metadata; can be used for enumeration.
   - Recommendation: require admin key or tenant key pinned to that tenant.

2. **Callback/task restart patterns are fragile across reconnect scenarios**
   - Files: `main.py`, `src/core/engine.py`, `src/exchange/kraken_ws.py`, `src/exchange/coinbase_ws.py`
   - Detail: the system relies on a combination of WS-client internal reconnect loops plus an outer “restart wrapper.” This is workable, but it is easy to accidentally introduce duplicate subscriptions/callback registration if additional restarts are added later.
   - Recommendation: register callbacks exactly once and treat WS connection lifecycle as a state machine; add explicit instrumentation around “subscription count per channel.”

### Medium

1. **Tenant mismatch in close-position thought logging (fixed)**
   - Files: `src/execution/executor.py:445`
   - Detail: `_close_position()` logged thoughts under `self.tenant_id` even when closing as a different tenant (eg close-all scoped); this was corrected to log under `tid`.
   - Status: fixed in this review.

2. **SQLite timestamp parsing inconsistencies affected retention and “today” stats (fixed)**
   - Files: `src/core/database.py:626`, `src/core/database.py:783`
   - Detail: timestamps were stored as ISO8601 strings, but cleanup/stats queries compared them against `datetime('now', ...)`, which can fail when strings include `T`/timezone. “today_pnl” used `date(exit_time)` which is also format-sensitive.
   - Status: fixed in this review by introducing a tolerant SQL datetime wrapper and using `substr(exit_time,1,10)` for “today.”

3. **Engine health monitor could spawn duplicate WS loops (fixed)**
   - Files: `src/core/engine.py:658`
   - Detail: it attempted to detect “WS task alive” by introspecting coroutine strings; under the task-wrapper approach this can evaluate incorrectly and spawn an extra WS loop.
   - Status: fixed in this review by removing WS task spawning from health monitor.

4. **Vault crypto claims are misleading**
   - Files: `src/core/vault.py`
   - Detail: the docstring claims “AES-256-GCM” but the implementation uses `cryptography.fernet.Fernet` (AES-128-CBC + HMAC).
   - Impact: security documentation mismatch; may create false confidence.
   - Recommendation: correct the docs, or implement AES-256-GCM explicitly (and add integrity checks actually enforced).

### Low

1. **Outlier rejection threshold may reject legitimate crypto moves**
   - Files: `src/exchange/market_data.py`
   - Detail: rejects bars with >20% deviation from last close.
   - Recommendation: make threshold configurable per pair/volatility regime; log counters to observe how often this triggers.

2. **Unicode/emoji in logs and DB thought messages**
   - Files: `src/core/engine.py`, `src/execution/executor.py`, `src/utils/telegram.py`
   - Detail: emojis are written into DB and logs.
   - Impact: mostly operational (log pipelines/terminals); not a correctness issue.
   - Recommendation: ensure log sinks and DB consumers are UTF-8 safe; optionally provide an “ascii-only logs” mode.

## What I Would Change / Remove

- Make the dashboard API “secure by default”:
  - Require auth for reads and WS in live mode (and ideally always, with a simple local setup path).
  - Split keys into “read-only” and “control” scopes.
  - Add per-IP rate limiting and request size limits for all endpoints.
- Standardize timestamps everywhere (ideally store epoch seconds as `REAL`, or enforce one UTC string format and never mix).
- Tighten tenancy:
  - Make tenant_id a first-class parameter throughout the engine, executor, DB reads/writes, and control router.
  - In multi-exchange mode, clearly separate “exchange” from “tenant” routing.
- Add reconciliation:
  - In live mode, reconcile open positions and fills with the exchange on a schedule; alert when divergence is detected.

## What I Would Add Next (Highest ROI)

1. **Security hardening pass**: auth-required reads/WS, CSP headers, configurable CORS, rate limiting, audit logging of control actions.
2. **Execution correctness tests**: property tests for partial fills, order retries, and “close_all/kill” behavior across reconnects.
3. **Accounting correctness**: consistent fee model, realized/unrealized PnL reconciliation, and a “ledger” table.
4. **Operational guardrails**: live-mode startup checklist, invariant checks (stale feed, spreads, max exposure), automatic safe-stop triggers.
5. **Performance profiling**: scan loop CPU and memory profiling under 8+ pairs and multi-timeframe mode; indicator-cache hit rate metrics.

## Notes On Current State Of The Repo

- There are multiple historical review documents (`docs/notes/FinalReview.md`, `GPTReview.md`, etc.) that align with many of the improvements already present.
- CI exists in `.github/workflows/tests.yml` (Python 3.11/3.12). Locally, the venv used Python 3.13.7; that conflicts with `pyproject.toml` (`<3.13`) and should be reconciled for consistent deployments.

## System-By-System Review (Key Notes)

### Lifecycle + Orchestration

- `main.py` owns lifecycle and starts background tasks under a restart wrapper. This is a good direction for long-running services, but it increases the importance of “exactly once” registration for callbacks and idempotent startup behavior.
- Signal handling uses `loop.add_signal_handler(...)`, which will not work on some platforms (notably Windows). If Windows support matters, add a fallback using `signal.signal(...)`.

### Engine (`src/core/engine.py`)

- Strength: the engine separates concerns cleanly (warmup, scan loop, position loop, WS loop, health monitor, cleanup, retrainer) and uses a queue-based “event scan” mechanism to reduce unnecessary scanning.
- Risk: the WS loop currently registers callbacks each time `_ws_data_loop()` is called. This is safe as long as `_ws_data_loop()` is called exactly once for the lifetime of the engine; if it is ever restarted, callbacks can be registered multiple times (duplicated processing per message). If you keep the outer restart wrapper, add a guard flag like `_ws_callbacks_registered`.
- The scan pipeline logs rich “analysis thoughts” for every non-neutral confluence signal; great for transparency, but it will grow `thought_log` quickly under heavy traffic.

### Market Data (`src/exchange/market_data.py`, `src/core/structures.py`)

- The RingBuffer-based OHLCV cache is a pragmatic choice for low-latency indicators.
- Outlier rejection is hard-coded at 20%. Crypto can gap more than that on illiquid pairs; consider making this configurable and/or regime-based.
- Staleness tracking is based on last update timestamps; this is good, but you should ensure all relevant update paths (ticker, ohlc, rest poll) update `_last_update` consistently.

### Exchange Integrations

- Kraken (`src/exchange/kraken_rest.py`, `src/exchange/kraken_ws.py`): the REST client has rate limiting, retry backoff, and nonce safety; the WS client has reconnect logic and resubscription support.
- Coinbase (`src/exchange/coinbase_rest.py`, `src/exchange/coinbase_ws.py`): ticker normalization is done into a Kraken-like shape (`a`/`b`) which keeps executor logic simple.
- Production note: the “pair mapping” problem (Kraken internal symbols vs external, Coinbase product ids) is always a source of edge cases; add tests that round-trip every configured pair through each adapter.

### Strategies + Confluence (`src/strategies/*`, `src/ai/confluence.py`)

- Confluence does real work (multi-timeframe resampling, regime weighting, order-book and microstructure gating). This is the central “edge” module, and it is implemented coherently.
- Strategy execution is protected by timeouts; good. However, timeouts should be tracked as metrics (per strategy) so you can see if a strategy is chronically timing out under load.
- Stop-loss / take-profit aggregation is “best-effort.” For production you generally want a clear contract: either confluence sets SL/TP deterministically, or execution derives them from current ATR/volatility at fill time.

### Risk + Execution (`src/execution/risk_manager.py`, `src/execution/executor.py`)

- RiskManager uses fixed-fractional sizing as the primary method, with Kelly as a cap when sufficient history exists. This is a sensible choice for early-stage bots because it keeps the system trading while collecting data.
- Executor is “one position per pair,” which simplifies risk and avoids accidental doubling.
- Live-mode closure uses market orders for safety. If slippage is a major concern, you can add a limit-close option for take-profit exits while retaining market for stop-loss exits.
- Persistence of trailing state: the stop-loss state is only written when the stop price changes; this can lose trailing_high/low details across restarts. If you want better restore fidelity, persist `stop_loss_state` periodically or on a timer.

### Persistence (`src/core/database.py`)

- SQLite WAL + an async lock is good enough for a single-operator bot.
- For “heavy live traffic,” SQLite becomes a bottleneck; you would likely need a real DB (Postgres) or a write-behind queue and a separate writer task.
- Timestamp handling is a known footgun in SQLite when mixing ISO8601 strings and SQLite datetime functions. The repo should pick one timestamp representation and enforce it everywhere.

### API + Dashboard (`src/api/server.py`, `static/`)

- WebSocket payload caching (once per second) is a good optimization.
- The security model is currently “good enough if you trust the network.” If you ever expose this publicly, you need auth required for reads and WS, plus rate limiting and CSP headers.
- Browser key handling via `localStorage.DASHBOARD_API_KEY` is fine for local operator usage, but for production you should avoid long-lived secrets in browser storage and prefer short-lived tokens.

### ML (`src/ml/trainer.py`, `src/ml/backtester.py`)

- Training in a subprocess is the right approach to prevent TensorFlow from destabilizing the main event loop.
- The normalization step computes mean/std on the entire dataset before splitting; this is a mild form of leakage. Fix by computing mean/std on train only, and applying to val.

### Ops + Deployment

- Docker and a structured docs set exist (`docs/kb-*`), including runbooks and security notes. That’s a strong foundation.
- For real production deployments, add a “secure default” compose stack: reverse proxy auth, TLS, log rotation, and resource limits.

---

## END OF PRIOR RESULTS (up to 2026-02-14)
## BEGIN NEW FINAL COMPREHENSIVE REVIEW (2026-02-21)

### Scope And Method
- Full local codebase pass focused on end-to-end lifecycle correctness, interconnectivity, performance hot paths, and error-handling resilience.
- Verification stack executed locally on 2026-02-21.

### Validation Matrix (New Run)
- `./venv/bin/python -m pytest -q` -> **126 passed in 4.60s**.
- `./venv/bin/python scripts/walk_forward_gate.py` -> **PASS** (OOS gate passed).
- `./venv/bin/python -m ruff check src/api/server.py src/execution/executor.py src/stocks/swing_engine.py tests/test_executor_runtime_guards.py tests/test_ws_update_resilience.py` -> **All checks passed**.
- `./venv/bin/python -m mypy src tests` -> **fails with 291 errors in 37 files** (typed-safety debt remains high).

### Deep Lifecycle Review (What Was Verified)
- Signal -> risk -> execution -> persistence path reviewed in `src/execution/executor.py:208`, `src/execution/executor.py:631`, `src/core/database.py` trade/close paths.
- Dashboard realtime aggregation and engine interconnectivity reviewed in `src/api/server.py:3254` and related auth/tenant helpers.
- Stocks scan/open/close/reconcile flow reviewed in `src/stocks/swing_engine.py:497` and related broker reconciliation paths.
- Runtime error pathways were fault-injected (failing engine snapshots, partial component failures) to verify degradation behavior instead of hard failure.

### Optimizations And Refactors Applied In This Pass
1. **Trade-rate throttle DB query caching**
- Added short TTL cache in executor to avoid repeated SQLite `count_trades_since` on every candidate signal.
- Files: `src/execution/executor.py:262`, `src/execution/executor.py:600`.
- Impact: lower DB contention/latency in high-signal scan cycles.

2. **Stop-loss state persistence correctness fix**
- Fixed metadata persistence condition so `stop_loss_state` is written even when stop price is unchanged.
- Files: `src/execution/executor.py:715`, `src/execution/executor.py:727`.
- Impact: improved restart fidelity for trailing/breakeven state.

3. **WebSocket update path refactor for performance + resilience**
- Added per-engine snapshot collector and concurrent collection via `asyncio.gather`.
- Added fallback behavior when shared DB thought fetch fails.
- Files: `src/api/server.py:3160`, `src/api/server.py:3254`, `src/api/server.py:3291`.
- Synthetic benchmark (3 engines, 50ms IO per query class): update build remained ~201ms and continued returning `type=update` even with one engine failing.

4. **Stocks scanner fetch parallelization**
- Refactored daily-bar fetch from per-symbol serial calls to bounded-concurrency batch fetch.
- Files: `src/stocks/swing_engine.py:497`, `src/stocks/swing_engine.py:536`.
- Synthetic benchmark (6 symbols, 50ms each): ~50ms batched vs ~300ms serial-equivalent expectation.

5. **Lint hygiene in touched server paths**
- Removed unused imports and ambiguous variable names in chart aggregation path.
- File: `src/api/server.py` (touched sections around aggregation/rest chart parsing).

### New Regression Tests Added
- `tests/test_executor_runtime_guards.py`
  - Verifies stop-loss metadata persistence when SL is unchanged.
  - Verifies recent-trade count cache behavior.
- `tests/test_ws_update_resilience.py`
  - Verifies websocket updates continue when one engine snapshot fails.
  - Verifies snapshot collection is parallelized.

### Findings (Current Remaining Risks)

#### High
1. **Static type safety gate is currently not enforceable**
- Evidence: `mypy` reports 291 errors across core runtime files.
- Impact: higher risk of latent regressions during ongoing rapid iteration.
- Recommendation: staged typing hardening plan (start with `src/api/server.py`, `src/execution/*`, `src/stocks/*`, `src/core/config.py`) and move to CI warning-to-fail rollout.

#### Medium
1. **1Password vault topology mismatch vs expected operational model**
- Service-account-visible vaults currently show only `dev` (not separate `dev trading`, `dashboard`, `billing`, `data` vaults).
- Impact: weaker separation-of-duties and harder least-privilege permissioning.
- Recommendation: split or alias vault structure by domain (trading/dashboard/billing/data) and assign scoped service-account access.

2. **Billing critical inputs still appear incomplete for production webhooks**
- Present in vault inventory: `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_RESTRICTED_KEY`.
- Not observed in current vault field inventory: `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_ID`.
- Impact: subscription checkout and webhook verification flows may be partially configured.

3. **Webhook signing secret coverage should be explicitly confirmed**
- Signal webhook path exists (`SIGNAL_WEBHOOK_SECRET`) but corresponding secret was not visible in current vault inventory snapshot.
- Impact: webhook endpoints risk disabled/weak auth if left empty.

### 1Password Secret Inventory (Sanitized, names/fields only)
- Vault visible to service account: `dev`.
- Item `trading`: `ALPACA_ENDPOINT`, `ALPACA_KEY`, `ALPACA_SECRET_KEY`, `COINBASE_KEY_ID`, `COINBASE_KEY_NAME`, `COINBASE_ORG_ID`, `COINBASE_PRIVATE_KEY`, `KRAKEN_API_KEY`, `KRAKEN_API_SECRET`, `POLYGON_API_KEY`, `POLYGON_NAME`.
- Item `dashboard`: `DASHBOARD_ADMIN_KEY`, `DASHBOARD_ADMIN_PASSWORD`, `DASHBOARD_ADMIN_PASSWORD_HASH`, `DASHBOARD_ADMIN_USERNAME`, `DASHBOARD_READ_KEY`, `DASHBOARD_SESSION_SECRET`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.
- Item `billing`: `STRIPE_PUBLISHABLE_KEY`, `STRIPE_RESTRICTED_KEY`, `STRIPE_SECRET_KEY`.
- Item `data`: `CRYPTOPANIC_API_KEY`, `ES_API_KEY`.

### HumanDeliverables (What You Still Need To Acquire/Finalize)
1. `STRIPE_WEBHOOK_SECRET` and `STRIPE_PRICE_ID` for production billing flow completion.
2. Explicit decision and implementation of 1Password vault split/access model (separate domain vaults vs single `dev` vault with strict item ACL).
3. `SIGNAL_WEBHOOK_SECRET` value (if external signal ingestion is intended live).
4. Optional but recommended data-quality key: `COINGECKO_API_KEY` for richer ES enrichment coverage.
5. Final production ops decision on type-check policy (`mypy` debt burn-down timeline) before paid traffic scale-up.

### Honest Readiness Assessment
- **For controlled pilot traffic:** **Yes**, with guardrails. Core runtime and tests are stable locally, and this pass improved hot-path performance/resilience.
- **For aggressive paid acquisition at scale:** **Not fully yet**. Main blockers are typed-safety debt and a few production-config/procurement gaps (billing webhook/price IDs, secret governance structure).
- **Readiness score (pragmatic):** **7.5 / 10** for pilot, **5.5 / 10** for scale.

---

## CONTINUATION PASS (2026-02-21, release-prep follow-up)

### What Was Completed In This Follow-Up
1. **Signal webhook release guardrails tightened**
- `scripts/live_preflight.py` now fails when `webhooks.enabled=true` and `SIGNAL_WEBHOOK_SECRET` is missing.
- Added warning when signal webhooks are enabled without `allowed_sources`.
- Added regression test coverage in `tests/test_live_preflight.py`.

2. **Billing + enrichment env/config gaps closed**
- Added `STRIPE_WEBHOOK_SECRET`, `COINGECKO_API_KEY`, and `CRYPTOPANIC_API_KEY` to `.env.example`.
- Added Stripe env override mapping in `src/core/config.py`:
  - `BILLING_STRIPE_ENABLED`
  - `STRIPE_SECRET_KEY`
  - `STRIPE_WEBHOOK_SECRET`
  - `STRIPE_PRICE_ID`
  - `STRIPE_CURRENCY`
- Added regression test: `tests/test_billing_env_overrides.py`.

3. **Stocks scanner resilience fix**
- Fixed `asyncio.gather(..., return_exceptions=True)` handling in `src/stocks/swing_engine.py` to handle `BaseException` safely in parallel fetch path.

4. **Runtime typing contract cleanup**
- Updated `src/execution/executor.py` callback type annotation to match actual callback usage (`strategy`, `pnl`, `trend_regime`, `vol_regime`).

5. **Docs synchronized for release**
- Updated endpoint wiring + release checklist docs:
  - `docs/BILLING.md`
  - `docs/kb-internal/06-billing-tenancy.md`
  - `docs/kb-internal/09-testing-ci.md`
  - `docs/kb-internal/10-release-checklist.md`
  - `docs/kb-merged/09-billing-tenancy-security.md`
  - `docs/kb-merged/10-troubleshooting-operations-release.md`
  - `README.md`
  - `LiveRunbook.md`

6. **Billing plan tiers upgraded (free/pro/premium)**
- Added multi-plan Stripe price support:
  - `STRIPE_PRICE_ID_PRO`
  - `STRIPE_PRICE_ID_PREMIUM`
  - `STRIPE_PRICE_ID` retained as legacy fallback to pro.
- `POST /api/v1/billing/checkout` now accepts `plan` = `free|pro|premium`.
- `free` plan path now provisions tenant as `trialing` without Stripe checkout.
- Added regression coverage:
  - `tests/test_stripe_service_plans.py`
  - `tests/test_billing_checkout_plans.py`

### Fresh Validation Results (2026-02-21)
- `./venv/bin/python -m pytest -q` -> **136 passed**
- `./venv/bin/python scripts/walk_forward_gate.py` -> **PASS**
- `./venv/bin/python -m ruff check src/api/server.py src/execution/executor.py src/stocks/swing_engine.py scripts/live_preflight.py tests/test_live_preflight.py tests/test_executor_runtime_guards.py tests/test_ws_update_resilience.py tests/test_billing_env_overrides.py` -> **All checks passed**
- `./venv/bin/python -m mypy src tests` -> **289 errors in 37 files** (informational quality signal; still not release-blocking)

### Final Non-Stripe Remaining Human Inputs
1. 1Password topology decision: **resolved** as `single vault + strict item ACLs` for launch.
2. If signal webhooks will be used live, provide `SIGNAL_WEBHOOK_SECRET` value in runtime secrets.
3. Optional quality uplift: provide `COINGECKO_API_KEY` for richer enrichment coverage.

### Vault Decision Record (2026-02-21)
- Launch decision: keep a single vault model for speed.
- Mandatory control: enforce least-privilege item-level ACLs per service account.
- Runtime account should be read-only and restricted to required items only (trading/dashboard/billing/data keys used by NovaPulse runtime).
- `STRIPE_WEBHOOK_ENDPOINT` may be stored for operator reference, but runtime code currently consumes `STRIPE_SECRET_KEY`, `STRIPE_PRICE_ID`, and `STRIPE_WEBHOOK_SECRET`.
- Post-launch hardening target: migrate to split domain vaults (`trading`, `dashboard`, `billing`, `data`) after release window.
