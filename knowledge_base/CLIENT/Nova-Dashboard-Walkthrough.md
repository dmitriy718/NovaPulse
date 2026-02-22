# NovaPulse Dashboard Walkthrough

**Last updated:** 2026-02-22

Your NovaPulse dashboard is your command center -- the single place where you can see everything the bot is doing, review its performance, and take control when needed. This guide explains every section in detail.

---

## Logging In

1. Open your dashboard URL in any modern web browser.
2. Enter your username and password.
3. A session cookie keeps you logged in for up to 12 hours. After that, you will be prompted to log in again.

> **Tip:** If you are on a shared computer, click **Log Out** when you are done rather than just closing the tab.

---

## Status Indicator

At the top of the dashboard, you will see a status badge that shows the bot's current state:

```
+---------------------+
|   RUNNING           |  <-- Status badge
|   Kraken | Paper    |  <-- Exchange and mode
+---------------------+
```

| Status | Color | Meaning |
|--------|-------|---------|
| **RUNNING** | Green | The bot is actively scanning and trading normally |
| **PAUSED** | Yellow | Trading is paused -- no new trades will be opened, but existing positions are still monitored and protected |
| **STOPPED** | Red | Emergency stop is engaged -- all positions closed, no activity |
| **STALE FEED** | Orange | Market data is stale or disconnected -- the bot has automatically paused for safety |
| **OFFLINE** | Gray | The dashboard cannot reach the API server |

The status area also shows:
- **Exchange:** Which exchange is connected (Kraken or Coinbase)
- **Mode:** Whether you are in "paper" (simulated) or "live" (real money) mode
- **Uptime:** How long the bot has been running since last restart
- **Scan Count:** How many market scans have been completed

---

## Performance Overview

The performance section gives you a high-level summary of how the bot is doing:

```
+--------------------------------------------------+
|  PERFORMANCE OVERVIEW                            |
|                                                  |
|  Total P&L:      +$342.18 (+3.42%)              |
|  Win Rate:        68.2%                          |
|  Sharpe Ratio:    1.85                           |
|  Sortino Ratio:   2.41                           |
|  Max Drawdown:    -2.8%                          |
|  Total Trades:    44                             |
|  Profit Factor:   2.14                           |
+--------------------------------------------------+
```

| Metric | What It Means |
|--------|--------------|
| **Total P&L** | Your net profit or loss after all fees. Both the dollar amount and percentage are shown. |
| **Win Rate** | The percentage of closed trades that were profitable. |
| **Sharpe Ratio** | How much return you get per unit of risk. Higher is better. Above 1.0 is good; above 2.0 is excellent. |
| **Sortino Ratio** | Similar to Sharpe, but only counts downside volatility. Higher is better. |
| **Max Drawdown** | The largest peak-to-trough decline in your account. Smaller is better. |
| **Total Trades** | The number of trades that have been opened and closed. |
| **Profit Factor** | Total gross profit divided by total gross loss. Above 1.0 means profitable overall; above 2.0 is strong. |

For detailed explanations of every metric, see [Understanding Metrics](Understanding-Metrics.md).

---

## Active Positions

This panel shows all currently open trades:

```
+--------+------+----------+----------+-----------+--------+--------+
| Pair   | Side | Entry    | Current  | Unreal.PL | SL     | TP     |
+--------+------+----------+----------+-----------+--------+--------+
| BTC/USD| LONG | 64,250.00| 64,890.50| +$128.12  | 62,800 | 67,100 |
| ETH/USD| LONG |  3,420.00|  3,385.20| -$17.40   |  3,340 |  3,590 |
+--------+------+----------+----------+-----------+--------+--------+
```

| Column | Meaning |
|--------|---------|
| **Pair** | The trading pair (e.g., BTC/USD means Bitcoin priced in US dollars) |
| **Side** | LONG (betting price goes up) or SHORT (betting price goes down) |
| **Entry** | The price at which the trade was opened |
| **Current** | The current market price |
| **Unrealized P&L** | Profit or loss if the trade were closed right now (it is "unrealized" because the trade is still open) |
| **SL (Stop Loss)** | The price at which the trade will automatically close to limit losses |
| **TP (Take Profit)** | The price at which the trade will automatically close to lock in profits |

**Understanding stop loss movement:** You may notice that the stop loss price changes over time. This is because NovaPulse uses **trailing stops** -- as the price moves in your favor, the stop loss moves up too, locking in profits. See [Risk and Safety](Risk-Safety.md) for details.

---

## Trade History

The trade history panel shows all completed trades:

```
+--------+------+----------+----------+---------+----------+--------+
| Pair   | Side | Entry    | Exit     | P&L     | Duration | Status |
+--------+------+----------+----------+---------+----------+--------+
| BTC/USD| LONG | 63,800.00| 64,250.00| +$90.00 | 2h 14m   | TP Hit |
| ETH/USD| SHORT|  3,510.00|  3,480.00| +$15.00 | 45m      | TP Hit |
| BTC/USD| LONG | 64,100.00| 63,850.00| -$50.00 | 1h 22m   | SL Hit |
+--------+------+----------+----------+---------+----------+--------+
```

