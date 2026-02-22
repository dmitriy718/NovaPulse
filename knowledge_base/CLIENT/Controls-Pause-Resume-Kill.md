# Controls: Pause, Resume, Close All, and Emergency Kill

**Last updated:** 2026-02-22

NovaPulse gives you full control over the bot at all times. Whether you want to temporarily pause trading, close all positions, or hit the emergency stop, you can do it instantly from the dashboard, Telegram, Discord, or Slack.

---

## Overview of Controls

```
+------------------------------------------------------------------+
|                                                                  |
|    [ PAUSE ]    [ RESUME ]    [ CLOSE ALL ]    [ KILL ]          |
|                                                                  |
|    Pause new     Resume        Close all         Emergency       |
|    trades        trading       positions         shutdown        |
|                                                                  |
+------------------------------------------------------------------+
```

| Control | What It Does | Existing Positions? | New Trades? |
|---------|-------------|---------------------|-------------|
| **Pause** | Stops new trades from opening | Still managed and protected (stop losses, trailing stops active) | Blocked |
| **Resume** | Lifts the pause and allows trading again | Continues normal management | Allowed again |
| **Close All** | Closes every open position at market price immediately | All closed | Still allowed (bot keeps running) |
| **Kill** | Emergency: closes all positions AND stops the bot entirely | All closed | Blocked (bot is stopped) |

---

## Pause

**What happens when you pause:**

1. The bot stops opening new trades.
2. The scanner keeps running -- you can still see signals and confluence on the dashboard.
3. All existing positions remain open and fully protected:
   - Stop losses continue to be monitored
   - Trailing stops continue to adjust
   - Take profit targets are still active
   - If a stop loss or take profit is hit, the trade closes normally
4. The status indicator changes to **PAUSED** (yellow).
5. A notification is sent to your configured channels (Telegram, Discord, Slack).

**When to use Pause:**

- You want to take a break from trading for a while
- The market feels unusually volatile and you want to be cautious
- You want to review settings or performance before continuing
- You are diagnosing unexpected behavior

**Pause does NOT close your existing trades.** It simply prevents new ones from opening. Your existing positions are still fully managed.

---

## Resume

**What happens when you resume:**

1. The pause flag is cleared.
2. The bot begins placing new trades again on the next scan (if signals meet the thresholds).
3. The status indicator changes back to **RUNNING** (green) -- unless a circuit breaker is still active (e.g., stale data), in which case it will show the relevant status instead.
4. A notification is sent to your configured channels.

**When to use Resume:**

- You previously paused and are ready to allow trading again
- You have reviewed the situation and are confident it is safe to continue

> **Note:** If the bot was auto-paused by a circuit breaker (daily loss limit, consecutive losses, stale data, etc.), resuming clears the manual pause flag, but the circuit breaker condition may still block trading. Check the Risk Shield panel on the dashboard to see if any circuit breakers are still active.

---

## Close All

**What happens when you close all:**

1. Every open position is closed immediately at market price.
2. Realized P&L is recorded for each closed trade.
3. The bot continues running and scanning -- it may open new trades on the next scan unless you also pause.
4. A notification is sent with the number of positions closed.

**When to use Close All:**

- You want to go flat (no open positions) before a major market event (e.g., interest rate announcements, regulatory news)
- You want to reset and start fresh
- You see something in the market that concerns you

**Important:** Close All does NOT pause the bot. If you want to close everything AND prevent new trades, use Close All followed by Pause, or use Kill.

---

## Emergency Kill

**What happens when you kill:**

1. Every open position is closed immediately at market price.
2. The bot engine is shut down entirely.
3. No new scans or trades will occur.
4. The status indicator changes to **STOPPED** (red).
5. A notification is sent to your configured channels.

**When to use Kill:**

- You suspect your API credentials have been compromised
- You see unexpected or erroneous trading behavior
- You want to completely freeze all activity until support reviews
- Any situation where you want an immediate, total stop

**After a Kill:** The bot remains stopped until it is manually restarted (by you via Resume, or by support). No automatic restart occurs after a Kill.

---

## How to Use Controls

### From the Dashboard

The control buttons are located in the header area of your dashboard:
- Click **Pause** to pause trading
- Click **Resume** to resume trading
- Click **Close All** to close all positions
- **Kill** may require confirmation (a dialog will ask "Are you sure?")

### From Telegram

If you have the Telegram bot set up (see [Notifications](Notifications.md)):

| Command | Action |
|---------|--------|
| `/pause` | Pause trading |
| `/resume` | Resume trading |
| `/close_all` | Close all positions |
| `/kill` | Emergency stop (requires confirmation -- reply "yes" within 30 seconds) |

### From Discord

If you have the Discord bot set up:

| Command | Action |
|---------|--------|
| `/pause` | Pause trading |
| `/resume` | Resume trading |
| `/close_all` | Close all positions |
| `/kill` | Emergency stop |

### From Slack

If you have the Slack bot set up:

| Command | Action |
|---------|--------|
| `/trading-pause` | Pause trading |
| `/trading-resume` | Resume trading |
| `/trading-close-all` | Close all positions |
| `/trading-kill` | Emergency stop |

### Via API

If you are using the API directly:

| Endpoint | Method | Action |
|----------|--------|--------|
| `/api/v1/control/pause` | POST | Pause trading |
| `/api/v1/control/resume` | POST | Resume trading |
| `/api/v1/control/close_all` | POST | Close all positions |

API calls require your admin API key in the `X-API-Key` header.

---

## What Happens After a Restart

If the bot restarts (due to a system update, server reboot, or manual restart):

1. The bot re-initializes and goes through its warmup phase (downloading recent price data).
2. It reads its last known state from the database.
3. Any positions that were open before the restart are re-detected from the exchange.
4. If it was paused before the restart, it comes back in a paused state.
5. If it was killed before the restart, it comes back in a stopped state and will not resume automatically.

The restart process typically takes 1-2 minutes. During this time, your exchange's native stop-loss orders (if enabled) continue to protect your positions.

---

## Automatic Pauses (Circuit Breakers)

NovaPulse can also pause itself automatically when safety conditions are triggered. These are different from a manual pause:

| Trigger | Threshold | What Happens |
|---------|-----------|-------------|
| **Daily loss limit** | Losses exceed 5% of bankroll | Auto-pauses until next day |
| **Consecutive losses** | 4 losses in a row (default) | Auto-pauses for review |
| **Drawdown limit** | Drawdown exceeds 8% | Auto-pauses and may reduce position sizes |
| **Stale market data** | No fresh data for 3+ checks | Auto-pauses until data recovers |
| **Exchange disconnect** | WebSocket down for 5+ minutes | Auto-pauses until reconnected |

When an auto-pause occurs:
- You receive a notification explaining what triggered it
- The Risk Shield panel on the dashboard shows the active circuit breaker
- You can resume manually once you have reviewed the situation

---

## Decision Flowchart

```
  Something concerns you?
         |
         v
  Is it urgent / suspected compromise?
        / \
      YES   NO
       |     |
       v     v
     KILL   Do you want to close positions?
              / \
            YES   NO
             |     |
             v     v
         CLOSE    PAUSE
         ALL      (keeps positions,
         then     stops new trades)
         PAUSE
```

---

*If you are unsure which action to take, **Pause** is always a safe first step -- it stops new trades while keeping your existing positions protected. You can then review the situation calmly before deciding whether to Close All, Resume, or Kill.*

*For additional help, see [Troubleshooting](Troubleshooting.md) or [Contact Support](Contact-Support.md).*
