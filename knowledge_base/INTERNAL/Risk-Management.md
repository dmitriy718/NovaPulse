# NovaPulse Risk Management

**Version:** 4.0.0
**Last Updated:** 2026-02-22

---

## Overview

The NovaPulse risk management system provides multi-layered capital preservation through position sizing, stop loss management, daily loss limits, and circuit breakers. The primary goal is to survive losing streaks and protect the bankroll while allowing profitable trades to compound.

**File:** `src/execution/risk_manager.py`
**Class:** `RiskManager`

---

## Position Sizing

### Primary Method: Fixed Fractional Risk

The bot sizes every position based on a fixed percentage of the current bankroll:

```
risk_amount = bankroll * max_risk_per_trade
position_size_usd = risk_amount / stop_loss_distance_pct
```

Default: `max_risk_per_trade = 0.02` (2% of bankroll per trade).

This means if the bankroll is $10,000 and the stop loss distance is 2.5%, the raw position size would be:

```
risk_amount = $10,000 * 0.02 = $200
position_size = $200 / 0.025 = $8,000
```

### Secondary Method: Kelly Criterion Cap

Kelly Criterion is used as a **cap only** -- it never increases position size beyond fixed fractional, it can only reduce it.

**Kelly Formula:**
```
kelly_full = max((p * b - q) / b, 0)
kelly_adjusted = kelly_full * kelly_fraction * confidence
kelly_adjusted = min(kelly_adjusted, max_kelly_size)
```

Where:
- `p` = win rate (from DB performance stats)
- `q` = 1 - p
- `b` = average win / average loss ratio
- `kelly_fraction` = 0.25 (quarter-Kelly for safety)
- `confidence` = AI confidence in the signal (0-1)
- `max_kelly_size` = 0.10 (absolute cap at 10% of bankroll)

**Kelly only activates after 50+ trades** and only when the edge is positive (`kelly_full > 0`). With fewer than 50 trades, Kelly is skipped entirely to allow the bot to collect training data.

### Position Size Adjustments

After the base size is calculated, multiple adjustment factors are applied multiplicatively:

#### 1. Drawdown Scaling

Reduces position size as drawdown from peak bankroll increases:

| Drawdown | Size Factor |
|----------|------------|
| < 3% | 1.00 (full size) |
| 3-7% | 0.80 |
| 7-12% | 0.60 |
| 12-18% | 0.35 |
| > 18% | 0.15 |

#### 2. Streak-Based Sizing

- **3+ consecutive losses:** reduces size by 15% per additional loss (min 0.4x)
- **3+ consecutive wins:** increases size by 5% per additional win (max 1.2x)

#### 3. Spread-Adjusted Sizing

Wide spreads eat into the edge, so position size is reduced:
```
If spread > 0.1%:
    spread_penalty = max(0.5, 1.0 - (spread - 0.001) * 50)
    position_size *= spread_penalty
```

#### 4. Volatility Regime Sizing

| Condition | Factor |
|-----------|--------|
| Low vol + vol_level < 0.3 | 1.15 (slightly larger) |
| High vol + vol_level > 0.8 | 0.60 |
| High vol + vol_level > 0.7 | 0.70 |
| High vol (general) | 0.80 |
| Vol expanding (any regime) | x0.60 additional |

Minimum factor: 0.30 (never reduces below 30% of base size).

#### 5. Caps

After all adjustments:
- `max_position_usd` hard cap (default $500)
- Portfolio heat limit: total exposure cannot exceed `max_total_exposure_pct` of bankroll (default 50%)
- Minimum position: $10 (below this, trade is rejected)

### Config

```yaml
risk:
  max_risk_per_trade: 0.02
  max_daily_loss: 0.05
  max_position_usd: 500.0
  initial_bankroll: 10000.0
  kelly_fraction: 0.25
  max_kelly_size: 0.10
  max_daily_trades: 0           # 0 = unlimited
  max_total_exposure_pct: 0.50
```

---

## Stop Loss Management

### Initial Stop Loss Placement

Stop losses are computed by each strategy using ATR:

