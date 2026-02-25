# Changelog

All notable changes to NovaPulse are documented in this file.

---

## v5.0.0 (2026-02-25) — Advanced Intelligence Suite

Major release adding 10 new advanced features: macro event calendar, cross-pair lead-lag intelligence, regime transition prediction, on-chain data integration, structural stop loss placement, liquidity-aware position sizing, anomaly detection circuit breaker, P&L attribution dashboard, ensemble ML model, and Bayesian hyperparameter optimization. All features default to `enabled: false` for backward compatibility.

### New Features

**Signal Intelligence**
- **Macro Event Calendar** — auto-pauses trading during FOMC/CPI/NFP blackout windows; static JSON schedule + optional Polygon earnings fetch; `GET /api/v1/events` endpoint
- **Cross-Pair Lead-Lag Intelligence** — monitors BTC/ETH leader moves and adjusts follower altcoin confidence by -0.10 to +0.15 based on correlation and move magnitude; `GET /api/v1/lead-lag` endpoint
- **Regime Transition Prediction** — anticipates range-to-trend and trend-to-range transitions using squeeze duration, ADX slope, volume trend, and choppiness analysis; boosts trend strategy confidence during "emerging_trend"; `GET /api/v1/regime` endpoint
- **On-Chain Data Integration** — fetches blockchain sentiment signals (exchange flows, stablecoin supply, large txns); applies +/- 0.08 confidence adjustment for aligned/opposing signals; `GET /api/v1/onchain` endpoint

**Risk Management**
- **Structural Stop Loss Placement** — places stops behind recent swing highs/lows instead of fixed ATR multiples; reuses MarketStructureStrategy swing detection; min 0.5x ATR buffer, max 4x ATR distance; `GET /api/v1/structural-stops` endpoint
- **Liquidity-Aware Position Sizing** — reduces position size when order book depth is thin relative to trade size; configurable max impact % and min depth ratio; `GET /api/v1/liquidity` endpoint

**Monitoring & Analytics**
- **Anomaly Detection Circuit Breaker** — detects spread spikes (3x), volume anomalies (5x), correlation anomalies (>60% same direction), and depth drops (>50%); auto-pauses trading for configurable cooldown; `GET /api/v1/anomalies` endpoint
- **P&L Attribution Dashboard** — records strategy, regime, volatility, session, and confluence metadata per trade; query by strategy/regime/pair/date with `GET /api/v1/attribution`

**Machine Learning**
- **Ensemble ML Model** — combines existing TFLite predictor with LightGBM binary classifier; weighted average (configurable 40/60 split); graceful fallback when either model unavailable; `GET /api/v1/ensemble` endpoint
- **Bayesian Hyperparameter Optimization** — Optuna-based TPE optimization of confluence_threshold, min_confidence, trailing_activation, risk params; supports sharpe_ratio/profit_factor/calmar_ratio metrics; `GET /api/v1/optimizer` + `/optimizer/history` endpoints

### Dashboard
- New **Advanced Features** panel showing real-time status of all 10 features (enabled/disabled, blackout state, regime, training status, etc.)
- 5 new REST API endpoints: `/api/v1/lead-lag`, `/api/v1/regime`, `/api/v1/onchain`, `/api/v1/structural-stops`, `/api/v1/liquidity`
- Feature status streamed via WebSocket for real-time dashboard updates
- Settings modal now includes feature toggle visibility
- Version bumped to v5.0 in header

### New Files (17)
- `src/utils/event_calendar.py`, `data/events/macro_events.json`
- `src/ai/lead_lag.py`, `src/ai/regime_predictor.py`, `src/ai/ensemble_model.py`, `src/ai/bayesian_optimizer.py`
- `src/exchange/onchain_data.py`
- `src/execution/anomaly_detector.py`
- Tests: `test_event_calendar.py`, `test_lead_lag.py`, `test_regime_predictor.py`, `test_onchain_data.py`, `test_structural_stop.py`, `test_liquidity_sizing.py`, `test_anomaly_detector.py`, `test_ensemble_model.py`, `test_bayesian_optimizer.py`, `test_strategy_attribution.py`, `test_feature_integration.py`

