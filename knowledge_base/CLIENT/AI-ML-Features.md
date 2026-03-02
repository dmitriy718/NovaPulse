# AI and Machine Learning Features

**Version:** 5.0.0
**Last updated:** 2026-03-01

Nova|Pulse uses artificial intelligence and machine learning to improve the quality of its trading decisions. This guide explains how the AI works in plain language -- what it does, what it does not do, and why it matters for your account.

---

## The Key Principle

Nova|Pulse's AI does not replace the technical strategies -- it enhances them. Think of the twelve strategies as your core analysts, and the AI as a supervisor that:

- Learns which strategies work best in which conditions
- Predicts whether a trade setup is likely to succeed
- Adjusts confidence scores based on historical patterns
- Tunes strategy parameters based on accumulated data

The AI never overrides a strategy signal. It adjusts confidence levels and can tip a marginal setup below the threshold, or boost a strong setup higher.

---

## TFLite Predictor

### What It Does

The TFLite (TensorFlow Lite) predictor is a lightweight neural network that evaluates trade setups:

- **Input:** A vector of market features (RSI, ATR percentage, Bollinger Band position, ADX, volume ratio, OBI, momentum score, trend strength, spread percentage)
- **Output:** A probability score indicating how likely the trade is to be profitable
- **Impact:** The prediction influences the final confidence score for the trade

### How It Trains

The model trains on your bot's own trade history:
1. Every completed trade has its entry-time features recorded in the database
2. The outcome (profitable or not) is also recorded
3. Periodically (default weekly), the model retrains on this accumulating dataset
4. Minimum 500 trades are needed before training begins

### Cold Start

When you first start, the model has no data. During this period:
- The model gracefully falls back to a neutral prediction
- Strategies and confluence still work normally without the AI boost
- As trades accumulate, the model starts learning

---

## Continuous Learner

### What It Does

In addition to the periodic retraining, a continuous learner uses online SGD (Stochastic Gradient Descent) to make small, ongoing adjustments to the model after each trade completes.

**Why this matters:** Markets change. A model trained on last month's data may not perfectly fit this month's conditions. The continuous learner provides incremental adaptation between major retraining cycles.

### How It Works

1. A trade closes
2. The continuous learner compares the prediction to the actual outcome
3. It makes a small weight adjustment (much smaller than full retraining)
4. The model gradually adapts to shifting market conditions

---

## Session Analyzer

### What It Does

The session analyzer tracks your bot's win rate and profitability by hour of the day (UTC). It then applies confidence multipliers:

- **High-performing hours** get a small confidence boost (up to 15%)
- **Low-performing hours** get a small confidence penalty (down to 85% of baseline)
- **Insufficient data hours** get no adjustment

### Why This Matters

Different hours of the day have different market characteristics:
- Asian session (UTC 0-8) has different liquidity than US session (UTC 14-20)
- Some hours consistently produce better setups than others
- The session analyzer learns this from your specific trading history

### Requirements

The analyzer needs at least 5 trades per hour before applying adjustments. Until then, all hours are treated equally.

---

## Auto Strategy Tuner

### What It Does

The auto-tuner runs weekly (default) and evaluates each strategy's performance:

1. Calculates Sharpe ratio, win rate, and profit factor for each strategy over a rolling window
2. Strategies with Sharpe ratio below -0.3 (consistently losing) can be auto-disabled
3. Strategy weights can be rebalanced within bounds (0.05 to 0.50)
4. A minimum of 15 trades per strategy is required before changes

### What This Means for You

- Strategies that stop working in current conditions get sidelined
- Working strategies get more influence
- The bot adapts its strategy mix over time based on real performance
- Disabled strategies are re-evaluated periodically

---

## Ensemble ML Model (v5.0, Optional)

### What It Does

When enabled, the ensemble model combines two different ML approaches:

1. **TFLite neural network** -- the existing predictor (deep learning approach)
2. **LightGBM gradient boosting** -- a tree-based model that excels at tabular data

The two models make independent predictions, which are then combined using a weighted average (default: 40% LightGBM, 60% TFLite).

### Why Two Models?

Different model architectures have different strengths:
- Neural networks capture complex nonlinear relationships
- Gradient boosting is excellent at learning from structured features
- Combining them often produces more robust predictions than either alone

### Requirements

- LightGBM Python package must be installed (optional dependency)
- Minimum 100 trades for training
- Retrains every 24 hours (default)

### Feature Importance

LightGBM provides built-in feature importance, showing which market features (RSI, volume ratio, ADX, etc.) are most predictive for your specific trading. This is visible in the Advanced Features dashboard panel.

---

## Bayesian Hyperparameter Optimizer (v5.0, Optional)

### What It Does

The optimizer uses Optuna (a Bayesian optimization framework) to automatically search for better parameter values:

