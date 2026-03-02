# Trading Strategies

**Last updated:** 2026-03-01 | **Version:** 5.0.0

Nova|Pulse uses twelve independent trading strategies, each looking at the market from a different angle. No single strategy makes decisions alone -- instead, the bot requires multiple strategies to agree before entering a trade. This approach, called **confluence**, dramatically reduces false signals and improves trade quality.

This guide explains each strategy in plain language, how confluence works, and how the system adapts over time.

---

## The Core Idea: Confluence

Imagine twelve analysts sitting around a table, each studying the same market but using different methods. One looks at price channels. Another watches for oversold conditions. A third tracks volume patterns. A fourth studies order flow.

Nova|Pulse only opens a trade when at least two (or more, depending on your settings) of these analysts independently agree on the same direction at the same time. This is confluence -- the alignment of multiple independent viewpoints.

**Why this works:**
- Any single indicator can produce false signals
- When multiple unrelated methods agree, the probability of a genuine move is much higher
- The bot avoids impulsive entries that rely on one data point

---

## The Twelve Strategies

### 1. Keltner Channel (Weight: 0.25)

**What it watches:** Price bouncing off the walls of a dynamic channel built around the average price (20-period EMA with ATR-based bands).

**When it signals:** When price touches or crosses the lower Keltner band (potential buy) or upper band (potential sell), confirmed by MACD alignment and RSI not being overbought/oversold in the wrong direction.

**Why it works:** Keltner Channels adapt to volatility. When price hits the channel edge and other indicators confirm, it often marks a reversal point.

**Best conditions:** Works well in oscillating and mildly trending markets. This is Nova|Pulse's highest-weighted strategy based on historical performance.

---

### 2. Mean Reversion (Weight: 0.20)

**What it watches:** Price stretching far from the mean (average), measured using Bollinger Bands.

**When it signals:** When price moves beyond 2.5 standard deviations from the 50-period average, combined with RSI confirming oversold (below 25) or overbought (above 75) conditions.

**Why it works:** Markets tend to revert to their average. Extreme deviations are often temporary, and a return toward the mean provides a trading opportunity.

**Best conditions:** Ranging markets where price oscillates between levels. Less effective in strong trends where price can stay extended.

---

### 3. Volatility Squeeze (Weight: 0.18)

**What it watches:** When Bollinger Bands tighten inside Keltner Channels (a "squeeze"), indicating compressed volatility that often precedes a big move.

**When it signals:** After detecting a squeeze lasting at least 5 bars, it watches for the breakout direction using momentum. When the squeeze releases and momentum confirms, it signals.

**Why it works:** Volatility tends to cycle between compression and expansion. A prolonged squeeze builds pressure, and the breakout is often directional and strong.

**Best conditions:** Excellent in markets transitioning from calm to active. This is the TTM Squeeze concept, widely used by professional traders.

---

### 4. VWAP Momentum Alpha (Weight: 0.15)

**What it watches:** Price pulling back to the Volume-Weighted Average Price (VWAP) during a trending market, with volume and slope confirming the trend.

**When it signals:** When price is in an established trend (VWAP slope positive for longs, negative for shorts), pulls back to within a configurable distance of VWAP, and volume confirms interest.

**Why it works:** VWAP is a key reference price used by institutional traders. Pullbacks to VWAP in a trending market often represent entry opportunities before the trend resumes.

**Best conditions:** Trending markets with clear directional bias. Less useful in choppy, directionless markets.

---

### 5. Order Flow (Weight: 0.12)

**What it watches:** The order book -- who is buying and who is selling, and how aggressively.

**When it signals:** When order book imbalance shows strong directional pressure (bid side much larger than ask, or vice versa), confirmed by tight spread (showing real interest) and a pattern of higher lows (for longs) or lower highs (for shorts).

**Why it works:** The order book reveals the intentions of other traders before price moves. Heavy buy pressure with tight spreads suggests genuine demand.

**Best conditions:** Markets with liquid order books. Requires active book data from the exchange.

---

### 6. Market Structure (Weight: 0.12)

**What it watches:** The pattern of swing highs and swing lows -- the fundamental building blocks of market structure.

**When it signals:** When it detects a clear uptrend structure (higher highs and higher lows) and price pulls back to a previous swing level, or a clear downtrend structure (lower highs and lower lows) with a rally to a previous swing level.

