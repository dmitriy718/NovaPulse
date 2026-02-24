# Correlation-Based Position Sizing

**Version:** 4.5.0
**Date:** 2026-02-24
**Source:** `src/execution/risk_manager.py`
**Class:** `RiskManager`

---

## Overview

Correlation-based position sizing reduces exposure when a new trade candidate is highly correlated with existing open positions. This prevents concentrated directional risk -- for example, going full-size into ETH/USD when an equally-sized BTC/USD long is already open and the two assets move in lockstep.

---

## Price History Tracking

```python
# In RiskManager.__init__:
self._price_history: Dict[str, Deque[float]] = {}
```

Each pair gets a rolling deque of the last **100** price ticks:

```python
def update_price(self, pair: str, price: float) -> None:
    if pair not in self._price_history:
        self._price_history[pair] = deque(maxlen=100)
    self._price_history[pair].append(price)
```

`update_price()` is called from the engine's scan loop on every price update for every active pair, ensuring the correlation calculation always has recent data.

---

## Correlation Factor Computation

```python
def _get_correlation_factor(self, pair: str) -> float:
```

The method computes the **Pearson correlation coefficient** between the candidate pair's price series and every open position's pair price series, using numpy:

```python
corr = float(np.corrcoef(a, b)[0, 1])
```

### Algorithm

1. Retrieve the candidate pair's price history. If fewer than 20 ticks, return 1.0 (no reduction).
2. For each open position's pair (excluding the candidate itself):
   - Retrieve its price history. Skip if fewer than 20 ticks.
   - Align arrays to the minimum overlapping length (at least 20 bars).
   - Skip if either array has zero standard deviation (flat price = no meaningful correlation).
   - Compute Pearson correlation, take absolute value.
   - Track the maximum correlation across all open positions.
3. Apply reduction formula:

```python
if max_corr > 0.7:
    return max(0.5, 1.0 - (max_corr - 0.7) * 2)
return 1.0
```

### Reduction Curve

| Max Correlation | Factor | Size Reduction |
|----------------|--------|----------------|
| <= 0.70        | 1.00   | 0%             |
| 0.75           | 0.90   | 10%            |
| 0.80           | 0.80   | 20%            |
| 0.85           | 0.70   | 30%            |
| 0.90           | 0.60   | 40%            |
| 0.95           | 0.50   | 50% (floor)    |
| 1.00           | 0.50   | 50% (floor)    |

The floor is **0.5** -- no trade is reduced by more than 50% due to correlation alone. This ensures the bot can still trade correlated assets, just at reduced size.

---

## Integration in Position Sizing Pipeline

The correlation factor is applied **after** the volatility factor and **before** the max position cap in `calculate_position_size()`:

```python
# Volatility regime sizing
vol_factor = self._get_volatility_factor(vol_regime, vol_level, vol_expanding)
position_size_usd *= vol_factor

# Correlation-based sizing
corr_factor = self._get_correlation_factor(pair)
position_size_usd *= corr_factor

# Apply maximum position cap
position_size_usd = min(position_size_usd, self.max_position_usd)
```

The full sizing pipeline order:

1. Fixed fractional risk sizing (primary)
2. Kelly Criterion cap (if 50+ trades and positive edge)
3. Drawdown scaling factor
4. Streak-based sizing (win/loss streaks)
5. Spread penalty (wide spreads reduce size)
6. **Volatility regime factor**
7. **Correlation factor** <-- here
8. Max position USD cap
9. Portfolio heat limit (remaining capacity from local + global risk)
10. Minimum $10 check

---

## Example Scenario

Suppose BTC/USD is open with a long position:

1. ETH/USD signal arrives. Engine has been calling `update_price("ETH/USD", price)` on every tick.
2. `_get_correlation_factor("ETH/USD")` runs:
   - Gets ETH/USD price history (100 ticks).
   - Iterates open positions, finds BTC/USD.
   - Gets BTC/USD price history (100 ticks).
   - Aligns to 100 bars, computes Pearson correlation = **0.85**.
   - `max_corr = 0.85 > 0.7`, so factor = `max(0.5, 1.0 - (0.85 - 0.7) * 2)` = `max(0.5, 0.70)` = **0.70**.
3. Position size is multiplied by 0.70, resulting in a **30% reduction**.

If a third correlated asset (e.g., SOL/USD) tries to enter while both BTC and ETH are open, the correlation factor is computed against both -- the maximum correlation (likely still BTC at ~0.80+) determines the reduction.

---

## Caveats

- **Price history is in-memory only.** After a restart, the deques are empty and correlation cannot be computed until 20+ ticks accumulate (typically a few minutes of WebSocket data).
- **Correlation is computed on raw prices, not returns.** This means two assets trending upward will show high correlation even if their short-term moves are independent. For the purpose of risk management (avoiding concentrated directional exposure), this is the desired behavior.
- **Only pairs with open positions are compared.** Pairs that were recently closed but might re-enter are not considered.
