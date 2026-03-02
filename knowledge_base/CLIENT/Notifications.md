# Notifications: Telegram, Discord, and Slack

**Last updated:** 2026-03-01

Nova|Pulse can send you real-time notifications and accept commands through Telegram, Discord, or Slack. This means you can monitor your bot and control it from your phone, even when you are away from your dashboard.

---

## What You Get Notified About

| Event | Description | Channel |
|-------|-------------|---------|
| **Trade Opened** | Pair, direction, entry price, position size, strategy | All |
| **Trade Closed** | Pair, P&L, close reason (TP, SL, trailing, manual) | All |
| **Auto-Pause** | When the bot pauses due to loss streak, drawdown, or stale data | All |
| **Auto-Resume** | When auto-pause conditions clear | All |
| **System Start** | Bot startup confirmation with mode and version | All |
| **System Error** | Critical errors (exchange auth failure, database issues) | All |
| **Periodic Check-In** | Status summary every 30 minutes (configurable) | Telegram |
| **Daily Summary** | End-of-day performance report | Telegram |

---

## Telegram (Recommended)

Telegram is the recommended notification channel because it supports both incoming notifications and outgoing commands. You can monitor and control your bot entirely from your phone.

### Setting Up Telegram

**Step 1: Create a Telegram Bot**

1. Open Telegram and search for **@BotFather**
2. Send `/newbot`
3. Follow the prompts to name your bot (e.g., "NovaPulse Bot")
4. BotFather gives you a **bot token** -- a long string like `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`
5. Save this token securely

**Step 2: Get Your Chat ID**

1. Start a chat with your new bot (search for it by the name you chose)
2. Send any message (e.g., "hello")
3. Open this URL in your browser: `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
4. Look for `"chat":{"id":XXXXXXXX}` -- that number is your chat ID
5. Note: your chat ID is a number like `123456789`

**Step 3: Configure Nova|Pulse**

Provide your bot token and chat ID to your operator. They will set:

```yaml
control:
  telegram:
    enabled: true
    token: "your_bot_token_here"
    chat_ids: [123456789]
    send_checkins: true
    checkin_interval_minutes: 30
```

Or via environment variables:
```
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=123456789
```

### Telegram Commands

Once connected, you can send commands to your bot:

| Command | Action |
|---------|--------|
| `/status` | Current bot status: running/paused, mode, uptime, open positions |
| `/positions` | List all open positions with P&L |
| `/pnl` | P&L summary: total, today, win rate, trades |
| `/risk` | Risk report: bankroll, exposure, daily loss, consecutive losses |
| `/trades` | Recent trade history |
| `/pause` | Pause trading (no new trades) |
| `/resume` | Resume trading |
| `/close_all` | Close all open positions |
| `/kill` | Stop the bot process |
| `/help` | List available commands |

### Check-In Messages

When `send_checkins` is enabled, the bot sends periodic status updates:

```
[NovaPulse Check-In]
Status: RUNNING
Mode: PAPER
Uptime: 4h 22m
Positions: 3 open
Today P&L: +$42.15
Win Rate: 62.5% (8 trades)
```

You can set the interval with `checkin_interval_minutes` (default 30).

### Multiple Chat IDs

You can send notifications to multiple Telegram users or groups:

```yaml
chat_ids: [123456789, 987654321]
```

All configured chat IDs receive notifications and can send commands.

### Security

- Only chat IDs in the `chat_ids` allowlist can interact with the bot
- Messages from unknown chat IDs are silently ignored
- Commands from unauthorized users never reach the control router

---

## Discord

Discord integration lets you receive notifications and send commands in a dedicated Discord channel.

### Setting Up Discord

**Step 1: Create a Discord Bot**

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications)
2. Click **New Application** and name it (e.g., "NovaPulse")
3. Go to the **Bot** tab and click **Add Bot**
4. Copy the **bot token**
5. Under **Privileged Gateway Intents**, enable **Message Content Intent**

**Step 2: Invite the Bot to Your Server**

1. In the Developer Portal, go to the **OAuth2** > **URL Generator** tab
2. Under Scopes, select **bot**
3. Under Bot Permissions, select **Send Messages** and **Read Message History**
4. Copy the generated URL and open it to invite the bot to your Discord server

**Step 3: Get Your Channel and Guild IDs**

1. In Discord, enable Developer Mode (User Settings > Advanced > Developer Mode)
2. Right-click your channel and select **Copy Channel ID**
3. Right-click your server name and select **Copy Server ID** (this is the guild ID)

**Step 4: Configure Nova|Pulse**

```yaml
control:
  discord:
    enabled: true
    token: "your_discord_bot_token"
    allowed_channel_ids: [1234567890123456]
    allowed_guild_id: 9876543210987654
