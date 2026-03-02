# Understanding Your Metrics

**Last updated:** 2026-03-01

Nova|Pulse tracks a wide range of performance and risk metrics so you can understand exactly how the bot is performing. This guide explains every metric in plain language, why it matters, and what values to look for.

---

## Profitability Metrics

### Total P&L (Profit and Loss)

**What it is:** The sum of all realized profits and losses from closed trades since the last stats reset.

**Why it matters:** This is your bottom line. A positive number means the bot has made money overall; negative means it has lost money.

**What to look for:** Steady growth over time rather than a single big jump. Consistent small gains are healthier than volatile swings.

---

### Unrealized P&L

**What it is:** The paper profit or loss on positions that are currently open. If you closed all positions right now at current prices, this is roughly what you would gain or lose (minus fees and slippage).

**Why it matters:** It tells you how your current positions are doing. A large negative unrealized P&L means your open positions are underwater.

**What to look for:** Watch for unrealized P&L that is deeply negative -- the stop loss system should prevent this from getting too large, but it is worth monitoring.

---

### Realized P&L (Daily)

**What it is:** Profit and loss from trades that were opened and closed today (UTC day boundary).

**Why it matters:** Lets you track day-by-day performance. Some days will be positive, some negative. What matters is the trend over weeks and months.

---

### Win Rate

**What it is:** The percentage of closed trades that ended in profit.

**Example:** If 65 out of 100 trades were winners, your win rate is 65%.

**Why it matters:** Higher win rates feel better psychologically, but win rate alone does not determine profitability. A system with 40% win rate can still be very profitable if the average win is much larger than the average loss.

**What to look for:**
- Above 50% is generally good for the strategies Nova|Pulse uses
- Between 40-50% can still be profitable if the profit factor is above 1.5
- Below 40% warrants investigation

---

### Profit Factor

**What it is:** Total gross profit divided by total gross loss.

**Example:** If your winning trades made $500 total and your losing trades lost $300, your profit factor is 500/300 = 1.67.

**Why it matters:** This is one of the best single numbers for evaluating a trading system. It accounts for both win rate and win/loss size.

**What to look for:**
- Above 1.0 = profitable (you make more than you lose)
- Above 1.5 = solid
- Above 2.0 = strong
- Below 1.0 = losing money

---

### Sharpe Ratio

**What it is:** A measure of risk-adjusted return. It asks: "How much return am I getting per unit of risk (volatility)?"

**Why it matters:** Two systems might both return 10%, but one might have huge swings while the other is steady. The steady one has a higher Sharpe ratio and is generally preferable.

**What to look for:**
- Above 0.5 = acceptable
- Above 1.0 = good
- Above 2.0 = excellent
- Negative = losing money on a risk-adjusted basis

---

### Average Win / Average Loss

**What it is:** The average profit on winning trades and the average loss on losing trades.

**Why it matters:** The ratio between these two numbers determines how high your win rate needs to be for profitability. If your average win is $50 and average loss is $25 (a 2:1 ratio), you only need to win 33% of the time to break even.

**What to look for:** Average win should be larger than average loss. If they are close or the average loss is larger, the win rate needs to be high to compensate.

---

### Best Trade / Worst Trade

**What it is:** The single most profitable trade and the single largest loss.

**Why it matters:** These show your extremes. A system where the worst trade is much larger than the best trade suggests risk management needs tightening. Ideally, your best trade should be larger than (or at least comparable to) your worst loss.

---

### Total Trades

**What it is:** The number of closed trades since the last stats reset.

**Why it matters:** Metrics become more statistically meaningful with more trades. A 90% win rate on 5 trades does not tell you much; a 65% win rate on 200 trades is a reliable signal.

**What to look for:** Be patient in the early days. It may take several days or weeks to accumulate enough trades for metrics to be meaningful.

---

## Risk Metrics

### Current Bankroll

**What it is:** Your working capital for trading. Calculated as initial bankroll plus total realized P&L.

**Why it matters:** This is the base from which position sizes are calculated. As you make money, positions can grow (compounding). As you lose, positions shrink (protection).

---

### Daily Loss

**What it is:** How much you have lost today (UTC day). Displayed alongside the daily loss limit.

**Why it matters:** When daily losses reach the configured limit (default 5% of bankroll), trading automatically pauses for the rest of the day. This prevents spiral losses during bad conditions.

---

### Total Exposure

**What it is:** The sum of all open position sizes in USD.

**Example:** If you have a $200 BTC position and a $150 ETH position, total exposure is $350.

**Why it matters:** Higher exposure means more capital at risk simultaneously. The bot caps total exposure at a configurable percentage of bankroll (default 50%).

---

### Exposure Percentage

**What it is:** Total exposure divided by current bankroll, expressed as a percentage.

**Why it matters:** Shows how much of your capital is actively at risk. At 50% exposure, half your bankroll is in open positions and half is in reserve.

