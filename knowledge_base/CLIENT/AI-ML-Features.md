# AI and Machine Learning Features

**Version:** 4.5.0
**Last updated:** 2026-02-24

NovaPulse uses artificial intelligence to improve the quality of its trading decisions. This guide explains how the AI works in plain language -- what it does, what it does not do, and why it matters for your account.

---

## The Key Principle

**The AI does not make trading decisions. It provides a quality score that helps filter out lower-probability signals.**

Think of it this way: NovaPulse's nine trading strategies are like a team of analysts who identify potential opportunities. The AI acts as a senior reviewer who examines each opportunity and rates it on a scale from low to high quality. If the AI rates a signal poorly, NovaPulse reduces its confidence and may skip the trade. If the AI rates it well, the confidence is boosted and the trade is more likely to be taken.

The strategies find the opportunities. The AI helps separate the good ones from the mediocre ones.

---

## The Two AI Models

NovaPulse uses two separate AI models that work together. Each approaches the problem differently, and combining them produces better results than either one alone.

### 1. TFLite Neural Network (The Trained Expert)

This is a pre-trained neural network -- a type of AI model that has been trained on historical trade data to recognize patterns associated with winning and losing trades.

**How it works:**

1. When a trading signal is generated, NovaPulse extracts 12 features from the current market conditions (more on these features below).
2. These 12 features are fed into the neural network.
3. The network outputs a probability score between 0 and 1, representing its estimate of how likely this signal is to result in a winning trade.
4. This score is used to adjust the signal's confidence.

**Plain-language analogy:** Imagine an experienced doctor who has seen thousands of patients. When a new patient walks in, the doctor quickly recognizes patterns -- "I have seen these symptoms before, and 70% of the time they indicate condition X." The neural network does the same thing with market conditions: it has seen thousands of historical trades and recognizes which patterns tend to lead to winners.

**Retraining:** The neural network is periodically retrained (weekly by default) using your actual trade history. This means it adapts to current market conditions over time. If market behavior shifts, the model learns from recent trades and adjusts.

### 2. Continuous Learner (The Adaptive Student)

The Continuous Learner is an online model that improves with every single trade, in real time.

**How it works:**

1. Every time a trade closes, the Continuous Learner receives the trade's features and outcome (win or loss).
2. It immediately updates its internal model with this new data point.
3. On the next signal, it provides its own probability score based on its accumulated learning.

**Plain-language analogy:** If the neural network is the experienced doctor, the Continuous Learner is a medical resident who learns from each new case in real time. The resident may not have as much historical experience, but they are learning rapidly and are especially attuned to what is happening right now.

**Key properties:**

- Starts with no knowledge and builds up over time (needs at least 50 trade examples before it starts making predictions).
- Persists across restarts -- its learning is saved to disk.
- Fail-safe: if anything goes wrong with the Continuous Learner, NovaPulse silently falls back to the neural network or pure strategy-based confidence.

---

## How the Two Models Combine

When both models are available and have enough data, NovaPulse blends their scores to produce a final AI confidence:

```
Strategy Confidence:    Based on the strength of the signals from the nine strategies
Neural Network Score:   Based on 12 features, trained on historical trades
Continuous Learner:     Based on real-time learning from recent trades
                        |
                        v
                 Final Confidence
```

The blending works as follows:

- **For multi-strategy signals** (strong confluence, 2+ strategies agree): The final confidence is an equal blend of the strategy confidence and the AI confidence. However, the AI can never fully veto a strong multi-strategy consensus -- the blended result is floored at 85% of the original strategy confidence. This prevents a temporarily pessimistic AI from overriding strong technical signals.

- **For single-strategy signals** (only one strategy firing): The strategy confidence gets 70% weight and the AI gets 30% weight. Solo signals are inherently less reliable, so the AI has a smaller role -- these trades are primarily used as learning opportunities for the AI.

This means the AI refines existing signals rather than generating its own. It acts as a quality filter, not a signal generator.

---

## The 12 Features the AI Analyzes

Every time a signal is generated, NovaPulse extracts these 12 features from the current market state:

