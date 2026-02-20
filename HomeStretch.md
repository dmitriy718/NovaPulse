# NovaPulse Home Stretch Review

Date: 2026-02-20
Scope: Full codebase sweep (backend, frontend, crypto, stocks, ops scripts, config) with line-referenced findings and v4.0 plan.

## Review Method
- Read core runtime, API, strategy, execution, data, stocks, UI, and ops scripts.
- Validated current test baseline with `pytest -q`.
- Result: `93 passed in 3.40s` (1 warning from `pytest-asyncio` about unset fixture loop scope).

## Executive Summary
- The main technical blocker is architecture mismatch in persistence expectations: runtime truth is SQLite-per-engine/account, while Elasticsearch is currently best-effort enrichment/mirroring, not the primary ledger.
- Multi-account routing has a concrete correctness bug in chart engine resolution when scanner labels include `exchange:account`.
- Stock live execution has a high-risk state-sync gap that can create orphan broker positions.
- Frontend and API are in generally strong shape, but a few correctness/security issues need closure before v4.0 freeze.

## Section Review

### 1) Data & Persistence

#### HS-001 (P0) Source-of-truth mismatch (SQLite primary, ES secondary)
- Evidence:
  - `src/core/database.py:50` (`DatabaseManager` is SQLite)
  - `src/core/engine.py:420` (bot initializes SQLite DB as critical subsystem)
  - `src/execution/executor.py:1111` (ES trade writes are non-blocking mirror events)
- Impact:
  - Local host process and Docker process can show different trade history if DB paths/mounts differ.
  - ES cannot currently be treated as canonical trading ledger.
- Required for v4.0:
  - Decide and enforce single source of truth (recommended: SQL ledger canonical, ES analytics-only).

#### HS-002 (P0) Cross-account chart/engine misrouting bug
- Evidence:
  - Scanner labels include account: `src/api/server.py:1553`.
  - Frontend parses parenthesized token as `exchange`: `static/js/dashboard.js:309`.
  - Engine resolver expects plain exchange name: `src/api/server.py:416`.
- Impact:
  - `kraken:main` will not match `exchange_name == kraken`; resolver can fall back to wrong engine.
  - Wrong account context for chart/backtest requests when pairs overlap across accounts.

#### HS-003 (P1) ES enqueue buffer can silently drop oldest docs under pressure
- Evidence:
  - `deque(maxlen=buffer_maxlen)`: `src/data/es_client.py:203`
  - `append` with no drop telemetry: `src/data/es_client.py:328`
- Impact:
  - Data loss in analytics/training stream during bursts with no explicit alert.

#### HS-004 (P1) Runtime/docs ambiguity: local ES service + cloud ES config
- Evidence:
  - Compose runs local ES: `docker-compose.yml:63`
  - App config points to cloud host: `config/config.yaml:350`
- Impact:
  - Operators can mistakenly assume both environments are writing to same ES target.

#### HS-005 (P1) Ops health script only inspects first resolved exchange DB
- Evidence:
  - Uses `resolve_exchange_names` and first name path: `scripts/health_check.sh:126`, `scripts/health_check.sh:133`
- Impact:
  - In multi-account/multi-exchange mode, health output can hide failing account DBs.

### 2) Crypto Engine

#### HS-006 (P1) Multi-engine critical loops are not marked critical
- Evidence:
  - Single-engine mode marks critical loops with `critical=True`: `main.py:331`
  - Multi-engine mode does not: `main.py:511`
- Impact:
  - Repeated failures in scan/ws/position loops won’t trigger auto-pause guard in multi-engine mode.

#### HS-007 (P2) Aggregated Sharpe/Sortino may mislead in multi-engine mode
- Evidence:
  - Uses first engine metrics for Sharpe/Sortino pass-through: `src/api/server.py:306`
- Impact:
  - Dashboard risk ratios can misrepresent total portfolio quality.

### 3) Stocks Engine

#### HS-008 (P0) Live order fill-sync gap can create orphan broker positions
- Evidence:
  - Live open requires immediate fill qty; otherwise treated as rejected: `src/stocks/swing_engine.py:341`
  - Alpaca client returns accepted order even when not yet filled after short poll: `src/stocks/alpaca_client.py:74`
- Impact:
  - Broker can fill after the bot has already abandoned local trade creation.
  - Local DB and broker positions diverge (high operational risk).

#### HS-009 (P1) No startup reconciliation against broker open positions
- Evidence:
  - Stock engine initializes DB/clients only: `src/stocks/swing_engine.py:202`
  - Alpaca client does not expose/list open positions endpoint in current adapter.
- Impact:
  - Restart after interruption can miss already-open live positions.

#### HS-010 (P1) Stock strategy stats are placeholders for win rate/avg pnl
- Evidence:
  - Hardcoded `win_rate: 0.0`, `avg_pnl: 0.0`: `src/stocks/swing_engine.py:494`
- Impact:
  - Strategy monitor misleads operator decisions.

#### HS-011 (P2) Stock close accounting omits fees/slippage
- Evidence:
  - `fees=0.0` on close: `src/stocks/swing_engine.py:432`
- Impact:
  - Reported stock PnL optimistic vs real brokerage fills/costs.

### 4) Trading Backend (API / Control / Backtesting)