```
SL distance = ATR * atr_multiplier_sl (default 2.0)
TP distance = ATR * atr_multiplier_tp (default 3.0)
```

**Percentage floors** prevent unreasonably tight stops on low-timeframe candles:
- Minimum SL: 2.5% from entry
- Minimum TP: 5.0% from entry

When a fill occurs at a price different from the planned entry, SL/TP are shifted by the same delta to maintain consistent risk distances (`_shift_levels_to_fill()`).

### Trailing Stop

The trailing stop system has three phases:

#### Phase 1: Initial Stop (no movement)
The stop stays at the initial level until breakeven activation.

#### Phase 2: Breakeven Activation
When unrealized P&L reaches `breakeven_activation_pct` (default 1.0%):
- For longs: stop moves up to entry price (breakeven)
- For shorts: stop moves down to entry price

#### Phase 3: Trailing Stop Activation
When unrealized P&L reaches `trailing_activation_pct` (default 1.5%):
- Stop begins trailing the highest price (for longs) or lowest price (for shorts)
- Trail distance: `trailing_step_pct` (default 0.5%)

**Acceleration on large profits:**
- P&L > 5%: trail tightens to 0.3x of `trailing_step_pct` (locks in gains aggressively)
- P&L > 3%: trail tightens to 0.5x of `trailing_step_pct`

**Critical rule:** Stops only move in the profitable direction -- never backwards.

### Exchange-Native Stop Orders

In live mode, an exchange-native stop-loss order is placed as a **crash-proof backstop**:
- Placed at the initial SL price via `rest_client.place_order(order_type="stop-loss")`
- Updated when the trailing stop moves significantly (> 0.5% change)
- Cancelled when the position is closed normally
- Acts as safety net if the bot process crashes or loses connectivity

The exchange stop txid is stored in the trade's metadata for later amendment/cancellation.

### Config

```yaml
risk:
  atr_multiplier_sl: 2.0
  atr_multiplier_tp: 3.0
  trailing_activation_pct: 0.015
  trailing_step_pct: 0.005
  breakeven_activation_pct: 0.01
```

---

## Smart Exit (Partial Position Closes)

When enabled, smart exit closes the position in tiered chunks instead of waiting for the flat TP or stop-out.

### Default Tiers

| Tier | Close % | TP Multiplier | Description |
|------|---------|---------------|-------------|
| 1 | 50% | 1.0x | Close half at original TP distance |
| 2 | 60% | 1.5x | Close 60% of remainder at 1.5x TP |
| 3 | 100% | 0 (trailing) | Let rest ride with trailing stop |

### How It Works

1. Each position management cycle checks if the current price has reached the next tier target
2. `tier_target = entry + tp_distance * tp_mult` (for longs)
3. When triggered, a partial close is executed (market order in live mode)
4. The remaining quantity is updated in the DB
5. `RiskManager.reduce_position_size()` updates tracked exposure
6. Partial P&L is accumulated in `metadata.partial_pnl_accumulated`
7. When the final close happens, accumulated partial P&L is added to the total

### Config

```yaml
risk:
  smart_exit:
    enabled: false     # Off by default until tested
    tiers:
      - pct: 0.5
        tp_mult: 1.0
      - pct: 0.6
        tp_mult: 1.5
      - pct: 1.0
        tp_mult: 0     # 0 = trailing stop only
```

---

## Pre-Trade Risk Checks

Before any position is opened, the following checks must all pass:

### 1. Global Cooldown
After every losing trade, a global cooldown prevents new entries for `global_cooldown_seconds_on_loss` (default 1800 = 30 minutes).

### 2. Daily Loss Limit
If `daily_pnl <= -(initial_bankroll * max_daily_loss)`, all new entries are blocked. Resets at midnight UTC.

Note: The daily loss check uses the **initial** bankroll (not current) so the limit does not shrink as losses accumulate intraday.

### 3. Per-Pair Cooldown
Each pair has a minimum cooldown between trades: `cooldown_seconds` (default 300 = 5 minutes).

### 4. Max Concurrent Positions
Cannot exceed `max_concurrent_positions` (default 5).

