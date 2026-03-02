# Advanced Features (v5.0)

**Version:** 5.0.0
**Last updated:** 2026-03-01

Nova|Pulse v5.0 introduces ten optional advanced intelligence and risk features. All of these are **off by default** so upgrading does not change behavior until you or your operator explicitly enables them. This guide summarizes what each feature does in plain language, when you might want it, and what to expect.

---

## Overview

| Feature | Category | What It Does | Default |
|---------|----------|--------------|---------|
| **Macro Event Calendar** | Signal Intelligence | Pauses new trades during high-impact events | Off |
| **Lead-Lag Intelligence** | Signal Intelligence | Adjusts altcoin confidence based on BTC/ETH leader moves | Off |
| **Regime Transition Predictor** | Signal Intelligence | Anticipates trend/range shifts and boosts matching strategies | Off |
| **On-Chain Data** | Signal Intelligence | Applies blockchain sentiment to confidence scoring | Off |
| **Structural Stop Loss** | Risk Management | Places stops behind swing highs/lows instead of fixed ATR | Off |
| **Liquidity-Aware Sizing** | Risk Management | Reduces position size when order book depth is thin | Off |
| **Anomaly Detection** | Monitoring | Auto-pauses when spread/volume/depth anomalies are detected | Off |
| **P&L Attribution** | Analytics | Records which strategy/regime/session produced each trade | On (logging only) |
| **Ensemble ML** | Machine Learning | Combines TFLite + LightGBM for signal scoring | Off |
| **Bayesian Optimizer** | Machine Learning | Suggests parameter improvements based on historical performance | Off |

---

## Macro Event Calendar

### What It Is

A schedule of high-impact economic events -- FOMC interest rate decisions, CPI reports, Non-Farm Payrolls, and similar -- during which Nova|Pulse will **not open new trades**. Existing positions are still managed (stop losses still work, trailing stops still trail).

### Why It Matters

Volatility spikes around major economic announcements can trigger false signals, widen spreads unpredictably, and cause slippage. By sitting out a short blackout window (default: 30 minutes before and after the event), the bot avoids the most chaotic price action.

### How It Works

1. Events are loaded from a static JSON file (`data/events/macro_events.json`)
2. Each event has a datetime and a configurable blackout window
3. Before each scan, the bot checks: are we in a blackout?
4. If yes, new trades are skipped. A message appears in the thought feed: "Event blackout: FOMC Decision"
5. When the blackout ends, trading resumes automatically

### Optional: Earnings Data

If enabled and a Polygon API key is available, the calendar can also fetch upcoming earnings announcements and create blackout windows around them. This is particularly useful for stock trading.

### Dashboard

When the event calendar is enabled, the Advanced Features panel shows:
- Whether a blackout is currently active
- The name of the current/next event
- Time until the blackout starts or ends

---

## Lead-Lag Intelligence

### What It Is

A cross-pair signal enhancer that monitors "leader" pairs (BTC/USD, ETH/USD by default) and adjusts confidence on "follower" altcoins based on what the leaders are doing.

### How It Works

- The tracker keeps a rolling price history for leader pairs (last 5 minutes)
- When a leader makes a significant move (above 1x ATR magnitude):
  - If the move aligns with a follower's signal direction, confidence gets a boost (up to +0.15)
  - If the move opposes the follower's signal direction, confidence gets a penalty (up to -0.10)
- The adjustment is scaled by the correlation between leader and follower
- Minimum correlation threshold: 0.5 (uncorrelated pairs get no adjustment)

### When to Enable

This feature is most useful when:
- You trade multiple altcoin pairs
- BTC/ETH frequently lead your altcoin pairs (which is typical in crypto)
- You want an additional confirmation layer beyond pure technical analysis

### Example

You are about to buy SOL/USD. At the same time, BTC/USD just dropped 2% (a significant ATR-level move). The lead-lag tracker sees this opposing move and reduces your SOL confidence by 0.08 (scaled by the BTC-SOL correlation). This might tip the trade below the confidence threshold, preventing an entry into a market where the leader is signaling caution.

---

## Regime Transition Predictor

### What It Is

An anticipatory model that tries to detect when the market is about to shift between range-bound and trending conditions.

### The Four States