#### HS-012 (P1) Backtest likely double-counts execution friction
- Evidence:
  - `slippage_pct` and `fee_pct` both set from taker fee: `src/api/server.py:2003`
- Impact:
  - Backtest quality metrics are biased pessimistic and inconsistent with live fill model.

#### HS-013 (P1) Slack command handlers can fail event-loop lookup in callback threads
- Evidence:
  - `asyncio.get_event_loop()` used inside Bolt handlers: `src/utils/slack_bot.py:75`, `src/utils/slack_bot.py:87`, `src/utils/slack_bot.py:99`, `src/utils/slack_bot.py:119`, `src/utils/slack_bot.py:149`, `src/utils/slack_bot.py:171`
- Impact:
  - Intermittent control command failures in production thread contexts.

### 5) Trading Frontend

#### HS-014 (P1) Positions table inserts unescaped pair/side via `innerHTML`
- Evidence:
  - Raw interpolation of `pos.pair`/`pos.side`: `static/js/dashboard.js:197`
- Impact:
  - XSS risk if untrusted symbol strings ever enter payloads.

#### HS-015 (P2) Exchange label parsing conflates exchange and account in scanner UI
- Evidence:
  - Parser stores full token as exchange: `static/js/dashboard.js:315`
- Impact:
  - UI state and backend routing ambiguity across multi-account scanners.

### 6) UX / UI

#### HS-016 (P2) Stock market state uses static schedule, no holiday calendar
- Evidence:
  - Time-only logic in JS: `static/js/dashboard.js:319`
- Impact:
  - Market status badge may be wrong on market holidays/half-days.

### 7) Test & Quality

#### HS-017 (P2) Async test loop scope warning should be fixed before freeze
- Evidence:
  - `pytest-asyncio` warning during test run.
- Impact:
  - Future plugin default changes can cause test behavior drift.

## Prioritized Fix Queue (Execution Order)
1. HS-001 (persistence contract and single source of truth enforcement)
2. HS-008 (stock live order reconciliation and orphan-position prevention)
3. HS-002 + HS-015 (multi-account exchange/account routing normalization)
4. HS-006 (critical loop handling parity for multi-engine)
5. HS-012 (backtest friction model correction)
6. HS-013 (Slack loop handling hardening)
7. HS-014 (frontend escaping hardening)
8. HS-009 + HS-011 (stock startup reconciliation and true net PnL)
9. HS-003 + HS-005 + HS-004 (observability/ops reliability fixes)
10. HS-007 + HS-010 + HS-016 + HS-017 (metrics/UI/testing polish)

## Plan to Finalized Product (v4.0)

### Phase A: Core Correctness (must-pass)
- Lock persistence model: canonical ledger + explicit analytics sink role.
- Fix account-aware routing contract (`exchange`, `account_id` as separate fields end-to-end).
- Add startup and periodic broker reconciliation jobs (crypto + stocks).
- Prevent orphan orders by tracking accepted-but-not-filled lifecycle.
- Acceptance gate:
  - No cross-account route bleed in chart/backtest/control.
  - Restart-safe position parity with broker/exchange.

### Phase B: Safety & Operations
- Make multi-engine critical loops auto-pause on repeated failures.
- Add explicit data-loss counters for ES queue overflow.
- Upgrade health checks to account-level reporting.
- Acceptance gate:
  - Fault-injection test confirms auto-pause in both single and multi-engine modes.
  - Health output lists every active account/exchange.

### Phase C: Product Reliability
- Harden API/UI sanitization and control-plane command robustness.
- Fix stock strategy reporting to real computed stats.
- Correct backtest execution-cost modeling.
- Acceptance gate:
  - Backtest/live parity checks within tolerance band.
  - UI shows accurate per-strategy and per-account stats.

### Phase D: v4.0 Release Candidate
- Freeze config schema.
- Run full regression suite + 7-day soak on paper/sandbox.
- Produce operator runbooks and rollback scripts.
- Tag and ship `v4.0.0`.

## Human Deliverables

### Accounts, APIs, and Vendor Access
- Final production API credentials for Kraken and Coinbase (separate per account profile if multi-account).
- Polygon plan with required real-time/historical depth for stock scan/chart workload.
- Alpaca production account approval + live trading permissions (if moving from paper).
- Stripe production setup (product, price IDs, webhook endpoint secret) for subscriptions.

### Infrastructure & Services
- Production hosting target(s) and environment inventory (primary + backup node recommended).
- Centralized log/metric destination decision (self-hosted or SaaS) and account access.
- Backup storage destination for DB snapshots and release snapshots.

### Domain & Product Assets
- Production domain/DNS control for dashboard and subscription site.
- Final brand assets used in UI/share surfaces (icons, watermark variants if needed).

### Operational Inputs (Needed to Complete Engineering)
- Final account matrix to support in v4 (`account_id:exchange` list).
- Canonical persistence decision approval (SQL-ledger-first vs ES-ledger-first).
- Approved release checklist owner and on-call owner for v4 cutover window.

## Current Readiness Snapshot
- Test baseline: green (`93/93`).
- Architecture baseline: functional but not v4-final due P0/P1 items above.
- Recommended v4 target condition: all P0 + P1 closed, 7-day soak complete, reconciliation proven across restart scenarios.
