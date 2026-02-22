# Risk and Safety

**Last updated:** 2026-02-22

NovaPulse is built with safety as its foundation. Multiple layers of protection work together to guard your capital against large losses. This guide explains every safety feature in detail, so you can trade with confidence knowing how your money is protected.

---

## The Safety Philosophy

No trading system can guarantee profits -- markets are inherently unpredictable. What NovaPulse can do is **manage risk meticulously** so that:

- No single trade can seriously damage your account
- Losing streaks are detected and contained
- The bot pauses itself when conditions are unsafe
- Your capital is preserved so you live to trade another day

Think of it like layers of armor. Any one layer might have a gap, but together they provide comprehensive protection.

---

## Layer 1: Paper Trading (Risk-Free Testing)

Before risking real money, NovaPulse lets you run in **paper trading mode** -- full simulation using real market data but zero real money.

**What happens in paper mode:**
- The bot watches real markets and generates real signals
- Trades are simulated internally -- no orders are sent to your exchange
- All metrics (P&L, win rate, Sharpe ratio) are tracked as if they were real
- The dashboard looks and works identically to live mode

**Why this matters:** You can verify that NovaPulse's behavior matches your expectations, test different settings, and build confidence -- all without any financial risk. We recommend at least 1-2 weeks of paper trading before going live.

---

## Layer 2: Position Sizing (Kelly Criterion)

Before every trade, NovaPulse calculates the right position size using the **Kelly Criterion** -- a mathematical formula that determines how much to invest based on:

- Your recent win rate (how often trades are profitable)
- Your average win vs. average loss (how big the wins are vs. the losses)
- Your overall bankroll (how much capital you have)

**How it protects you:**

