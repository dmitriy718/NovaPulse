# Getting Started with Nova|Pulse by Horizon Services

**Last updated:** 2026-03-02

Welcome! This guide walks you through everything you need to get started with Nova|Pulse -- from creating your Horizon account and choosing a plan, to connecting your exchange and watching your first market scan. No prior experience with trading bots is required.

---

## What Is Nova|Pulse?

Nova|Pulse is an AI-powered trading platform built and operated by **Horizon Services**. It consists of two components:

1. **The NovaPulse Trading Bot** -- A Python-based engine that runs 12 AI strategies in parallel across crypto and stock markets, uses a confluence engine to filter signals, and executes trades on your behalf with institutional-grade risk management.

2. **The Horizon Dashboard** -- A web application at [horizonsvc.com](https://horizonsvc.com) where you manage your account, monitor your bot's performance in real time, track achievements, and access support.

Think of it like having a tireless analyst who:

- Monitors multiple crypto pairs (BTC/USD, ETH/USD, SOL/USD, and more) and up to 96 stocks every few seconds
- Applies twelve different trading strategies simultaneously to each market
- Only enters a trade when multiple strategies agree -- this is called **confluence**
- Automatically sets protective stop losses and take profit levels on every trade
- Manages risk so that no single bad trade can seriously damage your account
- Learns from its own performance and adjusts over time

You interact with Nova|Pulse through the **Horizon web dashboard**, the **bot's built-in dashboard**, and optionally through **Telegram**, **Discord**, or **Slack** for mobile notifications and commands.

---

## Step 1: Create Your Horizon Account

### Sign Up

1. Navigate to [horizonsvc.com/signup](https://horizonsvc.com/signup) or click **Get Started** from the pricing page.
2. You can create an account using:
   - **Email and password**: Enter your email address and choose a strong password
   - **Google SSO**: Click "Sign in with Google" to use your Google account
3. Firebase Authentication handles all account creation securely.

### Complete the Onboarding Wizard

After signing up, you are redirected to the onboarding wizard at `/onboarding`. This collects information to tailor your experience:

- **First Name** and **Last Name** (required)
- **Age** (must be 18 or older)
- **ZIP Code** (required, minimum 5 characters)
- **Street Address**, **City**, **State** (optional)
- **Email address** (pre-filled from your signup)
- **Notification preferences** (optional -- you can set these later in Settings)

### Verify Your Email

After registration, you receive a verification email from `support@horizonsvc.com`. You must verify your email before accessing the dashboard.

- If you did not receive the email, check your spam folder
- You can request a new verification email from the dashboard verification modal
- The dashboard polls your verification status every 3 seconds automatically
- Once verified, the modal dismisses and you have full dashboard access

**Important**: Email verification is required to:
- Access the trading dashboard
- Subscribe to a paid plan (Stripe checkout)
- Use the Pro scanner feature
- Submit authenticated support tickets

---

## Step 2: Choose Your Plan

Visit [horizonsvc.com/pricing](https://horizonsvc.com/pricing) to choose your subscription tier and hosting option.

### Subscription Tiers

| Feature | Starter | Pro | Elite |
|---|---|---|---|
| AI Trading Strategies | 12 | 12 | 12 + Custom |
| Multi-Exchange Support | Kraken, Coinbase, Alpaca | Same | Same |
| Real-Time Dashboard | Yes | Yes | Yes |
| Custom Strategy Weights | No | Yes | Yes |
| Custom Confluence Thresholds | No | Yes | Yes |
| P&L Attribution Reports | No | Yes | Yes |
| Telegram/Discord Alerts | No | Yes | Yes |
| Bot Instances | 1 | 1 | Up to 3 |
| Email Support | < 24hr | < 4hr | < 1hr |

### Hosting Options

**Self-Hosted** ($49.99 - $199.99/mo):
- You run the NovaPulse Docker container on your own server
- Your API keys never leave your infrastructure
- Requires: 2+ CPU cores, 4GB+ RAM, Docker, Ubuntu 22+ recommended
- You handle updates and monitoring

**Horizon-Hosted** ($99.99 - $249.99/mo):
- Dedicated instance on Horizon infrastructure
- 24/7 monitoring, automatic restarts, automatic software updates
- Zero server management -- connect your exchange API keys and go
- Live in under 5 minutes

### Subscribe

1. Click the plan you want
2. You are redirected to Stripe Checkout
3. Complete payment with your credit card
4. After successful payment, you are redirected back with a success message
5. Your subscription status is updated via Stripe webhooks

See the [Billing and Plans](Billing-Plans.md) guide for full pricing details, hosting comparison, and subscription management.

---

## Step 3: Create Your Exchange Account and API Keys

### Exchange Accounts

If you do not already have one, sign up at your chosen exchange:

- **Kraken** (recommended for crypto): Go to [kraken.com](https://www.kraken.com), click "Create Account", and complete identity verification (usually takes a few hours to a day).
- **Coinbase**: Go to [coinbase.com](https://www.coinbase.com), click "Sign Up", and complete identity verification.
- **Alpaca** (for stocks): Go to [alpaca.markets](https://alpaca.markets) and create either a paper or live account.

Fund your exchange account with USD (or your local currency). Nova|Pulse recommends starting with at least **$500** for meaningful results, though there is no strict minimum.

### Generate API Keys

API keys let Nova|Pulse communicate with your exchange account. They are like a limited-access pass: Nova|Pulse can view balances and place trades, but **cannot withdraw funds** (as long as you set up the keys correctly).

**Kraken:**
1. Log in at [kraken.com](https://www.kraken.com) > **Security** > **API** > **Add Key**
2. Enable: Query Funds, Query Open/Closed Orders & Trades, Create & Modify Orders
3. **Do NOT enable "Withdraw Funds"**
4. Copy both the API Key and Private Key immediately (shown only once)

**Coinbase:**
1. Log in at [coinbase.com](https://www.coinbase.com) > **Settings** > **API** > **New API Key**
2. Enable: View, Trade
3. **Do NOT enable Transfers or Send**
4. Copy your API Key and API Secret

**Alpaca (for stocks):**
1. Log in at [alpaca.markets](https://alpaca.markets) > **View API Keys** > **Generate New Key**
2. Copy your API Key ID and Secret Key

**Polygon (for stock market data):**
1. Sign up at [polygon.io](https://polygon.io) (free tier is sufficient)
2. Copy your API key from the dashboard

---

## Step 4: Connect Your Bot

Once subscribed, connect your NovaPulse trading bot to the Horizon dashboard.

### Navigate to Settings

Go to [horizonsvc.com/settings](https://horizonsvc.com/settings) and click the **Bot Connection** tab.

### Enter Connection Details

- **Bot URL**: The full URL of your NovaPulse dashboard API (e.g., `https://nova.horizonsvc.com:8080`)
- **API Key**: The read-only API key from your NovaPulse dashboard (found in your bot's `.secrets/env` file or welcome email)
- **Hosting Type**: Select Managed or Self-Hosted
- **Label**: A friendly name for this bot connection (default: "My Bot")

### Test and Connect

Click **Connect Bot**. The system will:
1. Validate the URL format
2. Check SSRF protection (the URL cannot point to internal/private network addresses)
3. Attempt to reach the bot's `/api/v1/status` endpoint
4. If successful, save the connection and display a success message

### For Self-Hosted Users: Provide API Keys to the Bot

If you run Nova|Pulse on your own server, create a `.secrets/env` file in your Nova|Pulse directory with your exchange keys:

```
KRAKEN_API_KEY=your_kraken_api_key_here
KRAKEN_API_SECRET=your_kraken_private_key_here
COINBASE_API_KEY=your_coinbase_api_key
COINBASE_API_SECRET=your_coinbase_api_secret
POLYGON_API_KEY=your_polygon_key
ALPACA_API_KEY=your_alpaca_key
ALPACA_API_SECRET=your_alpaca_secret
```

This file is volume-mounted into the Docker container and read at startup. It is never committed to version control.

### For Horizon-Hosted Users

Your operator configures the exchange keys for you during setup. You can provide them securely through the setup wizard or by contacting support.

---

## Step 5: Start in Paper Mode (Recommended)

We strongly recommend starting in **paper trading mode** first. In paper mode, Nova|Pulse simulates trades using real market data but does not place actual orders on your exchange. This lets you:

- Verify that everything is connected and working
- Get comfortable with the dashboard and controls
- Observe how the strategies behave in current market conditions
- Build confidence before risking real capital

Paper mode is the default. Your dashboard header will show **MODE: PAPER** to confirm.

To switch between paper and live modes later, see the [Configuration Guide](Configuration-Guide.md).

---

## Step 6: Explore the Dashboard

Once Nova|Pulse is running, you can monitor it in two ways:

### The Horizon Dashboard (horizonsvc.com)

Visit [horizonsvc.com/dashboard](https://horizonsvc.com/dashboard) to see:
- **Overview Tab**: Bot status, headline P&L, equity chart, top strategies, gamification
- **Positions Tab**: All currently open positions with real-time P&L
- **Trades Tab**: Complete trade history with CSV export
- **Strategies Tab**: Per-strategy performance breakdown
- **AI Tab**: Live thought log showing the bot's reasoning for every decision

The dashboard updates every 5 seconds with live data. See the [Horizon Dashboard guide](Horizon-Dashboard.md) for a complete walkthrough.

### The Bot Dashboard (Built-In)

Your bot also runs its own web dashboard at the URL provided in your welcome email (typically `https://nova.horizonsvc.com` or `http://your-server-ip:8090`). This is the full admin panel with a HUD-style command center. See the [Bot Dashboard Walkthrough](Nova-Dashboard-Walkthrough.md) for details.

---

## Step 7: Configure Notifications

### Email Notifications (Horizon Dashboard)

In Settings > Notifications on horizonsvc.com, configure which emails you want to receive:
- **Account Security**: Password changes, failed logins, lockouts (always enabled)
- **Trading Alerts**: Daily loss limits, max exposure, consecutive losses, anomaly detection
- **Performance Reports**: Daily summaries, weekly digests, monthly reports
- **Marketing**: Newsletter, feature announcements

See the [Horizon Email Notifications](Horizon-Email-Notifications.md) guide for full details.

### Telegram, Discord, and Slack (Bot Notifications)

Set up direct bot notifications for real-time trade alerts and commands from your phone. See the [Notifications](Notifications.md) guide for step-by-step instructions.

---

## Step 8: Your First Trades

After Nova|Pulse has been running for a few minutes in paper mode, you will start to see activity:

1. **Warmup phase** (first 15 minutes): Nova|Pulse loads historical candle data to calculate indicators. You will see "Warming up" messages in the thought feed.

2. **Scanning phase**: Once warmed up, the bot scans all pairs every 15 seconds (configurable). The thought feed shows each scan.

3. **Signals**: When strategies agree on a direction, a confluence signal appears. If it passes all filters (confidence threshold, risk checks, spread gate), a trade is placed.

4. **Position management**: Open positions are monitored every 2 seconds. Trailing stops adjust, the smart exit system may partially close profitable positions, and stops are moved to breakeven when appropriate.

---

## What Happens During Different Market Hours?

Nova|Pulse has a **priority scheduler** that coordinates between crypto and stock trading:

- **During US market hours (9:30 AM -- 4:00 PM Eastern, weekdays):** Stock trading is active, crypto trading is paused.
- **Outside market hours:** Crypto trading is active, stock trading is paused.

This happens automatically. The thought feed will log priority schedule transitions.

---

## Next Steps

Once you are comfortable with paper mode and see consistent behavior:

1. **Review your settings** -- See the [Configuration Guide](Configuration-Guide.md) to understand what you can customize
2. **Understand the strategies** -- Read [Trading Strategies](Trading-Strategies.md) to learn how decisions are made
3. **Set up all notifications** -- Configure both email and Telegram/Discord/Slack alerts
4. **Explore gamification** -- Check out [achievements, levels, and ranks](Horizon-Gamification.md) on the Horizon dashboard
5. **Go live** -- When ready, your operator can switch the bot to live mode. Start with conservative settings and a modest bankroll

---

## Quick Troubleshooting

| Symptom | Likely Cause | Solution |
|---------|-------------|----------|
| Dashboard shows "Bot Unreachable" | Bot not running or URL incorrect | Check bot container status; verify URL in Settings |
| No trades after 30+ minutes | Market conditions do not meet confluence threshold | Normal -- the bot is selective by design. Check the thought feed |
| "Paused" status | Auto-pause triggered (loss streak, drawdown, stale data) | Check the thought feed for the pause reason |
| API key error | Keys not configured or expired | Re-check your API keys |
| Email verification modal stuck | Verification link not clicked or expired | Click "Resend Verification Email" on the dashboard |

For more help, see the full [Troubleshooting guide](Troubleshooting.md) or [Contact Support](Contact-Support.md).

---

## Need Help?

- **Knowledge Base**: You are here -- browse the full documentation index at [README](README.md)
- **Academy**: Learn about trading strategies at [horizonsvc.com/academy](https://horizonsvc.com/academy)
- **Blog**: Read latest updates at [horizonsvc.com/blog](https://horizonsvc.com/blog)
- **Support**: Submit a ticket at [horizonsvc.com/support](https://horizonsvc.com/support) or email support@horizonsvc.com

---

*Nova|Pulse v5.0.0 by Horizon Services -- Your first scan is just minutes away.*
