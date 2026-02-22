# Trading Strategies

**Last updated:** 2026-02-22

NovaPulse uses nine independent trading strategies, each looking at the market from a different angle. No single strategy makes decisions alone -- instead, the bot requires multiple strategies to agree before entering a trade. This section explains each strategy in plain language, how confluence works, and how the AI adapts over time.

---

## The Nine Strategies

### 1. Keltner Channel (Weight: 0.30 -- Highest)

**What it looks for:** Price bouncing off a channel that is drawn around the average price. The channel width is based on recent volatility. When price touches the lower channel and momentum indicators confirm, it is a buy signal. When price touches the upper channel with confirmation, it is a sell signal.

**Plain-language analogy:** Imagine a ball bouncing between two walls. The Keltner Channel strategy watches for the ball (price) to hit one of the walls and bounce back. It also checks that the bounce has real momentum behind it (confirmed by MACD and RSI indicators) before calling it a trade.

**When it works best:** Ranging and gently trending markets where price oscillates within a channel. This has been NovaPulse's top-performing strategy historically.

---

### 2. Mean Reversion (Weight: 0.25)

**What it looks for:** Extreme conditions where price has stretched far from its average. When price drops below the lower Bollinger Band and RSI confirms oversold conditions, the strategy expects price to "snap back" toward the average.

**Plain-language analogy:** Think of a rubber band. The further you stretch it, the harder it snaps back. Mean Reversion looks for prices that have been stretched too far in one direction and bets on the snap-back.

**When it works best:** Sideways/ranging markets. In strong trends, price can stay "stretched" for a long time, so this strategy gets less weight during trending conditions.

---

### 3. Ichimoku Cloud (Weight: 0.15)

**What it looks for:** This strategy uses a Japanese charting system called the Ichimoku Cloud, which identifies trend direction, support/resistance levels, and momentum all in one view. It looks for price breaking above or below the "cloud" with confirming signals.

**Plain-language analogy:** Imagine a weather forecast that shows a "cloud" of expected price ranges. When price breaks above the cloud, it is like the sun coming out -- bullish. When it drops below, storm clouds are forming -- bearish. The thicker the cloud, the stronger the support or resistance.

**When it works best:** Trending markets with clear directional movement. It gets extra weight in trending conditions and less in choppy markets.

---

### 4. Order Flow (Weight: 0.15)

**What it looks for:** This strategy reads the actual order book -- the list of real buy and sell orders waiting to be filled on the exchange. It detects imbalances: if there are significantly more buy orders than sell orders, buying pressure is building (and vice versa).

**Plain-language analogy:** Imagine you are at an auction. If you can see that many people have their hands raised to bid but few are selling, you know the price is likely going up. Order Flow gives NovaPulse this "insider view" of supply and demand in real time.

**When it works best:** When there is strong directional pressure from real market participants. This strategy is unique because it looks at live order data rather than historical price patterns.

---

### 5. Trend Following (Weight: 0.15)

**What it looks for:** Established trends with strong momentum. It uses moving averages to identify the trend direction and the ADX indicator to measure trend strength. It only signals when the trend is strong and clear.

**Plain-language analogy:** "The trend is your friend." This strategy follows the crowd -- if prices have been going up consistently with strong momentum, it goes long. If they have been falling, it goes short. It sits out when there is no clear trend.

**When it works best:** Strong, sustained moves in one direction. Gets extra weight in trending markets, less in ranging conditions.

---

### 6. Stochastic Divergence (Weight: 0.12)

**What it looks for:** A disconnect between price and momentum. Specifically, when price makes a new high but the stochastic oscillator does not (or vice versa), it signals that the move is losing steam and a reversal may be coming.

**Plain-language analogy:** Imagine a runner who keeps moving forward but is clearly slowing down. Their legs (price) are still carrying them, but their energy (momentum) is fading. Divergence catches this "tired runner" pattern, which often precedes a direction change.