### 5. Daily Trade Cap
If `max_daily_trades > 0`, blocks after that many entries in the current UTC day.

### 6. Risk of Ruin
If the calculated risk of ruin exceeds `risk_of_ruin_threshold` (default 1%), blocks new trades.

### 7. Bankroll Depletion
If `current_bankroll <= 0`, all trades are blocked.

### 8. Stop Loss Distance
Rejects trades with SL distance <= 0% or > 10% of entry price.

### 9. Risk-Reward Ratio
Rejects trades where `TP_distance / SL_distance < min_risk_reward_ratio` (default 1.2).

---

## Risk of Ruin Calculation

Uses the classic formula:

```
RoR = ((1 - edge_ratio) / (1 + edge_ratio)) ^ units
```

Where:
- `edge = win_rate * avg_win - (1 - win_rate) * avg_loss`
- `edge_ratio = edge / avg_bet`
- `units = bankroll / avg_bet`

**Requires 50+ trades** for statistical validity. With fewer trades, returns 0.0 (no block).

If edge is negative (losing overall), returns 1.0 (100% ruin probability, blocks trading).

---

## Circuit Breakers (Monitoring System)

**File:** `src/core/engine.py` (health_monitor method)
**Config:** `monitoring:` section

These circuit breakers automatically pause trading when dangerous conditions are detected:

### 1. Stale Data Auto-Pause
If market data is stale for `stale_data_pause_after_checks` (default 3) consecutive health checks, trading is paused.

### 2. WebSocket Disconnect Auto-Pause
If WebSocket has been disconnected for `ws_disconnect_pause_after_seconds` (default 300), trading is paused.

### 3. Consecutive Losses Auto-Pause
If `consecutive_losses_pause_threshold` (default 4) consecutive losses occur, trading is paused.

### 4. Drawdown Auto-Pause
If drawdown exceeds `drawdown_pause_pct` (default 8.0%), trading is paused.

### Emergency Close on Auto-Pause
When `emergency_close_on_auto_pause: true`, all open positions are closed when any circuit breaker triggers. Default is `false`.

### Config

```yaml
monitoring:
  auto_pause_on_stale_data: true
  stale_data_pause_after_checks: 3
  auto_pause_on_ws_disconnect: true
  ws_disconnect_pause_after_seconds: 300
  auto_pause_on_consecutive_losses: true
  consecutive_losses_pause_threshold: 4
  auto_pause_on_drawdown: true
  drawdown_pause_pct: 8.0
  emergency_close_on_auto_pause: false
```

---

## Position Reconciliation

**File:** `src/execution/executor.py`
**Method:** `reconcile_exchange_positions()`

Runs every 5 minutes (configurable in engine). Compares DB state against exchange state:

### Ghost Positions
DB trade references an `order_txid` not found in exchange open orders. Could mean:
- Order was filled (normal)
- Order was cancelled externally
- Network issue during order placement

### Orphan Orders
Exchange has an open order not tracked by any DB trade. Could mean:
- Manual order placed outside the bot
- DB write failed after order placement
- Race condition during restart

Reconciliation is **informational only** -- nothing is auto-closed or cancelled. It logs warnings for manual investigation.

### Position Reinitialization

On restart, `reinitialize_positions()` restores all open positions from the DB:
- Re-registers each position with `RiskManager` (with `is_restart=True` to skip daily counter increment)
- Restores stop loss state including trailing_high/trailing_low from trade metadata
- Ensures continuity of position management after container restart

---

## Correlation Groups

Pairs in the same correlation group share a position limit to prevent concentrated directional exposure:

| Group | Pairs | Max Concurrent |
|-------|-------|---------------|
| btc | BTC/USD | 2 |
| major | ETH/USD | 2 |
| alt_l1 | SOL/USD, AVAX/USD, DOT/USD, ADA/USD | 2 |
| alt_payment | XRP/USD | 2 |
| alt_oracle | LINK/USD | 2 |

If 2 positions are already open in the `alt_l1` group (e.g., SOL/USD and AVAX/USD), a new DOT/USD signal will be blocked.
