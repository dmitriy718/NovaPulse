# Getting Started with NovaPulse

**Last updated:** 2026-02-22

Welcome! This guide will walk you through everything you need to get NovaPulse up and running -- from creating your exchange account to watching your first market scan. No prior experience with trading bots is required.

---

## What Is NovaPulse?

NovaPulse is an AI-powered trading assistant that watches the cryptocurrency markets around the clock and makes trading decisions on your behalf. Think of it like having a tireless analyst who:

- Monitors multiple crypto pairs (like BTC/USD, ETH/USD) every minute
- Applies nine different trading strategies simultaneously
- Only enters a trade when multiple strategies agree (this is called **confluence**)
- Automatically sets protective stop losses and take profit levels on every trade
- Manages risk so that no single bad trade can seriously damage your account

You interact with NovaPulse through a **web dashboard** (your control center) and optionally through **Telegram**, **Discord**, or **Slack** (for mobile notifications and quick commands).

---

## What You Need Before Starting

1. **A NovaPulse subscription** -- You should have received a welcome email with your dashboard URL and login credentials. If you have not, contact [support](Contact-Support.md).

2. **A cryptocurrency exchange account** -- NovaPulse currently supports:
   - **Kraken** (recommended) -- [kraken.com](https://www.kraken.com)
   - **Coinbase** (Advanced Trade) -- [coinbase.com](https://www.coinbase.com)

3. **API keys from your exchange** -- These allow NovaPulse to view your balances and place trades on your behalf. See the step-by-step instructions below.

---

## Step 1: Create Your Exchange Account

If you do not already have one, sign up at your chosen exchange:

- **Kraken:** Go to [kraken.com](https://www.kraken.com), click "Create Account", and complete identity verification (this is required by law and usually takes a few hours to a day).
- **Coinbase:** Go to [coinbase.com](https://www.coinbase.com), click "Sign Up", and complete identity verification.

Fund your account with USD (or your local currency) using bank transfer, wire, or other supported method. NovaPulse recommends starting with at least **$500** for meaningful results, though there is no strict minimum.

---

## Step 2: Generate API Keys

API keys let NovaPulse communicate with your exchange account. They are like a limited-access pass: NovaPulse can view balances and place trades, but **cannot withdraw funds** (as long as you set up the keys correctly).

### Kraken API Key Setup

1. Log in to your Kraken account at [kraken.com](https://www.kraken.com).
2. Click on your **profile icon** (top right), then select **Security** > **API**.
3. Click **Add Key** (or **Generate New Key**).
4. Set a descriptive name, like "NovaPulse Bot".
5. Under **Permissions**, enable:
   - **Query Funds** (so NovaPulse can see your balances)
   - **Query Open Orders & Trades** (so NovaPulse can see order status)
   - **Query Closed Orders & Trades** (for trade history)
   - **Create & Modify Orders** (so NovaPulse can place trades)
   - **Cancel/Close Orders** (so NovaPulse can manage orders)
6. **Do NOT enable:**
   - Withdraw Funds
   - Query/Manage Staking
   - Access WebSockets API (NovaPulse handles this separately)
7. Click **Generate Key**.
8. **Copy both the API Key and the Private Key immediately.** The Private Key is only shown once.
9. Store both values securely (a password manager is ideal).

### Coinbase API Key Setup

1. Log in to your Coinbase account.
2. Go to **Settings** > **API** (or visit the Coinbase Developer Portal).
3. Click **New API Key**.
4. Under Permissions, enable:
   - **View** (account balances and history)
   - **Trade** (place and manage orders)
5. **Do NOT enable:**
   - Transfer/Send/Withdraw
6. Complete two-factor authentication to confirm.
7. **Copy the API Key and API Secret immediately.** The secret is only shown once.
8. Store both values securely.

> **Important:** Never share your API keys with anyone. NovaPulse stores them encrypted on our servers. See [Security and Privacy](Security-Privacy.md) for details.

---

## Step 3: Log In to Your Dashboard

1. Open your web browser (Chrome, Firefox, Safari, or Edge all work).
2. Navigate to the **dashboard URL** from your welcome email.
3. Enter your **username** and **password** (also from your welcome email).
4. You will see the NovaPulse dashboard -- your command center.

If you see a "401 Unauthorized" error, double-check your credentials. If problems persist, see [Troubleshooting](Troubleshooting.md) or contact [support](Contact-Support.md).

---

## Step 4: Start in Paper Trading Mode

**Paper trading** is simulated trading using real market data but no real money. This is the safest way to learn how NovaPulse works before committing real funds.

When your account is first set up, it is typically configured in **paper mode**. Here is what that means:

- NovaPulse watches the real markets and generates real signals
- Trades are **simulated** -- no actual orders are placed on your exchange
- Profits and losses are tracked as if they were real
- All dashboard features work identically to live mode

**We strongly recommend running in paper mode for at least 1-2 weeks** to:
- Get comfortable with the dashboard
- See how the bot handles different market conditions
- Understand the types of trades it makes
- Verify that the risk settings match your comfort level

---

## Step 5: Understand Your First Scan

Once NovaPulse is running, here is what happens behind the scenes:

1. **Warmup:** The bot downloads recent price history (about 500 candles of data per pair) to calculate its indicators. This takes a minute or two when the bot first starts.

2. **Scanning:** Every 60 seconds (by default), NovaPulse analyzes each configured trading pair:
   - It runs all nine strategies against the current price data
   - Each strategy votes: BUY, SELL, or NO SIGNAL
   - If enough strategies agree (this is **confluence**), a signal is generated

3. **Signal evaluation:** When a signal is generated:
   - The AI checks the **confidence score** (how strong the signal is)
   - It checks risk limits (daily loss, exposure, position count)
   - It calculates the right position size using the Kelly Criterion
   - If everything passes, the trade is placed (or simulated, in paper mode)

4. **Position management:** For open trades:
   - Stop losses and take profit levels are monitored every 2 seconds
   - Trailing stops lock in profits as price moves favorably
   - Breakeven protection kicks in after a certain profit threshold

You will see all of this activity on your dashboard -- the scanner view shows what the bot is looking at, the thought feed shows its reasoning, and the positions panel shows any active trades.

---

## Step 6: Switching from Paper to Live Mode

When you are ready to trade with real money:

1. Ensure your exchange API keys are configured (contact support if you have not provided them yet).
2. Review your risk settings (see [Configuration Guide](Configuration-Guide.md)):
   - **Risk per trade:** How much of your bankroll to risk on a single trade (default: 2%)
   - **Max daily loss:** Auto-pause threshold (default: 5%)
   - **Max position size:** Dollar cap per trade (default: $500)
3. Consider starting with **Canary Mode** -- this is an ultra-conservative live mode that:
   - Trades only 1-2 pairs
   - Uses very small position sizes (e.g., $100 max)
   - Requires higher confidence before entering trades
   - Lets you verify real-money execution with minimal risk
4. Contact support to switch your instance to live mode (or canary mode).
5. Monitor your dashboard closely for the first few days.

> **Reminder:** Trading cryptocurrency involves risk. Only trade with money you can afford to lose. See [Risk and Safety](Risk-Safety.md) for a full discussion of protections.

---

## Quick Reference Card

| Setting | Default | What It Means |
|---------|---------|--------------|
| Mode | Paper | Simulated trading (no real money) |
| Trading Pairs | BTC/USD, ETH/USD | Which markets the bot watches |
| Scan Interval | 60 seconds | How often the bot checks the market |
| Confluence Threshold | 3 strategies | How many strategies must agree |
| Min Confidence | 0.65 (65%) | Minimum signal strength to trade |
| Risk Per Trade | 2% | Max bankroll risked on one trade |
| Max Daily Loss | 5% | Auto-pause if daily losses hit this |
| Max Position Size | $500 | Dollar cap per trade |
| Max Concurrent Positions | 5 | No more than 5 trades open at once |
| Max Total Exposure | 50% | Never more than half the bankroll at risk |

---

## Next Steps

- **Explore the dashboard:** See [Dashboard Walkthrough](Nova-Dashboard-Walkthrough.md)
- **Understand the metrics:** See [Understanding Metrics](Understanding-Metrics.md)
- **Set up mobile alerts:** See [Notifications](Notifications.md)
- **Learn about the strategies:** See [Trading Strategies](Trading-Strategies.md)
- **Understand your protections:** See [Risk and Safety](Risk-Safety.md)

---

*Questions? See our [FAQ](FAQ.md) or [contact support](Contact-Support.md) -- we are here to help.*