**When it works best:** At the end of extended moves, when trends are exhausting themselves. Performs well in ranging markets.

---

### 7. Volatility Squeeze (Weight: 0.12)

**What it looks for:** Periods of unusually low volatility -- when the market is "coiling up" like a compressed spring. It detects when Bollinger Bands contract inside Keltner Channels (called a "squeeze") and then waits for the breakout direction.

**Plain-language analogy:** Imagine shaking a can of soda. The pressure builds while the can is sealed (the squeeze), and when you pop the top, the energy releases in a burst. This strategy identifies the pressure build-up and positions for the explosive move.

**When it works best:** Before major breakouts. It performs especially well in high-volatility environments after a brief consolidation period.

---

### 8. Supertrend (Weight: 0.10)

**What it looks for:** An adaptive trend-following indicator that adjusts its sensitivity based on current volatility. It places a dynamic support/resistance line that flips between bullish and bearish based on price action, confirmed by above-average volume.

**Plain-language analogy:** Think of a thermostat that automatically adjusts to the temperature. Supertrend is a moving line that stays close to price during calm markets and gives it more room during volatile ones. When price crosses this line with strong volume, it signals a trend change.

**When it works best:** Trending markets with clear trend changes. Gets a boost in trending and high-volatility conditions.

---

### 9. Reversal (Weight: 0.10)

**What it looks for:** Extreme market conditions that are ripe for a sharp reversal. It looks for RSI at extreme levels (very overbought or very oversold) combined with confirmation candles showing the reversal has actually begun.

**Plain-language analogy:** Markets sometimes overreact -- like a pendulum that swings too far. The Reversal strategy catches these overreactions and positions for the swing back, but only after seeing confirmation that the reversal is underway (not just hoping it will happen).

**When it works best:** At extreme highs or lows, especially in ranging markets. Gets extra weight in ranging conditions, less in strong trends.

---

## How Confluence Works

Confluence is NovaPulse's core principle: **multiple strategies must agree before any trade is placed.**

Here is how it works:

1. Every 60 seconds, NovaPulse runs all nine strategies against each trading pair.
2. Each strategy independently votes: BUY, SELL, or NO SIGNAL.
3. The bot counts how many strategies agree on the same direction.
4. **By default, at least 3 strategies must agree** for a signal to be actionable.
5. The confidence score is calculated based on how strongly the agreeing strategies are aligned.
6. If both the confluence threshold AND the confidence threshold (default 0.65) are met, the bot evaluates the trade for risk and may enter.

**Why confluence matters:** Any single strategy can produce false signals. But when three, four, or five independent strategies all see the same opportunity from different angles, the probability of a valid signal increases dramatically. It is like getting multiple expert opinions before making a big decision.

```
  Strategy 1 (Keltner):     BUY  ---+
  Strategy 2 (Mean Rev):    ---     |
  Strategy 3 (Ichimoku):    BUY  ---+---> Confluence = 4 (meets threshold)
  Strategy 4 (Order Flow):  BUY  ---+     Confidence = 0.78
  Strategy 5 (Trend):       BUY  ---+     ==> SIGNAL GENERATED
  Strategy 6 (StochDiv):    ---
  Strategy 7 (VolSqueeze):  ---
  Strategy 8 (Supertrend):  ---
  Strategy 9 (Reversal):    ---
```

---

## How the AI Weighs Strategies

Not all strategies are equal. NovaPulse uses **adaptive strategy weighting** that adjusts each strategy's influence based on two factors:

### 1. Market Regime Detection

NovaPulse continuously analyzes the current market conditions and classifies them into regimes:

| Regime | What It Means | Strategies That Get Boosted | Strategies That Get Reduced |
|--------|--------------|---------------------------|---------------------------|
| **Trending** | Strong directional movement | Trend, Ichimoku, Supertrend | Mean Reversion, Stoch Divergence, Reversal |
| **Ranging** | Sideways, back-and-forth | Mean Reversion, Stoch Divergence, Keltner | Trend, Ichimoku, Supertrend |
| **High Volatility** | Large, rapid price swings | Volatility Squeeze, Supertrend, Order Flow | Mean Reversion, Stoch Divergence |
| **Low Volatility** | Calm, quiet market | Mean Reversion, Stoch Divergence, Keltner | Volatility Squeeze, Supertrend |

This means the bot automatically adjusts which strategies have the most influence based on what the market is doing right now. Trend strategies matter more in trends; mean-reversion strategies matter more in ranges.

### 2. Auto-Tuner (Weekly Performance Review)

Every week, the **Auto-Tuner** reviews each strategy's performance over the last 50 trades and adjusts weights:

- Strategies with strong results (good Sharpe ratio, high win rate) get their weight increased
- Strategies with poor results get their weight decreased
- If a strategy performs very poorly (negative Sharpe below -0.3 over 30+ trades), it may be temporarily disabled
- Weights are bounded: no strategy can go below 0.05 or above 0.50

This means the bot continuously learns from its own results and adapts. Strategies that work well in the current market environment are given more influence; those that do not are pulled back.

---

## Strategy Guardrails

As an additional safety measure, NovaPulse monitors each strategy's rolling performance and can temporarily disable a strategy if it becomes a consistent loser:

- **Minimum win rate:** If a strategy's win rate drops below 35% over its last 30 trades, it is temporarily disabled for 2 hours
- **Minimum profit factor:** If a strategy's profit factor drops below 0.85 over its last 30 trades, it is temporarily disabled
- After the cooldown period, the strategy is re-enabled and given another chance

This prevents a single malfunctioning strategy from dragging down overall performance.

---

## Multi-Timeframe Analysis

NovaPulse does not just look at one time frame. It analyzes multiple time frames simultaneously:

- **1-minute candles:** Short-term price action
- **5-minute candles:** Medium-term trend
- **15-minute candles:** Longer-term trend

For a trade to be taken, the signal typically needs agreement across at least two time frames. This provides an extra layer of confirmation: a buy signal on the 1-minute chart is much more reliable if the 5-minute and 15-minute charts also agree.

The wider time frames also influence stop loss and take profit placement -- they tend to produce wider stops that are less likely to be hit by normal market noise.

---

## Session-Aware Trading

NovaPulse adjusts its confidence thresholds based on historical performance at different times of day. If the bot has historically performed better during certain hours (e.g., during US market hours), it gives a slight confidence boost during those times. During historically poor hours (e.g., very late night/early morning UTC), it applies a penalty.

This is a subtle adjustment (ranging from 0.70x to 1.15x confidence multiplier) but helps the bot be more selective during low-quality trading periods.

---

## Frequently Asked Questions About Strategies

**Can I disable a strategy?**
Yes. You can disable any strategy from the settings panel. However, we recommend keeping all strategies enabled -- the confluence system means underperforming strategies simply get outvoted, and you might miss opportunities if they happen to be right.

**Can I change strategy weights?**
The Auto-Tuner handles this automatically. Manual weight changes are possible via the configuration but are generally not recommended for most users.

**Why did the bot not take a trade that one strategy was signaling?**
Because confluence requires multiple strategies to agree. A single strategy signaling BUY while the others are silent or disagree does not meet the threshold. This is by design -- it keeps the bot selective and reduces false signals.

**What if all nine strategies agree?**
This is extremely rare but would produce a very high-confidence signal. In such a case, the bot would likely enter the trade (assuming risk limits allow it). Nine-strategy confluence would typically produce a confidence score well above the minimum threshold.

---

*For more on how NovaPulse protects you from losses, see [Risk and Safety](Risk-Safety.md).*
*For detailed metric explanations, see [Understanding Metrics](Understanding-Metrics.md).*