Features:
- **Filtering:** Filter by pair, side (long/short), date range, or result (win/loss).
- **Sorting:** Click any column header to sort by that column.
- **CSV Export:** Click the export button to download your full trade history as a CSV file -- useful for your own analysis or tax records.
- **Status codes:** "TP Hit" means take profit was reached; "SL Hit" means stop loss was triggered; "Manual" means the trade was closed by you or by the Close All command.

---

## Scanner View

The scanner shows what the bot is currently analyzing across all trading pairs:

```
+--------+--------+------------+---------+----------------------------+
| Pair   | Signal | Confidence | Conflu. | Strategies Voting          |
+--------+--------+------------+---------+----------------------------+
| BTC/USD| BUY    | 0.78       | 4/9     | Keltner, Trend, Ichi, ST   |
| ETH/USD| --     | 0.42       | 1/9     | MeanRev                    |
| SOL/USD| SELL   | 0.71       | 3/9     | StochDiv, Reversal, Keltner|
+--------+--------+------------+---------+----------------------------+
```

| Column | Meaning |
|--------|---------|
| **Pair** | The trading pair being scanned |
| **Signal** | BUY, SELL, or -- (no signal). This is the bot's current verdict for that pair. |
| **Confidence** | A score from 0 to 1 indicating how strong the signal is. Higher means the bot is more confident. The minimum threshold to trade is 0.65 (65%) by default. |
| **Confluence** | How many of the nine strategies agree on the signal direction. The minimum to trade is 3 by default. |
| **Strategies Voting** | Which specific strategies are voting in agreement |

A signal appears in the scanner even if it does not meet the thresholds to trigger a trade. This lets you see what the bot is "thinking" at all times.

---

## Strategy Performance

This panel shows how each of the nine strategies is performing individually:

```
+-----------------------+--------+----------+---------+-----------+
| Strategy              | Weight | Win Rate | Trades  | Avg P&L   |
+-----------------------+--------+----------+---------+-----------+
| Keltner Channel       | 0.30   | 72.5%    | 12      | +$18.40   |
| Mean Reversion        | 0.25   | 66.7%    | 9       | +$12.10   |
| Ichimoku Cloud        | 0.15   | 60.0%    | 5       | +$8.50    |
| Order Flow            | 0.15   | 57.1%    | 7       | +$5.20    |
| Trend Following       | 0.15   | 62.5%    | 8       | +$11.30   |
| Stochastic Divergence | 0.12   | 50.0%    | 4       | +$3.80    |
| Volatility Squeeze    | 0.12   | 66.7%    | 3       | +$14.60   |
| Supertrend            | 0.10   | 55.6%    | 9       | +$4.20    |
| Reversal              | 0.10   | 50.0%    | 2       | +$6.00    |
+-----------------------+--------+----------+---------+-----------+
```

| Column | Meaning |
|--------|---------|
| **Strategy** | The name of the trading strategy |
| **Weight** | How much influence this strategy has. Higher weight = more impact on the final decision. These weights are adjusted automatically by the AI over time (adaptive weighting). |
| **Win Rate** | Percentage of this strategy's trades that were profitable |
| **Trades** | Total number of trades where this strategy was part of the confluence |
| **Avg P&L** | Average profit or loss per trade for this strategy |

**Adaptive weighting** means the bot learns from its own results. Strategies that perform well get more influence; strategies that perform poorly get less. This happens automatically via the weekly auto-tuner.

---

## Risk Shield

The risk panel shows the current state of all risk management protections:

```
+--------------------------------------------------+
|  RISK SHIELD                                     |
|                                                  |
|  Daily P&L:         -$82.40 / -$500.00 limit     |
|  Open Exposure:     $1,240 / $5,000 max (24.8%)  |
|  Open Positions:    2 / 5 max                     |
|  Drawdown:          -1.6% / -8.0% limit           |
|  Consec. Losses:    1 / 4 limit                   |
|                                                  |
|  Circuit Breakers:  ALL CLEAR                     |
|  Exchange Feed:     HEALTHY (1s ago)              |
+--------------------------------------------------+
```

| Field | Meaning |
|-------|---------|
| **Daily P&L** | Today's profit/loss vs. the daily loss limit. If losses hit the limit, trading auto-pauses. |
| **Open Exposure** | Total dollar value of open positions vs. the maximum allowed. Shown as a percentage of your bankroll. |
| **Open Positions** | Number of open trades vs. the maximum allowed. |
| **Drawdown** | Current drawdown (decline from peak) vs. the auto-pause threshold. |
| **Consecutive Losses** | Number of losses in a row vs. the auto-pause threshold. |
| **Circuit Breakers** | Shows ALL CLEAR when everything is fine. If any circuit breaker trips, it will show which one and why. |
| **Exchange Feed** | Whether market data is flowing. Shows how long ago the last data was received. |

---

## AI Thought Feed

The thought feed is a real-time log of the bot's reasoning. Think of it as the bot "thinking out loud":

