# Telegram Guide

Telegram is an optional control surface.

## Setup

1. Create a Telegram bot token (BotFather).
2. Add your chat id to allowlist.
3. Set config:
- `control.telegram.enabled: true`
- `control.telegram.token: <token>`
- `control.telegram.chat_ids: [<your_chat_id>]`

## Commands

Common:
- `/status`
- `/pnl`
- `/positions`
- `/risk`
- `/pause`
- `/resume`
- `/close_all`
- `/kill`
- `/whoami` (shows your chat id)

Security:
- Only allowed chat ids are authorized to use commands.

