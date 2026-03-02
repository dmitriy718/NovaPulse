# NovaPulse Technical Indicator Library

**Version:** 5.0.0
**Last Updated:** 2026-02-27

---

## Overview

All technical indicator computations are centralized in a single module with vectorized NumPy implementations. No strategy computes its own indicators directly -- they either call functions from the indicator library or retrieve precomputed values from the `IndicatorCache`. This architecture ensures consistency (every strategy sees the same RSI for the same data), eliminates redundant computation, and keeps hot-path code free of Python loops.

---

## Indicator Functions

**File:** `src/utils/indicators.py` (~713 lines)

Every function takes NumPy arrays as input and returns NumPy arrays. No pandas dependency.

### Moving Averages

| Function | Signature | Description |
|----------|-----------|-------------|
| `ema(data, period)` | `np.ndarray, int -> np.ndarray` | Exponential Moving Average using Wilder smoothing factor `2/(period+1)` |
| `sma(data, period)` | `np.ndarray, int -> np.ndarray` | Simple Moving Average via cumulative sum trick |

EMA is seeded with the SMA of the first `period` values. Output length equals input length; the first `period-1` values are `NaN`.

### RSI

```python
def rsi(close: np.ndarray, period: int = 14) -> np.ndarray:
```

Relative Strength Index using the Wilder smoothing method:

1. Compute price deltas: `delta = np.diff(close)`
2. Separate gains and losses
3. Compute initial average gain/loss as SMA of first `period` values
4. Subsequent values: `avg_gain = (prev_avg_gain * (period-1) + gain) / period`
5. RS = avg_gain / avg_loss
6. RSI = 100 - (100 / (1 + RS))

Returns array of length `len(close)` with first `period` values as `NaN`.

### MACD

```python
def macd(close: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9
        ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
```

Returns `(macd_line, signal_line, histogram)`:
- `macd_line = EMA(fast) - EMA(slow)`
- `signal_line = EMA(macd_line, signal)`
- `histogram = macd_line - signal_line`

### Bollinger Bands

```python
def bollinger_bands(close: np.ndarray, period: int = 20, std_dev: float = 2.0
                   ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
```

Returns `(upper, middle, lower)`:
- `middle = SMA(period)`
- `upper = middle + std_dev * rolling_std(period)`
- `lower = middle - std_dev * rolling_std(period)`

Rolling standard deviation uses the population formula (ddof=0) for consistency with TradingView.

### Keltner Channels

```python
def keltner_channels(high: np.ndarray, low: np.ndarray, close: np.ndarray,
                     ema_period: int = 20, atr_period: int = 14, multiplier: float = 1.5
                    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
```

Returns `(upper, middle, lower)`:
- `middle = EMA(close, ema_period)`
- `upper = middle + multiplier * ATR(atr_period)`
- `lower = middle - multiplier * ATR(atr_period)`

### ATR (Average True Range)

```python
def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14
       ) -> np.ndarray:
```

True Range = max(high-low, abs(high-prev_close), abs(low-prev_close)). ATR = EMA(True Range, period).

### ADX (Average Directional Index)

```python
def adx(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14
       ) -> np.ndarray:
```

Computes +DI, -DI, and ADX using Wilder smoothing. Returns the ADX array only. Values above 25 indicate a trending market; below 20 indicates ranging.

### Supertrend

```python
def supertrend(high: np.ndarray, low: np.ndarray, close: np.ndarray,
               period: int = 10, multiplier: float = 3.0
              ) -> Tuple[np.ndarray, np.ndarray]:
```

Returns `(supertrend_line, direction)`:
- `direction[i] = 1` (bullish) or `-1` (bearish)
- Band flip logic: upper band flips to support when broken, lower band flips to resistance

### Ichimoku Cloud

```python
def ichimoku(high: np.ndarray, low: np.ndarray, close: np.ndarray,
             tenkan: int = 9, kijun: int = 26, senkou_b: int = 52, displacement: int = 26
            ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
```

Returns 5 lines: `(tenkan_sen, kijun_sen, senkou_span_a, senkou_span_b, chikou_span)`.

- Tenkan-sen: (highest high + lowest low) / 2 over `tenkan` periods
- Kijun-sen: (highest high + lowest low) / 2 over `kijun` periods
- Senkou Span A: (tenkan + kijun) / 2, displaced forward by `displacement`
- Senkou Span B: (highest high + lowest low) / 2 over `senkou_b`, displaced forward
- Chikou Span: close displaced backward by `displacement`

### Stochastic K/D

```python
def stochastic(high: np.ndarray, low: np.ndarray, close: np.ndarray,
               k_period: int = 14, d_period: int = 3
              ) -> Tuple[np.ndarray, np.ndarray]:
```

Returns `(k_line, d_line)`:
- `%K = 100 * (close - lowest_low(k_period)) / (highest_high(k_period) - lowest_low(k_period))`
- `%D = SMA(%K, d_period)`

### VWAP

```python
def vwap(high: np.ndarray, low: np.ndarray, close: np.ndarray,
         volume: np.ndarray) -> np.ndarray:
```

Volume-Weighted Average Price: `cumsum(typical_price * volume) / cumsum(volume)` where `typical_price = (high + low + close) / 3`. Resets at session boundaries are not implemented (continuous VWAP).

