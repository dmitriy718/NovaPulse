# Nova|Pulse on Horizon -- Your Web Dashboard

**Last updated:** 2026-03-01

---

## What Is the Horizon Dashboard?

The Horizon dashboard at **horizonsvc.com** is your central hub for monitoring your Nova|Pulse trading bot from any device. It connects securely to your bot and displays live performance data, open positions, trade history, strategy breakdowns, AI reasoning, and more -- all from your web browser.

Think of it this way: your Nova|Pulse bot does the trading. The Horizon dashboard lets you **watch, understand, and track** what the bot is doing -- from anywhere, on any device.

---

## How It Differs from the Bot Dashboard

Your bot has two dashboards:

| Feature | Bot Dashboard (built-in) | Horizon Dashboard (horizonsvc.com) |
|---------|-------------------------|-----------------------------------|
| **Access** | Direct URL to your bot server | horizonsvc.com web app |
| **Design** | HUD-style command center | Mobile-friendly, modern design |
| **Controls** | Full control (pause, resume, close all) | Monitoring focused (control via bot or Telegram) |
| **Gamification** | Not available | Achievements, streaks, leaderboards |
| **Multi-bot** | Single bot view | Manage multiple bots from one account |
| **Auth** | Username/password login | horizonsvc.com account + bot API key |

Both show the same underlying data. The Horizon dashboard pulls data from your bot via its API.

---

## Getting Connected

### If You Have a Horizon-Hosted Bot (Managed)

When you subscribed, we sent you a welcome email containing:

1. **Bot URL** -- looks like `https://nova.horizonsvc.com`
2. **API Key** -- a 64-character hex string

To connect:

1. Go to [horizonsvc.com](https://horizonsvc.com) and log in (or create an account)
2. Navigate to your **Dashboard**
3. If no bot is connected, you will see a setup wizard
4. Select **"Hosted by Horizon"**
5. Enter the **Bot URL** and **API Key** from your welcome email
6. Click **"Test & Connect"**
7. If the connection succeeds, your dashboard immediately shows live data

> **Cannot find your email?** Check your spam folder, or email support@horizonsvc.com and we will resend your credentials.

### If You Run Your Own Bot (Self-Hosted)

1. Go to [horizonsvc.com](https://horizonsvc.com) and log in
2. Select **"Self-Hosted"** in the setup wizard
3. Enter your bot's **public URL** (must be HTTPS or accessible from the internet)
4. Enter your bot's **read API key** (from your `.secrets/env` file or dashboard config)
5. Click **"Test & Connect"**

**Requirements for self-hosted:**
- Your bot must be reachable from the internet (not just localhost)
- HTTPS is strongly recommended (use Caddy or Nginx for TLS)
- The read API key must be configured in your bot

---

## Dashboard Tabs

### Overview

The main view showing:
- **Live P&L** -- total, unrealized, realized
- **Win rate and trade count**
- **Equity chart** -- visual representation of your portfolio value over time
- **Status** -- bot operational state, mode (paper/live), uptime

### Positions

A live table of all open positions across all exchanges:
- Pair, direction, entry price, current price, unrealized P&L
- Size, confidence, confluence count
- Visual SL/TP distance indicators

### Trades

Complete trade history with filtering:
- Filter by date range, pair, strategy, direction
- Sort by any column
- Export to CSV for your records
- Each trade shows entry/exit prices, P&L, duration, strategy, and exit reason

### Strategies

Performance breakdown per strategy:
- Win rate, trade count, total P&L for each of the twelve strategies
- Which strategies are enabled vs. disabled
- Current weights and regime adjustments

### AI Reasoning

The thought feed -- a chronological log of the bot's decisions:
- Why signals were generated or skipped
- Confluence scores and confidence levels
- Risk rejections and their reasons
- System events (starts, pauses, restarts)

### Settings

Profile and connection management:
- Update your bot connection details
- View API key status
- Notification preferences

---

## Gamification

The Horizon dashboard includes gamification features to make monitoring more engaging:

### Achievements

Unlock achievements based on your bot's performance:
- **First Trade** -- opened your first position
- **Win Streak** -- 5 consecutive winning trades
- **Profit Milestone** -- reached $100, $500, $1,000 cumulative P&L
- **Strategy Master** -- all 12 strategies have contributed to winning trades
- **Night Owl** -- profitable trade during overnight hours
- And many more

### Streaks

Track consecutive days of:
- Positive P&L
- Active trading
- Dashboard check-ins

### Leaderboard

See how your bot compares to other Nova|Pulse users (anonymized):
- Ranked by Sharpe ratio, win rate, or total return
- Opt-in only -- you choose whether to participate
- No real usernames or financial details are shared

---

## Mobile Experience

The Horizon dashboard is specifically designed for mobile:
- Responsive layout that adapts to any screen size
- Touch-friendly controls
- Quick-glance summary cards
- Pull-to-refresh for latest data

Open [horizonsvc.com](https://horizonsvc.com) in your phone's browser and bookmark it for quick access. No app installation required.

---

## Data Refresh

The Horizon dashboard polls your bot's API at regular intervals (typically every few seconds) to keep data fresh. This means:

- There may be a 1-3 second delay compared to the bot's own dashboard (which uses WebSocket for instant updates)
- If your bot goes offline, the Horizon dashboard will show the last known data with a "stale" indicator
- Data freshness is indicated by a timestamp ("Last updated: 2s ago")

---

## Security

### Connection Security

- Your bot URL is stored encrypted in the Horizon database
- API keys are transmitted over HTTPS only
- Bot URLs are validated against SSRF attacks (the proxy will not connect to internal network addresses)

### Authentication

- Your Horizon account is separate from your bot login
- Horizon uses the bot's read API key (cannot trigger control actions)
- For control actions (pause, resume), use the bot's own dashboard or Telegram

### Data Privacy

- Horizon displays data from your bot but does not persistently store your trading data
- Your exchange credentials are never transmitted to or through Horizon
- See [Security and Privacy](Security-Privacy.md) for full details

---

## Troubleshooting

### "Connection Failed" When Adding Bot

1. **Check the URL** -- must include `https://` and be accessible from the internet
2. **Check the API key** -- copy the full 64-character string
3. **Check that the bot is running** -- the Horizon server needs to reach your bot
4. **Check CORS** -- your bot must allow requests from horizonsvc.com origins

### Dashboard Shows Stale Data

1. Check that your bot is still running
2. Check your bot's internet connectivity
3. The Horizon dashboard will show a "last updated" timestamp -- if it is growing, data is stale

### Cannot See Positions or Trades

1. Verify you are using the correct API key type (read or admin)
2. Check that `require_api_key_for_reads: true` is set and the key matches

---

## Common Questions

**Q: Do I need the Horizon dashboard?**
A: No. The bot's built-in dashboard provides full functionality. The Horizon dashboard is an enhanced, mobile-friendly alternative.

**Q: Can I use both dashboards?**
A: Yes. Both can be open simultaneously. They show the same data.

**Q: Does the Horizon dashboard cost extra?**
A: No. Access to horizonsvc.com is included in all Nova|Pulse plans.

**Q: Can I connect multiple bots?**
A: Yes (Premium plan). You can manage multiple bot connections from a single Horizon account.

---

*Nova|Pulse v5.0.0 -- Monitor your bot from anywhere, on any device.*