### New DB Tables
- `strategy_attribution` — per-trade P&L attribution records with strategy/regime/session metadata
- `anomaly_events` — anomaly detection event log

### New Dependencies
- `lightgbm>=4.0.0,<5` (optional — ensemble ML)
- `optuna>=3.5.0,<4` (optional — Bayesian optimization)

### Config
- 10 new config models: `EventCalendarConfig`, `LeadLagConfig`, `RegimePredictorConfig`, `OnChainConfig`, `StructuralStopConfig`, `LiquiditySizingConfig`, `AnomalyDetectorConfig`, `EnsembleMLConfig`, `BayesianOptimizerConfig`
- All nested under existing sections (ai, risk, monitoring, event_calendar)
- All default to `enabled: false` — zero behavior change when upgrading

### Testing
- Test suite: 319 passed, 20 skipped (up from 175)
- 20 skips are for optional dependency tests (lightgbm: 9, optuna: 11)
- 11 cross-feature integration tests validating feature interactions

---

## v4.5.0 (2026-02-24) — Strategy Expansion & Adaptive Intelligence

The largest single release since v4.0. Implements all recommendations from Deep Review #4: three new strategies expanding the portfolio to 12, adaptive exit intelligence, correlation-aware sizing, and cross-engine risk aggregation. Jumped from v4.1.1 directly to v4.5.0 to reflect the scope.

### New Strategies
- **VWAP Momentum Alpha** (weight 0.15) — activated from dormant module; trades pullbacks to VWAP in trending markets with volume and slope confirmation
- **Market Structure** (weight 0.12) — new `src/strategies/market_structure.py`; detects higher-highs/higher-lows (uptrend) and lower-highs/lower-lows (downtrend) via swing point analysis, enters on pullbacks to previous swing levels
- **Funding Rate** (weight 0.10) — new `src/strategies/funding_rate.py` + `src/exchange/funding_rates.py`; exploits perpetual futures funding rate extremes from Kraken Futures public API (5-min TTL cache, no auth required)

### Strategy Modifications
- **Trend Following**: now requires fresh EMA cross (`require_fresh_cross: true`) — prevents constant re-signaling throughout trends; weight reduced 0.15 → 0.08
- **Order Flow**: relaxed higher-lows confirmation from 4 consecutive to 2-of-3 — fires more often with meaningful structure
- **Weight rebalancing**: all 12 strategies rebalanced (Keltner 0.25, Mean Reversion 0.20, Vol Squeeze 0.18, VWAP 0.15, Order Flow 0.12, Market Structure 0.12, Supertrend 0.12, Funding Rate 0.10, Trend 0.08, Ichimoku 0.08, Stochastic Divergence 0.06, Reversal 0.06)

### Confluence Improvements
- **Opposition penalty** strengthened: 0.04/0.12 → 0.07/0.25 (opposing signals now carry real cost)
- **Regime multiplier cap**: `min(mult, 2.0)` prevents runaway stacking in favorable regimes
- **Strategy family diversity scoring**: 3+ unique families among agreeing signals → +0.05 confidence bonus; all same family → -0.05 penalty. Families: mean_reversion, trend_following, momentum, microstructure, vwap, structure, sentiment

### Adaptive Exit Intelligence
- **Smart exit enabled** (`enabled: true` in config) — multi-tier partial position closing now active
- **Time-based exit tightening**: positions held >30 min with <0.5% profit → TP reduced to 60%; >60 min with <1.0% → TP reduced to 40%
- **Volatility-regime-aware trailing stops**: `high_vol` → trailing step ×1.5 (more room); `low_vol` → ×0.7 (tighter)

