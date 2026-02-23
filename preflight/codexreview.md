# Codex Codebase Review

## 0. Executive Summary
- Critical leak: a live-looking Elasticsearch API key is committed (`eskey`), and analytics is enabled to a cloud cluster by default.
- Data exfil risk: default config ships telemetry to an external Elastic host without an explicit opt-in or local fallback guard.
- Operational tooling bug: stress tester leaks API keys in URLs and cannot authenticate WebSocket checks when auth is required.
- Build health: full Python test suite passes (173 tests in ~4.4s); docker build is lean and non-root by default.
- Observability is strong (rate limits, auth, circuit breakers), but dependency pinning is only partial and repo includes vendored artifacts (`node_modules`, `venv`).
- Documentation and versioning drift (README v4.0 vs pyproject 4.1.1) may confuse operators.
- Verdict: **CONDITIONAL** — ship only after rotating the leaked ES key and disabling or re-scoping the default external telemetry target.

## 1. System Map
Components (flow left→right):
- Exchanges (Kraken/Coinbase REST+WS) → `MarketDataCache` (`src/exchange/market_data.py`) → `ConfluenceDetector` + strategy suite (`src/ai`, `src/strategies`) → `RiskManager` + `TradeExecutor` (`src/execution`) → SQLite ledger (`data/*.db`) [+ optional Elasticsearch mirror].
- Control plane: `DashboardServer` (FastAPI/WS, `src/api/server.py`) serves REST, WebSocket `/ws/live`, static dashboard; guarded by API keys/sessions/CSRF/rate limits.
- ML/AI: TFLite predictor (`src/ai/predictor.py`), ContinuousLearner, ModelTrainer/AutoRetrainer (`src/ml`), strategy tuner.
- Ops/Billing: Stripe service (`src/billing/stripe_service.py`), health/stress tooling (`scripts/health_check.sh`, `stress_test.py`), watchdog (`scripts/vps_watchdog.py`).
- Stocks swing engine (`src/stocks/swing_engine.py`) optional; orchestrated by `main.py` (single or multi-exchange hub).

Entrypoints & processes:
- `main.py` (bot lifecycle, dashboard, background tasks, instance lock).
- Docker: `Dockerfile`, `docker-compose.yml`, `SuperStart.sh`.
- Ops scripts: health_check, log_watch, vps_watchdog, stress_test.
- Backtest/optimize via `/api/v1/backtest/*`; signal intake via `/api/v1/signals/webhook`.

## 2. Findings (Prioritized)

### Security
- Hardcoded Elasticsearch API key in repo (SEVERITY: Critical)  
  Evidence: `eskey:1-2`.  
  Impact: Credential already exposed; anyone can write/read analytics cluster; potential data exfiltration and billing abuse.  
  Recommended fix: Rotate key immediately in Elastic Cloud; delete `eskey` from repo history; load via secret manager/.env only; add CI secret scan.  
  Estimated effort: S.  
  Suggested owner: Security/DevOps.

- External telemetry enabled by default (SEVERITY: High)  
  Evidence: `config/config.yaml:383-407` (`elasticsearch.enabled: true`, host points to Elastic Cloud).  
  Impact: On first boot, trade/orderbook data may stream to external host, violating data residency/PII expectations and failing in air‑gapped installs.  
  Recommended fix: Default `elasticsearch.enabled` to false unless `ES_API_KEY` is set; gate cloud hosts behind explicit `ELASTICSEARCH_ALLOW_CLOUD=1`; document.  
  Estimated effort: M.  
  Suggested owner: DevOps.

- API key leakage via stress tool URL (SEVERITY: Medium)  
  Evidence: `stress_test.py:125-144` appends `?api_key=` query; server expects header.  
  Impact: API keys land in shell history/proxies/logs; WS auth fails when reads are protected, giving false negatives.  
  Recommended fix: send `X-API-Key` header for WS, drop query param; redact key in logs.  
  Estimated effort: S.  
  Suggested owner: DevOps.

- Broad default CORS allowlist includes production public origin (SEVERITY: Medium)  
  Evidence: `src/api/server.py:892-919` always appends `DASHBOARD_PUBLIC_ORIGIN` defaulting to `https://nova.horizonsvc.com`.  
  Impact: If an operator disables read auth for dev, the public origin can legitimately load data cross-site; increases exposure surface.  
  Recommended fix: make public origin opt-in; warn when auth is off and origin != localhost.  
  Estimated effort: S.  
  Suggested owner: Security/Frontend.

