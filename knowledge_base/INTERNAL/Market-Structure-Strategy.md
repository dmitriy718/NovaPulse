# Market Structure Strategy

**Version:** 4.5.0
**Date:** 2026-02-24
**Source:** `src/strategies/market_structure.py`
**Class:** `MarketStructureStrategy(BaseStrategy)`

---

## Overview

The Market Structure strategy identifies trend structure via swing point analysis (higher highs / higher lows for uptrends, lower highs / lower lows for downtrends) and enters on pullbacks to previous swing levels. It is a structure-based strategy that trades with the trend rather than against it, confirmed by RSI, volume, and momentum filters.

---

## Configuration

| Parameter                | Default | Description                                     |
|--------------------------|---------|-------------------------------------------------|
| `swing_lookback`         | 5       | N-bar lookback for swing detection (min 2)      |
| `pullback_tolerance_pct` | 0.005   | Max distance from swing level (0.5%)            |
| `rsi_floor`              | 35      | Minimum RSI for long entries                    |
| `rsi_ceiling`            | 65      | Maximum RSI for short entries                   |
| `atr_period`             | 14      | ATR period for SL/TP computation                |
| `weight`                 | 0.12    | Confluence weight                               |
| `enabled`                | True    | Strategy toggle                                 |

Minimum bars required: `max(swing_lookback * 6 + 10, 50)`.

---

## Swing Detection

The static method `_find_swings()` iterates through the price series and identifies swing points:

```python
@staticmethod
def _find_swings(
    highs: np.ndarray, lows: np.ndarray, lookback: int,
) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
```

A **swing high** occurs at bar `i` when `highs[i]` is the maximum of the window `[i - lookback : i + lookback + 1]`. A **swing low** occurs when `lows[i]` is the minimum of the same window. Each swing is stored as an `(index, price)` tuple.

The lookback parameter controls the granularity: larger values find more significant swing points but require more data and produce fewer swings.

---

## Trend Detection

Using the last 2 swing highs (SH) and last 2 swing lows (SL):

```python
higher_highs = sh[1][1] > sh[0][1]
higher_lows  = sl[1][1] > sl[0][1]
lower_highs  = sh[1][1] < sh[0][1]
lower_lows   = sl[1][1] < sl[0][1]

uptrend   = higher_highs and higher_lows   # HH + HL
downtrend = lower_highs  and lower_lows    # LH + LL
```

At least **2 swing highs and 2 swing lows** are required. If the structure is ambiguous (e.g., HH + LL), the signal is NEUTRAL.

---

## Entry Conditions

### LONG (Uptrend)

All must be true:

1. **Uptrend detected** (HH + HL pattern).
2. **Price pulled back** to within `pullback_tolerance_pct` of the most recent swing low: `curr_price <= prev_swing_low * (1 + tolerance)`.
3. **RSI > rsi_floor** (not oversold; default RSI > 35).

Strength/confidence bonuses:
- **Distance bonus**: Price very close to swing low (within 50% of tolerance): +0.10 strength, +0.08 confidence.
- **Volume confirmation**: Volume ratio > 1.0 (above average): +0.10 strength, +0.08 confidence.
- **Momentum improving**: Current momentum > previous momentum: +0.10 strength, +0.08 confidence.
- **Trend width bonus**: HH spread > 1% between consecutive swing highs: +0.10 confidence.

### SHORT (Downtrend)

All must be true:

1. **Downtrend detected** (LH + LL pattern).
2. **Price pulled back** to within `pullback_tolerance_pct` of the most recent swing high: `curr_price >= prev_swing_high * (1 - tolerance)`.
3. **RSI < rsi_ceiling** (not overbought; default RSI < 65).

Same bonus structure as LONG, with momentum weakening instead of improving.

---

## SL/TP Computation

Uses `compute_sl_tp()` from `src/utils/indicators`:

- **Stop loss:** 2.0x ATR below entry (long) or above entry (short).
- **Take profit:** 3.5x ATR above entry (long) or below entry (short).
- Fee adjustment: `round_trip_fee_pct` is passed through to widen TP past the breakeven point.

```python
stop_loss, take_profit = compute_sl_tp(
    curr_price, curr_atr, side, sl_mult=2.0, tp_mult=3.5,
    round_trip_fee_pct=fee_pct,
)
```

---

## Indicator Cache Usage

The strategy uses `indicator_cache` (passed via kwargs) for all indicator computation to avoid redundant recalculation across strategies:

| Indicator       | Method                    | Period |
|-----------------|---------------------------|--------|
| RSI             | `cache.rsi(14)`           | 14     |
| ATR             | `cache.atr(atr_period)`   | 14     |
| Volume Ratio    | `cache.volume_ratio(20)`  | 20     |
| Momentum        | `cache.momentum(5)`       | 5      |

Falls back to direct indicator function calls if no cache is provided.

---

## Signal Metadata

The returned `StrategySignal.metadata` dict includes:

```python
{
    "uptrend": True,
    "downtrend": False,
    "swing_highs": 5,       # Total swing highs detected
    "swing_lows": 4,        # Total swing lows detected
    "rsi": 42.15,
    "atr": 0.000823,
    "volume_ratio": 1.34,
    "momentum": 0.000156,
}
```

---

## Confluence Integration

In the confluence detector:

- **Family:** `"structure"` (unique family -- contributes to diversity bonus).
- **Default weight:** 0.12 (normalized).
- **Regime multipliers:**

| Regime     | Multiplier | Notes                               |
|------------|-----------|--------------------------------------|
| Trending   | 1.1       | Structure aligns well with trends    |
| Ranging    | 0.9       | Swing structure less reliable        |
| High vol   | 1.0       | Neutral                              |
| Low vol    | 1.0       | Not in low_vol map (defaults to 1.0) |

- **Binary gating:** Not included in either `_TREND_STRATEGIES` or `_MEAN_REVERSION_STRATEGIES`, so it is never hard-gated by regime.