- **What it tunes:** Confluence threshold, minimum confidence, trailing stop activation, risk parameters, and more
- **How it searches:** Tree-structured Parzen Estimator (TPE) -- an efficient algorithm that learns which parameter regions produce better results
- **What it optimizes for:** Configurable metric -- Sharpe ratio (default), profit factor, or Calmar ratio

### How It Works

1. The optimizer runs periodically (default every 48 hours)
2. It evaluates different parameter combinations against your historical trade data
3. Each trial simulates how the system would have performed with different settings
4. After 50 trials (default), it reports the best parameters found
5. The operator can review and apply the suggestions

### Important Note

The optimizer **suggests** parameter changes -- it does not automatically apply them. This is intentional. Parameter changes should be reviewed by a human before deployment.

### Requirements

- Optuna Python package must be installed (optional dependency)
- Minimum 200 trades for meaningful optimization
- The optimization result is visible on the dashboard and via the API

---

## Lead-Lag Intelligence (v5.0, Optional)

### What It Does

Monitors "leader" pairs (BTC/USD, ETH/USD) for significant moves, then adjusts confidence on "follower" altcoins:

- If BTC moves up strongly and your signal is to buy an altcoin, confidence gets a small boost (up to +0.15)
- If BTC moves down strongly and your signal is to buy an altcoin, confidence gets a small penalty (up to -0.10)

### Why This Matters

In crypto markets, BTC and ETH often lead altcoin movements. When Bitcoin rallies, altcoins typically follow. The lead-lag tracker uses this correlation to validate or caution against altcoin trades.

### How It Decides

- Tracks leader pair prices over a rolling window (default 5 minutes)
- Calculates the magnitude of the move relative to ATR
- Computes correlation between the leader and follower pair
- Only applies adjustment when correlation exceeds the minimum threshold (0.5)

---

## Regime Transition Predictor (v5.0, Optional)

### What It Does

Anticipates when the market is about to shift from range-bound to trending (or vice versa) by analyzing:

1. **Squeeze duration** -- how long Bollinger Bands have been inside Keltner Channels
2. **ADX slope** -- whether trend strength is increasing or decreasing
3. **Volume trend** -- whether volume is expanding or contracting
4. **Choppiness analysis** -- whether price action is becoming more or less organized

### Output States

- **stable_range** -- market staying range-bound
- **stable_trend** -- market in an established trend
- **emerging_trend** -- range about to break into trend (boosts trend strategies)
- **emerging_range** -- trend about to collapse into range (boosts mean reversion strategies)

### Why This Matters

By the time a trend is obvious, much of the move is over. The regime predictor tries to detect the transition early, giving trend-following strategies a head start when a new trend is forming.

---

## On-Chain Data Integration (v5.0, Optional)

### What It Does

Fetches blockchain-level sentiment data (exchange flows, stablecoin supply changes, large transactions) and applies a small confidence adjustment:

- Aligned on-chain sentiment (e.g., outflows from exchanges = bullish, matching a long signal) adds up to +0.08 confidence
- Opposing sentiment applies up to -0.08 penalty

### Current Status

The on-chain module is architecturally complete but currently uses a stub data source. Real API integration (Glassnode, DeFiLlama, etc.) will be connected when API keys are available.

---

## What the AI Cannot Do

To set expectations clearly:

- **The AI cannot predict the future.** It identifies patterns from historical data, but past patterns do not guarantee future results.
- **The AI does not replace risk management.** Even a high-confidence prediction can lose money. Stop losses and position sizing protect you regardless of the AI's opinion.
- **The AI needs data to learn.** In the first weeks, the model is essentially neutral. Give it time to accumulate enough trades (ideally 200+) before evaluating its contribution.
- **The AI can be wrong.** It is one input among many. The confluence system, risk checks, and circuit breakers provide additional layers of judgment.

---

## Summary of AI Components

| Component | What It Does | When Active | Data Needed |
|-----------|-------------|-------------|-------------|
| TFLite Predictor | Neural network trade scoring | After 500 trades | Automatic |
| Continuous Learner | Ongoing model adaptation | Always | Automatic |
| Session Analyzer | Per-hour confidence adjustment | After 5 trades/hour | Automatic |
| Auto Tuner | Weekly strategy weight rebalancing | Weekly | 15 trades/strategy |
| Ensemble ML | Combined LightGBM + TFLite | When enabled, after 100 trades | Requires lightgbm package |
| Bayesian Optimizer | Parameter tuning suggestions | When enabled, after 200 trades | Requires optuna package |
| Lead-Lag Intelligence | Cross-pair confidence adjustment | When enabled | Real-time |
| Regime Predictor | Market state transition detection | When enabled | Real-time |
| On-Chain Data | Blockchain sentiment adjustment | When enabled + API available | External API |

---

*Nova|Pulse v5.0.0 -- Intelligence that learns from every trade.*
