# Troubleshooting, Operations, and Release

## Troubleshooting (Client)

### I See 401 Unauthorized

Meaning:

1. Your credentials are wrong or have been rotated.

Fix:

1. Request updated credentials from support.
1. If your browser cached old credentials, try:
1. Open the dashboard in an incognito window.
1. Close all tabs for the domain and reopen.
1. Clear saved site credentials for the domain (browser settings).

### I See OFFLINE

Meaning:

1. The UI cannot reach the API.

Fix:

1. Wait 30 to 60 seconds and refresh.
1. If it persists, contact support and include the time window and what you were doing.

### I See STALE FEED

Meaning:

1. The system detected stale market data.
1. Trading is intentionally blocked until feeds are healthy again.

Fix:

1. Wait for automatic reconnect.
1. If it persists, contact support.

### Dashboard Shows RECONNECTING

Common causes:

1. transient network issue
1. WS reconnect loop
1. exchange API instability

Safe response:

1. wait briefly
1. if it persists, pause trading and contact support

### No Trades

Common causes:

1. trading paused
1. stale feed
1. thresholds too strict (`ai.confluence_threshold`, `ai.min_confidence`)
1. risk limits blocking entries (`risk.max_daily_loss`, etc)
1. spread filter too strict (`trading.max_spread_pct`)

### Control Buttons Do Nothing

Common causes:

1. missing dashboard API key for control actions
1. incorrect credentials (managed deployments)

### Unsupported Python

Use Python 3.11 or 3.12 only.

## Operations (Support/Dev, Local Bot)

### Support Intake (What To Collect First)

1. Client-reported time range in UTC.
1. Domain affected (if managed): dashboard hostname or agent hostname.
1. Exact error: `401`, `502`, `OFFLINE`, `STALE FEED`, or "no trades".
1. Whether the client pressed Pause, Resume, Close All, or Kill.

### Quick Health Checks

1. `GET /api/v1/status`
1. `GET /api/v1/scanner`
1. WS: `/ws/live`

### Logs and Artifacts

1. `logs/trading_bot.log`
1. `logs/errors.log`
1. DB default: `data/trading.db`

### Safe Control Actions

1. Pause before maintenance.
1. Validate feed freshness before resuming.

## Operations (Support/Dev, Managed Stack)

If your deployment uses a container stack behind a reverse proxy, typical operator tasks include:

1. service status checks (systemd)
1. container status checks (docker compose)
1. tailing logs (docker logs)
1. validating basic-auth protected health endpoints
1. running safe restarts

These details are environment-specific and should be documented per environment.

### Example Managed Stack (Nova Horizon / "horizon" Host)

Only applicable if your production environment matches these paths and hostnames.

Host basics:

1. Hostname: `horizon`
1. Provider: DigitalOcean droplet
1. OS: Ubuntu 22.04

Where the stack lives:

1. Compose directory: `/home/ops/agent-stack`
1. Compose file: `/home/ops/agent-stack/docker-compose.yml`
1. Caddyfile: `/home/ops/agent-stack/Caddyfile`
1. Data directory: `/home/ops/agent-stack/data` (container path typically `/data`)

Service management (systemd):

1. Unit: `agent-stack.service`
1. Location: `/etc/systemd/system/agent-stack.service`

Common commands:

```bash
sudo systemctl status agent-stack.service --no-pager -l
sudo systemctl start agent-stack.service
sudo systemctl stop agent-stack.service
```

Compose-level commands:

```bash
cd /home/ops/agent-stack
docker compose ps
docker compose up -d --remove-orphans
docker compose down
```

Health checks:

```bash
curl -sS https://agent.horizonsvc.com/health
curl -u "nova:<PASSWORD>" -sS https://nova.horizonsvc.com/api/health
curl -u "nova:<PASSWORD>" -sS https://nova.horizonsvc.com/api/state
```

Logs:

```bash
docker logs --tail 200 agent-api
docker logs --tail 200 market
docker logs --tail 200 caddy
docker logs --tail 200 qdrant
```

### Managed Stack Runbooks (Common Incidents)

Nova Horizon shows OFFLINE:

1. `docker ps | rg caddy`
1. `docker ps | rg market`
1. `docker logs --tail 200 caddy`
1. `docker logs --tail 200 market`
1. Validate upstream inside container:

```bash
docker exec market python -c 'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:9000/api/health").read().decode())'
```

Nova Horizon returns 401:

1. Retrieve current password:

```bash
cat /home/ops/agent-stack/.nova_pass
```

2. Validate:

```bash
curl -u "nova:<PASSWORD>" -sS https://nova.horizonsvc.com/api/health
```

Agent `/chat` returns 401:

1. Retrieve current password:

```bash
cat /home/ops/agent-stack/.agent_chat_pass
```

2. Validate:

```bash
curl -u "agent:<PASSWORD>" -sS https://agent.horizonsvc.com/chat -H "Content-Type: application/json" -d '{"query":"ping"}'
```

Trading is not happening:

1. Inspect `/api/state`:
1. `trading_enabled` should be `true`.
1. `kill_switch` should be `false`.
1. `paused` should be `false`.
1. `feed_stale` should be `false` for the active exchange.

Emergency stop:

```bash
curl -u "nova:<PASSWORD>" -X POST https://nova.horizonsvc.com/api/kill
curl -u "nova:<PASSWORD>" -X POST https://nova.horizonsvc.com/api/resume
```

Safe restart:

```bash
cd /home/ops/agent-stack
sudo systemctl start agent-stack.service
```

### Backups and Data Formats (Managed Stack)

Backups:

1. Script: `/home/ops/agent-stack/ops/backup.sh`
1. Output: `/home/ops/agent-stack/backups`
1. Cron: `/etc/cron.d/agent-stack-backup` (daily at 03:15 UTC)

NDJSON and Parquet:

1. NDJSON artifacts often live under `/home/ops/agent-stack/data` (for example `.../YYYY-MM-DD.ndjson`)
1. If `PARQUET_ROLLUP=1`, the engine may roll prior day NDJSON into Parquet (`...YYYY-MM-DD.parquet`)

## Testing and CI (Dev)

1. Run tests: `pytest`
1. CI (if enabled): `.github/workflows/tests.yml`
1. Run walk-forward gate: `python scripts/walk_forward_gate.py`
1. Run strict preflight before live: `python scripts/live_preflight.py --strict`

## Release Checklist (Dev/Support)

1. Run tests on Python 3.11 and 3.12.
1. Validate dashboard controls auth (no hardcoded secret).
1. Validate stale feed guard behavior.
1. Validate paper mode end-to-end.
1. Validate live mode requirements and secret presence.
1. If billing is enabled, verify Stripe endpoint wiring:
1. `POST /api/v1/billing/checkout` from app.
1. `POST /api/v1/billing/webhook` from Stripe with required events.
1. If signal webhooks are enabled, verify `SIGNAL_WEBHOOK_SECRET` and source allowlist are set.

## FAQ (Client + Support)

1. Does the bot guarantee profits? No.
1. Can I run multiple exchanges? Yes, if configured via `TRADING_EXCHANGES`.
1. Can I control it remotely? Yes, via authenticated dashboard control endpoints or Telegram (if enabled).

## Glossary (Client-Friendly)

1. Realized PnL: profit/loss from closed trades.
1. Unrealized PnL: profit/loss on open positions based on current price.
1. Confluence: multiple independent signals agreeing.
1. Stale feed: market data not updating; entries should be blocked.
