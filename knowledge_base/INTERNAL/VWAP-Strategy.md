# VWAP Momentum Alpha Strategy

**Version:** 5.0.0
**Date:** 2026-02-27
**Source:** `src/strategies/vwap_momentum_alpha.py`
**Class:** `VWAPMomentumAlphaStrategy(BaseStrategy)`

---

## Overview

The VWAP Momentum Alpha strategy is a volume-weighted pullback strategy. It computes a rolling VWAP with volume-weighted standard deviation bands and enters when price pulls back toward VWAP in the direction of the VWAP slope. It is a momentum-style strategy that buys/sells dips within a trending VWAP environment.

This strategy was dormant since v4.0 when Ichimoku replaced it in the active lineup. It was re-activated in v4.5 with proper registration in the confluence detector's strategy list and `configure_strategies()` map.

---

## Configuration

| Parameter                      | Default   | Description                                        |
|--------------------------------|-----------|----------------------------------------------------|
| `vwap_window`                  | 20        | Rolling VWAP computation window (bars)             |
| `band_std`                     | 1.5       | Standard deviation multiplier for bands            |
| `pullback_z`                   | 0.6       | Base z-score threshold for pullback detection      |
| `slope_period`                 | 5         | Bars lookback for VWAP slope calculation           |
| `volume_multiplier`            | 1.0       | Minimum volume ratio for confirmation              |
| `slope_min_pct`                | 0.0005    | Minimum slope (as fraction of VWAP) to count       |
| `pullback_z_trend_adjust`      | -0.12     | Z-score adjustment in trending regime              |
| `pullback_z_range_adjust`      | 0.12      | Z-score adjustment in ranging regime               |
| `pullback_z_high_vol_adjust`   | 0.10      | Z-score adjustment in high volatility              |
| `pullback_z_low_vol_adjust`    | -0.05     | Z-score adjustment in low volatility               |
| `weight`                       | 0.12      | Confluence weight (0.15 after normalization)       |
| `enabled`                      | True      | Strategy toggle                                    |

Minimum bars required: `max(vwap_window + slope_period + 5, 50)`.

---

## VWAP Computation

The `_rolling_vwap_and_std()` module-level function computes the rolling VWAP and volume-weighted standard deviation using convolution for efficiency:

```python
def _rolling_vwap_and_std(closes, volumes, window):
    pv = price * vol           # price * volume
    p2v = (price ** 2) * vol   # price^2 * volume

    sum_vol = np.convolve(vol, kernel, mode="valid")
    sum_pv  = np.convolve(pv, kernel, mode="valid")
    sum_p2v = np.convolve(p2v, kernel, mode="valid")

    vwap = sum_pv / sum_vol
    variance = (sum_p2v / sum_vol) - (vwap ** 2)
    vwap_std = sqrt(max(variance, 0))
```

Returns two arrays aligned to the closes length, with NaN for warmup bars (first `window - 1` bars).

---

## VWAP Bands

The upper and lower bands are conceptual (not explicitly stored), defined as:

- **Upper band:** `VWAP + band_std * vwap_std`
- **Lower band:** `VWAP - band_std * vwap_std`

The z-score of current price relative to VWAP is:

```python
zscore = (curr_price - curr_vwap) / curr_std
```

---

## VWAP Slope

The slope is computed as the absolute change in VWAP over `slope_period` bars:

```python
vwap_slope = curr_vwap - vwap[-1 - slope_period]
slope_pct = vwap_slope / curr_vwap
```

A positive slope with `slope_pct >= slope_min_pct` indicates an uptrend. A negative slope with `abs(slope_pct) >= slope_min_pct` indicates a downtrend.

---

## Entry Conditions

### LONG

All must be true:

1. **VWAP slope positive** and meets minimum slope threshold.
2. **Price pulls back below VWAP** with z-score <= -pullback_z (adjusted for regime).
3. **Volume above average**: `volume_ratio >= volume_multiplier`.
4. **Momentum improving**: `curr_mom > prev_mom`.

### SHORT

All must be true:

1. **VWAP slope negative** and meets minimum slope threshold.
2. **Price pulls back above VWAP** with z-score >= pullback_z (adjusted for regime).
3. **Volume above average**: `volume_ratio >= volume_multiplier`.
4. **Momentum weakening**: `curr_mom < prev_mom`.

### Regime-Adjusted Pullback Z-Score

The z-score threshold is dynamically adjusted based on the current regime:

```python
pullback_z = 0.6  # base

# Trend regime: easier entry (lower z required)
if trend_regime == "trend":
    pullback_z += -0.12   # -> 0.48

# Range regime: harder entry (higher z required)
elif trend_regime == "range":
    pullback_z += 0.12    # -> 0.72

# Vol adjustments stack on top
if vol_regime == "high_vol":
    pullback_z += 0.10    # Wider pullback needed
elif vol_regime == "low_vol":
    pullback_z += -0.05   # Easier entry in calm markets

pullback_z = max(0.2, pullback_z)  # Floor at 0.2
```

---

## Strength and Confidence Scoring

Base strength: `0.35 + min(abs(zscore) / band_std, 0.3)` -- deeper pullbacks produce stronger signals.

Modifiers (each +0.10 strength or confidence):

| Condition                         | Strength | Confidence |
|-----------------------------------|----------|------------|
| Volume ratio >= multiplier        | +0.10    | +0.10      |
| Momentum confirming               | +0.10    | +0.10      |
| Strong VWAP slope (> 0.1%)        | --       | +0.10      |
| Deep pullback (z-score > 1.0)     | --       | +0.10      |

Maximum possible: strength ~0.85, confidence ~0.75.

---

## SL/TP

- **Stop loss:** 2.0x ATR
- **Take profit:** 3.0x ATR

```python
stop_loss, take_profit = compute_sl_tp(
    curr_price, curr_atr, side, 2.0, 3.0, round_trip_fee_pct=fee_pct
)
```

---

## Signal Metadata

```python
{
    "vwap": 97234.123456,
    "vwap_std": 142.567890,
    "zscore": -0.8234,
    "vwap_slope": 12.345678,
    "slope_pct": 0.000127,
    "volume_ratio": 1.45,
    "momentum": 0.002345,
    "pullback_z": 0.48,
    "trend_regime": "trend",
    "vol_regime": "mid_vol",
}
```

---

## Confluence Integration

- **Strategy name:** `"vwap_momentum_alpha"`
- **Family:** `"vwap"` (unique family -- always contributes to diversity bonus).
- **Registration:** Listed in both `ConfluenceDetector.__init__` strategy list and the `configure_strategies()` strategy map.

### Regime Multipliers

| Regime     | Multiplier | Notes                                        |
|------------|-----------|-----------------------------------------------|
| Trending   | 1.2       | VWAP pullbacks work well in trends            |
| Ranging    | 1.0       | Neutral (VWAP slope is flat in ranges anyway) |
| High vol   | 0.9       | Slightly downweighted (noisy VWAP)            |
| Low vol    | 1.1       | Cleaner VWAP signals in calm markets          |

### Re-activation History

The strategy was originally added in v3.5 but was removed from the active strategy list in v4.0 when Ichimoku was promoted. In v4.5, it was re-activated with:

1. Addition to `ConfluenceDetector.__init__` strategy list with `weight=0.15`.
2. Addition to the `strategy_map` in `configure_strategies()`.
3. Regime-adaptive pullback z-score thresholds (new in v4.5).
4. Proper regime multiplier entries in all four default weight maps.
