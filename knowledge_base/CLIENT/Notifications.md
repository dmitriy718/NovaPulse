# Notifications: Telegram, Discord, and Slack

**Last updated:** 2026-02-22

NovaPulse can send you real-time notifications and accept commands through Telegram, Discord, or Slack. This means you can monitor your bot and control it from your phone, even when you are away from your dashboard.

---

## What You Get Notified About

Regardless of which notification platform you use, NovaPulse sends alerts for:

| Event | What You Receive |
|-------|-----------------|
| **New trade opened** | Pair, direction (long/short), entry price, position size, stop loss, take profit |
| **Trade closed** | Pair, entry price, exit price, P&L, reason (TP hit, SL hit, manual close, etc.) |
| **Auto-pause triggered** | Which circuit breaker fired and why |
| **Exchange connection issues** | Disconnect/reconnect events |
| **Error conditions** | API errors, order failures, data feed issues |
| **Periodic check-ins** | Summary of status, positions, and P&L (every 30 minutes) |

---

## Telegram Bot

Telegram is the most fully-featured notification channel. It supports both notifications AND interactive commands to monitor and control your bot.

### Setting Up the Telegram Bot

**Step 1: Create your bot with BotFather**

1. Open Telegram and search for `@BotFather`.
2. Send the command `/newbot`.
3. BotFather will ask for a name -- enter something like "My NovaPulse Bot".
4. BotFather will ask for a username -- enter something like `my_novapulse_bot` (must end in "bot").
5. BotFather will respond with a **bot token** -- a long string like `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`. Copy this carefully.

**Step 2: Find your Chat ID**

1. Open a conversation with your new bot in Telegram (search for the username you just created).
2. Send any message (like "hello") to the bot.
3. Open this URL in your browser (replace YOUR_TOKEN with the token from step 1):
   `https://api.telegram.org/botYOUR_TOKEN/getUpdates`
4. Look for `"chat":{"id":123456789}` in the response -- that number is your **Chat ID**.
5. Alternatively, after the bot is connected, send `/whoami` and it will reply with your chat ID.

**Step 3: Provide credentials to NovaPulse**

Share your bot token and chat ID with NovaPulse support, or enter them in the settings panel of your dashboard. NovaPulse will configure them securely.

**Step 4: Verify**

Once configured, your bot should send you a startup message. Try sending `/status` to verify it responds.

### Telegram Commands

| Command | What It Does |
|---------|-------------|
| `/status` | Shows system status: running/paused, mode, exchange, uptime, scan count |
| `/pnl` | Shows performance summary: total P&L, win rate, trade count |
| `/positions` | Lists all open positions with entry price, current price, and unrealized P&L |
| `/risk` | Shows risk report: daily P&L, exposure, position count, circuit breaker states |
| `/health` | Health check: exchange connectivity, data feed status, memory usage |
| `/uptime` | Shows how long the bot has been running |
| `/strategies` | Shows per-strategy performance: weights, win rates, trade counts |
| `/exposure` | Shows current exposure as percentage of bankroll |
| `/scanner` | Shows the latest scanner results for all pairs |
| `/exchange` | Shows which exchange is active and connection status |
| `/pairs` | Lists all configured trading pairs |
| `/config` | Shows key configuration values (mode, risk settings, thresholds) |
| `/pause` | Pauses trading (no new trades; existing positions still managed) |
| `/resume` | Resumes trading |
| `/close_all` | Closes all open positions at market price |
| `/kill` | Emergency stop -- closes all positions and shuts down the bot. Requires confirmation: reply "yes" within 30 seconds. |
| `/whoami` | Shows your Telegram chat ID (useful for setup) |
| `/help` | Shows the list of available commands |

### Periodic Check-Ins

Every 30 minutes, the Telegram bot sends an automatic check-in message with:
- Current status (running, paused, etc.)
- Open position count and total unrealized P&L
- Any recent trades or alerts

This means you can glance at your phone every few hours and see that everything is running smoothly, even without actively checking.

### Security

- Only chat IDs in your allowlist can interact with the bot. Unauthorized users are ignored.
- The `/kill` command requires explicit confirmation (you must reply "yes" within 30 seconds) to prevent accidental shutdowns.
- Your bot token is stored encrypted on NovaPulse servers.

---

## Discord Bot

The Discord bot provides monitoring and control commands via slash commands in your Discord server.

### Setting Up the Discord Bot

**Step 1: Create a Discord Application**

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications).
2. Click **New Application** and name it (e.g., "NovaPulse").
3. Go to the **Bot** section and click **Add Bot**.
4. Copy the **bot token** -- you will need this.
5. Under **Privileged Gateway Intents**, enable **Message Content Intent**.

