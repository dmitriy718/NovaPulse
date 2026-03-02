# Trading Features

Nova by Horizon runs the NovaPulse AI trading engine -- a fully autonomous bot that executes trades 24/7 across cryptocurrency and US stock markets. This guide explains how the trading engine works, what strategies are available, and how risk is managed.

---

## Overview

The NovaPulse engine is a multi-engine, multi-exchange trading bot that:
- Runs **12 AI strategies simultaneously** in parallel
- Trades on **3 exchanges**: Kraken (crypto), Coinbase (crypto), and Alpaca (stocks)
- Uses a **confluence engine** that requires multiple strategy agreement before executing
- Applies **institutional-grade risk management** on every trade
- Supports **multi-timeframe analysis** (5-minute and 15-minute candles)
- Detects **volatility regimes** (low/medium/high) and adapts behavior
- Implements a **smart exit system** with trailing stops and adaptive take-profit

---

## The 12 AI Strategies

Each strategy generates signals independently. The confluence engine then evaluates which strategies agree before executing a trade.

### 1. Keltner Channel (Weight: 0.25)
Detects price breakouts from Keltner Channels (exponential moving average with ATR-based bands). High-confidence signals when price breaks above/below the channel with volume confirmation.

### 2. Mean Reversion (Weight: 0.20)
Identifies statistically extreme deviations from the mean price. When an asset moves too far from its average, the strategy signals a reversal trade back toward the mean.

### 3. Volatility Squeeze (Weight: 0.18)
Monitors for Bollinger Band/Keltner Channel squeeze patterns. When volatility contracts (bands compress), the strategy prepares for a breakout in either direction once the squeeze releases.

### 4. VWAP Momentum Alpha (Weight: 0.15)
Combines Volume-Weighted Average Price analysis with momentum indicators. Signals are generated when price momentum aligns with VWAP support/resistance levels.

### 5. Order Flow (Weight: 0.12)
Analyzes order book imbalances to detect buying/selling pressure before it moves price. Requires real-time order book data from WebSocket feeds.

### 6. Market Structure (Weight: 0.12)
Identifies key support and resistance levels, trend structure breaks, and market structure shifts. Trades breakouts of significant structural levels.

### 7. Supertrend (Weight: 0.12)
A trend-following strategy based on Average True Range (ATR). Generates buy/sell signals when price crosses the Supertrend line, with ATR-based stop placement.

### 8. Funding Rate (Weight: 0.10)
Analyzes cryptocurrency perpetual futures funding rates. Extreme positive/negative funding rates indicate crowded positioning, creating opportunities for contrarian trades.

### 9. Trend (Weight: 0.08)
Uses Exponential Moving Average (EMA) crossovers with a "fresh cross" requirement -- the cross must be recent to avoid stale signals. Requires price above EMA20 above EMA50 for longs.

### 10. Ichimoku (Weight: 0.08)
Applies the Ichimoku Cloud system for trend confirmation. Evaluates Tenkan-Sen, Kijun-Sen, Senkou Span A/B, and Chikou Span for multi-dimensional trend analysis.

### 11. Stochastic Divergence (Weight: 0.06)
Detects divergences between price action and the Stochastic oscillator. Bullish divergence (price makes lower low, oscillator makes higher low) signals potential reversal.

### 12. Reversal (Weight: 0.06)
Identifies countertrend reversal patterns at key levels. Lower weight reflects the higher risk of trading against the trend.

---

## Confluence Engine

The confluence engine is the core decision-making system. It prevents the bot from chasing every signal -- trades only execute when multiple independent strategies agree.

### How It Works

1. Every scan interval (configurable, default 15 seconds), each strategy evaluates the current market for each trading pair
2. Strategies that produce a signal "vote" with a direction (long/short) and a confidence score
3. The confluence engine counts votes and calculates a weighted confluence score
4. A trade is only executed if:
   - The confluence score meets the minimum threshold (default: 2.0)
   - The confidence score meets the minimum (default: 0.50)
   - The risk/reward ratio meets the minimum (default: 1.0)
   - Multi-timeframe agreement is satisfied
   - The volatility regime allows it
   - No cooldown is active for that pair or strategy
   - The risk manager approves the position size

### Multi-Timeframe Confirmation

The bot analyzes both 5-minute and 15-minute candle data. The primary timeframe is 15 minutes, but signals from the 5-minute timeframe provide additional confirmation or early warnings.

### Volatility Regime Detection

The bot continuously classifies the current market into three regimes:
- **Low Volatility** -- Tighter position sizing, lower confluence thresholds, smaller trailing activation
- **Medium Volatility** -- Standard parameters
- **High Volatility** -- Wider stops, reduced position sizes, higher confluence requirements

The regime detection uses multiple indicators including ATR, Choppiness Index, Bollinger Band width, and ADX.

---

## Smart Exit System

Exits are as important as entries. The smart exit system uses multiple methods:

### Trailing Stops

- **Regime-Aware**: Trailing stop distances adapt to the current volatility regime
- **Adaptive Activation**: Trailing stops activate after a configurable profit threshold (default: 0.04%)
  - Low volatility: 2.5% activation
  - Medium volatility: 4.0% activation
  - High volatility: 6.0% activation

### Take-Profit Tiers

The exit system uses multiple take-profit levels:
- **TP1**: Partial exit at the first target
- **TP2**: Partial exit at the second target
- **TP3**: Full exit at the final target

Take-profit levels are calculated based on the entry price, ATR, and support/resistance levels.

### Structural Stop-Loss

When enabled, stop-loss placement is based on swing points rather than fixed percentages. The bot identifies recent swing highs/lows and places stops just beyond them, giving trades room to breathe while protecting against structural breaks.

---

## Risk Management

The bot implements multiple layers of risk control.

### Per-Trade Sizing

Every trade is sized based on:
- Account balance (bankroll)
- Maximum risk per trade (percentage of account)
- Distance to stop-loss
- Current volatility regime
- Correlation with existing positions

### Drawdown Limits

The bot monitors total drawdown from the account peak. If drawdown exceeds the configured limit, trading is automatically paused.

### Daily Loss Limit

If the day's cumulative losses exceed a percentage of the account balance, the bot pauses trading for the remainder of the day.

### Consecutive Loss Pause

After a configurable number of consecutive losing trades (default: 5), the bot automatically pauses to prevent tilt-like behavior.

### Global Cooldown on Loss

After any losing trade, a brief cooldown period (default: 30 seconds) prevents immediately re-entering the market.

### Correlation-Based Caps

The bot limits exposure to correlated assets. If you already hold a BTC/USD position, the bot reduces sizing on ETH/USD because they are highly correlated.

### Cross-Engine Risk Aggregation

When running multiple engines (e.g., Kraken + Coinbase + Stocks), a GlobalRiskAggregator ensures total exposure across all engines stays within safe limits.

---

## Multi-Exchange Support

### Kraken (Cryptocurrency)

- WebSocket v2 for real-time price data
- REST API for historical candles and order execution
- Supports major crypto pairs: BTC/USD, ETH/USD, SOL/USD, DOGE/USD, ADA/USD, XRP/USD, DOT/USD, AVAX/USD, and more
- 24/7 trading

### Coinbase (Cryptocurrency)

- REST candle polling + WebSocket for live data
- Invalid pairs are automatically excluded via a detection system
- Same crypto pairs as Kraken where available
- 24/7 trading

### Alpaca (US Stocks)

- Polygon daily bars for market data
- Alpaca API for order execution
- Dynamic universe scanner: scans 8,000+ tickers, selects top 96 by volume
- 4 pinned blue chips: AAPL, MSFT, NVDA, TSLA
- 92 dynamically selected stocks refreshed hourly
- Market hours only (9:30 AM - 4:00 PM ET, weekdays)

### Priority Scheduling

The bot automatically manages priority between markets:
- During US market hours (9:30-16:00 ET weekdays): Stock trading takes priority
- Outside market hours: Crypto engines take full priority
- This ensures the bot focuses its analysis capacity on whichever market is active

---

## Session-Aware Trading

The bot is aware of trading sessions and adjusts behavior:
- **Quiet hours** (configurable): Reduced activity during low-liquidity periods (default: 3 AM UTC)
- **Session penalties**: Maximum penalty of 0.85 applied during off-peak hours to reduce trade frequency
- **Weekend handling**: Stock markets are closed; crypto continues trading

---

## Bot Controls

From the dashboard, you have full control over your bot:

- **Pause**: Temporarily stop all new trades (existing positions remain open)
- **Resume**: Re-enable trading after a pause
- **Kill**: Emergency stop that closes all positions and halts the bot

These controls are accessed via the dashboard UI and are forwarded to the bot via the proxy API.

---

## Advanced Features (v5.0)

The following advanced features are available (default disabled, can be enabled in configuration):

1. **Event Calendar** -- Automatic blackout periods around FOMC, CPI, NFP events
2. **Lead-Lag Intelligence** -- BTC/ETH leader move detection for follower pairs
3. **Regime Transition Predictor** -- Predicts upcoming regime changes using squeeze/ADX/vol/chop voting
4. **On-Chain Data** -- Blockchain sentiment signals for additional confluence
5. **Structural Stops** -- Swing-point-based stop-loss placement
6. **Liquidity Sizing** -- Order book depth-based position reduction
7. **Anomaly Detector** -- Circuit breaker for abnormal spread/volume/correlation
8. **P&L Attribution** -- Per-trade strategy attribution records
9. **Ensemble ML** -- TFLite + LightGBM weighted average model
10. **Bayesian Optimizer** -- Optuna TPE hyperparameter tuning

---

*Last updated: March 2026*