```
+-------+----------+---------------------------------------------+
| Time  | Source   | Message                                     |
+-------+----------+---------------------------------------------+
| 14:32 | scanner  | BTC/USD: 4/9 confluence, confidence 0.78    |
| 14:32 | risk     | Position size: $245 (Kelly 0.0245)          |
| 14:32 | executor | BUY 0.00381 BTC/USD @ $64,250 (paper)      |
| 14:33 | system   | Stop loss set at $62,800, TP at $67,100     |
| 14:45 | monitor  | BTC/USD trailing stop activated at +1.5%    |
| 15:01 | system   | Trading PAUSED via Telegram command          |
+-------+----------+---------------------------------------------+
```

| Message Type | What It Means |
|-------------|--------------|
| **scanner** | Results from the latest market scan (signals, confluence, confidence) |
| **risk** | Risk management decisions (position sizing, limit checks) |
| **executor** | Trade execution events (orders placed, filled, canceled) |
| **system** | System-level events (pause, resume, restarts, configuration changes) |
| **monitor** | Position monitoring events (stop loss updates, trailing stop activations) |
| **warning** | Something that needs attention but is not critical |
| **error** | Something went wrong (connection issues, order failures, etc.) |

The thought feed keeps the last 200 entries. This is extremely useful for understanding why the bot did or did not take a particular trade.

---

## Chart View

The chart view shows price action and indicators for a selected pair:

- **Candlestick chart:** Shows price movement over time (each candle represents one time period)
- **Bollinger Bands:** The shaded channel around price -- when price touches the outer bands, it may be stretched too far
- **RSI indicator:** Momentum oscillator shown below the chart (above 70 = overbought, below 30 = oversold)
- **Volume bars:** Trading volume shown at the bottom of the chart
- **Entry/Exit markers:** Your trades are marked on the chart with arrows

You can select different trading pairs and time frames to explore what the bot is seeing.

---

## Favorites

You can mark certain trading pairs as favorites for quick access:

- Click the star icon next to any pair to add it to your favorites
- Favorited pairs appear at the top of the scanner view
- Click the star again to remove it from favorites
- Favorites are saved per account and persist across sessions

---

## Settings Panel

The settings panel lets you view and adjust your configuration. Key sections include:

| Setting | What It Does |
|---------|-------------|
| **Trading Mode** | Paper (simulated) or Live (real money) |
| **Trading Pairs** | Which crypto pairs the bot monitors and trades |
| **Risk Per Trade** | Maximum percentage of bankroll risked per trade |
| **Max Position Size** | Maximum dollar amount per trade |
| **Max Daily Loss** | Percentage loss that triggers auto-pause |
| **Confidence Threshold** | Minimum signal strength to enter a trade |
| **Confluence Threshold** | Minimum number of agreeing strategies |
| **Strategy Enable/Disable** | Turn individual strategies on or off |
| **Quiet Hours** | UTC hours during which no new trades are opened |

See [Configuration Guide](Configuration-Guide.md) for detailed explanations of every setting.

> **Important:** Some settings (like switching from paper to live mode) require contacting support. The dashboard will indicate which settings you can change yourself.

---

## Integrations

The integrations panel shows the status of your exchange connections:

```
+--------------------------------------------------+
|  EXCHANGE CONNECTIONS                            |
|                                                  |
|  Kraken:    CONNECTED (WebSocket + REST)         |
|  Coinbase:  NOT CONFIGURED                       |
|                                                  |
|  Last REST call: 2s ago                          |
|  WebSocket: Connected (uptime: 14h 22m)          |
+--------------------------------------------------+
```

This tells you:
- Whether NovaPulse can reach your exchange
- Whether both the real-time data feed (WebSocket) and the order API (REST) are working
- How long since the last successful communication

---

## Alerts

The alerts panel shows important system events that may need your attention:

- **Warning:** Non-critical issues (e.g., an order took longer than expected to fill)
- **Error:** Something failed (e.g., order rejected by exchange)
- **Critical:** Requires immediate attention (e.g., exchange credentials expired)

Alerts are also sent to your notification channels (Telegram, Discord, Slack) if configured.

---

## WebSocket Live Data

Your dashboard receives real-time updates via a WebSocket connection. This means:

- **No need to refresh:** Position prices, P&L, and scan results update automatically
- **Live indicator:** A small connection indicator shows whether the live feed is active
- **Reconnection:** If the connection drops, the dashboard automatically reconnects within seconds
- **Refresh interval:** Data refreshes approximately every second

If the live feed shows as disconnected, try refreshing the page. If it persists, see [Troubleshooting](Troubleshooting.md).

---

## Dashboard Keyboard Shortcuts

| Key | Action |
|-----|--------|
| Refresh the page | F5 or Ctrl+R |
| Open settings | Click the gear icon |

---

*For detailed explanations of every metric you see on the dashboard, see [Understanding Metrics](Understanding-Metrics.md).*
*For help with any issues, see [Troubleshooting](Troubleshooting.md).*
