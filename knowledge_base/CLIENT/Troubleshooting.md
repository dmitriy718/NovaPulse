# Troubleshooting

**Last updated:** 2026-02-22

This guide covers the most common issues you might encounter with NovaPulse and how to resolve them. If your issue is not covered here, please [contact support](Contact-Support.md).

---

## Bot Is Not Placing Trades

This is the most common question. There are several reasons why the bot might not be trading:

### 1. Check the Mode

**Symptom:** No trades at all, even after days of running.

**Check:** Look at the status area on your dashboard. Is the mode set to "paper" or "live"?

**If paper mode:** The bot IS trading -- but trades are simulated. Check the trade history panel to see if simulated trades are being recorded. If trades appear in the history, everything is working correctly.

### 2. Check the Status

**Symptom:** Status shows PAUSED, STOPPED, or STALE FEED.

**Fix:**
- **PAUSED:** Someone (you, a team member, or an auto-pause circuit breaker) paused trading. Check the AI Thought Feed for the reason. If it was manual, use Resume. If it was automatic, check the Risk Shield panel for which circuit breaker triggered.
- **STOPPED:** The bot was killed. Use Resume to restart, or contact support.
- **STALE FEED:** Market data is stale. Wait for automatic reconnection (usually resolves within minutes). If it persists for more than 15 minutes, contact support.

### 3. Check Confidence and Confluence

**Symptom:** Status shows RUNNING but no trades are being placed.

**Check:** Look at the Scanner view. Are any signals appearing? What are the confidence scores and confluence counts?

**Common reasons:**
- **Confidence too low:** All signals are below the 0.65 threshold. The market may be choppy or unclear. This is the bot being appropriately cautious.
- **Confluence too low:** Strategies are not agreeing. Only 1-2 strategies see a signal, which is below the 3-strategy threshold. Again, this is protective behavior.
- **Solution:** Wait for clearer market conditions. Do NOT lower the thresholds to force trades -- that defeats the purpose of the safeguards.

### 4. Check Circuit Breakers

**Symptom:** The Risk Shield panel shows an active circuit breaker.

**Common triggers:**
- **Daily loss limit:** You have hit the daily loss cap. Trading will resume the next day (or when you manually resume after review).
- **Consecutive losses:** Four or more losses in a row. Review recent trades to understand why, then resume.
- **Drawdown limit:** Account drawdown exceeds the threshold. Review and resume when ready.
- **Trade cooldown:** A recent loss triggered a 30-minute cooldown. Wait for it to expire.

### 5. Check Exchange Connection

**Symptom:** Integrations panel shows exchange as disconnected.

**Fix:** See "Exchange Connection Issues" below.

### 6. Check Quiet Hours

**Symptom:** Bot runs normally at some times but not during certain hours.

**Check:** Are quiet hours configured? During quiet hours, no new trades are opened. Existing positions are still managed.

---

## Dashboard Will Not Load

### Symptom: Blank page or loading spinner that never finishes

**Try these steps in order:**

1. **Refresh the page** (F5 or Ctrl+R)
2. **Try a different browser** (Chrome, Firefox, Safari, Edge)
3. **Clear your browser cache:**
   - Chrome: Settings > Privacy > Clear browsing data > Cached images and files
   - Firefox: Settings > Privacy > Clear Data > Cached Web Content
   - Safari: Develop > Empty Caches
4. **Try incognito/private mode** to rule out browser extensions
5. **Check your internet connection** -- can you reach other websites?
6. If none of the above work, contact support with your browser name and version

### Symptom: 401 Unauthorized

Your login credentials are incorrect or expired.

**Fix:**
1. Double-check your username and password (case-sensitive)
2. Try an incognito/private window (in case old credentials are cached)
3. Clear saved site credentials in your browser settings
4. If you have forgotten your password, contact support for a credential reset

### Symptom: 502 Bad Gateway or 503 Service Unavailable

The server may be restarting or temporarily unavailable.

**Fix:**
1. Wait 30-60 seconds and refresh
2. If it persists for more than 5 minutes, contact support

---

## Telegram Bot Not Responding

### Bot does not reply to any commands

**Check these in order:**

1. **Is Telegram enabled?** Verify with support that Telegram is configured for your instance.
2. **Is polling enabled?** The bot needs polling enabled to receive your messages. Confirm with support.
3. **Is your Chat ID in the allowlist?** Send `/whoami` to get your chat ID and confirm it matches what is configured. If you get no response at all, your chat ID may not be on the allowlist.
4. **Is the bot token correct?** If the token was rotated or is invalid, the bot cannot connect to Telegram. Contact support to verify.
5. **Wait a moment and try again.** The bot polls for messages periodically -- there may be a short delay.

### Bot sends notifications but does not respond to commands

Polling may be disabled (the bot is in send-only mode). This happens when multiple instances share a bot token -- only one can poll at a time. Contact support to enable polling for your instance.

---

## Trade Closed at a Loss

**This is normal.** Even the best trading systems have losing trades. Here is what to understand:

### Why losses happen

- The market moved against the trade faster than expected
- The stop loss was hit -- this is the system working as designed (limiting your loss)
- A sudden news event or market shift caused a rapid move

### What to check

