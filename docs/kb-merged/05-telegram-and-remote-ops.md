# Telegram and Remote Ops

## Telegram Setup (Client)

Telegram is optional. If enabled:

1. Set the bot token in config.
1. Set an allowlist of chat IDs (do not run without an allowlist).
1. Start the bot and confirm the Telegram task is running.

Common commands:

1. `/status`
1. `/positions`
1. `/pause`
1. `/resume`
1. `/close_all`
1. `/kill`

Implementation:

1. `src/utils/telegram.py`

## Remote Control Via HTTP (Support/Dev)

Local bot controls:

1. `POST /api/v1/control/pause`
1. `POST /api/v1/control/resume`
1. `POST /api/v1/control/close_all`

These require `X-API-Key`.

## Optional Managed "Agent" Endpoint

Some deployments also expose an "agent" service for operations help:

1. `GET /health`
1. `POST /chat`

Auth is deployment-specific (often Basic Auth). If used, treat those credentials as production secrets.

Example validation (if your deployment matches):

```bash
curl -sS https://agent.horizonsvc.com/health
curl -u "agent:<PASSWORD>" -sS https://agent.horizonsvc.com/chat -H "Content-Type: application/json" -d '{"query":"ping"}'
```