| # | Feature | What It Measures |
|---|---------|-----------------|
| 1 | **RSI** | Relative Strength Index -- how overbought or oversold the market is (0-100) |
| 2 | **EMA Ratio** | Ratio of the short-term average to the long-term average -- measures trend strength |
| 3 | **Bollinger Band Position** | Where the current price sits relative to its Bollinger Bands -- near the top, middle, or bottom |
| 4 | **ADX** | Average Directional Index -- how strong the current trend is, regardless of direction |
| 5 | **Volume Ratio** | Current volume compared to the recent average -- detecting unusual activity |
| 6 | **Order Book Imbalance** | The balance between buy and sell orders on the exchange -- real-time supply/demand pressure |
| 7 | **ATR%** | Average True Range as a percentage of price -- current volatility level |
| 8 | **Momentum Score** | A composite measure of recent price momentum across multiple timeframes |
| 9 | **Trend Strength** | How consistent and strong the directional trend is |
| 10 | **Spread%** | The bid-ask spread as a percentage of price -- a measure of liquidity and trading cost |
| 11 | **Trend Regime Encoding** | A numeric code representing the current market regime (trending vs. ranging) |
| 12 | **Volatility Regime Encoding** | A numeric code representing the current volatility environment (high vs. low) |

**Why these 12?** Each feature captures a different dimension of the market. Together, they give the AI a comprehensive snapshot: Is the market trending or ranging? Is volatility high or low? Is there unusual volume or order flow? Is the price near an extreme or in the middle of its range? The AI uses all of these simultaneously to form its assessment.

---

## Auto Strategy Tuner

Beyond the two AI models, NovaPulse includes an **Auto Strategy Tuner** that adjusts strategy weights based on real performance data.

**How it works:**

1. Every week, the Tuner reviews the last 50 trades for each of the nine strategies.
2. For each strategy, it calculates performance metrics: win rate, Sharpe ratio (a measure of risk-adjusted return), and profit factor.
3. Strategies that have been performing well get their weight increased.
4. Strategies that have been performing poorly get their weight decreased.
5. If a strategy has been consistently losing (negative Sharpe ratio below -0.3 over 30+ trades), it may be temporarily disabled.

**Guardrails:**
- No strategy's weight can go below 0.05 (5%) or above 0.50 (50%).
- Disabled strategies are re-enabled after a cooldown period and given another chance.
- Weight changes are gradual -- no sudden, dramatic shifts.

**Plain-language analogy:** Imagine a coach managing a nine-player team. Each week, the coach reviews game film and adjusts the lineup. Players who have been scoring get more playing time; those who have been struggling get fewer minutes but are not cut from the team. The Tuner is this coach, continuously optimizing the lineup based on recent results.

---

## Session-Aware Trading

NovaPulse does not treat all hours of the day equally. The **Session Analyzer** tracks historical win rates by hour and adjusts confidence accordingly.

**How it works:**

1. Over time, NovaPulse builds up a picture of which hours of the day have historically produced better results.
2. During hours with strong historical performance, confidence gets a slight boost (up to 1.15x).
3. During hours with historically poor performance, confidence gets a slight penalty (down to 0.70x).
4. This data is refreshed hourly from your actual trade history.

**Why this matters:** Crypto markets behave differently at different times of day. During US and European business hours, there tends to be more volume and clearer price action. During the quietest hours (late night UTC), signals can be less reliable. The Session Analyzer nudges NovaPulse to be more selective during historically weak hours and more confident during historically strong ones.

**The adjustment is subtle.** This is not a major gate -- it is a gentle multiplier that provides a small edge over time.

---

## Cross-Exchange ML Training

If you are running multiple exchanges (see [Multi-Exchange Trading](Multi-Exchange-Trading.md)), NovaPulse's AI can learn from trades across all of them.

**How it works:**

1. The primary (leader) engine collects training data from its own database.
2. It also reads labeled trade data from the other exchange databases (Coinbase, Stocks).
3. When the neural network retrains, it uses this aggregated dataset.
4. Patterns that are consistent across exchanges are reinforced; exchange-specific noise is diluted.