### Correctness / Reliability
- Stress tester WebSocket check always fails when auth is on (SEVERITY: Medium)  
  Evidence: `stress_test.py:125-144` uses query param; server only reads `x-api-key` header in `/ws/live` (`src/api/server.py:3166-3202`).  
  Impact: Health runs report WS down even when healthy; weak signal during incidents.  
  Recommended fix: align client auth to header; add regression test.  
  Estimated effort: S.  
  Suggested owner: DevOps.

- External ES target failure silently disables analytics (SEVERITY: Low)  
  Evidence: `_init_observability` in `src/core/engine.py:904-960` logs warning then drops pipeline.  
  Impact: Operators may assume analytics is active when it is not; backtests/monitoring quietly lose data.  
  Recommended fix: add startup health gate that surfaces in `/api/v1/status` and Telegram alerts; optionally fail-fast in live mode.  
  Estimated effort: M.  
  Suggested owner: Backend/DevOps.

### Performance / Scalability
- Single SQLite lock with per-signal logging can choke under multi-engine + high scan cadence (SEVERITY: Medium)  
  Evidence: Global `asyncio.Lock` around all writes in `src/core/database.py:47-96`, frequent `log_thought` calls in main loops.  
  Impact: Head-of-line blocking on DB writes; WS/data loops may stall at high throughput or with many tenants.  
  Recommended fix: separate locks per table or use WAL reader/writer pools; batch thought logs; add perf counters.  
  Estimated effort: M.  
  Suggested owner: Backend.

### Maintainability
- Vendored artifacts in repo (`node_modules`, `venv`) (SEVERITY: Low)  
  Evidence: top-level `node_modules/`, `venv/`.  
  Impact: Bloats repo, hides supply-chain updates, slows CI.  
  Recommended fix: prune from git, enforce `.gitignore`, add clean task.  
  Estimated effort: S.  
  Suggested owner: DevOps.

- Version drift across docs (SEVERITY: Low)  
  Evidence: `README.md:1` shows v4.0 vs `pyproject.toml:6-7` version 4.1.1.  
  Impact: Operator confusion about feature set / migration notes.  
  Recommended fix: single source of truth (pyproject) and template README from it.  
  Estimated effort: S.  
  Suggested owner: Docs.

### Testing
- No automated coverage for `/ws/live` with auth on (SEVERITY: Medium)  
  Evidence: tests focus on REST/auth (`tests/*`) but no WS auth scenario; current stress bug slipped through.  
  Impact: WS regressions reach production unnoticed.  
  Recommended fix: add pytest-asyncio WS test that sets `X-API-Key` and asserts stream payload shape.  
  Estimated effort: M.  
  Suggested owner: Backend/QA.

- No regression test for Elastic pipeline health (SEVERITY: Low)  
  Evidence: missing tests around `_init_observability` branches.  
  Impact: changes to ES config can silently disable analytics.  
  Recommended fix: add unit test with fake ESClient capturing connect/fail paths; assert status surface.  
  Estimated effort: M.  
  Suggested owner: Backend/QA.

### Docs / Ops
- No runbook for Elastic key rotation / cloud disablement (SEVERITY: Medium)  
  Evidence: README lacks rotation steps; sensitive key already leaked.  
  Impact: Operators may reuse compromised key or leave telemetry on unintentionally.  
  Recommended fix: add rotation + opt-out steps to README/ops docs; bake into SuperStart prompts.  
  Estimated effort: S.  
  Suggested owner: DevOps/Docs.

- Stress/health tooling doesn’t document required auth headers (SEVERITY: Low)  
  Evidence: `stress_test.py` and README sections omit header guidance.  
  Impact: false negatives and key leakage risk.  
  Recommended fix: update docs and scripts to prefer headers.  
  Estimated effort: S.  
  Suggested owner: DevOps/Docs.

## 3. Quick Wins (Do these first)
- Rotate and remove committed ES key (`eskey`).  
- Default `elasticsearch.enabled` to false unless `ES_API_KEY` is set (`config/config.yaml:383-388`).  
- Fix stress tester to send `X-API-Key` header and drop query param (`stress_test.py:125-144`).  
- Add warning when auth is disabled but public origin is non-localhost (`src/api/server.py:892-919`).  
- Surface ES connection status in `/api/v1/status` response (`src/api/server.py:1446-1525`).  
- Prune `node_modules/` and `venv/` from repo; keep `.gitignore` entries (`.gitignore`, repo root).  
- Align README version banner with `pyproject` (`README.md:1`, `pyproject.toml:6-7`).  
- Add small pytest for WS auth path using `X-API-Key` (`tests/` new).  
- Fail fast when `DASHBOARD_ADMIN_PASSWORD_HASH` is missing in live mode (additional guard in `src/api/server.py:set_bot_engine`).  
- Add CI secret scan step (e.g., gitleaks) to catch future key commits.

