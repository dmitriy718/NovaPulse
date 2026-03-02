# Risk and Safety

**Last updated:** 2026-03-01

Nova|Pulse is built with safety as its foundation. Multiple layers of protection work together to guard your capital against large losses. This guide explains every safety feature in detail, so you can trade with confidence knowing how your money is protected.

---

## The Safety Philosophy

No trading system can guarantee profits. Markets are unpredictable, and losses are a normal part of trading. Nova|Pulse's approach is: **accept that losses will happen, but make sure no single loss -- or sequence of losses -- can cause devastating damage to your account.**

Every trade has a defined maximum loss before it is entered. Every day has a loss limit. Every position is sized relative to your bankroll. And multiple circuit breakers stand ready to pause the system if things go wrong.

---

## Layer 1: Position Sizing

### How Size Is Calculated

Every trade's position size is calculated using the **Kelly Criterion** -- a mathematical formula originally developed for gambling that optimizes growth while managing ruin risk. Nova|Pulse uses a conservative "Quarter-Kelly" approach:

1. The Kelly formula calculates the optimal bet size based on your win rate and average win/loss ratio
2. This is then divided by 4 (quarter-Kelly) for extra conservatism
3. The result is capped at 10% of your bankroll (absolute maximum per trade)
4. The position is further limited by the maximum USD position size (default $350 for crypto, $500 for stocks)

**What this means in practice:** A typical position might be 1-3% of your bankroll. Even a string of losing trades will not significantly deplete your account because each loss is small relative to the whole.

### Risk Per Trade

The maximum risk per trade is 1% of your bankroll by default. This means:
- On a $5,000 bankroll, the maximum loss on any single trade is $50
- On a $10,000 bankroll, the maximum loss is $100
- The stop loss is placed to enforce this limit

### Correlation-Based Sizing

If you have an existing position in a correlated pair (e.g., SOL/USD when you already hold ADA/USD -- both are Layer 1 altcoins), the new position size is reduced. Specifically:
- The bot calculates the Pearson correlation between the two pairs over recent prices
- If correlation exceeds 0.7, position size is reduced proportionally
- At correlation 1.0, size is halved

This prevents concentrated risk in assets that move together.

---

## Layer 2: Stop Losses

Every position opened by Nova|Pulse has a stop loss -- a price level at which the position is automatically closed to limit loss.

### ATR-Based Stops

Stop loss distance is calculated using the Average True Range (ATR), which measures recent volatility:
- Default stop loss = 2x ATR from entry price
- In volatile markets, the stop is wider (giving the trade room to breathe)
- In calm markets, the stop is tighter

### Percentage Floors

To prevent stops from being too tight (which causes premature exits), minimum percentage floors are enforced:
- Stop loss: at least 2.5% from entry
- Take profit: at least 5.0% from entry

### Structural Stops (v5.0, Optional)

When enabled, stop losses are placed behind recent swing highs or swing lows (actual support/resistance levels) rather than arbitrary ATR multiples. This is more intelligent because:
- Stops are placed where the market has shown it does not want to go
- A minimum 0.5x ATR buffer is added below the swing level
- Maximum distance is capped at 4x ATR to prevent absurdly wide stops

---

## Layer 3: Trailing Stops and Breakeven

Once a trade moves in your favor, the protection system adapts:

### Breakeven Activation

When a trade reaches 3% profit (default), the stop loss is moved to the entry price. This means:
- If the market reverses back to your entry, you exit at breakeven (no loss, minus small fees)
- You have locked in a "free trade" -- the downside is eliminated

### Trailing Stop

When profit reaches 4% (default), a trailing stop activates:
- The trailing stop follows the price upward (for longs) or downward (for shorts)
- It never moves backward -- only forward in the profitable direction
- The trailing distance is 0.8% by default
- In high-volatility regimes, the distance is widened (1.5x) to give the trade room
- In low-volatility regimes, the distance is tightened (0.7x) to capture profit sooner

This lets winning trades run while systematically protecting profits as they grow.

---

## Layer 4: Smart Exit System

Instead of using a single take-profit level, the Smart Exit System closes positions in tiers:

| Tier | Action | When |
|------|--------|------|
| **Tier 1** | Close 50% of the position | At 1x the original take-profit distance |
| **Tier 2** | Close 60% of the remaining (30% of original) | At 1.5x the take-profit distance |
| **Tier 3** | Close remaining 20% | Via trailing stop only (no fixed target) |

**Why this works:**
- Tier 1 locks in profit on the majority of the position early
- Tier 2 captures additional profit if the move extends
- Tier 3 lets the final portion ride as far as the trend goes, protected by the trailing stop

### Time-Based Exit Tightening

Positions that linger without making progress get tighter exits:
- After 30 minutes with less than 0.5% profit: take profit is reduced to 60% of original
- After 60 minutes with less than 1.0% profit: take profit is reduced to 40% of original

This prevents capital from being tied up in stale trades that are not going anywhere.

See the [Smart Exit System guide](Smart-Exit-System.md) for the full breakdown.

---

## Layer 5: Daily Loss Limit

Nova|Pulse enforces a maximum loss per day (UTC boundary):

- Default: 5% of bankroll per day
- When the limit is reached, **all new trading is paused** for the rest of the day
- Existing positions continue to be managed (stops still work)
- Trading automatically resumes at the next UTC midnight

**Example:** On a $5,000 bankroll, the daily loss limit is $250. If losses for the day reach $250, the bot stops opening new trades.

---