**Why it works:** Market structure is the foundation of technical analysis. Higher highs and higher lows define an uptrend. Pullbacks to swing levels in a healthy trend are classic entry points.

**Best conditions:** Markets with clear directional structure. RSI must be in the appropriate range (not too extended).

---

### 7. Supertrend (Weight: 0.12)

**What it watches:** An ATR-based adaptive trend indicator that flips between bullish and bearish based on price relative to a dynamic support/resistance level.

**When it signals:** When the Supertrend indicator flips direction (bearish to bullish, or vice versa) and volume confirms the flip (above 1.2x the 20-period average).

**Why it works:** Supertrend adapts to volatility through ATR, making it responsive in both calm and volatile markets. Volume confirmation filters out false flips.

**Best conditions:** Markets that establish clear trends. The volume confirmation prevents signals in low-conviction moves.

---

### 8. Funding Rate (Weight: 0.10)

**What it watches:** The funding rate on perpetual futures contracts (from Kraken Futures public API).

**When it signals:** When funding rates reach extreme levels (above 0.01% or below -0.01%), it signals a potential reversal in the opposite direction of the crowd. Extremely positive funding = too many longs = potential sell signal.

**Why it works:** Extreme funding rates indicate overcrowded positioning. When everyone is on one side of the trade, the market often reverses to "punish" the crowd.

**Best conditions:** After periods of sustained one-directional positioning. This is a sentiment-based strategy rather than purely price-based.

---

### 9. Trend Following (Weight: 0.08)

**What it watches:** EMA (Exponential Moving Average) crossovers -- when the fast EMA (20-period) crosses above or below the slow EMA (50-period).

**When it signals:** Only on a **fresh** EMA cross (the cross must have happened within the last few bars, preventing constant re-signaling throughout a trend), confirmed by strong ADX (above 30, indicating genuine trend strength).

**Why it works:** Moving average crossovers are one of the oldest and most reliable trend signals. The "fresh cross" requirement and ADX confirmation filter out the many false crossovers that happen in ranging markets.

**Best conditions:** Markets transitioning from range to trend, or early in a new trend direction.

---

### 10. Ichimoku Cloud (Weight: 0.08)

**What it watches:** The Ichimoku Cloud system -- a comprehensive Japanese charting method that analyzes support/resistance (the cloud), momentum (Tenkan/Kijun lines), and trend direction all in one framework.

**When it signals:** When price and the Tenkan line cross above or below the Kijun line, with the cloud confirming the direction.

**Why it works:** Ichimoku provides multiple confirmations in a single system. Its cloud component (Senkou spans) gives a visual representation of support/resistance zones.

**Best conditions:** Trending markets. Ichimoku was designed for markets that move in clear directions.

---

### 11. Stochastic Divergence (Weight: 0.06)

**What it watches:** Divergence between price and the stochastic oscillator -- when price makes a new low but the oscillator makes a higher low (bullish divergence), or when price makes a new high but the oscillator makes a lower high (bearish divergence).

**When it signals:** When divergence is detected with the stochastic in extreme territory (below 20 for bullish, above 80 for bearish), suggesting exhaustion in the current move.

**Why it works:** Divergence between price and momentum is one of the strongest reversal signals in technical analysis. It indicates that the current move is losing steam.

**Best conditions:** End-of-trend situations where momentum is fading. Less useful in strong, sustained trends.

---

### 12. Reversal (Weight: 0.06)

**What it watches:** Extreme RSI conditions (below 15 or above 85) followed by confirmation candles showing price reversing.

**When it signals:** Only at extreme oversold/overbought readings (much more extreme than typical RSI levels), and only after price confirms the reversal with at least 5 candles of follow-through. Also requires the ATR percentage to exceed a minimum floor.

**Why it works:** Extreme RSI readings (not the commonly used 30/70 levels) represent genuine panic or euphoria. Confirmation candles help avoid catching falling knives.

**Best conditions:** Sharp market drops or spikes that create genuine extreme conditions. This is deliberately the lowest-weighted strategy because extreme readings are rare.

---

## How Confluence Scoring Works

When the bot scans a pair, all twelve strategies evaluate the data independently. The confluence engine then:

1. **Counts agreements:** How many strategies signal the same direction? This is the "confluence count."