```

### Discord Commands

Commands are prefixed with `!` (exclamation mark):

| Command | Action |
|---------|--------|
| `!status` | Show bot status |
| `!positions` | Show open positions |
| `!pnl` | Show P&L summary |
| `!pause` | Pause trading |
| `!resume` | Resume trading |
| `!close_all` | Close all positions |

### Security

- Only messages from the allowed channel in the allowed guild are processed
- The bot ignores messages from other channels, other servers, and DMs
- Deny-by-default: unknown sources are silently dropped

---

## Slack

Slack integration provides notifications and commands through a Slack workspace channel.

### Setting Up Slack

**Step 1: Create a Slack App**

1. Go to [api.slack.com/apps](https://api.slack.com/apps) and click **Create New App**
2. Choose **From scratch**, name it "NovaPulse", and select your workspace
3. Under **OAuth & Permissions**, add these scopes:
   - `chat:write` (send messages)
   - `commands` (respond to slash commands)
4. Install the app to your workspace
5. Copy the **Bot User OAuth Token** (starts with `xoxb-`)

**Step 2: Set Up Signing Secret**

1. In your Slack app settings, go to **Basic Information**
2. Copy the **Signing Secret** (used to verify requests come from Slack)

**Step 3: Configure Nova|Pulse**

```yaml
control:
  slack:
    enabled: true
    token: "xoxb-your-slack-bot-token"
    signing_secret: "your_signing_secret"
    allowed_channel_id: "C01234ABCDE"
```

### Slack Commands

Commands are Slack slash commands:

| Command | Action |
|---------|--------|
| `/nova status` | Show bot status |
| `/nova pnl` | Show P&L summary |
| `/nova pause` | Pause trading |
| `/nova resume` | Resume trading |

### Security

- Requests are verified using the Slack signing secret
- Only the configured channel ID is allowed
- Invalid signatures are rejected

---

## Which Channel Should I Use?

| If You... | Recommendation |
|-----------|---------------|
| Want full mobile control + monitoring | **Telegram** (most complete command set) |
| Already use Discord for your community | **Discord** (good for team monitoring) |
| Your team lives in Slack | **Slack** (integrates with existing workflow) |
| Want maximum control | **Telegram** (supports all commands including /kill) |
| Want multiple people to monitor | **Discord** or **Slack** (channel-based, team-friendly) |

You can enable multiple channels simultaneously. Notifications go to all enabled channels. Commands can be sent from any enabled channel.

---

## Notification Rate

Notifications are sent in real time when events occur. During active trading, you might receive several notifications per hour. During quiet markets, you might only see the periodic check-in.

The check-in interval (Telegram only) is configurable. Setting it to 0 disables check-ins while keeping trade notifications active.

---

## Troubleshooting

**No notifications received:**
1. Check that the integration is enabled in config (`enabled: true`)
2. Verify the token is correct (no extra spaces or characters)
3. For Telegram, make sure you sent a message to the bot first (to initialize the chat)
4. Check the bot logs for connection errors

**Commands not working:**
1. Verify your chat/channel ID is in the allowlist
2. Check that the bot has the correct permissions on the platform
3. For Telegram, ensure `polling_enabled: true` (but only enable on ONE deployment per bot token)

**Duplicate notifications:**
If you run multiple bot instances with the same Telegram token, both will try to poll for updates and create conflicts (HTTP 409 errors). Only enable `polling_enabled: true` on one deployment.

---

*Nova|Pulse v5.0.0 -- Stay connected, stay in control, from anywhere.*
