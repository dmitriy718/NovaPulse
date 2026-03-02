# NovaPulse Advanced Features (v5.0) — Internal

**Version:** 5.0.0  
**Last Updated:** 2026-02-27

---

## Overview

v5.0 introduces 10 optional advanced features. All default to `enabled: false` for backward compatibility. This document describes implementation details, config, DB schema, and API for support and developers.

---

## Feature Summary

| Feature | Config section | Main module(s) | API endpoint |
|--------|----------------|----------------|--------------|
| Macro Event Calendar | `event_calendar` | `src/utils/event_calendar.py` | `GET /api/v1/events` |
| Lead-Lag Intelligence | `ai.lead_lag` | `src/ai/lead_lag.py` | `GET /api/v1/lead-lag` |
| Regime Transition Prediction | `ai.regime_predictor` | `src/ai/regime_predictor.py` | `GET /api/v1/regime` |
| On-Chain Data | `ai.onchain` | `src/exchange/onchain_data.py` | `GET /api/v1/onchain` |
| Structural Stop Loss | `risk.structural_stop` | RiskManager + MarketStructureStrategy | `GET /api/v1/structural-stops` |
| Liquidity-Aware Sizing | `risk.liquidity_sizing` | RiskManager | `GET /api/v1/liquidity` |
| Anomaly Detection | `monitoring.anomaly_detector` | `src/execution/anomaly_detector.py` | `GET /api/v1/anomalies` |
| P&L Attribution | (recording only) | Executor + DB | `GET /api/v1/attribution` |
| Ensemble ML | `ai.ensemble_ml` | `src/ai/ensemble_model.py` | `GET /api/v1/ensemble` |
| Bayesian Optimizer | `ai.bayesian_optimizer` | `src/ai/bayesian_optimizer.py` | `GET /api/v1/optimizer`, `/optimizer/history` |

---

## Signal Intelligence

### Macro Event Calendar

- **Purpose:** Auto-pause trading during FOMC/CPI/NFP (and optional earnings) blackout windows.
- **Data:** Static JSON at `data/events/macro_events.json`; optional Polygon earnings fetch when `fetch_earnings: true`.
- **Config:** `EventCalendarConfig` — `enabled`, `blackout_minutes`, `events_file`, `fetch_earnings`, `earnings_refresh_hours`.
- **Integration:** Engine checks event calendar before allowing new entries; blackout state streamed to dashboard.

### Lead-Lag

- **Purpose:** Monitor BTC/ETH leader moves; adjust follower altcoin confidence by -0.10 to +0.15 based on correlation and move magnitude.
- **Config:** `LeadLagConfig` under `ai` — `enabled`, `leader_pairs`, `atr_multiplier`, `lookback_minutes`, `boost_confidence`, `penalize_confidence`, `min_correlation`.
- **Module:** `src/ai/lead_lag.py` — computes leader returns, correlates with follower, returns confidence delta.

### Regime Predictor

- **Purpose:** Anticipate range-to-trend and trend-to-range transitions (squeeze duration, ADX slope, volume trend, choppiness); boost trend strategy confidence during "emerging_trend".
- **Config:** `RegimePredictorConfig` — `enabled`, `squeeze_duration_threshold`, `adx_slope_period`, `adx_emerging_threshold`, `volume_ratio_threshold`, `emerging_trend_boost`.
- **Module:** `src/ai/regime_predictor.py`.

### On-Chain Data

- **Purpose:** Fetch blockchain sentiment (exchange flows, stablecoin supply, large txns); apply ±0.08 confidence adjustment when aligned/opposing.
- **Config:** `OnChainConfig` under `ai` — `enabled`, `cache_ttl_seconds`, `weight`, `min_abs_score`.
- **Module:** `src/exchange/onchain_data.py` — uses existing ingestion/cache patterns where applicable.

---

## Risk Management

### Structural Stop Loss

- **Purpose:** Place stops behind recent swing highs/lows (MarketStructureStrategy swing detection); min 0.5× ATR buffer, max 4× ATR distance.
- **Config:** `StructuralStopConfig` under `risk` — `enabled`, `lookback`, `buffer_atr_mult`, `max_distance_atr`.
- **Integration:** RiskManager (or executor) uses swing levels when `structural_stop.enabled`; falls back to ATR multiple otherwise.

### Liquidity-Aware Sizing

- **Purpose:** Reduce position size when order book depth is thin relative to trade size.
- **Config:** `LiquiditySizingConfig` under `risk` — `enabled`, `max_impact_pct`, `min_depth_ratio`.
- **Integration:** RiskManager scales size down when depth check fails.

---

## Monitoring & Analytics

### Anomaly Detection Circuit Breaker

- **Purpose:** Detect spread spikes (3×), volume anomalies (5×), correlation anomalies (>60% same direction), depth drops (>50%); auto-pause for configurable cooldown.
- **Config:** `AnomalyDetectorConfig` under `monitoring` — `enabled`, `spread_threshold_mult`, `volume_threshold_mult`, `correlation_threshold`, `depth_drop_threshold`, `pause_seconds`, `min_history_samples`.
- **Module:** `src/execution/anomaly_detector.py`. Events logged to `anomaly_events` table.

