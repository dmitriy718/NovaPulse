# Nova|Pulse Bot Dashboard Walkthrough

**Last updated:** 2026-03-01

Your Nova|Pulse bot has a built-in dashboard accessible directly on your bot's server (typically at port 8090 on the host, mapped to 8080 inside the container). This is your full admin panel where you can see everything the bot is doing, review performance, and take full control. This guide explains every section in detail.

> **Looking for the Horizon web dashboard?** If you want to monitor your bot from [horizonsvc.com](https://horizonsvc.com) (the cloud dashboard with gamification and a mobile-friendly design), see [Horizon Dashboard](Horizon-Dashboard.md). This page covers the **bot's built-in dashboard** -- the direct admin interface.

---

## Logging In

Navigate to your bot's URL in any modern browser. You will see a login screen.

- Enter your **username** and **password** (provided in your welcome email).
- The session is secured with CSRF protection and bcrypt-hashed passwords.
- After 5 failed login attempts in 5 minutes, the account locks temporarily (brute-force protection).

Once logged in, you land on the Command Center -- a single-page, dark-themed HUD that updates in real time.

---

## The Header Bar

The header bar spans the top of the page and is always visible, even when scrolling.

### Left Section

- **Logo:** "NOVA|PULSE v5.0" -- confirms the version running.
- **Status Indicator:** A color-coded pulsing dot with text:
  - **Green + "OPERATIONAL"** = WebSocket connected, data flowing normally.
  - **Yellow + "DEGRADED"** = Connected but data may be stale (no ticker updates recently).
  - **Red + "DISCONNECTED"** = WebSocket lost. The dashboard will attempt to reconnect automatically.
  - **Orange + "PAUSED"** = Bot is running but trading is paused (manually or by auto-pause).

### Center Section

Three key stats always visible at a glance:

| Stat | What It Shows |
|------|--------------|
| **MODE** | "PAPER" (simulated trades, no real money) or "LIVE" (real orders on your exchange) |
| **UPTIME** | Time since the bot started, displayed as HH:MM:SS |
| **SCAN #** | Total number of market scan cycles completed. Each scan evaluates all pairs across all strategies. |

### Right Section

Four action buttons:

| Button | Action |
|--------|--------|
| **LOGOUT** | Ends your session and returns to the login screen |
| **SETTINGS** | Opens the settings modal for dashboard customization |
| **PAUSE / RESUME** | Toggles trading on/off. When paused, no new trades are opened but existing positions continue to be managed (stops still work). |
| **CLOSE ALL** | Emergency button: closes all open positions at market price. Requires confirmation. Use with caution. |

---

## Portfolio Card

The primary card at the top of the main grid. This is your financial snapshot.

### Main Display

- **Total P&L** -- Large, prominent number. Your cumulative realized profit or loss across all closed trades since the last stats reset. Green when positive, red when negative.
- **Total Equity** -- Your current bankroll value, calculated as initial bankroll plus total realized P&L plus unrealized P&L on open positions.

### P&L Grid

| Metric | What It Means |
|--------|--------------|
| **Unrealized** | Paper profit/loss on currently open positions. This changes with every price tick. |
| **Realized** | Profit/loss from trades closed today (UTC day). |
| **Win Rate** | Percentage of closed trades that ended in profit. Example: "65.0%" means 65 winners per 100 trades. |
| **Total Trades** | Count of completed (closed) trades since last stats reset. |
| **Best Trade** | Your single most profitable trade in USD. |
| **Worst Trade** | Your largest losing trade in USD. |
| **Avg Win** | Average profit on winning trades. |
| **Avg Loss** | Average loss on losing trades. Healthy systems have avg win > avg loss. |
| **Profit Factor** | Gross profit divided by gross loss. Above 1.0 = profitable, above 2.0 = strong. |
| **Sharpe Ratio** | Risk-adjusted return. Above 1.0 is good, above 2.0 is excellent. |

### Share Stats

Click **Share Stats** to generate a visual summary image of your performance metrics. You can download it or share it directly. The image includes your key numbers in a branded format.

---

## Positions Table

Shows every currently open position across all exchanges and asset classes.

### Column Reference

| Column | Description |
|--------|------------|
| **Pair** | Trading pair (e.g., "BTC/USD") or stock symbol with exchange label (e.g., "AAPL (stocks:default)") |
| **Dir** | Direction: LONG (expecting price to rise) or SHORT (expecting price to fall) |
| **Entry** | Price at which the position was opened |
| **Current** | Latest market price |
| **Size (USD)** | Position size in US dollars |
| **Unrealized P&L** | Profit/loss if this position were closed right now |
| **Confidence** | AI confidence score at entry (0.00 to 1.00) |
| **Confluence** | Number of strategies that agreed on this trade |
| **Strategy** | Primary strategy that triggered the trade |
| **SL/TP Bars** | Visual bars showing distance to stop loss (red) and take profit (green) as a percentage of current price |
| **Duration** | How long the position has been open |

### Reading Position States

- **Green P&L** = position is in profit
- **Red P&L** = position is at a loss
- **"Trailing" badge** = trailing stop has activated (the position passed the activation threshold)
- **"Breakeven" badge** = stop loss has been moved to the entry price (your downside is protected)

### Stock vs. Crypto Positions

Stock positions appear with the "(stocks:default)" suffix and are only active during US market hours (9:30 AM -- 4:00 PM Eastern). Crypto positions can be open 24/7.

---

## Strategy Performance Panel

A table showing how each of the twelve strategies is performing.

| Column | Meaning |
|--------|---------|
| **Strategy** | Name (Keltner, Mean Reversion, Volatility Squeeze, VWAP Momentum Alpha, Order Flow, Market Structure, Supertrend, Funding Rate, Trend, Ichimoku, Stochastic Divergence, Reversal) |
| **Weight** | Current weight in the confluence voting system (higher = more influence) |
| **Trades** | Total trades this strategy participated in |
| **Win Rate** | What percentage of this strategy's trades were profitable |
| **Avg P&L** | Average profit/loss per trade for this strategy |
| **Status** | "Active" (enabled) or "Disabled" (auto-tuner turned it off due to poor performance) |

This panel helps you understand which strategies are pulling their weight and which may need attention.

---

## AI Thought Feed

A live-scrolling log of the bot's internal reasoning and system events. This is the most informative panel for understanding the bot's decisions.

### What You Will See

**Trade Activity:**
- "Confluence signal: BTC/USD LONG | confidence=0.72 | confluence=3 | strategies=[keltner, mean_reversion, volatility_squeeze]"
- "Trade opened: BTC/USD LONG | entry=$67,450 | size=$280 | SL=$66,100 | TP=$69,500"
- "Trade closed: ETH/USD SHORT | P&L=+$18.42 | reason=TP hit | duration=2h15m"
- "Risk rejected: SOL/USD LONG | reason=daily_loss_limit_reached"

**System Events:**
- "Bot engine STARTED - All systems operational"
- "Priority schedule PAUSED kraken engine | phase=equities_day_session"
- "Auto-pause: consecutive_losses | 5 losses in a row"
- "Health check: all pairs fresh, 8/8 WS subscriptions active"

**Warmup:**
- "Warming up BTC/USD: loading 900 bars of 1m data"
- "Warmup complete for all 8 pairs"

### Severity Color Coding

- **Blue (info)** -- Normal operational messages
- **Yellow (warning)** -- Degraded conditions, auto-pauses, stale data warnings
- **Red (error)** -- Exchange errors, connection failures, critical issues

The feed keeps the most recent 200 entries. Historical entries are preserved in the database and log files.

---

## Risk Report

Shows the current state of all risk management systems.

| Metric | Description |
|--------|------------|
| **Current Bankroll** | Working capital = initial bankroll + cumulative realized P&L |
| **Initial Bankroll** | Starting capital (configured in settings) |
| **Daily P&L** | Profit/loss for the current UTC day |
| **Daily Loss Limit** | Maximum loss per day (default 5% of bankroll). Trading pauses when reached. |
| **Daily Loss Used** | How much of the daily loss budget has been consumed |
| **Total Exposure** | Sum of all open positions in USD |
| **Exposure %** | Total exposure as percentage of bankroll |
| **Max Exposure** | Exposure cap (default 50% of bankroll) |
| **Open Positions** | Current count |
| **Max Positions** | Maximum allowed concurrent positions |
| **Consecutive Losses** | Current losing streak. Auto-pause triggers at threshold (default 5). |
| **Kelly Fraction** | Current Kelly Criterion sizing factor |
| **Correlation Groups** | Position count per correlation group (e.g., "alt_l1: 2/2") |

---

## Market Scanner

Shows the pairs being monitored and their current state.

| Column | Description |
|--------|------------|
| **Pair** | Trading pair or stock symbol |
| **Price** | Latest price |
| **Bars** | Number of candle bars loaded |
| **Regime** | Market regime classification: "trend", "range", "high_vol", or "low_vol" |
| **Vol Regime** | Volatility classification: "high_vol", "mid_vol", or "low_vol" |
| **Last Signal** | Most recent signal (if any) and its direction |
| **Freshness** | Whether data is current or stale |

---

## Advanced Features Panel (v5.0)

Visible when any v5.0 advanced feature is enabled. Shows real-time status of each feature.

Each feature displays:
- **Enabled/Disabled** toggle state
- **Current status** (e.g., "Blackout active: FOMC" for Event Calendar, or "emerging_trend (0.72)" for Regime Predictor)
- **Key metrics** specific to each feature

See the [Advanced Features guide](Advanced-Features.md) for what each feature does.

---

## Settings Modal

Click **Settings** in the header to customize your dashboard view:

- **Panel visibility** -- show or hide specific cards/panels
- **Refresh interval** -- how often the dashboard requests new data (default 1000ms)
- **Feature toggles** -- which v5.0 features to show in the Advanced panel
- **Thought feed depth** -- how many thought entries to display

**Important:** The settings modal changes the dashboard display only. It does not change the bot's trading behavior. For trading parameters, contact your operator or see the [Configuration Guide](Configuration-Guide.md).

---

## WebSocket Connection Details

The dashboard connects to `/ws/live` on your bot's server. This provides:

- Sub-second updates to positions, P&L, and the thought feed
- No need to manually refresh the page
- Automatic reconnection with exponential backoff if the connection drops
- API key authentication (passed as a query parameter or header)

If you see persistent "CONNECTING..." status, check:
1. The bot container is running (`docker ps`)
2. Your network allows WebSocket connections (some corporate firewalls block them)
3. The dashboard port is open (default 8090 on host, 8080 in container)

---

## Multi-Exchange Aggregated View

When running multiple exchange engines (e.g., Kraken + Coinbase + Stocks), the dashboard aggregates everything:

- **Portfolio totals** are summed across all engines
- **Positions** show the exchange label: "BTC/USD (kraken:default)", "AAPL (stocks:default)"
- **Strategy stats** combine results from all exchanges
- **Thought feed** includes entries from all engines, prefixed with the engine label
- **Risk report** shows both per-engine and global exposure

---

## Keyboard Shortcuts

While these are not officially documented in the UI, the dashboard responds to:

- **Escape** -- closes any open modal
- **Enter** -- confirms dialogs (like the Close All confirmation)

---

## Common Dashboard Questions

**Q: The dashboard shows different numbers than my exchange.**
A: Nova|Pulse tracks its own P&L based on the trades it placed. Your exchange balance reflects all activity, including manual trades and deposits/withdrawals. Small differences are normal due to fee estimation in paper mode.

**Q: Can multiple people log in at the same time?**
A: Yes. Multiple browser sessions can connect simultaneously. They all see the same live data.

**Q: What happens if I close the browser tab?**
A: Nothing happens to the bot. Nova|Pulse continues running and trading regardless of whether the dashboard is open. The dashboard is purely for monitoring and control.

**Q: How do I see historical trades?**
A: The trades panel shows recent closed trades. For full history, use the `/api/v1/trades` API endpoint or export to CSV via the dashboard.

---

*Nova|Pulse v5.0.0 -- Full visibility, full control.*
