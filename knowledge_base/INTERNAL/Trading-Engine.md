# NovaPulse Trading Engine

**Version:** 4.0.0
**Last Updated:** 2026-02-22

---

## Overview

The NovaPulse trading engine is built around a **multi-strategy confluence model**: nine independent technical analysis strategies run in parallel on every pair, and a trade is only considered when multiple strategies agree on direction. This section covers each strategy in detail, the confluence scoring engine, adaptive weighting, regime detection, multi-timeframe analysis, session-aware trading, the auto-tuner, and strategy guardrails.

---

## Strategy Lineup (9 Strategies)

Each strategy has a **base weight** that determines its influence on the final confluence score. Weights are further adjusted by regime multipliers and adaptive performance factors.

### 1. Keltner Channel Rebound (weight: 0.30)

**File:** `src/strategies/keltner.py`
**Class:** `KeltnerStrategy`

The highest-weighted strategy and historically the most profitable (100% WR in early testing).

**Logic:**
- Computes Keltner Channels: EMA(20) center line with ATR(14) x 1.5 upper/lower bands
- LONG signal: price rebounds off lower KC band + MACD histogram positive + RSI < 40
- SHORT signal: price rejects upper KC band + MACD histogram negative + RSI > 60
- SL/TP derived from ATR with percentage-based floors (2.5% SL, 5.0% TP)

**Config keys:**
```yaml
strategies:
  keltner:
    enabled: true
    weight: 0.30
    ema_period: 20
    atr_period: 14
    kc_multiplier: 1.5
    macd_fast: 12
    macd_slow: 26
    macd_signal: 9
    rsi_period: 14
    rsi_long_max: 40
    rsi_short_min: 60
```

### 2. Mean Reversion (weight: 0.25)

**File:** `src/strategies/mean_reversion.py`
**Class:** `MeanReversionStrategy`

Second-highest weight, historically strong (80% WR).

**Logic:**
- Bollinger Band extremes: price touches or breaks lower/upper band
- LONG signal: price below lower BB + RSI oversold (< 30)
- SHORT signal: price above upper BB + RSI overbought (> 70)
- Expects price to revert to the mean (BB middle line)

**Config keys:**
```yaml
strategies:
  mean_reversion:
    enabled: true
    weight: 0.25
    bb_period: 20
    bb_std: 2.0
    rsi_oversold: 30
    rsi_overbought: 70
```

### 3. Ichimoku Cloud (weight: 0.15)

**File:** `src/strategies/ichimoku.py`
**Class:** `IchimokuStrategy`

Replaced VWAP Momentum Alpha in v4.0.

**Logic:**
- Computes all 5 Ichimoku lines: Tenkan-sen, Kijun-sen, Senkou Span A/B, Chikou Span
- LONG signal: Tenkan crosses above Kijun + price above cloud + Chikou above past price
- SHORT signal: Tenkan crosses below Kijun + price below cloud + Chikou below past price
- ATR-based SL/TP with percentage floors

**Config keys:**
```yaml
strategies:
  ichimoku:
    enabled: true
    weight: 0.15
    tenkan_period: 9
    kijun_period: 26
    senkou_b_period: 52
    atr_period: 14
```

### 4. Order Flow (weight: 0.15)

**File:** `src/strategies/order_flow.py`
**Class:** `OrderFlowStrategy`

New in v4.0. Uses real-time order book microstructure data from WebSocket.

**Logic:**
- Reads book_score from `OrderBookAnalyzer` (computed in `src/ai/order_book.py`)
- LONG signal: book_score > threshold + spread tight + price near recent lows
- SHORT signal: book_score < -threshold + spread tight + price near recent highs
- Requires fresh book data (max 5 seconds old)

**Config keys:**
```yaml
strategies:
  order_flow:
    enabled: true
    weight: 0.15
    book_score_threshold: 0.3
    spread_tight_pct: 0.0010
    hl_lookback: 5
    max_book_age_seconds: 5
    atr_period: 14
```

### 5. Trend (weight: 0.15)

**File:** `src/strategies/trend.py`
**Class:** `TrendStrategy`

Classic EMA crossover with ADX trend strength filter.

**Logic:**
- LONG signal: EMA(5) crosses above EMA(13) + ADX > 25 (confirming trend)
- SHORT signal: EMA(5) crosses below EMA(13) + ADX > 25
- Only fires in trending markets (ADX threshold)

**Config keys:**
```yaml
strategies:
  trend:
    enabled: true
    weight: 0.15
    ema_fast: 5
    ema_slow: 13
    adx_threshold: 25
```

### 6. Stochastic Divergence (weight: 0.12)