| State | Meaning | What the Bot Does |
|-------|---------|-------------------|
| **stable_range** | Market is range-bound and likely to stay that way | Boosts mean-reversion strategies |
| **stable_trend** | Market is trending and likely to continue | Boosts trend-following strategies |
| **emerging_trend** | Range is about to break into a trend | Pre-boosts trend strategies (+0.10 confidence) |
| **emerging_range** | Trend is about to collapse into a range | Pre-boosts mean-reversion strategies |

### How It Decides

Four independent voters analyze the market:
1. **Squeeze duration:** How long Bollinger Bands have been inside Keltner Channels. Long squeezes predict breakouts.
2. **ADX slope:** Rising ADX below 20 suggests an emerging trend. Falling ADX above 30 suggests a fading trend.
3. **Volume trend:** Rising volume in a range suggests accumulation (emerging trend). Falling volume in a trend suggests exhaustion.
4. **Choppiness analysis:** Decreasing choppiness suggests price is becoming more directional.

The voters are combined to produce the state and a confidence level (0 to 1).

### When to Enable

Useful when you want the bot to be more proactive about regime changes rather than purely reactive. Particularly helpful in markets that alternate between long quiet periods and sudden trend breakouts.

---

## On-Chain Data Integration

### What It Is

A connector that fetches blockchain-level data (exchange inflows/outflows, stablecoin supply changes, large wallet movements) and uses it as an additional sentiment signal.

### How It Works

- Sentiment is scored from -1 (bearish) to +1 (bullish) per pair
- If the absolute score exceeds the minimum threshold (0.3), a confidence adjustment is applied
- Aligned sentiment adds up to +0.08 confidence
- Opposing sentiment subtracts up to -0.08 confidence
- Data is cached with a 15-minute TTL to avoid excessive API calls

### Current Status

The architecture is complete and tested. The current implementation uses a stub data source. Real API integration (Glassnode, DeFiLlama, blockchain.info) will be connected when API subscriptions are available. Enabling this feature without API access has no effect.

---

## Structural Stop Loss

### What It Is

An intelligent stop-loss placement method that places stops behind recent swing highs or swing lows (actual market structure) rather than at fixed ATR multiples.

### How It Works

- For **long** positions: the stop is placed below the most recent swing low
- For **short** positions: the stop is placed above the most recent swing high
- A minimum buffer of 0.5x ATR is added (to avoid being stopped out by a wick touching the exact swing level)
- Maximum distance is capped at 4x ATR (to prevent unreasonably wide stops)

### Why It Is Better

Fixed ATR stops are arbitrary -- they do not respect actual market levels. Structural stops are placed where the market has already demonstrated it does not want to go (a swing low in an uptrend, for example). This means:
- Stops are less likely to be hit by random noise
- When stops are hit, it genuinely means the market structure has changed
- You trade with the market's natural levels, not against them

### When to Enable

Good for all market conditions, but particularly useful in trending markets where clear swing points exist. In choppy markets, swing points may be very close together, which the minimum ATR buffer handles.

---

## Liquidity-Aware Position Sizing

### What It Is

A position-sizing adjustment that checks order book depth before entering a trade. If the order book is thin relative to your trade size, the position is reduced to minimize market impact.

### How It Works

1. Before sizing a trade, the bot checks the order book depth on the entry side
2. It calculates the ratio of available depth to desired position size
3. If the ratio is below the minimum threshold (default 3x), the position is reduced proportionally
4. Maximum impact is capped at 10% of the order book depth

### Example

You want to enter a $300 position in SOL/USD. The order book shows $600 of depth on the bid side within your price range. The depth ratio is 2x, which is below the 3x threshold. The position size is reduced to keep impact below 10%: new position = ~$60.

### When to Enable

Most useful when:
- Trading less liquid pairs
- Trading with larger position sizes
- You want to minimize slippage and market impact

---

## Anomaly Detection Circuit Breaker

### What It Is

A protective system that monitors market conditions for anomalies and automatically pauses trading when something unusual is detected.

### What It Detects

| Anomaly | Threshold | What It Means |
|---------|-----------|---------------|
| **Spread spike** | 3x normal | Bid-ask spread is unusually wide (market stress, low liquidity) |
| **Volume anomaly** | 5x normal | Volume is extremely high (possible news, manipulation) |
| **Correlation anomaly** | >60% same direction | Most positions are moving the same way (concentrated risk) |
| **Depth drop** | >50% decline | Order book depth has fallen significantly (liquidity withdrawal) |