## 4. Strategic Refactors (High leverage)
- Externalize analytics sink: pluggable observability interface (ES, S3, none) with opt-in flags and per-tenant routing; avoids accidental cloud exfiltration.  
- Move correlation groups and limits from hardcoded executor state to config with per-asset-class defaults; improves controllability for new pairs.  
- Introduce per-table connection pooling in SQLite or migrate to lightweight Postgres with WAL + async pool; unlocks higher scan cadence and multi-tenant throughput.  
- Consolidate config into a single Pydantic settings object with strict validation and runtime reload; reduce env/YAML divergence.  
- Add a unified health surface (REST+WS) that reports subsystem degradation (ES, WS, crypto_universe) and gates trading if critical dependencies fail in live mode.  
- Split dashboard frontend build from repo (ditch tracked node_modules) and add a reproducible build script; shrink attack surface and simplify updates.  
- Package bot as a Python wheel with entrypoints for bot, stress, health scripts; simplifies deployments and version pinning.

## 5. Test Plan Improvements
- WS auth regression test (header-based) and payload shape contract.  
- ES pipeline connect/fail unit tests with fake client; assert status surfacing.  
- Signal webhook signature tests covering timestamp skew and duplicate idempotency.  
- Multi-engine regression: verify shared-DB vs split-DB behavior (`_engines_share_db`) and per-tenant isolation.  
- Stress/health scripts golden tests to prevent key-in-URL regressions.  
- Backtest/optimize endpoints integration test with minimal in-memory data to ensure tuner paths stay working.

## 6. Dependency & Supply Chain Notes
- Python deps partially pinned (e.g., `tensorflow>=2.16.2,<2.21`, `pandas>=2.2,<3`); builds are non-deterministic across patch releases. Consider pip-compile lockfiles.  
- Node side only lists `bcrypt` but a full `node_modules/` is present—remove and rebuild to avoid stale transitive deps.  
- Secret exposure already occurred (ES key); add automated secret scanning and enforce pre-commit hooks.  
- Docker uses Python 3.11; pyproject allows up to 3.13—ensure CI covers both to catch ABI drift.

## 7. Appendix
- Commands attempted:  
  - `python -m pytest tests/test_core.py -q --maxfail=1` (pass, 63 tests).  
  - `python -m pytest -q --maxfail=1` (pass, 173 tests in 4.41s).  
- Assumptions: no live exchange keys available; did not execute live trading; ES cloud host not reachable during review.

## 8. Strategy & Scan Improvement Suggestions (10)
1) Category A — Add minimum order-book depth filter  
   - Change: Introduce `min_depth_usd` parameter to `strategies.order_flow` and enforce in `src/strategies/order_flow.py` before signaling.  
   - Where: `config/config.yaml` under `strategies.order_flow`; code in `order_flow.py` analyze.  
   - Rationale: Filters thin books where imbalance is noise, reducing slippage-driven losers; better regime fit in low-liquidity hours.  
   - Validation: Backtest last 90 days with depth thresholds (e.g., $50k/$100k); track win-rate, average slippage, max drawdown, turnover.  
   - Risk/Tradeoff: Fewer signals on minor alts; may miss early moves in new listings.

2) Category B — Tighten volatility squeeze confirmation  
   - Change: Raise `min_squeeze_bars` from 3→5 and require positive momentum slope before entry.  
   - Where: `config/config.yaml:144-153`; logic in `src/strategies/volatility_squeeze.py`.  
   - Rationale: Longer squeeze reduces false breakouts in choppy regimes; momentum slope avoids fading dead squeezes.  
   - Validation: Backtest squeeze strategy standalone; compare expectancy and win-rate; monitor drawdown/turnover deltas.  
   - Risk/Tradeoff: Later entries; may miss fastest breakouts.

