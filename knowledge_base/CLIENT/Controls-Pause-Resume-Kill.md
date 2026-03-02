# Controls: Pause, Resume, Close All, and Emergency Kill

**Last updated:** 2026-03-01

Nova|Pulse gives you full control over the bot at all times. Whether you want to temporarily pause trading, close all positions, or hit the emergency stop, you can do it instantly from the dashboard, Telegram, Discord, or Slack.

---

## Overview of Controls

| Action | What Happens | How to Trigger |
|--------|-------------|---------------|
| **Pause** | Stops opening new trades. Existing positions continue to be managed (stops, trailing, exits). | Dashboard button, Telegram `/pause`, Discord `!pause`, Slack `/pause` |
| **Resume** | Starts opening new trades again. | Dashboard button, Telegram `/resume`, Discord `!resume`, Slack `/resume` |
| **Close All** | Immediately closes every open position at market price. | Dashboard button (with confirmation), Telegram `/close_all`, Discord `!close_all` |
| **Kill** | Stops the bot process entirely. Positions remain open on the exchange. | Telegram `/kill`, Docker stop, SIGTERM |

---

## Pause Trading

Pausing is the most common control action. When paused:

- **No new trades** will be opened
- **Existing positions continue to be managed** -- stop losses are still enforced, trailing stops still tighten, the smart exit system still runs, and take profit levels still trigger
- **Market data continues flowing** -- the bot keeps watching prices and updating indicators
- **The dashboard stays fully operational** -- you can still see positions, P&L, and the thought feed

### When to Pause

- Before a major news event you are unsure about
- When you want to observe the bot's signals without acting on them
- If you notice unusual market conditions
- Before making configuration changes
- Any time you feel the bot should sit on its hands for a while

### How to Pause

**From the Dashboard:**
1. Click the **PAUSE** button in the header bar (top right)
2. The button text changes to **RESUME** and the status indicator turns orange

**From Telegram:**
Send `/pause` to your bot. You will receive confirmation:
```
Trading PAUSED. Existing positions still managed.
Send /resume to start trading again.
```

**From Discord:**
Send `!pause` in the allowed channel.

**From Slack:**
Send `/pause` in the allowed channel.

### How to Resume

Reverse the pause from any channel:
- Dashboard: click the **RESUME** button
- Telegram: `/resume`
- Discord: `!resume`
- Slack: `/resume`

The bot will resume scanning and opening new trades on the next scan cycle (within seconds).

---

## Close All Positions

This immediately sends market sell orders for every open position.

### What Happens

1. Every open position (crypto and stocks) is closed at the current market price
2. Market orders are used for speed -- no limit chasing
3. Each closure is logged in the thought feed with the reason "manual_close_all"
4. P&L for each position is recorded
5. The bot continues running and can open new trades (unless also paused)

### When to Use Close All

- Unexpected extreme market event (flash crash, black swan)
- You need to free up capital immediately
- The bot has accumulated positions you are uncomfortable with
- Before switching from live to paper mode

### How to Close All

**From the Dashboard:**
1. Click the **CLOSE ALL** button (red, top right)
2. A confirmation dialog appears: "Are you sure you want to close all positions?"
3. Click "Confirm" to proceed or "Cancel" to abort

**From Telegram:**
Send `/close_all` to your bot. Confirmation is sent:
```
Closing all 3 positions...
Closed BTC/USD LONG: P&L $42.15
Closed ETH/USD SHORT: P&L -$8.30
Closed SOL/USD LONG: P&L $12.70
All positions closed. Net P&L: $46.55
```

### Important Notes

- Close All uses market orders, so there may be small slippage in fast markets
- After Close All, the bot will resume scanning and may open new positions unless you also pause
- If you want to stop trading entirely, use Close All followed by Pause

---

## Emergency Kill

The kill command stops the bot process entirely. This is the nuclear option.

### What Happens

1. The bot stops its event loop and all background tasks
2. **Positions remain open on the exchange** -- Nova|Pulse does not close them
3. Exchange-native stop loss orders (if placed) remain active
4. The dashboard becomes unreachable
5. The bot must be restarted manually