### Garman-Klass Volatility

```python
def garman_klass(open_: np.ndarray, high: np.ndarray, low: np.ndarray,
                 close: np.ndarray, period: int = 20) -> np.ndarray:
```

A more efficient volatility estimator than close-to-close:
```
GK = 0.5 * ln(H/L)^2 - (2*ln(2) - 1) * ln(C/O)^2
```
Returns rolling mean of GK over `period` bars.

### Momentum

```python
def momentum(close: np.ndarray, period: int = 10) -> np.ndarray:
```

Simple rate of change: `(close[i] - close[i-period]) / close[i-period]`.

### OBV (On-Balance Volume)

```python
def obv(close: np.ndarray, volume: np.ndarray) -> np.ndarray:
```

Cumulative: add volume on up-closes, subtract on down-closes.

### SL/TP Computation

```python
def compute_sl_tp(entry_price: float, side: str, atr_value: float,
                  sl_atr_mult: float = 2.0, tp_atr_mult: float = 4.0,
                  fee_pct: float = 0.001,
                  sl_floor_pct: float = 0.025, tp_floor_pct: float = 0.05
                 ) -> Tuple[float, float]:
```

Fee-aware stop-loss and take-profit:

1. Raw SL distance = `atr_value * sl_atr_mult`
2. Raw TP distance = `atr_value * tp_atr_mult`
3. Adjust for round-trip fees: `sl_distance -= entry_price * fee_pct * 2`
4. Apply percentage floors: `sl_distance = max(sl_distance, entry_price * sl_floor_pct)`
5. Compute absolute levels based on `side` (LONG: entry - SL / entry + TP)

Returns `(stop_loss_price, take_profit_price)`.

---

## IndicatorCache

**File:** `src/utils/indicator_cache.py` (~194 lines)
**Class:** `IndicatorCache`

### Purpose

Multiple strategies need the same indicator values for the same pair in the same scan cycle. Without caching, RSI(14) would be computed 4+ times per pair per scan (by Mean Reversion, Keltner, Stochastic Divergence, and the ML feature extractor). The `IndicatorCache` ensures each indicator is computed exactly once per pair per cycle.

### Interface

```python
cache = IndicatorCache()

# Strategy or engine requests an indicator:
rsi_values = cache.get_or_compute("BTC/USD:rsi_14", lambda: indicators.rsi(closes, 14))

# Same key in same cycle returns cached result (no recomputation):
rsi_values = cache.get_or_compute("BTC/USD:rsi_14", lambda: indicators.rsi(closes, 14))

# Reset at the start of each scan cycle:
cache.reset()
```

### Key Naming Convention

Cache keys follow the pattern `{pair}:{indicator}_{params}`:

| Key Example | Indicator |
|-------------|-----------|
| `BTC/USD:rsi_14` | RSI with period 14 |
| `BTC/USD:atr_14` | ATR with period 14 |
| `BTC/USD:ema_20` | EMA with period 20 (fast) |
| `BTC/USD:ema_50` | EMA with period 50 (slow) |
| `BTC/USD:adx_14` | ADX with period 14 |
| `BTC/USD:bb_upper_20_2.0` | Bollinger upper band |
| `BTC/USD:bb_lower_20_2.0` | Bollinger lower band |
| `BTC/USD:bb_middle_20_2.0` | Bollinger middle band |
| `BTC/USD:macd_line_12_26_9` | MACD line |
| `BTC/USD:macd_signal_12_26_9` | MACD signal line |
| `BTC/USD:macd_hist_12_26_9` | MACD histogram |
| `BTC/USD:volume_ratio_20` | Volume / SMA(volume, 20) |
| `BTC/USD:momentum_10` | 10-bar momentum |

### Lifecycle

```
scan_loop iteration starts
  -> cache.reset()                        # clear all cached values
  -> for each pair in universe:
       -> strategies run, calling cache.get_or_compute() for indicators
       -> first call computes, subsequent calls return cached
  -> scan_loop iteration ends
```

The cache is **not** thread-safe by design -- it runs within a single asyncio task (the scan loop) and is never accessed concurrently. The reset at the start of each cycle prevents stale data from persisting across cycles.

### Passing to Strategies

The engine passes the cache to each strategy's `evaluate()` method via kwargs:

```python
signal = strategy.evaluate(
    pair=pair,
    closes=closes,
    highs=highs,
    lows=lows,
    volumes=volumes,
    indicator_cache=cache,
    **kwargs
)
```

Strategies use `indicator_cache.get_or_compute()` internally rather than calling indicator functions directly.

---

## Performance Characteristics

All indicator functions are implemented with vectorized NumPy operations. There are no Python-level loops over bar data. Typical computation times on a 500-bar array:

| Indicator | Approximate Time |
|-----------|-----------------|
| EMA(20) | ~15 us |
| RSI(14) | ~25 us |
| MACD(12,26,9) | ~40 us |
| Bollinger Bands(20) | ~30 us |
| ATR(14) | ~20 us |
| ADX(14) | ~50 us |
| Ichimoku (all 5 lines) | ~60 us |
| Full indicator set (all) | ~350 us |

With the `IndicatorCache`, the full indicator set is computed once per pair per cycle. For a 30-pair universe, total indicator computation per scan cycle is approximately 10ms.
