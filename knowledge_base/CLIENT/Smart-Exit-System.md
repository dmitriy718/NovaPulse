# Smart Exit System

**Version:** 5.0.0
**Last updated:** 2026-03-01

Getting into a trade at the right time is important. But getting out at the right time is just as important -- perhaps more so. A perfectly timed entry can still result in a loss if the exit is poorly managed. Nova|Pulse's Smart Exit System is designed to protect profits, limit losses, and adapt to changing market conditions as a trade progresses.

---

## Why Exits Matter as Much as Entries

A common mistake in trading is focusing all attention on when to enter and treating exits as an afterthought. Consider these scenarios:

- **Scenario A:** You enter a great trade that moves 5% in your favor, then reverses and you give it all back. A good exit system would have captured most of that 5%.
- **Scenario B:** You enter a trade that slowly drifts sideways for hours, tying up capital that could be used elsewhere. A time-based exit would free up that capital.
- **Scenario C:** You enter during a volatile session and your trailing stop gets clipped by normal noise. A volatility-aware trailing stop would have given the trade more room.

Nova|Pulse's Smart Exit System handles all of these scenarios through a layered approach.

---

## The Five Exit Mechanisms

Nova|Pulse positions are managed by five complementary mechanisms that work together. Each position is checked every 2 seconds.

### 1. Initial Stop Loss

Every position starts with a stop loss set at entry time.

**How it is calculated:**
- Base distance = 2x ATR (Average True Range) from entry price
- For longs: stop loss is below entry; for shorts: above entry
- Minimum floor of 2.5% is enforced to prevent absurdly tight stops
- Maximum is capped to prevent absurdly wide stops

**What happens when hit:** The position is closed at market price. The loss is recorded and counts toward daily loss limits and consecutive loss tracking.

**Structural Stops (v5.0, optional):** When enabled, the stop is placed behind a recent swing low (for longs) or swing high (for shorts) instead of using a fixed ATR multiplier. This places the stop where the market has demonstrated support/resistance, with a minimum 0.5x ATR buffer added for safety.

### 2. Breakeven Logic

Once a trade moves 3% in your favor (default), the stop loss is moved to the entry price.

**What this achieves:**
- You have a "free trade" -- if the market reverses, you exit at breakeven (minus small fees)
- The risk on this trade is now effectively zero
- You can let the position run without worrying about giving back your initial capital

**When it activates:** The breakeven check runs every position management cycle (every 2 seconds). The moment the position's profit exceeds the threshold, the stop is moved.

### 3. Trailing Stop

Once a trade reaches 4% profit (default), a trailing stop activates.

**How it works:**
- The trailing stop follows the price in the profitable direction
- It never moves backward -- only forward
- Default trailing distance: 0.8% from the highest (longs) or lowest (shorts) price since activation
- If the market pulls back by more than 0.8%, the trailing stop closes the position, locking in most of the profit

**Volatility-regime adaptation:**
- **High volatility:** trailing step is multiplied by 1.5 (more room to breathe, wider trailing). This prevents volatile markets from prematurely triggering the trailing stop on normal swings.
- **Mid volatility:** trailing step stays at the default (1.0x)
- **Low volatility:** trailing step is multiplied by 0.7 (tighter trailing). In calm markets, you want to capture profit quickly because big moves are less likely.

**Adaptive trailing activation:**
The activation threshold also adapts to volatility:
- **Low volatility:** 2.5% profit to activate
- **Mid volatility:** 4.0% profit to activate (default)
- **High volatility:** 6.0% profit to activate (give winners more room to develop)

### 4. Tiered Exit (Smart Exit)

Instead of closing the entire position at one price, the Smart Exit System closes it in three stages:

| Tier | What Happens | When | Example on $300 Position |
|------|-------------|------|-------------------------|
| **Tier 1** | Close 50% of the position | Price reaches 1x take-profit distance | Close $150 at 3% profit |
| **Tier 2** | Close 60% of remaining (30% of original) | Price reaches 1.5x take-profit distance | Close $90 at 4.5% profit |
| **Tier 3** | Close the final 20% | Via trailing stop (no fixed target) | Trail the last $60 until the trend ends |

**Why this is better than a single take-profit:**
- **Locks in profit early:** Tier 1 secures profit on the majority of the position, so even if the trade reverses after that, you have already banked gains.
- **Captures extended moves:** Tiers 2 and 3 stay in the market to capture larger moves when they happen.
- **Reduces regret:** You never have the feeling of "I should have held" (because part of the position is still running) or "I should have taken profit" (because you already took profit on the majority).

### 5. Time-Based Exit Tightening

Positions that sit without making meaningful progress get tighter exit parameters:

| Duration | Condition | Action |
|----------|-----------|--------|
| > 30 minutes | Less than 0.5% profit | Take profit is reduced to 60% of original |
| > 60 minutes | Less than 1.0% profit | Take profit is reduced to 40% of original |