1. **Was the loss within the expected stop-loss range?** Check the trade details. If entry was $64,000 and stop was $62,800, a close at $62,800 is a normal stop-loss exit.
2. **Look at the bigger picture.** One losing trade does not define performance. Check your win rate, profit factor, and total P&L over at least 20-50 trades.
3. **Check for patterns.** If many recent trades are losing, look at:
   - Market conditions (is the market very choppy?)
   - Whether circuit breakers have activated (the bot may have auto-paused itself already)
   - Strategy performance (is one strategy dragging things down? The auto-tuner will handle this.)

### When to be concerned

- Win rate drops below 35% over 30+ trades
- Max drawdown exceeds 10%
- Daily loss limit is being hit frequently
- Multiple circuit breakers are triggering regularly

If you see these patterns, contact support for a review of your configuration.

---

## "Stale Data" Warning

**What it means:** NovaPulse has not received fresh market data from your exchange for several consecutive health checks.

**Why it matters:** Trading on old data is dangerous -- the real price may have moved significantly. NovaPulse automatically pauses trading when data is stale.

**Common causes:**
- Temporary exchange maintenance or outage
- Internet connectivity issues between NovaPulse's server and the exchange
- Exchange API rate limiting

**What to do:**
1. **Wait.** Most stale data events resolve automatically within 1-5 minutes as the connection re-establishes.
2. If it persists for more than 15 minutes, check the exchange's status page:
   - Kraken: [status.kraken.com](https://status.kraken.com)
   - Coinbase: [status.coinbase.com](https://status.coinbase.com)
3. If the exchange is fine, contact support.

---

## "Auto-Paused" Notification

**What it means:** The bot paused itself because a circuit breaker was triggered.

**How to diagnose:**

| Check | What to Look For |
|-------|-----------------|
| **Risk Shield panel** | Shows which circuit breaker is active |
| **AI Thought Feed** | Shows the exact message and timestamp |
| **Notification message** | Should state the reason (daily loss, consecutive losses, drawdown, stale data, etc.) |

**What to do:**

1. **Read the reason.** The notification and dashboard will tell you why.
2. **Review recent trades.** Understand what happened -- was it a bad market day, or is there a deeper issue?
3. **Decide whether to resume.** If it was just a normal bad day, you can resume. If something looks wrong, contact support.
4. **To resume:** Use the Resume button on the dashboard, or send `/resume` via Telegram.

---

## Unexpected Fees

**Where fees come from:**

| Fee Type | Typical Rate | When It Applies |
|----------|-------------|----------------|
| **Maker fee** | ~0.16% | When your order adds liquidity (limit orders) |
| **Taker fee** | ~0.26% | When your order takes liquidity (market orders, stop triggers) |

**Both entry and exit incur fees.** A round-trip trade (buy + sell) costs approximately 0.32-0.52% in fees, depending on order type.

**Fee impact on P&L:** NovaPulse deducts estimated fees from your P&L calculations, so the numbers you see on the dashboard are net of fees. There should be no surprises.

**Why a trade might show a small loss even though the price barely moved:** If the entry-to-exit price move was smaller than the round-trip fees, the trade results in a net loss. NovaPulse's risk/reward calculations account for fees, but in rare cases a trade may close near breakeven and end up slightly negative.

---

## API Key Errors

### "Invalid API key" or "Permission denied"

**Common causes:**
- The API key was revoked or expired on the exchange
- Permissions were changed on the exchange side
- A typo in the key or secret during setup

**How to fix:**
1. Log in to your exchange and check your API keys
2. Verify that the correct permissions are enabled (see [Getting Started](Getting-Started.md))
3. Generate new API keys if needed
4. Contact support to update the keys in NovaPulse

### "Rate limit exceeded"

**What it means:** Too many API requests were sent to the exchange in a short period.

**How NovaPulse handles it:** The bot has built-in rate limiting and will automatically back off and retry. This usually resolves on its own within a few seconds.

**If it persists:** Contact support -- the rate limits may need adjustment.

---

## General Health Check Steps

When something does not seem right, run through this checklist:

1. **Check the status indicator** -- Is it RUNNING, PAUSED, STOPPED, STALE FEED, or OFFLINE?
2. **Check the Risk Shield** -- Are any circuit breakers active?
3. **Check the AI Thought Feed** -- Look for error or warning messages
4. **Check the Integrations panel** -- Is the exchange connected?
5. **Check the Scanner** -- Are signals being generated? What are the confidence/confluence levels?
6. **Check recent trade history** -- Has anything unusual happened?
7. **Send `/health` on Telegram** (if configured) for a quick health report
8. **Take a screenshot** of the dashboard and contact support with your observations

---

## When to Contact Support

Contact support if:

- A problem persists for more than 30 minutes despite troubleshooting
- You see error messages you do not understand
- The bot's behavior seems wrong (unexpected trades, wrong position sizes, etc.)
- You suspect a security issue (contact immediately and use Kill if needed)
- You want help interpreting your performance data

See [Contact Support](Contact-Support.md) for how to reach us and what to include in your message.

---

*For dashboard features, see [Dashboard Walkthrough](Nova-Dashboard-Walkthrough.md).*
*For control options, see [Controls](Controls-Pause-Resume-Kill.md).*
