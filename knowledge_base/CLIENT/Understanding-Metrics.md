# Understanding Your Metrics

**Last updated:** 2026-02-22

NovaPulse tracks a wide range of performance and risk metrics so you can understand exactly how the bot is performing. This guide explains every metric in plain language, why it matters, and what values to look for.

---

## Profitability Metrics

### Total P&L (Profit and Loss)

**What it is:** Your net profit or loss after all trading fees have been deducted. This is the bottom line -- how much money the bot has made (or lost) for you.

**Why it matters:** This is the single most important number. It tells you whether you are up or down overall.

**What to look for:**
- Positive is good, negative means losses
- Focus on the trend over weeks and months, not day-to-day fluctuations
- Expect some losing days -- even the best strategies have them

---

### Win Rate

**What it is:** The percentage of closed trades that ended in a profit. If 7 out of 10 trades are winners, the win rate is 70%.

**Why it matters:** Win rate tells you how often the bot is right, but it does not tell the whole story. A 50% win rate can still be very profitable if the average win is larger than the average loss.

**What to look for:**
- 50-70%: Typical for well-tuned strategies
- Below 40%: Concerning, but could still be profitable if winners are much larger than losers
- Above 80%: Excellent, but rare and may not be sustainable

---

### Average Win / Average Loss

**What it is:**
- **Average Win:** The average dollar amount gained on winning trades
- **Average Loss:** The average dollar amount lost on losing trades

**Why it matters:** These two numbers together tell you whether your winners are bigger than your losers. A bot that wins $50 on average but only loses $25 on average is doing well, even with a 50% win rate.

**What to look for:**
- Average Win should ideally be larger than Average Loss
- If Average Loss is larger, you need a high win rate to stay profitable

---

### Risk-Reward Ratio

**What it is:** The ratio of potential gain to potential loss on a trade. If your take profit is $100 away from entry and your stop loss is $50 away, the risk-reward ratio is 2:1.

**Why it matters:** Higher risk-reward means each win compensates for more losses. A 2:1 ratio means you only need to win 1 out of 3 trades to break even.

**What to look for:**
- 1.5:1 or higher is generally desirable
- Below 1:1 means you need a very high win rate to stay profitable
- NovaPulse defaults to a minimum risk-reward of 0.9:1 and typically aims higher

---

### Profit Factor

**What it is:** Total gross profit divided by total gross loss. If you have made $1,000 in winning trades and lost $500 in losing trades, your profit factor is 2.0.

**Why it matters:** This is one of the most reliable measures of a trading system's edge. It combines win rate and win/loss size into a single number.

**What to look for:**
- Below 1.0: You are losing money overall
- 1.0 to 1.5: Marginal -- the bot has a small edge
- 1.5 to 2.0: Good -- solidly profitable
- Above 2.0: Excellent
- Above 3.0: Outstanding (rare in live trading)

---

## Risk Metrics

### Sharpe Ratio

**What it is:** A measure of risk-adjusted return. It answers the question: "How much return am I getting for the risk I am taking?" Think of it as the "return per unit of volatility."

**Why it matters:** A high P&L is not impressive if you had to endure wild swings to get it. The Sharpe ratio rewards consistency -- steady, reliable returns score higher than a roller coaster that happens to end up positive.

**What to look for:**
- Below 0: You are losing money on a risk-adjusted basis
- 0 to 1.0: Subpar risk-adjusted returns
- 1.0 to 2.0: Good
- 2.0 to 3.0: Very good
- Above 3.0: Exceptional

**Analogy:** Imagine two road trips that both arrive on time. One was smooth highway driving; the other involved constant swerving and near-misses. The Sharpe ratio rewards the smooth ride.

---

### Sortino Ratio

**What it is:** Similar to the Sharpe ratio, but it only counts downside volatility (losses). Upside volatility (gains that exceed expectations) is not penalized.

**Why it matters:** Some people argue that upside volatility is not really "risk" -- it is a good thing. The Sortino ratio gives a more nuanced view by only penalizing the bad kind of volatility.

**What to look for:** Same scale as Sharpe, but Sortino is usually higher because it ignores upside swings. A Sortino above 2.0 is very good.

---

### Max Drawdown

**What it is:** The largest peak-to-trough decline in your account value. If your account went from $10,000 to $10,800 (peak) and then dropped to $10,400 before recovering, the max drawdown was ($10,800 - $10,400) / $10,800 = 3.7%.

**Why it matters:** Drawdown measures the worst-case pain you would have experienced if you were watching at the worst moment. Even profitable systems have drawdowns -- the question is how deep they go.

**What to look for:**
- Under 5%: Very good risk management
- 5-10%: Acceptable for crypto trading
- 10-20%: Concerning -- review risk settings
- Above 20%: Serious -- consider reducing risk per trade

NovaPulse has an auto-pause circuit breaker at 8% drawdown by default.

---

### Exposure