**Why this matters:** Capital tied up in stagnant trades could be deployed elsewhere. Time-based tightening encourages positions to either perform or be exited, keeping your capital working.

---

## How All Five Mechanisms Work Together

Here is a typical trade lifecycle showing how these mechanisms interact:

**Minute 0 -- Entry:**
- Position opened: BTC/USD LONG at $67,000 with $300 size
- Stop loss set at $65,660 (2.0% below entry, based on ATR)
- Take profit target at $69,010 (3.0% above entry)

**Minute 5 -- Price moves to $67,500 (0.7% profit):**
- Not yet at breakeven threshold (3%). Stop loss stays at $65,660.
- All five mechanisms are monitoring.

**Minute 12 -- Price moves to $69,010 (3.0% profit):**
- Breakeven activates: stop loss moves to $67,000 (entry price)
- Tier 1 triggers: 50% of position ($150) closed at $69,010. Profit banked: $4.50

**Minute 18 -- Price moves to $69,680 (4.0% profit):**
- Trailing stop activates with 0.8% trailing distance
- Trailing high set to $69,680

**Minute 22 -- Price moves to $70,005 (4.5% profit):**
- Tier 2 triggers: 60% of remaining ($90) closed at $70,005
- Remaining position: $60 (20% of original)
- Trailing high updated to $70,005

**Minute 30 -- Price reaches $70,800 (5.7% profit):**
- Trailing high updated to $70,800
- Trailing stop sits at $70,234 (0.8% below the high)

**Minute 35 -- Price pulls back to $70,234:**
- Trailing stop triggered
- Final $60 closed at $70,234
- Total result: profit from all three tiers combined

---

## Exit Reasons You Will See

In the thought feed and trade history, each trade closure shows a reason:

| Reason | What Happened |
|--------|--------------|
| **tp_hit** | Price reached the take-profit level |
| **sl_hit** | Price hit the stop loss |
| **trailing_stop** | Trailing stop was triggered |
| **breakeven_exit** | Price returned to entry after breakeven was activated |
| **smart_exit_tier_1** | Tier 1 partial close at 1x TP distance |
| **smart_exit_tier_2** | Tier 2 partial close at 1.5x TP distance |
| **time_tightened** | Time-based tightening reduced TP and it was hit |
| **manual_close** | You manually closed the position |
| **close_all** | Emergency close-all triggered |
| **max_duration** | Position exceeded maximum hold duration (24 hours default for crypto) |

---

## Configuration Options

The Smart Exit System has several configurable parameters. These are typically set by your operator, but here is what each controls:

| Setting | Default | What It Controls |
|---------|---------|-----------------|
| `smart_exit.enabled` | true | Whether tiered exits are active |
| `smart_exit.tiers[0].pct` | 0.50 | Tier 1: close 50% of position |
| `smart_exit.tiers[0].tp_mult` | 1.0 | Tier 1 triggers at 1x TP distance |
| `smart_exit.tiers[1].pct` | 0.60 | Tier 2: close 60% of remaining |
| `smart_exit.tiers[1].tp_mult` | 1.5 | Tier 2 triggers at 1.5x TP distance |
| `smart_exit.tiers[2].pct` | 1.00 | Tier 3: close remaining 100% |
| `smart_exit.tiers[2].tp_mult` | 0 | Tier 3: trailing only (no fixed TP) |
| `trailing_activation_pct` | 0.04 | 4% profit to activate trailing |
| `trailing_step_pct` | 0.008 | 0.8% trailing distance |
| `breakeven_activation_pct` | 0.03 | 3% profit to move SL to entry |
| `atr_multiplier_sl` | 2.0 | Stop loss = 2x ATR |
| `atr_multiplier_tp` | 3.0 | Take profit = 3x ATR |

---

## Stock Exits vs. Crypto Exits

Stock positions use a simpler exit model:
- **Stop loss:** Fixed percentage (default 2%)
- **Take profit:** Fixed percentage (default 4%)
- **Hold period:** 1-7 days (swing trading)
- **No Smart Exit tiers** -- stocks use single exit points because the hold period is longer and the daily bar granularity is coarser

Crypto positions use the full Smart Exit System described above because the shorter timeframes and 24/7 markets benefit from active management.

---

## Tips for Understanding Exit Behavior

1. **Partial closes are normal.** When you see a position's size decrease, it means a tier was triggered and profit was locked in. The remaining portion is still active.

2. **Trailing stops protect you.** If the trailing stop triggers after a big run, it means you captured most of the move. The trailing stop exists to prevent giving back gains.

3. **Time tightening is healthy.** Stale trades that go nowhere are a drag on performance. Tightening their exits frees capital for better opportunities.

4. **The system is designed for moderate consistency.** It will not catch the absolute top or bottom of every move. It aims to capture a reliable portion of each profitable move and limit the damage on losers.

---

*Nova|Pulse v5.0.0 -- Smart entries get you in. Smart exits keep you ahead.*