### What Happens

When an anomaly is detected:
1. Trading pauses immediately
2. The anomaly is logged (type, pair, severity, timestamp)
3. A cooldown timer starts (default 5 minutes)
4. When the cooldown expires, trading resumes
5. The dashboard shows the anomaly type and remaining cooldown

### When to Enable

Particularly useful during volatile market periods, around exchange maintenance windows, or when trading less liquid pairs. Acts as an early warning system for deteriorating market conditions.

---

## P&L Attribution

### What It Is

A reporting feature that records detailed metadata for each trade: which strategy triggered it, what regime the market was in, what session it was, what the confluence score was, and the eventual P&L.

### What Gets Recorded

| Field | Example |
|-------|---------|
| Strategy | "keltner" |
| Regime | "trend" |
| Volatility regime | "mid_vol" |
| Session hour (UTC) | 14 |
| Confluence count | 3 |
| Confidence | 0.72 |
| Pair | "BTC/USD" |
| Direction | "long" |
| P&L | +$42.15 |

### Why It Matters

Attribution data lets you (or your operator) answer questions like:
- "Which strategy is making the most money this month?"
- "Does the bot perform better in trending or ranging markets?"
- "Are trades during the Asian session profitable?"
- "What confluence count produces the best results?"

### Dashboard Integration

The attribution data is queryable via the dashboard API (`/api/v1/attribution`) with filters by strategy, regime, pair, and date range. The Advanced Features panel shows a strategy attribution breakdown.

### Default State

P&L attribution is **on by default** because it is purely observational -- it records data but does not change any trading behavior. There is no reason to disable it.

---

## Ensemble ML Model

### What It Is

A machine learning model that combines two different algorithms:
- **TFLite** (neural network) -- the existing predictor
- **LightGBM** (gradient boosting) -- a tree-based model

Their predictions are averaged with configurable weights (default: 40% LightGBM, 60% TFLite) to produce a more robust confidence estimate.

### Why Ensemble?

No single ML algorithm is universally best. Neural networks capture complex patterns but can overfit. Gradient boosting is robust on structured data but may miss nonlinear relationships. Combining them hedges the weaknesses of each.

### Requirements

- `lightgbm` Python package (optional dependency, installed separately)
- At least 100 trades for training
- Retrains every 24 hours

### When Enabled

The ensemble prediction replaces the standalone TFLite prediction in the confidence calculation. If LightGBM is not available, the system falls back to TFLite only.

---

## Bayesian Hyperparameter Optimizer

### What It Is

An automated system that searches for better trading parameters using Bayesian optimization (Optuna TPE algorithm).

### What It Tunes

- Confluence threshold
- Minimum confidence
- Trailing stop activation percentage
- Risk per trade
- Kelly fraction

### How It Works

1. Runs periodically (default every 48 hours)
2. Uses historical trade data to simulate "what if" scenarios with different parameters
3. Each trial evaluates the chosen metric (Sharpe ratio by default)
4. After 50 trials, reports the best parameters found
5. Results are visible on the dashboard and via API

### Important

The optimizer **suggests** -- it does not automatically apply changes. Your operator reviews the suggestions and decides whether to implement them. This prevents runaway parameter drift.

### Requirements

- `optuna` Python package (optional dependency)
- At least 200 trades for meaningful optimization

---

## Enabling Advanced Features

All v5.0 features are controlled through configuration. To enable a feature, your operator sets `enabled: true` in the appropriate config section. For example:

```yaml
event_calendar:
  enabled: true
  blackout_minutes: 30
```

You can ask your operator to enable specific features based on your trading style and risk preferences. We recommend enabling them one at a time and observing the effect before adding more.

---

## Feature Interaction

The features are designed to work independently or together:

- **Event Calendar + Anomaly Detector** = double protection during volatile periods
- **Lead-Lag + Regime Predictor** = both refine confluence confidence from different angles
- **Structural Stops + Liquidity Sizing** = smarter stop placement with depth-aware sizing
- **Ensemble ML + Bayesian Optimizer** = the ML model learns from data, the optimizer finds better parameters for the rules

Enabling all features is not necessary or recommended. Choose the ones that address your specific concerns.

---

*Nova|Pulse v5.0.0 -- Ten layers of optional intelligence, all under your control.*