- NovaPulse uses **quarter Kelly** (25% of the formula's suggestion), which is deliberately conservative
- Maximum position size is capped (default: $500 per trade or 10% of bankroll, whichever is smaller)
- If the bot is on a losing streak, the Kelly formula automatically suggests smaller positions
- If the risk/reward on a particular trade is poor, the position size is reduced further

**Plain-language analogy:** Imagine you are placing bets at a casino. Kelly sizing is like a mathematically calculated bet size that ensures you never bet so much that a losing streak could wipe you out, while still betting enough to grow your bankroll when you are winning.

---

## Layer 3: Stop Losses (Automatic Loss Limits)

Every single trade placed by NovaPulse has a **stop loss** -- a predetermined price at which the trade will be automatically closed to limit the loss.

**How stops are calculated:**
- NovaPulse uses the **ATR (Average True Range)** indicator to measure recent volatility
- Stop losses are placed at a distance that accounts for normal market noise
- The default stop distance is 2x ATR from entry (with a minimum floor of 2.5%)
- This means stops are far enough that normal fluctuations do not trigger them, but close enough to limit damage

**Example:**
- You buy BTC at $64,000
- Recent volatility (ATR) suggests normal moves of about $600
- Stop loss is set at $62,800 (about 1.9% below entry)
- If BTC drops to $62,800, the trade closes automatically -- you lose about 1.9% on this trade
- Your overall account impact is much smaller because position sizing limits how much capital is in the trade

---

## Layer 4: Trailing Stops (Locking In Profits)

Once a trade moves in your favor by a certain amount, the **trailing stop** activates. This is a stop loss that moves up (for long trades) or down (for short trades) as the price moves favorably.

**How it works:**

1. A trade is opened with a fixed stop loss (Layer 3).
2. When the trade is profitable by 1.5% or more, the trailing stop activates.
3. From that point, as the price continues moving in your favor, the stop loss follows behind by 0.5%.
4. The stop loss never moves backward -- it only tightens.
5. If the price reverses, the trailing stop catches it and closes the trade with a profit.

**Plain-language analogy:** Imagine you are climbing a mountain with a safety rope. As you climb higher, someone below pulls the rope tighter so that if you slip, you only fall a short distance. You can never fall back to the bottom.

```
Price:   $100 -> $102 -> $104 -> $106 -> $104 -> $102
Stop:    $97  -> $97  -> $101.5-> $103.5-> $103.5-> CLOSED at $103.5
                         ^trailing activates    ^trailing catches reversal
                                                  Profit: +$3.50
```

---

## Layer 5: Breakeven Protection

Once a trade reaches a profit of 1% from entry, the stop loss is moved to the **entry price** (breakeven). This means the trade can no longer result in a loss (ignoring fees).

**How it works:**
1. You enter a trade at $64,000 with a stop at $62,800.
2. Price rises to $64,640 (1% above entry).
3. Stop loss is automatically moved from $62,800 up to $64,000 (breakeven).
4. Now, even if price reverses all the way back down, you exit at $64,000 -- no loss.
5. If price continues higher, the trailing stop takes over and you capture the gain.

This protection kicks in before the trailing stop activates, providing an additional safety layer.

---

## Layer 6: Daily Loss Limit

NovaPulse tracks your total realized losses for each day. If daily losses reach **5% of your bankroll** (default), the bot **automatically pauses** and stops placing new trades.

**Why this matters:** Even good systems have bad days. The daily loss limit prevents a bad day from becoming a devastating one. Think of it as a "circuit breaker" for bad days.

**What happens when it triggers:**
- No new trades are opened
- Existing positions continue to be managed (stop losses still work)
- You receive a notification explaining what happened
- Trading resumes the next day (or when you manually resume after reviewing)

---

## Layer 7: Drawdown Protection

If your account experiences a drawdown (decline from its peak value) exceeding **8%** (default), the bot auto-pauses.

**What it does:** Prevents compounding losses during extended rough patches. When your account drops significantly from its high point, it is often better to step back and reassess rather than keep trading.

**Additionally:** During periods of elevated drawdown (even below the auto-pause threshold), NovaPulse automatically reduces position sizes. This means the bot trades more conservatively when it is in a tough stretch.

---

## Layer 8: Circuit Breakers

NovaPulse has several automatic circuit breakers that pause trading when conditions are unsafe:

| Circuit Breaker | Trigger | What Happens |
|----------------|---------|-------------|
| **Stale Data** | No fresh market data for 3+ consecutive checks | Trading pauses until data recovers. Prevents trading on outdated prices. |
| **Exchange Disconnect** | WebSocket connection lost for 5+ minutes | Trading pauses until reconnected. Prevents "blind" trading. |
| **Consecutive Losses** | 4 losses in a row (default) | Trading pauses for review. A losing streak may indicate changed market conditions. |
| **Daily Loss Limit** | 5% of bankroll lost in one day | Trading pauses until next day. Prevents catastrophic single-day losses. |
| **Drawdown Limit** | 8% decline from peak account value | Trading pauses for review. |

**After a loss-triggered pause:** A 30-minute cooldown period is applied before any new trades can be taken (even after resuming). This prevents emotional re-entry after a loss.

---

## Layer 9: Maximum Concurrent Positions

NovaPulse limits the number of trades that can be open at the same time -- **5 by default**. This prevents the bot from overcommitting capital across too many trades.

**Why this matters:** If you had 20 trades open at once and the market moved sharply against you, the losses could compound. By limiting concurrent positions, NovaPulse keeps your overall exposure manageable.

---

## Layer 10: Total Exposure Cap

Beyond limiting the number of positions, NovaPulse also caps the total dollar value of all open positions. By default, no more than **50% of your bankroll** can be deployed at any time.

**Example:** If your bankroll is $10,000, the bot will never have more than $5,000 in open positions combined. This ensures you always have reserves and are never "all in."

---

## Layer 11: Trade Rate Throttle

NovaPulse limits how many new trades can be opened per hour. This prevents runaway overtrading, which can happen if market conditions create rapid signals.

**The cooldown system:**
- After a trade is placed, a 5-minute cooldown prevents immediate re-entry in the same pair
- A global trades-per-hour limit can be configured
- After a losing trade, a 30-minute global cooldown applies before any new trades

---

## Layer 12: Exchange-Native Stop Orders

In addition to monitoring stop losses internally, NovaPulse can place **stop-loss orders directly on the exchange**. This provides a critical backup:

- If NovaPulse's server crashes, restarts, or loses connection, the exchange's own stop order is already in place
- The exchange will execute the stop regardless of what happens to NovaPulse
- This means your positions are protected even in the worst-case scenario

---

## Layer 13: Smart Exits (Optional)

When enabled, the Smart Exit system takes partial profits at multiple levels instead of waiting for a single take-profit target:

| Level | Action |
|-------|--------|
| **1x TP distance** | Close 50% of the position, locking in half the profit |
| **1.5x TP distance** | Close 30% of the remaining position |
| **Beyond 1.5x** | Trailing stop manages the final 20% |

**Why this helps:** It locks in guaranteed profit early while still leaving a portion open to capture larger moves. The trade-off is that you may capture less on big winners, but you are much less likely to watch a winning trade turn into a loser.

Smart Exits are **disabled by default** and can be enabled through the settings panel.

---

## Layer 14: Confluence Requirement

This is not strictly a risk feature, but it is a powerful form of protection. By requiring **at least 3 of 9 strategies** to agree before entering a trade, NovaPulse avoids acting on weak or ambiguous signals. This dramatically reduces the number of false entries.

See [Trading Strategies](Trading-Strategies.md) for more details.

---

## Summary: Your Multi-Layer Protection

```
+-----------------------------------------------------------+
|                    YOUR CAPITAL                            |
|                                                           |
|  Layer 1:  Paper Trading (test risk-free)                 |
|  Layer 2:  Position Sizing (Kelly Criterion, 1/4 Kelly)   |
|  Layer 3:  Stop Losses (ATR-based, every trade)           |
|  Layer 4:  Trailing Stops (lock in profits)               |
|  Layer 5:  Breakeven Protection (eliminate risk early)     |
|  Layer 6:  Daily Loss Limit (5% auto-pause)               |
|  Layer 7:  Drawdown Protection (8% auto-pause)            |
|  Layer 8:  Circuit Breakers (stale data, disconnects)     |
|  Layer 9:  Max Positions (5 concurrent)                   |
|  Layer 10: Exposure Cap (50% of bankroll max)             |
|  Layer 11: Trade Throttle (prevent overtrading)           |
|  Layer 12: Exchange-Native Stops (survive bot crashes)    |
|  Layer 13: Smart Exits (partial profit-taking)            |
|  Layer 14: Confluence (multi-strategy agreement)          |
|                                                           |
+-----------------------------------------------------------+
```

---

## Risk Disclosure

While NovaPulse implements comprehensive risk management, it is important to understand:

- **Trading cryptocurrency involves risk.** You can lose money, and past performance does not guarantee future results.
- **No system is perfect.** Black swan events, flash crashes, exchange outages, or extreme market conditions can cause losses that exceed stop-loss levels.
- **Slippage can occur.** In fast-moving markets, the actual execution price may differ slightly from the intended stop-loss price.
- **Only trade with money you can afford to lose.** NovaPulse helps you trade more systematically and with better risk management, but it does not eliminate risk entirely.

We believe in transparency: NovaPulse cannot promise profits, but it can promise disciplined, systematic risk management that gives you the best chance of long-term success.

---

*For default settings and how to adjust them, see [Configuration Guide](Configuration-Guide.md).*
*For emergency controls, see [Controls](Controls-Pause-Resume-Kill.md).*
