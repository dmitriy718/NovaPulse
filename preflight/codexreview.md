# Codex Codebase Review

## 0. Executive Summary
- ES analytics now default to OFF and require a key; `/api/v1/status` reports ES connectivity.
- WS auth hardened: stress tester uses headers; new tests cover `/ws/live`; CORS public origin is opt-in with warnings when reads are unauthenticated.
- Strategy/risk improvements shipped (depth floor, adaptive spread, high-vol confluence, guardrails, ATR floor, quiet hours, session-aware sizing).
- README version aligned; secret-scan helper added (`scripts/secret_scan.sh`); full test suite now 175 passing.
- Remaining caution: historical ES key still exists in repo history; rely on 1Password and run the scan script before releases.
- Verdict: **CONDITIONAL** — safe to ship with vault-managed secrets and explicit ES enablement.

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
- Hardcoded ES key in history (SEVERITY: Critical, partially mitigated) — `eskey` exists historically; runtime uses env/1Password. Added `scripts/secret_scan.sh`; rotate ES key and keep vault-only distribution. Owner: Security/DevOps.
- External telemetry default off (RESOLVED, was High) — `config/config.yaml` now `elasticsearch.enabled: false`; engine requires API key. Owner: DevOps.
- Stress tool API key leak (RESOLVED, Medium) — header auth in `stress_test.py`; regression tests added. Owner: DevOps.
- Public origin auto-allow (RESOLVED, Medium) — public origin now opt-in; warning when reads unauthenticated (`src/api/server.py`). Owner: Security/Frontend.

### Correctness / Reliability
- WS health false negatives (RESOLVED, Medium) — header auth fix + tests (`stress_test.py`, `tests/test_ws_auth_header.py`).
- ES pipeline silent disable (PARTIAL, Low) — ES status exposed in `/api/v1/status`; still best-effort start without fail-fast. Owner: Backend/DevOps.

### Performance / Scalability
- DB lock contention risk (UNCHANGED, Medium) — global SQLite lock remains; consider per-table locks/batching later. Owner: Backend.

### Maintainability
- Vendored artifacts (Low) — repo clean; `.gitignore` covers; no change needed. Owner: DevOps.
- Version drift (RESOLVED, Low) — README now 4.1.1. Owner: Docs.

### Testing
- WS auth coverage added (RESOLVED, Medium) — `tests/test_ws_auth_header.py`.
- ES status surfaced in tests (RESOLVED, Low) — `tests/test_es_queue_metrics.py`.

### Docs / Ops
- Secret scan helper added (Medium) — `scripts/secret_scan.sh`; rely on vault-managed secrets; optional history scrub. Owner: DevOps/Docs.
- Stress tooling header guidance now implicit in code; README update optional. Owner: DevOps/Docs.

## 3. Quick Wins (Do these first)
- ES default off + key guard — `config/config.yaml`, `src/core/engine.py`
- Stress tester header auth fixed — `stress_test.py`
- Warning on unauthenticated reads + public origin — `src/api/server.py`
- ES status surfaced in status endpoint — `src/api/server.py`, `tests/test_es_queue_metrics.py`
- README version aligned — `README.md`
- WS auth regression test added — `tests/test_ws_auth_header.py`
- Secret scan helper script — `scripts/secret_scan.sh`
- Order-flow depth/adaptive spread — `src/strategies/order_flow.py`, `config/config.yaml`, `src/core/config.py`
- Volatility squeeze tightening — `src/strategies/volatility_squeeze.py`, `config/config.yaml`
- Guardrails stricter — `src/core/config.py`, `config/config.yaml`
- Quiet hours configured — `config/config.yaml`
- Reversal ATR floor — `src/strategies/reversal.py`, `config/config.yaml`
- Correlation caps configurable — `src/execution/executor.py`, `src/core/config.py`, `config/config.yaml`
- Session-aware sizing — `src/execution/risk_manager.py`, `src/execution/executor.py`, `src/core/engine.py`
- High-vol confluence threshold — `src/ai/confluence.py`, `config/config.yaml`

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
  - `python -m pytest -q --maxfail=1` (pass, 175 tests in ~4.4s).  
  - Installed `uvicorn[standard]==0.34.0` into venv (zsh quoting fixed).  
  - Backed up and reset ledger: `cp data/trading.db data/trading.db.bak-YYYYmmddThhmmssZ`; cleared `trades`, `metrics`, `signals`, `order_book_snapshots`, `ml_features`, `thought_log`, `system_state`, `daily_summary` (now zero rows).  
  - Installed `elasticsearch[async]>=8.12,<9` into venv; added guard to skip ES pipeline when API key is unresolved `op://` placeholder (prevents 401 spam when 1Password isn’t loaded).  
  - Restarted bot in paper mode with `timeout 20s python main.py` (and with `INSTANCE_LOCK_PATH=/tmp/novapulse/test.lock` for verification) to reinitialize loops; warmup succeeded; WebSocket connected; shutdown clean on timeout. Background warnings remain: Telegram token rejected (expects 1Password), ES pipeline now cleanly disabled with placeholder warning only.  
  - Restored ledger from `data/trading.db.bak-20260224T020327Z` (5 open trades + metrics) after prior reset; archived post-reset copy at `data/trading.db.after-reset-<ts>`.  
  - Added Telegram guard: if token/chat_id are unresolved `op://` placeholders, bot disables itself with a warning (prevents repeated init failures when 1Password isn’t injected yet).  
  - Re-ran `python -m pytest -q --maxfail=1` after changes (pass, 175 tests).  
- Log analysis (2026-02-24): `logs/errors.log` shows early restarts from missing `uvicorn`; `logs/trading_bot.log` only shows ES bulk writes and graceful shutdown at 06:08Z on 2026-02-20; no trade lifecycle logs. Previously `data/trading.db` held 5 open short trades (XRP/USD, ADA/USD, SOL/USD, ETH/USD, LINK/USD) from 2026-02-19 with no closes, driving 0% win rate and –$21 unrealized P/L; that ledger has been restored from backup (5 open trades present again).  
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