**File:** `src/strategies/stochastic_divergence.py`
**Class:** `StochasticDivergenceStrategy`

New in v4.0. Replaced RSI Mean Reversion.

**Logic:**
- Computes Stochastic %K/%D oscillator
- Detects divergence: price makes new low but stochastic does not (bullish divergence) or vice versa
- LONG signal: bullish divergence + stochastic in oversold zone (< 20)
- SHORT signal: bearish divergence + stochastic in overbought zone (> 80)

**Config keys:**
```yaml
strategies:
  stochastic_divergence:
    enabled: true
    weight: 0.12
    k_period: 14
    d_period: 3
    smooth: 3
    oversold: 20.0
    overbought: 80.0
    divergence_lookback: 20
    atr_period: 14
```

### 7. Volatility Squeeze (weight: 0.12)

**File:** `src/strategies/volatility_squeeze.py`
**Class:** `VolatilitySqueezeStrategy`

New in v4.0. Replaced Breakout. Based on the TTM Squeeze concept.

**Logic:**
- Detects when Bollinger Bands are inside Keltner Channels (squeeze = low volatility compression)
- Signals when squeeze releases (BB expands outside KC) with momentum confirmation
- LONG signal: squeeze release + positive momentum (12-period)
- SHORT signal: squeeze release + negative momentum
- Requires minimum number of squeeze bars before release (default 3)

**Config keys:**
```yaml
strategies:
  volatility_squeeze:
    enabled: true
    weight: 0.12
    bb_period: 20
    bb_std: 2.0
    kc_ema_period: 20
    kc_atr_period: 14
    kc_multiplier: 1.5
    momentum_period: 12
    atr_period: 14
    min_squeeze_bars: 3
```

### 8. Supertrend (weight: 0.10)

**File:** `src/strategies/supertrend.py`
**Class:** `SupertrendStrategy`

New in v4.0. ATR-based adaptive trend following with volume confirmation.

**Logic:**
- Computes Supertrend indicator: ATR(10) x 3.0 multiplier
- LONG signal: price crosses above Supertrend line + volume above 1.2x average
- SHORT signal: price crosses below Supertrend line + volume above 1.2x average
- Volume filter prevents false signals in thin markets

**Config keys:**
```yaml
strategies:
  supertrend:
    enabled: true
    weight: 0.10
    st_period: 10
    st_multiplier: 3.0
    volume_period: 20
    volume_threshold: 1.2
    atr_period: 14
```

### 9. Reversal (weight: 0.10)

**File:** `src/strategies/reversal.py`
**Class:** `ReversalStrategy`

Extreme RSI with candlestick confirmation.

**Logic:**
- LONG signal: RSI < 20 (extreme oversold) + 3 consecutive bullish confirmation candles
- SHORT signal: RSI > 80 (extreme overbought) + 3 consecutive bearish confirmation candles
- Very selective; rarely fires but targets high-probability reversals

**Config keys:**
```yaml
strategies:
  reversal:
    enabled: true
    weight: 0.10
    rsi_extreme_low: 20
    rsi_extreme_high: 80
    confirmation_candles: 3
```

---

## Confluence Engine

**File:** `src/ai/confluence.py`
**Class:** `ConfluenceDetector`

The confluence engine is the central decision-making component. It does NOT trade on any single strategy alone -- it requires agreement from multiple strategies.

### Signal Flow

```
Per pair, per timeframe:
  1. Fetch OHLCV data from MarketDataCache
  2. Optionally resample to higher timeframe (5m, 15m)
  3. Detect market regime (trend/range, vol level)
  4. Run all 9 strategies in parallel (5s timeout each)
  5. Apply cooldown filtering per strategy
  6. Compute weighted confluence score
  7. Add OBI/book_score as synthetic signal (if enabled)
  8. Apply session-aware multiplier
  9. Detect "Sure Fire" setup (3+ strategies + OBI agreement)
  10. Combine timeframe results (2/3 agreement)
```

### Weighted Confluence Scoring

Each strategy signal carries a weight computed as:

```
effective_weight = base_weight
                 x adaptive_performance_factor
                 x regime_multiplier
```

The weighted strength and confidence are then computed:

```
weighted_strength = SUM(signal.strength * effective_weight) / SUM(effective_weight)
weighted_confidence = SUM(signal.confidence * effective_weight) / SUM(effective_weight)
```

**Confluence bonus:** Each additional agreeing strategy beyond the first adds +0.10 to confidence (capped at +0.30).

**Opposition penalty:** Each strategy actively signaling the opposite direction reduces confidence by 0.04 (capped at -0.12).

### "Sure Fire" Detection

