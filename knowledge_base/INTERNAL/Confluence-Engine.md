# Confluence Engine Deep Dive

**Version:** 4.5.0
**Date:** 2026-02-24
**Source:** `src/ai/confluence.py` (~1214 lines)
**Class:** `ConfluenceDetector`

---

## Overview

The ConfluenceDetector is the central decision engine. It runs all 12 registered strategies in parallel on every scan cycle, scores their agreement using weighted confluence, and produces a `ConfluenceSignal` that the executor either trades or discards. A "Sure Fire" setup occurs when enough strategies agree, order book imbalance confirms, and confidence exceeds the minimum threshold.

---

## 12-Strategy Parallel Execution

Strategies are instantiated in `__init__` with raw weights that are normalized to sum to 1.0 via `_normalize_weights()`:

```python
self.strategies: List[BaseStrategy] = [
    KeltnerStrategy(weight=0.25),
    MeanReversionStrategy(weight=0.20),
    VolatilitySqueezeStrategy(weight=0.18),
    VWAPMomentumAlphaStrategy(weight=0.15),
    OrderFlowStrategy(weight=0.12),
    MarketStructureStrategy(weight=0.12),
    SupertrendStrategy(weight=0.12),
    FundingRateStrategy(weight=0.10),
    IchimokuStrategy(weight=0.08),
    TrendStrategy(weight=0.08),
    StochasticDivergenceStrategy(weight=0.06),
    ReversalStrategy(weight=0.06),
]
```

Each strategy call is wrapped in `asyncio.wait_for` with a **5-second timeout**:

```python
signal = await asyncio.wait_for(
    strategy.analyze(pair, closes, highs, lows, volumes, ...),
    timeout=5.0,
)
```

If a strategy times out, the warning is logged and the strategy is silently skipped for that pair on that cycle. Exceptions are caught and logged with full tracebacks but do not crash the scan.

---

## Weighted Confluence Scoring

The effective weight for a given strategy signal is:

```
effective_weight = base_weight * adaptive_performance_factor * regime_multiplier
```

Where:

- **base_weight** -- the normalized weight from the strategy object (`strategy.weight`, summing to 1.0 across all strategies).
- **adaptive_performance_factor** -- returned by `strategy.adaptive_performance_factor(trend_regime, vol_regime)`, a sliding-window metric based on recent trade results for that strategy in the current regime.
- **regime_multiplier** -- from `_get_regime_multiplier()`, which multiplies trend regime weight and vol regime weight together, **capped at 2.0**: `return min(mult, 2.0)`.

The weighted strength and confidence for directional signals are computed as weighted averages:

```python
weighted_strength = sum(
    s.strength * get_weight(s.strategy_name, trend, vol)
    for s in directional_signals
) / total_weight
```

A **confluence bonus** adds up to +0.30 to confidence: `min((confluence_count - 1) * 0.1, 0.3)`.

---

## Opposition Penalty

When strategies disagree (some signal LONG while others signal SHORT), confidence is penalized:

```python
opposition_penalty = min(opposing_count * 0.07, 0.25)
weighted_confidence = max(weighted_confidence - opposition_penalty, 0.0)
```

- Each opposing signal costs **0.07** confidence.
- Maximum penalty is **0.25** (so 4+ opposing signals all hit the same cap).
- Synthetic `order_book` signals are excluded from the opposition count.

---

## Regime Multiplier Details

Four default regime weight maps exist: `_default_trend_weights`, `_default_range_weights`, `_default_high_vol_weights`, `_default_low_vol_weights`. These can be overridden via `regime_config` from YAML.

Regime detection (`_detect_regime`) returns 4 values -- **never stored on self** (race condition avoidance for parallel pair scanning):

```python
trend_regime, vol_regime, vol_level, vol_expanding = self._detect_regime(indicator_cache, closes)
```

- `trend_regime`: `"trend"` if ADX >= threshold (default 25), else `"range"`.
- `vol_regime`: `"high_vol"` if ATR% >= 2%, `"low_vol"` if ATR% <= 0.8%, else `"mid_vol"`.
- `vol_level`: Garman-Klass vol percentile (0.0-1.0) over rolling 100 bars.
- `vol_expanding`: True if current GK vol > 1.5x the value from 10 bars ago.

### Regime-Based Binary Gating

Beyond soft multipliers, hard gating completely skips mismatched strategies:

- If `trend_regime == "range"` and `ADX < 20`: skip `{trend, ichimoku, supertrend}`.
- If `trend_regime == "trend"` and `ADX > 40`: skip `{mean_reversion, stochastic_divergence, reversal}`.

---

## Strategy Family Diversity

Strategies are classified into families via `_STRATEGY_FAMILIES`:

| Family             | Strategies                                              |
|--------------------|---------------------------------------------------------|
| `mean_reversion`   | keltner, mean_reversion, reversal, stochastic_divergence|
| `trend_following`  | trend, ichimoku, supertrend                             |
| `momentum`         | volatility_squeeze                                      |
| `microstructure`   | order_flow                                              |
| `vwap`             | vwap_momentum_alpha                                     |
| `structure`        | market_structure                                        |
| `sentiment`        | funding_rate                                            |