**Step 2: Invite the Bot to Your Server**

1. In the Developer Portal, go to **OAuth2** > **URL Generator**.
2. Select scopes: `bot` and `applications.commands`.
3. Select permissions: `Send Messages`, `Read Messages/View Channels`, `Use Slash Commands`.
4. Copy the generated URL and open it in your browser.
5. Select your server and click **Authorize**.

**Step 3: Configure the Channel**

1. Note the **Channel ID** of the channel where the bot should respond:
   - In Discord, enable Developer Mode (Settings > Advanced > Developer Mode).
   - Right-click the channel and select **Copy Channel ID**.
2. Optionally, note your **Server (Guild) ID** for additional security:
   - Right-click your server name and select **Copy Server ID**.

**Step 4: Provide credentials to NovaPulse**

Share your bot token, channel ID, and optionally guild ID with support or enter them in the settings panel.

### Discord Slash Commands

| Command | What It Does |
|---------|-------------|
| `/pause` | Pauses trading |
| `/resume` | Resumes trading |
| `/close_all` | Closes all open positions |
| `/kill` | Emergency stop |
| `/status` | Shows system status |
| `/pnl` | Shows performance summary |
| `/positions` | Lists open positions |
| `/risk` | Shows risk report |

### Security

- The bot only responds in your authorized channel(s) or guild.
- Commands from unauthorized channels are silently denied.
- If no channels or guild are configured, ALL commands are denied (fail-closed for safety).

---

## Slack Bot

The Slack bot uses Socket Mode, which means no public URL is required -- it connects outbound from NovaPulse to Slack.

### Setting Up the Slack Bot

**Step 1: Create a Slack App**

1. Go to [api.slack.com/apps](https://api.slack.com/apps) and click **Create New App**.
2. Choose **From scratch** and name it (e.g., "NovaPulse").
3. Select your workspace.

**Step 2: Configure Permissions**

1. Go to **OAuth & Permissions**.
2. Add these Bot Token Scopes:
   - `chat:write` (send messages)
   - `commands` (slash commands)
3. Install the app to your workspace.
4. Copy the **Bot User OAuth Token** (starts with `xoxb-`).

**Step 3: Enable Socket Mode**

1. Go to **Socket Mode** in your app settings.
2. Enable Socket Mode.
3. Generate an **App-Level Token** with the `connections:write` scope.
4. Copy the token (starts with `xapp-`).

**Step 4: Create Slash Commands**

In your Slack app settings, go to **Slash Commands** and create these commands:

| Command | Description |
|---------|-------------|
| `/trading-pause` | Pause NovaPulse trading |
| `/trading-resume` | Resume NovaPulse trading |
| `/trading-close-all` | Close all open positions |
| `/trading-kill` | Emergency stop |
| `/trading-status` | Show system status |
| `/trading-pnl` | Show performance summary |
| `/trading-positions` | List open positions |
| `/trading-risk` | Show risk report |

**Step 5: Configure the Channel**

1. Note the **Channel ID** of the channel where the bot should respond:
   - In Slack, right-click the channel name > **View channel details** > scroll to the bottom for the Channel ID.

**Step 6: Provide credentials to NovaPulse**

Share your bot token (`xoxb-...`), app token (`xapp-...`), signing secret, and channel ID with support or enter them in the settings panel.

### Security

- The bot only responds in your authorized channel.
- Commands from other channels are denied.
- Request signatures are verified using your signing secret for additional security.

---

## Notification Preferences

You can configure the following preferences through the settings panel or by contacting support:

| Preference | Options | Default |
|-----------|---------|---------|
| **Trade notifications** | On/Off | On |
| **Auto-pause alerts** | On/Off | On |
| **Periodic check-ins** | On/Off, interval | On, every 30 minutes |
| **Error notifications** | On/Off | On |

---

## Choosing Your Notification Platform

| Feature | Telegram | Discord | Slack |
|---------|----------|---------|-------|
| Full command set (16 commands) | Yes | 8 commands | 8 commands |
| Periodic check-ins | Yes (every 30 min) | Via notifications | Via notifications |
| Mobile app | Yes | Yes | Yes |
| Kill confirmation | Yes (30s timeout) | Instant | Instant |
| Setup complexity | Easy | Moderate | Moderate |
| Best for | Individual traders | Team/community | Team/workplace |

**Recommendation:** For individual traders, Telegram offers the most complete experience with the easiest setup. For teams or organizations, Discord or Slack may be more convenient.

---

*For more on controlling NovaPulse, see [Controls](Controls-Pause-Resume-Kill.md).*
*For dashboard features, see [Dashboard Walkthrough](Nova-Dashboard-Walkthrough.md).*