## Layer 6: Exposure Caps

The bot limits how much capital can be at risk simultaneously:

- **Maximum total exposure:** Default 50% of bankroll. Even if every trade passes all filters, the bot will not deploy more than half your capital at once.
- **Maximum concurrent positions:** Default 10 for crypto, 6 for stocks.
- **Correlation group limits:** Default 2 positions per correlation group. You cannot have 5 altcoin positions at the same time if they are all in the same correlation group.

---

## Layer 7: Cross-Engine Risk Aggregation

If you trade on multiple exchanges (Kraken + Coinbase + Stocks), the **Global Risk Aggregator** tracks total exposure across all engines:

- Each engine reports its current exposure to the aggregator
- Before opening a new position, the engine checks global remaining capacity
- This prevents the combined exposure across all exchanges from exceeding the global cap

---

## Layer 8: Circuit Breakers

Multiple automatic pause mechanisms stand ready:

### Consecutive Loss Pause
After 5 losing trades in a row (default), trading pauses automatically. This prevents "tilt" behavior and gives the market time to change.

### Drawdown Pause
If peak-to-trough drawdown reaches 8% (default), trading pauses. This catches situations where losses are accumulating even if they are not consecutive.

### Stale Data Pause
If market data stops updating for more than 3 consecutive health checks, trading pauses. You cannot make good decisions with bad data.

### WebSocket Disconnect Pause
If the exchange WebSocket stays disconnected for more than 5 minutes, trading pauses until reconnection.

### Anomaly Detection Pause (v5.0, Optional)
The anomaly detector monitors for:
- **Spread spikes** (3x normal) -- unusual widening suggests unstable conditions
- **Volume anomalies** (5x normal) -- extreme volume may indicate manipulation or news
- **Correlation anomalies** (>60% of positions in the same direction) -- concentrated risk
- **Depth drops** (>50% of normal) -- thin order books increase execution risk

If detected, trading pauses for a cooldown period (default 5 minutes).

---

## Layer 9: Exchange-Native Stop Orders

For crash-proof protection, Nova|Pulse can place stop-loss orders directly on the exchange. This means:
- Even if the bot process crashes or loses connectivity, the exchange will execute the stop
- This is a backstop of last resort -- the bot normally manages stops itself

---

## Layer 10: Trade Quality Filters

Before any trade is placed, multiple filters must pass:

| Filter | What It Checks |
|--------|---------------|
| **Confluence threshold** | At least 2 strategies must agree |
| **Confidence threshold** | Overall confidence must exceed 0.50 |
| **Risk/reward ratio** | Must be at least 1.0 (potential profit >= potential loss) |
| **Spread gate** | The bid-ask spread must not be too wide (default max 0.30%) |
| **Quiet hours** | No trading during configured quiet hours (default UTC 3:00) |
| **Trade rate limit** | Maximum 20 trades per hour to prevent churn |
| **Pair cooldown** | At least 20 seconds between trades on the same pair |
| **Strategy cooldown** | At least 60 seconds between the same strategy signaling |
| **Canary mode** | If enabled, restricts to 2 pairs and tiny positions for testing |

---

## Layer 11: Macro Event Calendar (v5.0, Optional)

When enabled, the event calendar prevents new trades during high-impact economic events:
- FOMC interest rate decisions
- CPI (Consumer Price Index) releases
- NFP (Non-Farm Payrolls) reports
- Earnings announcements (if configured)

A configurable blackout window (default 30 minutes before and after) surrounds each event. Existing positions are still managed.

---

## Layer 12: Liquidity-Aware Sizing (v5.0, Optional)

When enabled, the bot checks order book depth before sizing a position:
- If the order book is thin relative to the desired position size, the position is reduced
- This prevents large orders from moving the market against you
- Configurable maximum market impact (default 10%) and minimum depth ratio (default 3x)

---

## What Nova|Pulse Cannot Protect Against

While the safety system is comprehensive, you should understand its limitations:

- **Extreme flash crashes or exchange outages:** If the exchange itself goes down or prices gap violently past your stop, losses may exceed the stop level.
- **Black swan events:** Unprecedented events (exchange hack, regulatory action) are impossible to model.
- **Guaranteed profits:** No amount of safety engineering can make a trading system profitable in all conditions. Safety reduces the severity of losses, not their occurrence.
- **Slow bleeds:** A strategy portfolio that is slightly negative over time will produce losses that are individually small but cumulative. The auto-tuner works to prevent this.

---

## Summary of Default Safety Settings

| Protection | Default Value |
|-----------|--------------|
| Risk per trade | 1% of bankroll |
| Maximum position size | $350 (crypto), $500 (stocks) |
| Stop loss distance | 2x ATR (minimum 2.5%) |
| Take profit distance | 3x ATR (minimum 5%) |
| Breakeven activation | 3% profit |
| Trailing stop activation | 4% profit |
| Trailing step | 0.8% |
| Daily loss limit | 5% of bankroll |
| Total exposure cap | 50% of bankroll |
| Max concurrent positions | 10 (crypto), 6 (stocks) |
| Positions per correlation group | 2 |
| Consecutive loss pause | 5 losses |
| Drawdown pause | 8% |
| Kelly fraction | 0.25 (quarter-Kelly) |
| Max Kelly size | 10% of bankroll |
| Max spread | 0.30% |
| Quiet hours | UTC 3:00 |
| Trade rate limit | 20 per hour |

---

*Nova|Pulse v5.0.0 -- Safety is not a feature; it is the foundation.*