### P&L Attribution

- **Purpose:** Record strategy, regime, volatility, session, and confluence metadata per trade; query by strategy/regime/pair/date.
- **DB table:** `strategy_attribution` — per-trade records with metadata.
- **API:** `GET /api/v1/attribution` with query params for filtering.

---

## Machine Learning

### Ensemble ML

- **Purpose:** Combine TFLite predictor with LightGBM binary classifier; weighted average (e.g. 40% LightGBM, 60% TFLite); graceful fallback if either unavailable.
- **Config:** `EnsembleMLConfig` under `ai` — `enabled`, `lgbm_weight`, `tflite_weight`, `min_training_samples`, `retrain_interval_hours`, `feature_names`.
- **Module:** `src/ai/ensemble_model.py`. Optional dependency: `lightgbm>=4.0.0,<5`.

### Bayesian Optimizer

- **Purpose:** Optuna TPE optimization of confluence_threshold, min_confidence, trailing_activation, risk params; metrics: sharpe_ratio, profit_factor, calmar_ratio. Suggestions only (not auto-applied).
- **Config:** `BayesianOptimizerConfig` under `ai` — `enabled`, `n_trials`, `optimization_interval_hours`, `min_trades_for_optimization`, `metric`.
- **Module:** `src/ai/bayesian_optimizer.py`. Optional dependency: `optuna>=3.5.0,<4`.
- **API:** `GET /api/v1/optimizer`, `GET /api/v1/optimizer/history`.

---

## New Database Tables

- **strategy_attribution** — P&L attribution: trade_id, strategy, regime, volatility_regime, session_utc_hour, confluence_count, (optional) P&L and metadata.
- **anomaly_events** — Anomaly log: timestamp, type (spread/volume/correlation/depth), pair, severity, pause_seconds, resolved_at.

See [Database-Schema](Database-Schema.md) for full column definitions and indexes.

---

## New API Endpoints (v5.0)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/events` | Event calendar status and blackout windows |
| GET | `/api/v1/lead-lag` | Lead-lag state and confidence deltas |
| GET | `/api/v1/regime` | Regime predictor state (e.g. emerging_trend) |
| GET | `/api/v1/onchain` | On-chain sentiment and confidence adjustment |
| GET | `/api/v1/structural-stops` | Structural stop placement status |
| GET | `/api/v1/liquidity` | Liquidity sizing status |
| GET | `/api/v1/anomalies` | Recent anomaly events |
| GET | `/api/v1/attribution` | P&L attribution with filters |
| GET | `/api/v1/ensemble` | Ensemble ML status and weights |
| GET | `/api/v1/optimizer` | Bayesian optimizer status and latest suggestion |
| GET | `/api/v1/optimizer/history` | Optimization run history |

All require dashboard auth and tenant resolution where applicable.

---

## Config Reference (v5.0)

See [Config-Reference](Config-Reference.md) for full tables. Summary:

- **event_calendar** (root): `enabled`, `blackout_minutes`, `events_file`, `fetch_earnings`, `earnings_refresh_hours`
- **ai.lead_lag**: `enabled`, `leader_pairs`, `atr_multiplier`, `lookback_minutes`, `boost_confidence`, `penalize_confidence`, `min_correlation`
- **ai.regime_predictor**: `enabled`, `squeeze_duration_threshold`, `adx_slope_period`, `adx_emerging_threshold`, `volume_ratio_threshold`, `emerging_trend_boost`
- **ai.onchain**: `enabled`, `cache_ttl_seconds`, `weight`, `min_abs_score`
- **ai.ensemble_ml**: `enabled`, `lgbm_weight`, `tflite_weight`, `min_training_samples`, `retrain_interval_hours`, `feature_names`
- **ai.bayesian_optimizer**: `enabled`, `n_trials`, `optimization_interval_hours`, `min_trades_for_optimization`, `metric`
- **risk.structural_stop**: `enabled`, `lookback`, `buffer_atr_mult`, `max_distance_atr`
- **risk.liquidity_sizing**: `enabled`, `max_impact_pct`, `min_depth_ratio`
- **monitoring.anomaly_detector**: `enabled`, `spread_threshold_mult`, `volume_threshold_mult`, `correlation_threshold`, `depth_drop_threshold`, `pause_seconds`, `min_history_samples`

---

## Dashboard

- **Advanced Features** panel shows real-time status of all 10 features (enabled/disabled, blackout, regime, training status).
- Feature status streamed via WebSocket for live updates.
- Settings modal exposes feature toggles where appropriate.
- Version header shows v5.0.

---

## Testing

- Unit tests per feature: `test_event_calendar.py`, `test_lead_lag.py`, `test_regime_predictor.py`, `test_onchain_data.py`, `test_structural_stop.py`, `test_liquidity_sizing.py`, `test_anomaly_detector.py`, `test_ensemble_model.py`, `test_bayesian_optimizer.py`, `test_strategy_attribution.py`, `test_feature_integration.py`.
- Optional dependency tests (LightGBM, Optuna) are skipped when packages not installed (20 skips in suite).
