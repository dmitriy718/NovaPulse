# Adaptive Exit System

**Version:** 5.0.0
**Date:** 2026-02-27
**Sources:** `src/execution/executor.py` (TradeExecutor), `src/execution/risk_manager.py` (RiskManager)

---

## Overview

NovaPulse uses a layered exit system: smart exit tiers for partial profit-taking, time-based TP tightening for stagnant positions, volatility-regime-aware trailing stops, exchange-native stop orders as crash-proof backstops, and hold-duration optimization based on historical strategy performance. All layers work in concert inside `_manage_position_inner()`.

---

## Smart Exit Tiers

Smart exit is controlled by `smart_exit_enabled` and `smart_exit_tiers` in the TradeExecutor constructor. The default tier structure when enabled:

| Tier | TP Multiplier | Position % Closed | Action           |
|------|---------------|-------------------|------------------|
| 1    | 1.0x          | 50%               | Partial close    |
| 2    | 1.5x          | 30%               | Partial close    |
| 3    | 0 (trailing)  | 20%               | Trail remainder  |

The TP multiplier is applied to the original TP distance: `tier_target = entry + tp_distance * tp_mult` for longs.

When a tier triggers:

1. Partial quantity is computed: `partial_qty = trade["quantity"] * tier_pct`.
2. If partial_qty covers the full remaining position, route through normal `_close_position()`.
3. Otherwise, `_close_partial()` calculates partial P&L (net of taker fees), updates metadata with `exit_tier`, accumulated `partial_pnl_accumulated`, and reduces the risk manager's tracked exposure via `reduce_position_size(trade_id, reduction_fraction=...)`.
4. When `tp_mult == 0`, the tier is "trailing only" -- handled by normal SL logic, not the smart exit check.

The final trade close sums the accumulated partial P&L:

```python
partial_pnl = float(meta.get("partial_pnl_accumulated", 0.0))
pnl += partial_pnl
```

---

## Time-Based Exit Tightening

Implemented directly in `_manage_position_inner()` in executor.py. Stagnant positions have their TP pulled closer to entry:

```python
# >60 min with < 1.0% profit -> TP to 40% of original distance
if age_minutes > 60 and pnl_pct < 0.01:
    new_tp = entry_price + (take_profit - entry_price) * 0.4  # long

# >30 min with < 0.5% profit -> TP to 60% of original distance
elif age_minutes > 30 and pnl_pct < 0.005:
    new_tp = entry_price + (take_profit - entry_price) * 0.6  # long
```

The tightened TP is persisted to the DB immediately and used for the remainder of that scan cycle. This prevents positions from sitting indefinitely in a narrow range, burning opportunity cost.

---

## Vol-Regime-Aware Trailing Stops

In `RiskManager.update_stop_loss()`, the trailing step is adjusted based on the vol_regime string passed from the trade's metadata:

```python
trailing_step = self.trailing_step_pct    # Base (e.g., 0.005 = 0.5%)
if vol_regime == "high_vol":
    trailing_step *= 1.5                  # 0.75% -- more room
elif vol_regime == "low_vol":
    trailing_step *= 0.7                  # 0.35% -- tighter
```

### Trailing Stop Lifecycle (Long Side)

1. **Breakeven activation** at `breakeven_activation_pct` (default 1.0%): SL is moved to entry price.
2. **Trailing activation** at `trailing_activation_pct` (default 1.5%): SL follows the trailing high.
3. **Base trail**: `new_sl = trailing_high * (1 - trailing_step)`.
4. **Acceleration at 3%+ profit**: `trailing_step * 0.5` (tighter).
5. **Acceleration at 5%+ profit**: `trailing_step * 0.3` (aggressive lock-in).
6. **One-way ratchet**: SL only moves up (long) or down (short), never backwards.

The vol_regime is stored in trade metadata at entry time and retrieved on each management cycle:

```python
meta = self._parse_meta(trade.get("metadata"))
vol_regime = meta.get("vol_regime", "")
state = self.risk_manager.update_stop_loss(trade_id, current_price, entry_price, side, vol_regime=vol_regime)
```

---

## Exchange-Native Stop Orders

After every trade entry in live mode, a stop-loss order is placed directly on the exchange as a crash-proof backstop:

```python
if self.mode == "live" and adjusted_sl > 0:
    await self._place_exchange_stop(trade_id, pair, side, adjusted_sl, filled_units)
```

This uses `rest_client.place_order()` with `order_type="stop-loss"` and `reduce_only=True`. The stop order txid is stored in trade metadata under `exchange_stop_txid`.

When the software trailing stop moves the SL significantly (>0.5% price change), `_update_exchange_stop()` cancels the old exchange stop and places a new one at the updated price. If the replacement fails, the trade is flagged with `software_stop_only: true` in metadata.

On position close, `_cancel_exchange_stop()` cleans up any remaining exchange stop order.

---

## Breakeven Activation

Configurable via `breakeven_activation_pct` (default 0.01 = 1%). When unrealized P&L reaches this threshold, the stop loss is moved to the entry price, guaranteeing at minimum a breakeven exit (minus fees).

```python
if not state.breakeven_activated and pnl_pct >= self.breakeven_activation_pct:
    state.breakeven_activated = True
    state.current_sl = max(state.current_sl, entry_price)  # Long
```

Breakeven always activates before trailing (since `breakeven_activation_pct < trailing_activation_pct` by default).

---

## Hold-Duration Optimization

The executor queries the confluence detector for the average winning hold time of the primary strategy:

```python
avg_win_hours = self._confluence.avg_winning_hold_hours(strategy_name)
if avg_win_hours > 0 and age_hours > 2 * avg_win_hours:
    # Tighten SL to 50% of current distance from price
    distance = current_price - state.current_sl  # long
    tightened = current_price - distance * 0.5
    if tightened > state.current_sl:
        state.current_sl = tightened
```

If a trade has been open for more than **2x** the strategy's average winning hold duration, the trailing stop is tightened to 50% of the current SL distance. This prevents "hope trades" from eroding gains.

The `avg_winning_hold_hours()` method on BaseStrategy computes the mean from the strategy's `_recent_trades` deque, filtering for winning trades only.

---

## Max Trade Duration

A hard cap on trade duration is enforced via `max_trade_duration_hours` (default 24):

```python
if age_hours >= max_duration_hours:
    await self._close_position(..., reason="max_duration")
```

This is checked before any stop/TP logic, ensuring positions never remain open indefinitely regardless of other exit conditions.

---

## Exit Priority Order

Within `_manage_position_inner()`, exit checks execute in this order:

1. **Max duration** -- auto-close if trade exceeds configured hours.
2. **Trailing stop update** -- adjust SL based on price movement.
3. **Time-based TP tightening** -- reduce TP for stagnant positions.
4. **Hold-duration optimization** -- tighten SL for overstaying trades.
5. **Stop-out check** -- close if price has breached the (possibly tightened) SL.
6. **Smart exit tiers** -- partial close at tier targets.
7. **Take profit** -- flat TP hit check.
8. **Persist SL changes** -- update DB and exchange stop if SL moved.