2. **Calculates weighted strength:** Each strategy has a weight (shown above). The total weighted strength is the sum of agreeing strategy weights. For example, if Keltner (0.25) and Mean Reversion (0.20) both signal long, the weighted strength is 0.45.

3. **Applies regime multipliers:** Strategy weights are adjusted based on the current market regime. In trending markets, trend-following strategies get a boost. In ranging markets, mean-reversion strategies get boosted.

4. **Checks opposition:** If some strategies disagree with the majority, a penalty is applied. This prevents the bot from entering when the signal is contested.

5. **Applies family diversity bonus:** Strategies are grouped into "families" (mean_reversion, trend_following, momentum, microstructure, etc.). If three or more different families agree, a confidence bonus is added. If all agreeing strategies are from the same family, a penalty is applied. Diversity of viewpoints is rewarded.

6. **Adds OBI vote (optional):** If enabled, order book imbalance agreeing with the direction adds an extra confluence vote.

7. **Final confidence:** The result is a confidence score between 0 and 1, and a confluence count. Both must exceed their minimum thresholds for a trade to be considered.

### Minimum Requirements (Default)

- Confluence count >= 2 (at least two strategies agree)
- Confidence score >= 0.50
- Risk/reward ratio >= 1.0

---

## Multi-Timeframe Analysis

Nova|Pulse does not just look at one timeframe. By default, it analyzes both 5-minute and 15-minute charts:

- The **15-minute timeframe** is primary and drives the signal direction
- The **5-minute timeframe** can boost confidence when it agrees

This prevents the bot from acting on very short-term noise while still being responsive to developing setups.

---

## Adaptive Strategy Weighting

The bot does not just use fixed strategy weights forever. Two systems adjust weights over time:

### Regime Multipliers

In different market conditions, different strategies get weight adjustments:

- **Trending market:** Trend, Ichimoku, Supertrend get boosted; Mean Reversion, Stochastic Divergence get reduced
- **Ranging market:** Mean Reversion, Stochastic Divergence, Keltner get boosted; Trend, Supertrend get reduced
- **High volatility:** Volatility Squeeze, Supertrend get boosted
- **Low volatility:** Mean Reversion, Keltner, VWAP get boosted

### Auto-Tuner

The weekly auto-tuner analyzes strategy performance from the database:
- Strategies with a Sharpe ratio below -0.3 (consistently losing) can be automatically disabled
- Strategy weights are rebalanced within configured bounds (0.05 to 0.50)
- A minimum number of trades is required before the tuner makes changes

---

## Strategy Families

The twelve strategies belong to these families, used for diversity scoring:

| Family | Strategies |
|--------|-----------|
| **Mean Reversion** | Keltner, Mean Reversion |
| **Trend Following** | Trend, Ichimoku, Supertrend |
| **Momentum** | Volatility Squeeze, Stochastic Divergence, Reversal |
| **Microstructure** | Order Flow |
| **VWAP** | VWAP Momentum Alpha |
| **Structure** | Market Structure |
| **Sentiment** | Funding Rate |

When strategies from three or more different families agree, the confidence score gets a bonus. This rewards genuine multi-perspective agreement.

---

## Strategy Cooldowns

After a strategy contributes to a trade, it enters a cooldown period (default 60 seconds) before it can contribute to another trade on the same pair. This prevents rapid-fire signals from a single strategy dominating.

---

## Strategy Guardrails

The bot monitors each strategy's ongoing performance:
- After a minimum number of trades (default 20), if a strategy's win rate falls below 35% or profit factor below 1.0, it can be temporarily disabled for 2 hours
- This prevents a strategy from continuing to lose money during conditions where it does not work
- Strategies are automatically re-enabled after the cooldown to test if conditions have improved

---

## What You Can Configure

While strategy tuning is typically handled by your operator, here are the key settings:

- **Which strategies are enabled** -- any of the twelve can be turned on or off
- **Confluence threshold** -- how many strategies must agree (default 2)
- **Confidence threshold** -- minimum confidence score (default 0.50)
- **Strategy weights** -- how much influence each strategy has
- **Cooldown periods** -- minimum time between signals per strategy per pair
- **Single strategy mode** -- for testing, you can run just one strategy in isolation

See the [Configuration Guide](Configuration-Guide.md) for details.

---

*Nova|Pulse v5.0.0 -- Twelve perspectives, one decision.*