### Risk Management
- **Correlation-based position sizing**: rolling 100-price Pearson correlation per pair; corr > 0.7 with existing positions → size reduced by `max(0.5, 1 - (corr - 0.7) * 2)`
- **Cross-engine risk aggregation**: new `GlobalRiskAggregator` singleton (`src/execution/global_risk.py`) tracks total exposure across Kraken + Coinbase + Stocks engines; each engine's `RiskManager._get_remaining_capacity()` checks both local and global caps

### Config
- 3 new config models: `VWAPMomentumAlphaConfig`, `MarketStructureConfig`, `FundingRateConfig`
- `TrendConfig` gains `require_fresh_cross: bool = True`
- All 4 regime multiplier dicts updated with entries for new strategies
- New strategy cooldown entries

### Infrastructure
- New files: `src/strategies/market_structure.py`, `src/strategies/funding_rate.py`, `src/exchange/funding_rates.py`, `src/execution/global_risk.py`
- Test suite: 175 tests passing (up from 154)
- All `py_compile` checks pass, no circular imports

---

## v4.1.1 (2026-02-22) — Cross-Exchange ML & Telemetry

### Features
- Cross-exchange ML training: leader engine aggregates training data from all exchange DBs
- Entry-time telemetry: precise timing metrics for signal-to-execution latency
- ML feature backfill for historical trades missing feature vectors
- Elasticsearch status surfaced in `/api/v1/status` endpoint

### Fixes
- Sync version string to 4.1.1 across all sources (was inconsistent)
- Exclude permanently invalid Coinbase pairs (USDC/USD, TRX/USD, XAUT/USD) from REST poll and stale checks
- Correct previous trading day calculation for Monday in Polygon grouped bars (offset=3→Friday, was offset=1→Sunday)
- Make public dashboard origins opt-in and warn when unauthenticated
- Use header auth for stress-test websocket check
- Disable Elasticsearch unless explicitly configured

---

## v4.1.0 (2026-02-21) — Dynamic Universe Scanners & Win-Rate Improvements

### Features
- Dynamic stock universe scanner: Polygon grouped daily bars → volume/price filter → top 96 symbols
- 4 pinned stocks (AAPL, MSFT, NVDA, TSLA) + 92 dynamic, refreshed hourly during market hours
- Kraken WS v2 migration complete
- Session performance multiplier for position sizing
- Pair-specific liquidity adaptation for order-flow spread gates
- Configurable correlation limits via risk settings
- Higher confluence threshold in high-vol regimes

### Strategy Tuning
- Keltner solo confidence floor raised
- Volatility squeeze: longer squeeze requirement + momentum slope gate
- Reversal: ATR floor added
- Order flow: configurable depth floor
- Strategy guardrails window tightened

### Fixes
- Aligned displayed equity with realized P&L
- WebSocket auth regression tests added

---

## v4.0.0 (2026-02-19) — Strategy Overhaul

The biggest architectural change since v3.0. Complete strategy portfolio replacement, new analysis frameworks, and hardened execution.

### New Strategies (5)
- **Ichimoku Cloud**: cloud crossovers, Tenkan/Kijun analysis (replaces VWAP Momentum Alpha)
- **Order Flow**: microstructure-based signals from order book data (book score, imbalance, spread)
- **Stochastic Divergence**: stochastic oscillator + price divergence detection (replaces RSI Mean Reversion)
- **Volatility Squeeze**: TTM Squeeze concept — BB inside KC + momentum breakout (replaces Breakout)
- **Supertrend**: ATR-based adaptive trend identification with volume confirmation

### Removed Strategies (4)
- Momentum (8% win rate), Breakout (0% win rate), VWAP Momentum Alpha (33% win rate), RSI Mean Reversion