**Why this helps:** More data means better learning. A signal pattern that leads to winning trades on both Kraken and Coinbase is more likely to be genuinely predictive than one that only works on a single exchange. Cross-exchange training gives the AI a broader, more robust view of what works.

---

## ES Enrichment (External Signals)

NovaPulse can optionally incorporate external data sources to give the AI additional context:

- **Fear and Greed Index:** A 0-100 score measuring overall market sentiment. Extreme fear often precedes reversals upward; extreme greed often precedes reversals downward.
- **Crypto Volume Trends:** 24-hour volume changes from CoinGecko, indicating whether market activity is increasing or decreasing.
- **Social Sentiment:** News sentiment from CryptoPanic, capturing whether recent headlines are positive, negative, or neutral.
- **On-Chain Data:** Blockchain-level activity metrics that can signal large-scale movements.

These external signals are stored and associated with each trade for training. Over time, the AI learns whether these broader market conditions correlate with better or worse trade outcomes.

**Important:** These enrichment features are supplementary. They enhance the AI's training data but are not required for NovaPulse to function. If any external data source is unavailable, the AI continues working normally with its core 12 features.

---

## What the AI Does NOT Do

Transparency is important, so here is what the AI is not:

- **It is not a crystal ball.** The AI provides probability estimates, not certainties. A high AI confidence score means the conditions are historically favorable, not that the trade is guaranteed to win.
- **It does not generate signals on its own.** The nine trading strategies generate signals; the AI only scores them.
- **It is not infallible.** The AI can be wrong, especially in market conditions that differ significantly from its training data. This is why NovaPulse uses it as one input among many, not as the sole decision-maker.
- **It does not override risk management.** Even if the AI gives a perfect score, all risk checks (position sizing, daily loss limits, max exposure) still apply. The AI cannot bypass safety systems.

---

## How the AI Improves Over Time

NovaPulse's AI is not static. It improves through several mechanisms:

1. **Weekly retraining:** The neural network retrains on the latest trade data, adapting to current market conditions.
2. **Continuous learning:** The Continuous Learner updates with every single trade in real time.
3. **Auto-tuning:** The Strategy Tuner adjusts weights weekly based on performance.
4. **Session analysis:** The Session Analyzer continuously refines its hourly confidence adjustments.
5. **Cross-exchange aggregation:** As you trade on more exchanges, the training dataset grows and diversifies.

Think of it as a system that gets a little smarter with every trade, every day, every week. The improvements are gradual but compounding.

---

## Frequently Asked Questions

**Can I turn off the AI?**
The AI is an integral part of NovaPulse and cannot be fully disabled through the subscriber dashboard. However, it is designed to enhance signals, not override them. If you want to understand how trades would look without AI scoring, paper mode lets you observe the system's behavior without financial risk.

**How long does the AI need to become effective?**
The neural network is effective from day one if pre-trained on historical data. The Continuous Learner needs at least 50 completed trades to start making predictions. Depending on market conditions and trading frequency, this typically takes one to three weeks.

**Does the AI work the same for stocks and crypto?**
The core 12 features are applicable to both asset classes, but the models are trained on exchange-specific data. The stock engine's signals use a different structure (EMA/RSI/momentum rather than nine-strategy confluence), so the AI's role in stock trading is less central. Over time, cross-exchange training allows the AI to find patterns that span both asset classes.

**What happens if the AI model file is corrupted or missing?**
NovaPulse includes fail-safe mechanisms. If the neural network cannot load, the system falls back to strategy-based confidence only. If the Continuous Learner encounters an error, it returns no score and the neural network handles the assessment alone. Trading never stops because of an AI issue.

---

*For details on the trading strategies the AI scores, see [Trading Strategies](Trading-Strategies.md).*
*For risk protections, see [Risk and Safety](Risk-Safety.md).*
*For multi-exchange features, see [Multi-Exchange Trading](Multi-Exchange-Trading.md).*
*Questions? See our [FAQ](FAQ.md) or [contact support](Contact-Support.md).*