A signal is classified as "Sure Fire" when ALL of the following are true:
- `confluence_count >= confluence_threshold` (default 3)
- Order Book Imbalance confirms the direction
- `weighted_confidence >= min_confidence` (default 0.65)

Sure Fire signals get a +0.15 strength bonus and +0.10 confidence bonus.

### Order Book Imbalance (OBI) as Confluence Vote

When `obi_counts_as_confluence: true` (config), OBI acts as a synthetic strategy signal:
- If book_score or OBI exceeds threshold in the signal direction, a synthetic "order_book" signal is added
- This means OBI + 1 real strategy = 2 confluence count = potentially tradeable
- The synthetic signal uses weight `obi_weight` (default 0.4)

When `obi_counts_as_confluence: false`, OBI only provides a small confidence bump (+0.05) when it agrees with direction.

---

## Regime Detection

**Method:** `ConfluenceDetector._detect_regime()`

The engine detects two independent regime dimensions:

### Trend Regime (ADX-based)
- **Trend:** ADX >= 25 (configurable via `regime.adx_trend_threshold`)
- **Range:** ADX < 25

### Volatility Regime (ATR %-based)
- **High Vol:** ATR% >= 2.0% (configurable via `regime.atr_pct_high`)
- **Mid Vol:** ATR% between low and high thresholds
- **Low Vol:** ATR% <= 0.8% (configurable via `regime.atr_pct_low`)

### Vol Level (Garman-Klass Percentile)
- A continuous 0-1 value representing where current Garman-Klass volatility sits relative to its rolling window (last 100 values)
- Used for position sizing adjustments in RiskManager

### Vol Expanding
- Boolean flag: current GK vol > 1.5x GK vol from 10 bars ago
- Indicates a regime transition (most dangerous period)
- Triggers aggressive position size reduction (0.6x)

### Regime Weight Multipliers

Each regime applies multipliers to strategy weights:

| Strategy | Trend Mult | Range Mult | High Vol Mult | Low Vol Mult |
|----------|-----------|-----------|---------------|-------------|
| Keltner | 0.9 | 1.2 | -- | 1.1 |
| Mean Reversion | 0.8 | 1.3 | 0.9 | 1.2 |
| Ichimoku | 1.2 | 0.8 | -- | 0.9 |
| Order Flow | 1.1 | 1.1 | 1.1 | -- |
| Trend | 1.3 | 0.8 | -- | -- |
| Stoch Divergence | 0.8 | 1.3 | 0.9 | 1.2 |
| Vol Squeeze | 1.1 | 0.9 | 1.3 | 0.8 |
| Supertrend | 1.2 | 0.8 | 1.1 | 0.9 |
| Reversal | 0.7 | 1.1 | 0.9 | -- |

These are configurable via `ai.regime.*_weight_multipliers` in config.yaml.

---

## Multi-Timeframe Analysis

NovaPulse can analyze multiple timeframes using 1-minute candles as the base:

```
1-min candles (base, always present)
    |
    +-- Resample to 5-min  --> Run 9 strategies --> Per-TF signal
    |
    +-- Resample to 15-min --> Run 9 strategies --> Per-TF signal
    |
    +-- Use 1-min directly --> Run 9 strategies --> Per-TF signal
    |
    v
Combine timeframes (see below)
```

### Resampling

`_resample_ohlcv()` uses numpy `reduceat` operations to convert 1-min OHLCV into higher timeframes:
- Open: first open in bucket
- High: maximum high in bucket
- Low: minimum low in bucket
- Close: last close in bucket
- Volume: sum of volumes in bucket

### Timeframe Combination

`_combine_timeframes()` logic:

1. **Primary TF drives direction** (default: 1-min). If primary is NEUTRAL, falls back to strongest non-primary signal with majority agreement.
2. **Minimum agreement** required: `multi_timeframe_min_agreement` (default 1). With 3 TFs, typically set to 2.
3. **TF confidence weights:** higher timeframes carry more weight:
   - 1-min: 1.0
   - 5-min: 1.3
   - 15-min: 1.5
   - 30-min: 1.7
   - 60-min: 2.0
4. **Unanimity bonus:**
   - All 3+ TFs agree: +0.15 confidence
   - Both 2 TFs agree: +0.10 confidence
   - Partial: scaled by weighted agreement ratio (max +0.10)
5. **SL/TP from highest agreeing TF** for wider, more survivable stops

### Config

```yaml
trading:
  timeframes: [1, 5, 15]

ai:
  multi_timeframe_min_agreement: 2
  primary_timeframe: 1
```

---

## Adaptive Strategy Weighting

Each strategy tracks its recent trade performance using a sliding window (50 trades by default). The `adaptive_performance_factor()` method on each `BaseStrategy` computes a Sharpe-like score from the P&L of recent trades in the current regime:

```
performance_factor = clamp(sharpe_like_score, 0.5, 1.5)
```

This means:
- A strategy on a winning streak gets up to 1.5x its base weight
- A strategy on a losing streak gets reduced to 0.5x its base weight
- The adjustment is regime-aware (computed separately per trend/vol regime)

The `record_trade_result()` method on `ConfluenceDetector` feeds P&L and regime info to the relevant strategy after each trade close.

---

## Session-Aware Trading

**File:** `src/ai/session_analyzer.py`
**Class:** `SessionAnalyzer`

Applies a per-hour-of-day confidence multiplier derived from historical win rates in the database.

### How It Works

1. On initialization, queries the DB for win rates grouped by UTC hour
2. Hours with fewer than `min_trades_per_hour` (default 5) get a neutral multiplier of 1.0
3. Hours with high win rates get a boost (up to `max_boost`, default 1.15)
4. Hours with low win rates get a penalty (down to `max_penalty`, default 0.70)
5. The multiplier is applied to `weighted_confidence` in `_compute_confluence()`

**Example:** Hour 0 UTC (midnight) might have a 0.70 multiplier, meaning all signals during that hour have their confidence reduced by 30%.

### Config

```yaml
ai:
  session:
    enabled: true
    min_trades_per_hour: 5
    max_boost: 1.15
    max_penalty: 0.70
```

---

## Auto Strategy Tuner

**File:** `src/ml/strategy_tuner.py`
**Class:** `StrategyTuner`

Runs on a configurable schedule (default: weekly) and analyzes strategy performance from the database.

### What It Does

1. Queries all closed trades grouped by strategy
2. For strategies with enough trades (`min_trades_per_strategy`, default 15):
   - Computes Sharpe-like ratio, win rate, profit factor
   - If Sharpe < `auto_disable_sharpe` (default -0.3) with 30+ trades, auto-disables the strategy
   - Adjusts weight within bounds (`weight_bounds`, default [0.05, 0.50])
3. Persists changes to `config/config.yaml` via `save_to_yaml()`
4. Changes take effect immediately (config hot-reload)

### Config

```yaml
tuner:
  enabled: true
  interval_hours: 168     # Weekly
  min_trades_per_strategy: 15
  weight_bounds: [0.05, 0.50]
  auto_disable_sharpe: -0.3
  auto_disable_min_trades: 30
```

---

## Strategy Guardrails (Runtime Auto-Disable)

A faster-acting safety mechanism than the weekly tuner. Evaluates each strategy after every trade close.

### How It Works

1. After each trade closes, `ConfluenceDetector.record_trade_result()` calls `_evaluate_strategy_guardrail()` on the strategy
2. Looks at the last `strategy_guardrails_window_trades` (default 30) trades for that strategy
3. If BOTH conditions are met:
   - Win rate < `strategy_guardrails_min_win_rate` (default 0.35)
   - Profit factor < `strategy_guardrails_min_profit_factor` (default 0.85)
4. The strategy is **runtime-disabled** for `strategy_guardrails_disable_minutes` (default 120 minutes)
5. After the timeout, the strategy is automatically re-enabled

This prevents strategies from accumulating losses during market conditions that don't suit them, without requiring a full tuner cycle.

### Config

```yaml
ai:
  strategy_guardrails_enabled: true
  strategy_guardrails_min_trades: 20
  strategy_guardrails_window_trades: 30
  strategy_guardrails_min_win_rate: 0.35
  strategy_guardrails_min_profit_factor: 0.85
  strategy_guardrails_disable_minutes: 120
```

---

## Important Technical Notes

### 1-Minute ATR Is Tiny

On 1-min candles, ATR is typically 0.06-0.10% of price. ATR-based SL/TP would be unreasonably tight without percentage floors. The `compute_sl_tp()` function in `src/utils/indicators.py` enforces:
- **Minimum SL:** 2.5% of entry price
- **Minimum TP:** 5.0% of entry price

Strategy-specific ATR multipliers only matter if `ATR * multiplier > floor`.

### Closed Candle Mode

When `use_closed_candles_only: true`, the most recent (potentially in-progress) candle is dropped before analysis. This prevents strategies from reacting to incomplete bar data but adds latency.

### Strategy Cooldowns

Per-strategy cooldowns prevent the same strategy from re-entering the same pair in the same direction within a configurable window:

```yaml
trading:
  strategy_cooldowns_seconds:
    keltner: 600
    mean_reversion: 600
```

### Single Strategy Mode

For testing, you can isolate a single strategy:

```yaml
trading:
  single_strategy_mode: "keltner"
```

Only that strategy will run; all others are skipped.