### New Features
- Multi-timeframe analysis: 1/5/15-minute candles, 2/3 agreement for entry
- Volatility regime detection (Garman-Klass) with regime-specific strategy weight multipliers
- Session-aware trading: per-hour confidence multipliers from historical win rates
- Auto Strategy Tuner: weekly DB analysis, auto-disable underperformers (Sharpe < -0.3)
- Smart exit system: multi-tier partial position closing (50%@1xTP, 30%@1.5xTP, 20% trailing)
- Exchange-native stop orders as crash-proof backstop
- Typed exchange exception hierarchy (transient vs permanent, smart retry)
- Correlation group position limits
- Trade rate throttle and quiet hours filtering
- Pydantic validators for all critical financial config values
- Login brute-force protection (5 failures/5min → lockout)
- Multi-plan Stripe billing (Pro/Premium)

### Performance
- Parallelized position management (`asyncio.gather`)
- O(1) trade lookup via `get_trade_by_id`
- Consolidated performance stats: 7 queries → 2 with 5s TTL cache
- Vectorized OHLCV resampling with NumPy
- RingBuffer contiguous optimization

### Architecture
- Decomposed `execute_signal` into 5 focused methods
- Decomposed `initialize()` into 5 factory methods
- Extracted `_exit_live_order` retry helper + `_parse_meta` helper
- `EngineInterface` Protocol for control router decoupling
- ConfigManager reset fixture for test isolation

---

## v3.5.0 (2026-02-18) — Profitability Recovery

Emergency release to address 24% win rate observed in production.

### Changes
- Percentage-based SL/TP floors (2.5% SL / 5.0% TP) — ATR-only stops were too tight on 1-min candles
- Disabled losing strategies identified via per-strategy P&L analysis
- ML cold-start handling: graceful fallback when model has insufficient training data
- Fix 24% win rate by combining tighter entry gates with wider exits

---

## v3.4.0 (2026-02-17) — Profitability Tuning & Resilience

### Features
- Dashboard settings modal for runtime configuration
- WS 1013 close code resilience (handled with retry backoff)

### Fixes
- 6 bug fixes across profitability tuning and exchange connectivity
- Kraken WebSocket reconnection improvements

---

## v3.3.1 (2026-02-17) — Hardening Patch

### Fixes
- 15 hardening fixes across REST clients, ML lifecycle, indicators, and dead code removal

---

## v3.3.0 (2026-02-16) — Comprehensive Bug Sweep

### Fixes
- 24 bug fixes across 18 files
- Strategy logic corrections (signal scoring, threshold validation)
- Exchange safety improvements (rate limiting, error handling)
- ML accuracy improvements (feature normalization, threshold tuning)

---

## v3.2.0 (2026-02-16) — Code Review & Crash Prevention

### Features
- Telegram error alert notifications

### Fixes
- 30 bug fixes identified via comprehensive code review
- Crash prevention across all subsystems
- Race condition fixes in concurrent position management

---

## v3.1.0 (2026-02-15) — Review & New Features

### Features
- 10 new features from 4-pass code review
- Strategy tuning based on initial paper trading results

### Fixes
- Multiple stability improvements from code review findings

---

## v3.0.0 (2026-02-14) — Initial Public Release

First Docker-deployable release with full trading capability.

### Features
- **Graceful Error Handler** ("Trade or Die"): classifies errors as CRITICAL / DEGRADED / TRANSIENT — only exchange-auth or database failures stop trading
- 4 trading strategies (Keltner, Mean Reversion, Trend, Reversal)
- Kraken REST + WebSocket integration
- Coinbase Advanced Trade REST + WebSocket
- Kelly Criterion position sizing with ATR-based stops
- FastAPI dashboard with WebSocket live streaming
- Telegram command center (15+ commands)
- Discord and Slack bot integrations
- SQLite WAL-mode database with multi-tenant support
- Docker-first deployment via SuperStart.sh
- Stress test containerized
- Stripe billing integration

### Fixes
- Coinbase WS sync callback crash
- Discord bot open authorization (deny-by-default)
- Stripe global API key thread-safety
- Kraken/Coinbase REST truthiness bugs
- Rate limiter memory leak (stale IP eviction)
- Slack bot deprecated API + missing await
- Version string consistency
- Kraken WS latency tracking

---

*Generated 2026-02-24. See `preflight/` for detailed code review reports.*