**What it is:** The total dollar value of all your open positions combined, usually shown as a percentage of your bankroll. If your bankroll is $10,000 and you have $3,000 in open positions, your exposure is 30%.

**Why it matters:** Higher exposure means more of your capital is at risk at any given moment. NovaPulse caps total exposure at 50% of bankroll by default, ensuring you always have reserves.

**What to look for:**
- 0%: No open positions (fully in cash)
- 10-30%: Conservative
- 30-50%: Moderate (near the default cap)
- Above 50%: Blocked by default risk settings

---

## Signal and AI Metrics

### Confidence Score

**What it is:** A number between 0 and 1 (or 0% to 100%) indicating how strong the AI thinks a trading signal is. Higher confidence means more factors are aligned in favor of the trade.

**Why it matters:** NovaPulse only takes trades when confidence exceeds the minimum threshold (default: 0.65 or 65%). This filters out weak, uncertain signals.

**What to look for:**
- Below 0.50: Weak signal -- bot will not trade
- 0.50 to 0.65: Moderate signal -- still below the trading threshold
- 0.65 to 0.80: Good signal -- meets the threshold
- Above 0.80: Strong signal -- high conviction

> **Note:** High confidence does NOT guarantee a profitable trade. It means the bot's analysis is strongly aligned, but the market can always move unexpectedly.

---

### Confluence Count

**What it is:** The number of strategies (out of nine) that agree on a trade direction. If four strategies say "BUY" and the rest say nothing, confluence is 4.

**Why it matters:** Confluence is NovaPulse's core safety mechanism for entries. Requiring multiple independent strategies to agree dramatically reduces false signals. It is like getting a second (and third, and fourth) opinion before making a decision.

**What to look for:**
- 1-2: Not enough agreement -- bot will not trade (default threshold is 3)
- 3: Meets the minimum threshold
- 4-5: Strong agreement -- higher-quality signal
- 6+: Very strong agreement -- rare but powerful

---

### Kelly Fraction

**What it is:** A mathematical formula (the Kelly Criterion) that determines optimal position size based on your win rate and average win/loss ratio. NovaPulse uses a conservative "quarter Kelly" by default, meaning it sizes positions at 25% of what the pure formula suggests.

**Why it matters:** Kelly sizing automatically adjusts your position size based on the bot's track record. When the bot is on a winning streak (higher win rate, bigger wins), Kelly suggests slightly larger positions. When results are poor, it suggests smaller ones.

**What to look for:**
- This is mostly an internal calculation -- the output is the actual position size in dollars
- The Kelly fraction shown on the dashboard tells you what percentage of bankroll the formula suggests
- NovaPulse caps this at 10% of bankroll per trade (max_kelly_size) regardless of what the formula says

**Analogy:** Imagine you are a poker player. Kelly sizing tells you how much to bet based on how good your cards are and how often you have been winning. When you have a strong hand and you have been running hot, you bet a bit more. When things are uncertain, you bet less.

---

## Position Metrics

### Open Positions

**What it is:** The number of trades currently active (not yet closed). NovaPulse limits this to 5 concurrent positions by default.

**Why it matters:** More open positions means more capital at risk and more complexity to manage. The limit prevents overtrading.

---

### Trade Count

**What it is:** The total number of trades that have been opened and closed since the bot started (or since the counter was reset).

**Why it matters:** More trades give you better statistical significance. A 70% win rate over 100 trades is much more meaningful than 70% over 10 trades.

---

### Unrealized P&L

**What it is:** The profit or loss on positions that are still open. It is "unrealized" because you have not locked it in yet -- the trade has not closed.

**Why it matters:** Unrealized P&L fluctuates with the market. A position showing +$50 right now might close at +$30 or +$80 or even at a loss if the stop is hit. Do not confuse unrealized P&L with actual realized profits.

---

### Realized P&L

**What it is:** The profit or loss from trades that have been completed (closed). This is actual locked-in money.

**Why it matters:** This is the real score. Realized P&L is definitive -- once a trade is closed, the result is final.

---

## Summary Table

| Metric | What It Measures | Good Value | Bad Value |
|--------|-----------------|------------|-----------|
| Total P&L | Net profit/loss | Positive and growing | Negative or shrinking |
| Win Rate | How often trades win | 50-70% | Below 40% |
| Sharpe Ratio | Return per unit of risk | Above 1.5 | Below 0.5 |
| Sortino Ratio | Return per unit of downside risk | Above 2.0 | Below 0.5 |
| Max Drawdown | Worst decline from peak | Under 5% | Above 15% |
| Profit Factor | Gross profit / gross loss | Above 1.5 | Below 1.0 |
| Confidence | Signal strength | Above 0.65 | Below 0.50 |
| Confluence | Strategy agreement | 3 or more | 1-2 |
| Exposure | Capital at risk | 10-40% | Above 50% |

---

*For more on how NovaPulse protects your capital, see [Risk and Safety](Risk-Safety.md).*
*For details on each trading strategy, see [Trading Strategies](Trading-Strategies.md).*