**What to look for:** The bot manages this automatically, but if you see it consistently near the cap, the bot is actively capital-constrained and may be rejecting trades.

---

### Consecutive Losses

**What it is:** The current streak of losing trades in a row.

**Why it matters:** Losing streaks happen to every trading system. The bot monitors this and auto-pauses at the configured threshold (default 5) to prevent emotional spiral trading.

---

### Max Drawdown

**What it is:** The largest peak-to-trough decline in your equity. If your equity peaked at $5,500 and dropped to $5,200, your max drawdown is $300 (5.5%).

**Why it matters:** Drawdown measures how bad the worst period was. Lower max drawdown means smoother returns. The bot auto-pauses at the drawdown threshold (default 8%).

---

## Confluence and AI Metrics

### Confluence Count

**What it is:** The number of strategies that agreed on a trade's direction when it was entered.

**Example:** A confluence count of 3 means three separate strategies independently signaled the same direction (e.g., all three said "buy BTC").

**Why it matters:** Higher confluence generally means higher conviction. The minimum confluence threshold (default 2) prevents trades on weak agreement. The highest-confluence trades are the bot's highest-conviction setups.

---

### Confidence Score

**What it is:** A composite score (0.00 to 1.00) representing how confident the bot was in a trade at entry. It incorporates strategy weights, regime alignment, session history, and AI model predictions.

**What to look for:**
- 0.50-0.60 = minimum threshold trades (lower conviction)
- 0.60-0.75 = moderate confidence
- 0.75-1.00 = high confidence

---

### OBI (Order Book Imbalance)

**What it is:** A measure of buying vs. selling pressure in the order book. Positive OBI means more buy pressure; negative means more sell pressure.

**Why it matters:** When OBI agrees with the trade direction, it counts as an additional confluence vote. OBI agreement adds conviction that the market's order flow supports the trade.

---

### Volatility Regime

**What it is:** The bot classifies current market conditions into one of four regimes:
- **Low volatility** -- calm, narrow price swings
- **Mid volatility** -- normal conditions
- **High volatility** -- wide price swings, potentially unstable

**Why it matters:** The bot adjusts strategy weights and trailing stop behavior based on the regime. During high volatility, it gives trailing stops more room to breathe. During low volatility, it tightens them.

---

### Market Regime

**What it is:** Whether the market is currently trending or ranging:
- **Trend** -- price moving consistently in one direction (ADX above threshold)
- **Range** -- price oscillating between support and resistance levels

**Why it matters:** Different strategies work better in different regimes. The bot automatically boosts trend-following strategies in trending markets and mean-reversion strategies in ranging markets.

---

## Strategy-Level Metrics

Each of the twelve strategies has its own performance tracking:

| Metric | Meaning |
|--------|---------|
| **Trades** | How many trades this strategy participated in (as a confluence contributor) |
| **Win Rate** | What percentage of this strategy's trades were profitable |
| **P&L** | Total profit/loss from trades where this strategy contributed |
| **Avg P&L** | Average profit/loss per trade |
| **Weight** | Current weight in the confluence system |
| **Status** | Active, disabled (by auto-tuner), or on cooldown |

---

## Stock-Specific Metrics

When stock trading is enabled, you will also see:

| Metric | Meaning |
|--------|---------|
| **Universe Size** | How many stocks are currently in the scan universe (up to 96) |
| **Pinned Stocks** | Core stocks always scanned (AAPL, MSFT, NVDA, TSLA, etc.) |
| **Dynamic Stocks** | Stocks added by the universe scanner based on volume and momentum |
| **Open Stock Positions** | Number of active stock swing trades |
| **Stock P&L** | Profit/loss from stock trades specifically |

---

## How Metrics Reset

- **Daily metrics** (daily P&L, daily trades) reset automatically at UTC midnight
- **Cumulative metrics** (total P&L, win rate, total trades) persist across restarts and only reset when manually triggered by your operator
- **Per-strategy metrics** persist and are used by the auto-tuner to evaluate strategy health

If you notice metrics look wrong or you want to start fresh, ask your operator to reset stats. This zeroes the counters without affecting your actual positions or bankroll.

---

## Reading Metrics Like a Pro

Here is a quick cheat sheet for evaluating your bot's performance:

| Scenario | What It Suggests |
|----------|-----------------|
| High win rate + low profit factor | Wins are small, losses are large. Stop losses may need tightening. |
| Low win rate + high profit factor | Losses are small, wins are large. The system is selective but effective. |
| High Sharpe + steady equity curve | Excellent risk-adjusted performance. The bot is doing well. |
| Increasing consecutive losses | Bad market conditions or strategy degradation. Auto-pause will trigger if it continues. |
| High exposure % consistently | The bot is fully deployed. It may be rejecting trades due to capacity limits. |
| Declining win rate over weeks | Market conditions may have shifted. The auto-tuner should adapt, but monitor closely. |

---

*Nova|Pulse v5.0.0 -- Numbers tell the story, but understanding them writes the next chapter.*