3) Category C — Configurable correlation limits  
   - Change: Expose `_correlation_groups` and `_max_per_correlation_group` as config (e.g., `risk.correlation_groups`, `risk.max_per_group`) and consume in `TradeExecutor`.  
   - Where: `src/execution/executor.py` and `config/config.yaml` (`risk` section).  
   - Rationale: Prevent clustering across highly correlated L1s; improves portfolio heat control.  
   - Validation: Simulate with/without new caps; metrics: exposure per group, max drawdown, Sharpe.  
   - Risk/Tradeoff: Lower concurrency; potential missed diversified gains if groups misclassified.

4) Category B — Raise solo-entry confidence for Keltner  
   - Change: Increase `ai.keltner_solo_min_confidence` to ~0.60 (currently 0.55) while keeping multi-strategy threshold unchanged.  
   - Where: `config/config.yaml:185-188`.  
   - Rationale: Reduces single-strategy false positives when confluence is low; better risk-adjusted expectancy.  
   - Validation: Replay recent month with/without change; track solo trade win-rate and PF.  
   - Risk/Tradeoff: Fewer trades; might underutilize proven Keltner edge if confidence calc is conservative.

5) Category A — Add weekend/illiquid quiet hours schedule  
   - Change: Populate `trading.quiet_hours_utc` with weekend low-liquidity windows (e.g., Sat/Sun 00:00–06:00 UTC) and enforce in executor gating.  
   - Where: `config/config.yaml` `trading.quiet_hours_utc`; gating already respected in `TradeExecutor`.  
   - Rationale: Crypto liquidity and spreads worsen on weekends; reduces whipsaws.  
   - Validation: Backtest with quiet hours vs none; metrics: win-rate, drawdown, exposure.  
   - Risk/Tradeoff: Miss occasional high-vol weekend trends.

6) Category B — Stricter strategy guardrails  
   - Change: Increase `ai.strategy_guardrails_min_profit_factor` to ≥1.0 and window to 50 trades before re-enable; adjust disable minutes if needed.  
   - Where: `config/config.yaml:190-195`.  
   - Rationale: Faster off-boarding of negative-expectancy strategies improves portfolio PF.  
   - Validation: Simulate guardrail toggles; metrics: number of disabled events, PF, drawdown.  
   - Risk/Tradeoff: Could sideline strategies during short slumps; requires monitoring.

7) Category A — ATR floor for reversal entries  
   - Change: Add `min_atr_pct` to `strategies.reversal` to skip signals when volatility is too low for targets to clear costs.  
   - Where: `config/config.yaml` under `strategies.reversal`; code in `src/strategies/reversal.py`.  
   - Rationale: Avoid micro-range reversals that fail to cover fees/slippage; reduces churn.  
   - Validation: Backtest varying floor (e.g., 0.5%/1%); metrics: win-rate, PF, turnover.  
   - Risk/Tradeoff: Fewer trades in calm markets; may miss early volatility expansions.

8) Category C — Dynamic confluence threshold by volatility regime  
   - Change: Allow `ai.confluence_threshold` to step up to 3 when `volatility_regime` == “high”; add config knob and branch in `ConfluenceDetector`.  
   - Where: `src/ai/confluence.py`; `config/config.yaml:172-195`.  
   - Rationale: In high vol, requiring an extra agreeing strategy can cut false positives; aligns with noise level.  
   - Validation: Backtest segmented by ATR percentile; compare high-vol performance with threshold 2 vs 3 (win-rate, expectancy, drawdown).  
   - Risk/Tradeoff: May under-trade strong trends if signals disagree.

9) Category B — Order-flow spread gate tied to pair liquidity  
   - Change: Scale `strategies.order_flow.spread_tight_pct` by average pair spread (stored in market data) instead of fixed 0.10%; add per-pair override in config.  
   - Where: `order_flow.py` and `MarketDataCache` for spread stats; `config/config.yaml:120-124`.  
   - Rationale: Normalizes entry filter across pairs; reduces bias toward majors only.  
   - Validation: Backtest majors vs alts with adaptive gate; metrics: win-rate, slippage, turnover.  
   - Risk/Tradeoff: Slight complexity; if stats stale, could mis-set thresholds.

10) Category A — Session-aware risk scaling  
   - Change: Extend `ai.session` to feed a multiplier into `RiskManager` sizing (e.g., scale Kelly fraction by hour-of-day win-rate).  
   - Where: `config/config.yaml:196-200`; implement hook in `TradeExecutor` sizing path.  
   - Rationale: Uses observed session performance to de-risk weak hours, improving drawdown control.  
   - Validation: Backtest with session weights vs flat; metrics: equity curve variance, max drawdown, turnover.  
   - Risk/Tradeoff: Requires stable session stats; misestimation could under-size good hours.