Scoring adjustment:

- **3+ distinct families** in agreeing signals: **+0.05** confidence bonus.
- **All signals from the same family** (and more than 1 signal): **-0.05** confidence penalty.

---

## Sure Fire Detection

A "Sure Fire" setup is the highest-quality signal. The conditions:

```python
is_sure_fire = (
    confluence_count >= threshold_for_regime  # Default 3, raised in high_vol
    and obi_agrees                            # OBI confirms direction
    and weighted_confidence >= min_confidence  # Default 0.65
)
```

- In `high_vol` regime, the threshold is raised: `max(confluence_threshold, high_vol_confluence_threshold)` (default: threshold + 1).
- When Sure Fire triggers, strength gets +0.15 and confidence gets +0.10 (both capped at 1.0).

---

## OBI as Synthetic Confluence Vote

When `obi_counts_as_confluence` is True (default), the order book imbalance generates a synthetic `"order_book"` signal that counts toward confluence:

```python
synthetic_strength = min(0.4 + abs(score_for_agreement) * 0.6, 1.0)
```

This means OBI + 1 real strategy = 2 confluence count, making it possible to trade without waiting for 3 strategies to agree. The OBI weight for the synthetic signal is controlled by `obi_weight` (default 0.4).

The detector prefers the microstructure `book_score` from order book analysis when available (fresher than raw OBI), falling back to raw OBI when `book_score` is not populated.

---

## Session-Aware Multiplier

If a `SessionAnalyzer` is injected, confidence is multiplied by the hour-of-day performance multiplier:

```python
session_mult = self.session_analyzer.get_multiplier(hour)
weighted_confidence *= session_mult
```

This scales down confidence during historically poor trading hours and scales it up during strong ones. The result is clamped to [0.0, 1.0].

---

## Funding Rates Injection

Funding rates are injected per scan cycle by the engine:

```python
# In BotEngine scan loop:
rates = await self.funding_rate_client.get_all_rates()
self.confluence.set_funding_rates(rates)
```

The stored `_funding_rates` dict is passed through to every strategy via `kwargs`:

```python
signal = await strategy.analyze(
    ...,
    funding_rates=self._funding_rates,
)
```

Only `FundingRateStrategy` reads the `funding_rates` kwarg; all other strategies ignore it.

---

## Strategy Cooldowns and Guardrails

### Per-Strategy Cooldowns

A cooldown checker function can be injected via `set_cooldown_checker(fn)`. For every non-neutral signal, the checker is called:

```python
if self._cooldown_checker(pair, signal.strategy_name, side):
    # Signal is reset to NEUTRAL with reason "strategy_cooldown"
```

### Runtime Guardrails

Guardrails auto-disable strategies that are performing poorly over a sliding window. Configured via constructor params:

| Parameter                           | Default | Description                                        |
|-------------------------------------|---------|----------------------------------------------------|
| `strategy_guardrails_enabled`       | True    | Master toggle                                      |
| `strategy_guardrails_min_trades`    | 20      | Minimum trades before evaluation                   |
| `strategy_guardrails_window_trades` | 30      | Sliding window size                                |
| `strategy_guardrails_min_win_rate`  | 0.35    | Win rate below this triggers check                 |
| `strategy_guardrails_min_profit_factor` | 0.85 | Profit factor below this triggers check           |
| `strategy_guardrails_disable_minutes` | 120   | How long to disable the strategy                   |

A strategy is disabled when **both** win rate and profit factor fall below their thresholds simultaneously. The disabled-until timestamp is stored in `_runtime_disabled_until[strategy_name]` and checked via `_is_runtime_disabled()` on every scan.

---

## Multi-Timeframe Confluence

The detector supports multiple timeframes (e.g., `[1, 5, 15]` minute). For each timeframe:

1. Base 1-minute OHLCV is resampled via `_resample_ohlcv()`.
2. Strategies run independently per timeframe.
3. Results are combined in `_combine_timeframes()`.

Timeframe weights (`_TF_WEIGHTS`): `{1: 1.0, 5: 1.3, 15: 1.5, 30: 1.7, 60: 2.0}`.

- If the primary TF is neutral but other TFs agree, the highest agreeing TF's signal is promoted.
- SL/TP are taken from the highest agreeing TF (wider stops = more survivable).
- Unanimous agreement across 3+ TFs: +0.15 confidence bonus.
- Unanimous across 2 TFs: +0.10.
- Partial agreement: up to +0.10 scaled by weighted agreement ratio.

---

## Key Data Structures

- `_last_confluence: Dict[str, ConfluenceSignal]` -- most recent signal per pair.
- `_signal_history: Deque[ConfluenceSignal]` -- ring buffer of last 1000 signals.
- `_runtime_disabled_until: Dict[str, float]` -- guardrail disable timestamps.
- `_funding_rates: Dict[str, float]` -- current cycle's funding rate data.