### When to Use Kill

- The bot is behaving unexpectedly and you want it fully stopped
- You need to perform maintenance on the server
- You are migrating to a new deployment

### How to Kill

**From Telegram:**
Send `/kill` to your bot. This triggers a graceful shutdown.

**From the Server:**
```bash
docker stop novatrader-trading-bot-1
```
Or send SIGTERM / SIGINT to the process.

### After a Kill

To restart:
```bash
docker start novatrader-trading-bot-1
# or
docker compose up -d
```

When the bot restarts, it reconciles its database with exchange positions (checking which positions are still open) and resumes management.

---

## Automatic Pauses

Nova|Pulse can automatically pause trading in several situations. These are safety features designed to protect your capital.

### Consecutive Loss Pause

If the bot suffers a streak of losing trades (default: 5 in a row), trading pauses automatically.

**What you see:** The thought feed shows "Auto-pause: consecutive_losses" and the status shows "PAUSED".

**What to do:** Review the recent trades to understand why. When ready, resume via any control channel. The consecutive loss counter resets when you resume.

### Daily Loss Limit Pause

If daily losses reach the configured maximum (default: 5% of bankroll), trading pauses for the rest of the UTC day.

**What you see:** "Auto-pause: daily_loss_limit_reached" in the thought feed.

**What to do:** Trading will automatically resume at the next UTC midnight, or you can manually resume if you have increased the limit.

### Drawdown Pause

If the bot's peak-to-trough drawdown exceeds the threshold (default: 8%), trading pauses.

**What you see:** "Auto-pause: drawdown_limit" in the thought feed.

**What to do:** Review your risk settings and recent trades. Resume when comfortable.

### Stale Data Pause

If market data stops updating for a prolonged period (e.g., WebSocket disconnection lasting >5 minutes), trading pauses.

**What you see:** "Auto-pause: stale_data" or "Auto-pause: ws_disconnect" in the thought feed.

**What to do:** This usually resolves on its own when the connection recovers. If it persists, check your network and exchange status.

### Priority Schedule Pause

The priority scheduler automatically pauses crypto engines during US stock market hours (9:30 AM -- 4:00 PM Eastern) and pauses stock engines outside those hours. This is normal behavior, not an error.

### Anomaly Detection Pause (v5.0)

If the anomaly detector is enabled and detects abnormal spread, volume, or depth conditions, trading pauses for a configurable cooldown (default 5 minutes).

---

## Control via Telegram Commands

For users with Telegram set up, here is the full list of control commands:

| Command | Action |
|---------|--------|
| `/status` | Show current bot status (running, paused, mode, positions) |
| `/pause` | Pause trading |
| `/resume` | Resume trading |
| `/close_all` | Close all open positions |
| `/kill` | Stop the bot process |
| `/positions` | Show current open positions |
| `/pnl` | Show P&L summary |
| `/risk` | Show risk report |
| `/trades` | Show recent trade history |

See the [Notifications guide](Notifications.md) for how to set up Telegram.

---

## Control Permissions

All control actions (pause, resume, close_all, kill) require authentication:

- **Dashboard:** requires an active login session
- **Telegram:** only responds to commands from authorized chat IDs
- **Discord:** only responds in authorized channels/guilds
- **API calls:** require the admin API key (not the read-only key)

Read-only API keys can view data but cannot trigger control actions.

---

## Best Practices

1. **Pause before panic.** If something looks wrong, pause first, investigate second. Pausing keeps existing protections active while preventing new exposure.

2. **Close All is for emergencies.** In normal operation, let the bot manage exits through its stop losses and smart exit system. Closing all at once may exit profitable positions prematurely.

3. **Kill is a last resort.** Remember that killing the bot leaves positions unmanaged. Only use it if the bot is truly misbehaving.

4. **Set up Telegram.** Having mobile control means you can pause from anywhere in seconds, even if you are not near your computer.

5. **Trust the auto-pauses.** They exist for a reason. When an auto-pause triggers, take it as a signal to review conditions before resuming.

---

*Nova|Pulse v5.0.0 -- You are always in control.*
